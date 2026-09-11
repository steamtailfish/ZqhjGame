"""Record package hashes without inspecting third-party or UE asset contents."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    paths = ["VERSION", "README.md", "SDK-API.md", "setup.ps1", "start.ps1", "stop.ps1",
             "verify.ps1", "preflight-check.ps1", "opensim-sim.exe", "bin/redis-server.exe",
             "bin/node.exe", "python/python.exe", "config/defaults.json", "config/terrain_bbox.json",
             "config/HeightSample.csv", "config/GridDataAll_18.csv", "config/points.json",
             "config/random_routes_20.json", "config/models/uav.json", "config/models/gimbal.json",
             "config/renderers/ue_testwl.json", "config/schema/sim-commands.schema.json",
             "config/schema/sim-state.schema.json", "competition/__main__.py", "competition/sdk/cli.py",
             "competition/scenarios/coop_decoy/scenario.json", "competition/scenarios/coop_decoy/config/algorithm.yaml",
             "competition/baselines/coop_distributed.py", "competition/user_algorithms/README.md",
             "ue-renderer/Windows/testwl/Content/Config/capture_config.json",
             "红枫2026无人集群自主协同智能算法挑战赛参赛手册.docx"]
    paths += [str(p.relative_to(root)).replace("\\", "/") for directory in
              ("competition/sdk/core", "competition/sdk/scenarios/coop_decoy", "competition/sdk/_vendored")
              for p in (root / directory).rglob("*.py")]
    paths += ["competition/sdk/scenarios/_astar_navigator.py"]
    inventory = []
    for name in sorted(set(paths)):
        path = root / name
        with path.open("rb") as source:
            digest = hashlib.sha256()
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        inventory.append({"path": name, "bytes": path.stat().st_size,
                          "sha256": digest.hexdigest()})
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True)
    result = {"recorded_utc": datetime.now(timezone.utc).isoformat(), "git_commit": proc.stdout.strip(),
              "version": (root / "VERSION").read_text(encoding="utf-8-sig"),
              "python": {"executable": sys.executable, "version": sys.version,
                         "packages": {p: importlib.metadata.version(p) for p in ("redis", "pyyaml", "pip")}},
              "platform": platform.platform(), "files": inventory,
              "note": "Hashes identify this local package; they are not an organizer signature. Hashing does not mean every file was read; consult ENVIRONMENT_AUDIT for review scope."}
    output = project / "docs" / "release_manifest.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Recorded {len(inventory)} files: {output}")


if __name__ == "__main__":
    main()
