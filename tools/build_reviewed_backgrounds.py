"""Reproduce the 36 background crops manually reviewed in selected.png.

Fixed completed recording, no automatic conversion of detections into labels.
All backgrounds belong to train; validation retains original fixture episodes.
"""
import json,hashlib
from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]
run=root/'artifacts/vision/runs/team180-seed90'
out=root/'artifacts/vision/datasets/background-review-v1';out.mkdir(exist_ok=False)
rows=[json.loads(s) for s in (root/'artifacts/vision/datasets/fixture-crops-v1/accepted.jsonl').read_text().splitlines()]
for log in sorted((run/'observations').glob('*/observations.jsonl')):
    records=[json.loads(s) for s in log.read_text().splitlines()]
    eligible=[r for r in records if r['diagnostics'].get('chosen_pixel') and (log.parent/(str(r.get('boxes_photo_sha256'))+'.image')).is_file()]
    for i,r in enumerate(eligible[::max(1,len(eligible)//12)][:12]):
        b=r['diagnostics']['chosen_pixel'];source=log.parent/(r['boxes_photo_sha256']+'.image')
        x=int((b['x1']+b['x2'])/2)-96;y=int((b['y1']+b['y2'])/2)-96
        name=f'background-{log.parent.name}-{i:02d}';path=out/(name+'.png')
        with Image.open(source) as im:im.convert('RGB').crop((x,y,x+192,y+192)).save(path)
        rows.append(dict(id=name,episode=run.name,uid=log.parent.name,image=str(path),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source='official_public_self_photo_export',
            source_photo=str(source),source_photo_sha256=r['boxes_photo_sha256'],crop_xyxy=[x,y,x+192,y+192],
            boxes=[],review_status='accepted',reviewer='Codex visual review',
            review_evidence='Inspected all 36 complete 192px crops in artifacts/checks/team180-analysis/selected.png: trees, rocks and shadows, no visible vehicle. Only these inspected crops are negative; the full images are not labelled negative.'))
(out/'accepted.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows),encoding='utf-8')
print(out/'accepted.jsonl')
