"""Offline contract probes of the shipped SDK. These are NOT engine results."""
from dataclasses import fields
import inspect
import json

from competition.sdk.cli import _load_agent_class
from competition.sdk.core import commands
from competition.sdk.core.observation import Detection, Message, Observation, SelfView, MissionBriefing
from competition.sdk.scenarios.coop_decoy import CoopAgent
from competition.sdk._vendored.coop_eval import CoopTrackingEvaluator, profile_multi_uav_coop_decoy
from competition.sdk._vendored.uav_target_map import TargetMatch


def main():
    baseline = _load_agent_class("baselines.coop_distributed:CoopDistributedAgent")
    entry = _load_agent_class("zqhj_entry:EntryAgent")
    for cls in (baseline, entry):
        assert issubclass(cls, CoopAgent)
        agents = [cls(my_uid=f"audit_{i}") for i in range(3)]
        for agent in agents:
            agent.configure({})
            agent.reset()
        assert len({id(a) for a in agents}) == 3
    signatures = {name: str(inspect.signature(getattr(commands, name))) for name in
                  ("fly_to", "set_heading", "set_speed", "point_gimbal", "set_gimbal_fov", "broadcast", "send_to", "report_target")}
    assert commands.broadcast("a" * 50).params["payload"] == "a" * 50
    assert len(commands.broadcast("中" * 16 + "ab").params["payload"].encode("utf-8")) == 50
    try:
        commands.broadcast("中" * 17)
    except commands.PayloadTooLarge:
        pass
    else:
        raise AssertionError("51 UTF-8 bytes were not rejected")
    schema = {cls.__name__: {f.name: str(f.type) for f in fields(cls)}
              for cls in (Detection, Message, SelfView, MissionBriefing, Observation)}
    assert "target_id" not in schema["Detection"]
    assert set(schema["Observation"]) == {"self", "comm_inbox", "briefing"}

    def track(count):
        return {f"u{i}": TargetMatch("audit_target", True, False) for i in range(count)}

    profile = profile_multi_uav_coop_decoy(duration_s=600, K=2)
    ev = CoopTrackingEvaluator(profile, {"audit_target"})
    for t in range(26):
        ev.observe(t, track(1), set())
    assert not ev.is_destroyed("audit_target")
    for t in range(26, 46):
        ev.observe(t, track(2), set())
    assert ev.is_destroyed("audit_target")
    ev = CoopTrackingEvaluator(profile, {"audit_target"})
    for t in range(21):
        ev.observe(t, {} if t in (16, 17) else track(2), set())
    assert ev.is_destroyed("audit_target")  # 2-second gap is backfilled.
    ev = CoopTrackingEvaluator(profile, {"audit_target"})
    for t in range(21):
        ev.observe(t, {} if t in (16, 17, 18) else track(2), set())
    assert not ev.is_destroyed("audit_target") and ev.states["audit_target"].resets == 1
    near = {"u0": (0, 0), "u1": (0, 0.0001)}
    far = {"u0": (0, 0), "u1": (0, 0.01)}
    ev = CoopTrackingEvaluator(profile, {"audit_target"})
    for t in range(5):
        ev.observe(t, {}, set(), uav_positions=near)
    assert ev.proximity_violations == 1
    ev.observe(5, {}, set(), uav_positions=far)
    ev.observe(6, {}, set(), uav_positions=near)
    assert ev.proximity_violations == 2
    # Demonstrate, without patching, the suspected epoch/time-score mismatch.
    epoch_scores = {}
    for origin in (0, -28800, 1780000000):
        ev = CoopTrackingEvaluator(profile, {"audit_target"})
        for t in range(301):
            ev.observe(origin + t, track(2) if t >= 281 else {}, set())
        epoch_scores[str(origin)] = {
            "destroyed_at_s": ev.mission_done_time,
            "mission_time_score": ev.score()["dimension_scores"]["mission_time"]}
    print(json.dumps({"result": "PASS", "scope": "SDK import and synthetic contract probes ONLY",
                      "command_signatures": signatures, "schema": schema,
                      "observed_epoch_score_mismatch": epoch_scores}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
