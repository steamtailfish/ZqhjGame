"""Check the recorded official release hashes without modifying that release."""
import argparse,ast,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];manifest=json.loads((root/'docs/release_manifest.json').read_text(encoding='utf-8'))
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
changed=[]
for item in manifest['files']:
    path=root.parent/item['path']
    if not path.is_file() or sha(path)!=item['sha256']:changed.append(item['path'])
sources={}
for folder in ('src','tools','tests','learning'):
    for path in (root/folder).glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8-sig'));sources[str(path.relative_to(root))]=sha(path)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(dict(official_files_checked=len(manifest['files']),official_changed=changed,
    source_syntax_count=len(sources),sources_sha256=sources),ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Official files checked: {len(manifest["files"])}; changed: {len(changed)}; parsed sources: {len(sources)}')
if changed:raise SystemExit(1)
