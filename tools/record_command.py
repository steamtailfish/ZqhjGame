"""Run an argv list without a shell and retain the command, log and exit status."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--cwd", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not argv:
        parser.error("command is required after --")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out = Path(__file__).resolve().parents[1] / "artifacts" / "checks" / (stamp + "-" + args.label)
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    meta = {"argv": argv, "command_line": subprocess.list2cmdline(argv),
            "cwd": str(args.cwd.resolve()), "started_utc": datetime.now(timezone.utc).isoformat(),
            "environment_overrides": {k: env[k] for k in ("PYTHONDONTWRITEBYTECODE", "PYTHONUTF8", "PYTHONIOENCODING")}}
    start = time.perf_counter()
    with (out / "console.log").open("wb") as log:
        result = subprocess.run(argv, cwd=args.cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    meta.update(exit_code=result.returncode, elapsed_seconds=round(time.perf_counter() - start, 3))
    (out / "command.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print((out / "console.log").read_text(encoding="utf-8", errors="replace"))
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"ARTIFACT_DIR={out}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
