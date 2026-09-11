"""Verify the current handoff assets after git lfs pull; no simulator needed."""
import hashlib
import json
from pathlib import Path


def verify(root, manifest):
    root = Path(root).resolve()
    failures = []
    for item in manifest['files']:
        path = (root / item['path']).resolve()
        if not path.is_relative_to(root / 'artifacts'):
            failures.append((item['path'], 'path outside artifacts'))
            continue
        if not path.is_file():
            failures.append((item['path'], 'missing; run git lfs pull'))
            continue
        with path.open('rb') as stream:
            prefix = stream.read(128)
            if prefix.startswith(b'version https://git-lfs.github.com/spec/v1'):
                failures.append((item['path'], 'LFS pointer; run git lfs pull'))
                continue
            if path.stat().st_size != item['bytes']:
                failures.append((item['path'], 'size mismatch'))
                continue
            stream.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != item['sha256']:
            failures.append((item['path'], 'SHA256 mismatch'))
    return failures


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'docs/V22_ASSETS.json').read_text(encoding='utf-8'))
    failures = verify(root, manifest)
    if failures:
        for path, reason in failures:
            print(f'{reason}: {path}')
        raise SystemExit(1)
    print(f"Verified {len(manifest['files'])} v22 assets: "
          f"{sum(item['bytes'] for item in manifest['files']) / 1024**2:.1f} MiB")


if __name__ == '__main__':
    main()
