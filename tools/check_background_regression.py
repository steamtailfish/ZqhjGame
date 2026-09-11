"""Full-frame inference on manually reviewed background locations, offline.

This is a training regression check, not a held-out accuracy estimate.
"""
import argparse,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from vision_support import load_detector,write,sha
p=argparse.ArgumentParser();p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True)
p.add_argument('--output',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1]
rows=[json.loads(s) for s in (root/'artifacts/vision/datasets/background-review-v1/accepted.jsonl').read_text(encoding='utf-8').splitlines()]
rows=[r for r in rows if r['episode']=='team180-seed90'];results=[]
for weights in (a.before,a.after):
    model=load_detector(weights,size=1024,confidence=.45,device='cpu');matches=[]
    for r in rows:
        boxes=model(Path(r['source_photo']).read_bytes());x1,y1,x2,y2=r['crop_xyxy']
        inside=[b for b in boxes if x1<=b.center[0]<=x2 and y1<=b.center[1]<=y2]
        matches.append(dict(id=r['id'],all_boxes=len(inside),true_candidates=sum(b.category=='true_vehicle' and b.confidence>=.55 for b in inside)))
    results.append(dict(weights=str(weights.resolve()),sha256=sha(weights),images=len(rows),
        false_boxes=sum(r['all_boxes'] for r in matches),false_true_candidates=sum(r['true_candidates'] for r in matches),details=matches))
write(a.output,dict(scope='36 manually reviewed training background locations in full frames; not generalization evidence',models=results))
print(json.dumps([{k:v for k,v in r.items() if k!='details'} for r in results]))
