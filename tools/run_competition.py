"""Launch the unchanged official CLI with project-local evidence and owned Redis.

This is an offline engineering tool, never imported by an online Agent.
It does not change the SDK, scores, physical parameters or original scenarios.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_AGENT = "baselines.coop_distributed:CoopDistributedAgent"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["help", "check", "test", "score-smoke", "dry-run", "smoke", "baseline", "agent", "collect"])
    parser.add_argument("--sim-root", type=Path, default=PROJECT_ROOT.parent)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--agent", default=None, help="module:Class; custom agent only in agent/dry-run modes")
    parser.add_argument("--submission", type=Path, help="exported single-module Python Agent; loaded as zqhj_submission:EntryAgent")
    parser.add_argument("--output", type=Path, help="new run directory inside this project; relative paths are project-relative")
    args = parser.parse_args()
    sim_root = args.sim_root.resolve()
    python_exe = args.python.resolve()
    scenario = sim_root / "competition" / "scenarios" / "coop_decoy" / "scenario.json"
    engine = sim_root / "opensim-sim.exe"
    redis_exe = sim_root / "bin" / "redis-server.exe"
    required = [sim_root / "SDK-API.md", sim_root / "VERSION", scenario, python_exe]
    real = args.mode in {"smoke", "baseline", "agent", "collect"}
    needs_redis = args.mode not in {"help", "check", "test"}  # Official dry-run ScorePublisher still connects lazily.
    if needs_redis:
        required += [redis_exe]
    if real:
        required += [engine, redis_exe, sim_root / "config" / "terrain_bbox.json"]
    for path in required:
        if not path.is_file():
            parser.error(f"required file not found: {path}")
    if args.submission:
        if args.mode not in {'agent','dry-run','collect'} or args.agent:
            parser.error('--submission requires agent/dry-run/collect and no --agent')
        args.submission = args.submission.resolve()
        if not args.submission.is_file() or args.submission.suffix != '.py':
            parser.error('--submission must be an existing exported .py module')
        args.agent = 'zqhj_submission:EntryAgent'
    if args.mode == 'collect' and not args.agent:
        args.agent = 'zqhj_entry:EntryAgent'
    if args.agent and args.mode not in {"agent", "dry-run", "collect"}:
        parser.error("baseline/smoke use the unchanged official baseline")
    if args.mode == "agent" and not args.agent:
        parser.error("agent mode requires --agent module:Class")
    duration = args.duration if args.duration is not None else (2.0 if args.mode == "dry-run" else 5.0 if args.mode == "smoke" else 600.0)
    if not 0 < duration <= 600:
        parser.error("duration must be in (0, 600] for this audit entry")
    if args.mode == "baseline" and duration != 600:
        parser.error("baseline mode is a full 600-second round; use smoke for short checks")
    if not 1 <= args.redis_port <= 65535:
        parser.error("invalid Redis port")
    if args.mode == "score-smoke" and args.redis_port != 6379:
        parser.error("the shipped score_e2e_smoke script requires port 6379")
    if args.seed <= 0 and args.mode != "help":
        parser.error("use an explicit positive seed for recorded runs")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out = args.output or Path("artifacts") / "runs" / f"{stamp}-{args.mode}-seed{args.seed}"
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    out = out.resolve()
    if not out.is_relative_to(PROJECT_ROOT) or out == PROJECT_ROOT:
        parser.error("output must be inside the existing ZqhjGame")
    if out.exists():
        parser.error(f"refusing to overwrite an existing run: {out}")
    out.mkdir(parents=True)
    if args.submission:
        shutil.copyfile(args.submission,out/'zqhj_submission.py')
    env = dict(os.environ)
    overrides = {
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join([str(out),str(sim_root), str(PROJECT_ROOT / "src")]),
        "OPENSIM_SIM_STDERR": str(out / "engine.stderr.log"),
    }
    # An inherited terrain override changes the judge's map. Refuse it explicitly.
    if env.get("OPENSIM_TERRAIN_CSV"):
        parser.error("OPENSIM_TERRAIN_CSV is set; remove that override before a baseline run")
    env.update(overrides)
    selected_scenario = scenario
    if real:
        raw = json.loads(scenario.read_text(encoding="utf-8-sig"))
        transport = raw.get("simulation", {})
        if transport.get("redis_port", 6379) != args.redis_port or transport.get("redis_host", "127.0.0.1") != "127.0.0.1":
            raw.setdefault("simulation", {}).update(redis_port=args.redis_port, redis_host="127.0.0.1")
            selected_scenario = out / "scenario_transport.json"
            write_json(selected_scenario, raw)
    argv = [str(python_exe), "-B", "-u", "-m", "competition", "run"]
    if args.mode == "help":
        argv += ["--help"]
    elif args.mode == "check":
        argv = [str(python_exe), "-B", "-u", str(PROJECT_ROOT / "tools" / "check_contract.py")]
    elif args.mode == "test":
        argv = [str(python_exe), "-B", "-u", "-m", "unittest", "discover", "-s", str(PROJECT_ROOT / "tests"), "-v"]
    elif args.mode == "score-smoke":
        argv = [str(python_exe), "-B", "-u", "-m", "examples._common.tests.score_e2e_smoke"]
    elif args.mode == 'collect':
        argv = [str(python_exe),'-B','-u',str(PROJECT_ROOT/'tools/collect_rollout.py'),
                '--agent',args.agent,'--duration',str(duration),'--seed',str(args.seed),
                '--scenario-json',str(selected_scenario),'--sim-binary',str(engine),
                '--redis-port',str(args.redis_port),'--output',str(out)]
    else:
        argv += ["--scenario", "coop_decoy", "--agent", args.agent or OFFICIAL_AGENT,
                 "--seed", str(args.seed), "--duration", str(duration), "--mode", "train",
                 "--photo-mode", "auto", "--scenario-json", str(selected_scenario),
                 "--output", str(out / "official"), "--redis-host", "127.0.0.1",
                 "--redis-port", str(args.redis_port)]
        if args.mode == "dry-run":
            argv += ["--dry-run", "--no-start-sim"]
        else:
            argv += ["--start-sim", "--sim-binary", str(engine)]
    meta = {
        "mode": args.mode, "argv": argv, "command_line": subprocess.list2cmdline(argv),
        "launcher_argv": [sys.executable, *sys.argv], "launcher_cwd": str(Path.cwd()),
        "cwd": str(sim_root), "project_root": str(PROJECT_ROOT), "python": str(python_exe),
        "seed": args.seed if args.mode not in {"help", "check", "test", "score-smoke"} else None,
        "requested_sim_seconds": duration if args.mode not in {"help", "check", "test", "score-smoke"} else None,
        "started_utc": datetime.now(timezone.utc).isoformat(), "environment_overrides": overrides,
        "release_version": (sim_root / "VERSION").read_text(encoding="utf-8-sig"),
        "source_sha256": {str(p.relative_to(sim_root)): sha256(p) for p in [scenario, sim_root / "SDK-API.md", sim_root / "competition" / "baselines" / "coop_distributed.py"]},
        "project_source_sha256": {str(p.relative_to(PROJECT_ROOT)): sha256(p)
                                  for p in sorted((PROJECT_ROOT / "src").glob("*.py"))},
        "submission_sha256": sha256(out/'zqhj_submission.py') if args.submission else None,
        "status": "starting", "real_engine": real,
        "limitations": ["Fixed seed does not fix decoy routes or perception RNG in this release.",
                        "Official SDK suppresses engine stdout; engine stderr is retained.",
                        "No UE renderer is launched; camera delivery is not verified."]}
    meta_path = out / "run.json"
    write_json(meta_path, meta)
    print(f"RUN_DIR={out}", flush=True)
    print(meta["command_line"], flush=True)
    started = time.perf_counter()
    owned_redis = None
    redis_log = None
    exit_code = 1
    try:
        environment_result = subprocess.run([str(python_exe), "-B", "-c",
            'import sys,json,importlib.metadata as m; print(json.dumps({"executable":sys.executable,"version":sys.version,"packages":{p:m.version(p) for p in ("redis","pyyaml","pip")}}))'],
            cwd=sim_root, env=env, capture_output=True, text=True, encoding="utf-8", check=True)
        meta["python_environment"] = json.loads(environment_result.stdout)
        if needs_redis:
            import redis
            # Bind probe plus checking the actual child avoids reusing or stopping an unrelated service.
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", args.redis_port))
            redis_dir = out / "redis"
            redis_dir.mkdir()
            redis_argv = [str(redis_exe), "--bind", "127.0.0.1", "--protected-mode", "yes",
                          "--port", str(args.redis_port), "--save", "", "--appendonly", "no",
                          "--dir", str(redis_dir), "--logfile", str(redis_dir / "redis.log")]
            meta["redis_argv"] = redis_argv
            redis_log = (redis_dir / "console.log").open("wb")
            owned_redis = subprocess.Popen(redis_argv, cwd=sim_root, env=env,
                stdout=redis_log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            meta["redis_pid"] = owned_redis.pid
            connection = redis.Redis(host="127.0.0.1", port=args.redis_port,
                                     socket_connect_timeout=0.3, socket_timeout=0.3)
            deadline = time.monotonic() + 8
            try:
                while True:
                    if owned_redis.poll() is not None:
                        raise RuntimeError("owned Redis exited before becoming ready; see redis logs")
                    try:
                        if connection.ping():
                            break
                    except redis.RedisError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError("owned Redis did not become ready")
                    time.sleep(0.2)
                meta["redis_server"] = {k: connection.info("server").get(k) for k in ("redis_version", "process_id", "run_id")}
            finally:
                connection.close()
        meta["status"] = "running"
        write_json(meta_path, meta)
        with (out / "console.log").open("wb") as log:
            result = subprocess.run(argv, cwd=sim_root, env=env, stdout=log, stderr=subprocess.STDOUT)
        meta["cli_exit_code"] = result.returncode
        exit_code = result.returncode
        evaluations = sorted((out / "official").glob("*.evaluation.json"))
        meta["evaluation_files"] = [str(p.relative_to(out)) for p in evaluations]
        if args.mode not in {"help", "check", "test", "score-smoke"} and not evaluations:
            raise RuntimeError("official CLI produced no evaluation file (even a CLI exit 0 is insufficient)")
        if evaluations:
            evaluation = json.loads(evaluations[-1].read_text(encoding="utf-8"))
            timeline = evaluation.get("score_timeline", [])
            last_t = max((row["sim_time"] for row in timeline), default=0)
            meta["last_score_sim_seconds"] = last_t
            meta["official_result"] = {k: evaluation.get(k) for k in ("total_score", "base_score", "penalty", "passed", "n_destroyed", "n_targets", "dimension_scores", "n_reports", "targeting_rmse_m", "tick_count")}
            if real and (evaluation.get("n_targets") != 3 or last_t < duration - 1):
                raise RuntimeError("evaluation exists but expected three targets/full requested duration were not verified")
        meta["status"] = "completed" if exit_code == 0 else "failed"
    except Exception as exc:
        meta.update(status="failed", error=repr(exc))
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        exit_code = exit_code or 1
    finally:
        if owned_redis is not None and owned_redis.poll() is None:
            owned_redis.terminate()
            try:
                owned_redis.wait(timeout=5)
            except subprocess.TimeoutExpired:
                owned_redis.kill()
                owned_redis.wait(timeout=5)
        if owned_redis is not None:
            meta["redis_exit_code"] = owned_redis.returncode
        if redis_log is not None:
            redis_log.close()
        meta.update(exit_code=exit_code, elapsed_seconds=round(time.perf_counter() - started, 3),
                    finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(meta_path, meta)
    print(json.dumps({k: meta.get(k) for k in ("status", "exit_code", "elapsed_seconds", "official_result", "error")}, ensure_ascii=False), flush=True)
    print(f"EVIDENCE={meta_path}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
