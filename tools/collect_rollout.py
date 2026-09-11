"""Official runner wrapper: export ONLY instance-local public planning inputs after exit."""
import argparse
import json
from pathlib import Path
import uuid

from competition.sdk.cli import _load_agent_class
from competition.sdk.scenarios.coop_decoy.runner import run
from zqhj_features import FEATURE_VERSION


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--agent',required=True)
    p.add_argument('--duration',type=float,required=True)
    p.add_argument('--seed',type=int,required=True)
    p.add_argument('--scenario-json',required=True)
    p.add_argument('--sim-binary',required=True)
    p.add_argument('--redis-port',type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    args = p.parse_args()
    base = _load_agent_class(args.agent)
    if not hasattr(base,'on_planning_input'):
        p.error('collection requires the project planning-input hook')
    instances = []
    episode = str(uuid.uuid4())
    class RecordedAgent(base):
        def __init__(self,my_uid):
            super().__init__(my_uid)
            self.recorded_samples = []
            instances.append(self)  # Offline registry; never passed into any Agent.

        def on_planning_input(self,record,now):
            if len(self.recorded_samples) < 1500:
                self.recorded_samples.append((now,record))

    succeeded = False
    try:
        run(RecordedAgent,duration=args.duration,seed=args.seed,scenario=args.scenario_json,
            output_dir=str(args.output/'official'),port=args.redis_port,mode='train',
            photo_mode='auto',sim_binary=args.sim_binary,start_sim=True)
        succeeded = True
    finally:
        # No online file I/O; this code runs strictly after the official runner stops.
        path = args.output/'public-planning.jsonl'
        with path.open('x',encoding='utf-8') as stream:
            for agent in instances:
                for now,record in agent.recorded_samples:
                    row = dict(feature_version=FEATURE_VERSION,episode_id=episode,agent_uid=agent.my_uid,
                               sim_s=now,provenance='official_public_observation_train_mode',record=record)
                    stream.write(json.dumps(row,allow_nan=False)+'\n')
        summary = dict(episode_id=episode,runner_returned=succeeded,seed=args.seed,
                       samples=sum(len(a.recorded_samples) for a in instances),
                       callback_io=False,records_contain_judge_truth=False,
                       agents=[dict(uid=a.my_uid,samples=len(a.recorded_samples),diagnostics=a.diagnostics) for a in instances])
        (args.output/'collection.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
