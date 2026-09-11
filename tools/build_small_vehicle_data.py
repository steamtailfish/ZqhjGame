"""Scale reviewed training crops and add the 36 explicitly inspected rocks.

No judge trace, coordinates, IDs or diagnostic true-target views are consumed.
Validation remains the unchanged controlled height200 episodes.
"""
import json,hashlib
from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]
out=root/'artifacts/vision/datasets/small-review-v5';out.mkdir(exist_ok=False)
rows=list(map(json.loads,(root/'artifacts/vision/datasets/background-review-v1/accepted.jsonl').read_text().splitlines()))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
for r in list(rows):
    if r['episode'] not in ('true-v2','decoy-v1'):continue
    for scale in (.45,.65):
        original=Image.open(r['image']).convert('RGB');w,h=original.size;sw,sh=round(w*scale),round(h*scale);left,top=(256-sw)//2,(256-sh)//2
        image=Image.new('RGB',(256,256),(114,114,114));image.paste(original.resize((sw,sh),Image.Resampling.BILINEAR),(left,top))
        path=out/(r['id']+f'-scale{scale}.png');image.save(path)
        boxes=[dict(x1=b['x1']*sw/w+left,x2=b['x2']*sw/w+left,y1=b['y1']*sh/h+top,y2=b['y2']*sh/h+top,category=b['category']) for b in r['boxes']]
        rows.append(dict(r,id=path.stem,image=str(path),sha256=sha(path),boxes=boxes,augmentation={'scale':scale,'parent_sha256':r['sha256']},review_evidence=r['review_evidence']+'; deterministic image/box resize of reviewed train crop, no new object labels'))
run=root/'artifacts/vision/runs/score600-seed101'
assert json.loads((run/'run.json').read_text())['status']=='completed'
for log in sorted((run/'observations').glob('*/observations.jsonl')):
    records=list(map(json.loads,log.read_text().splitlines()))
    eligible=[r for r in records if r['diagnostics'].get('chosen_pixel') and (log.parent/(str(r.get('boxes_photo_sha256'))+'.image')).is_file()]
    for i,r in enumerate(eligible[::max(1,len(eligible)//12)][:12]):
        b=r['diagnostics']['chosen_pixel'];source=log.parent/(r['boxes_photo_sha256']+'.image');x=int((b['x1']+b['x2'])/2)-96;y=int((b['y1']+b['y2'])/2)-96
        path=out/f'rock101-{log.parent.name}-{i:02d}.png';Image.open(source).convert('RGB').crop((x,y,x+192,y+192)).save(path)
        rows.append(dict(id=path.stem,episode=run.name,uid=log.parent.name,image=str(path),sha256=sha(path),source='official_public_self_photo_export',source_photo=str(source),source_photo_sha256=r['boxes_photo_sha256'],crop_xyxy=[x,y,x+192,y+192],boxes=[],review_status='accepted',reviewer='Codex visual review',review_evidence='All 36 complete crops manually inspected in artifacts/checks/score101-selected.png: rocks, trees, shadows; no physical vehicle. Only these crops are negatives.'))
(out/'accepted.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows),encoding='utf-8');print(len(rows),out/'accepted.jsonl')
