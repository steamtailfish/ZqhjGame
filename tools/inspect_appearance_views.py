"""Post-run appearance diagnostic; projections never enter model inference.

An approximate projected region is not a reviewed training label or a measured
recognition benchmark. This command does not modify datasets or Agents.
"""
import argparse,json,sys,math,hashlib
from pathlib import Path
import torch,cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_patch_vision import VehicleAppearance,PatchPhotoDetector

p=argparse.ArgumentParser();p.add_argument('--weights',type=Path,required=True)
p.add_argument('--views',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
torch.set_num_threads(2);cv2.setNumThreads(1)
model=VehicleAppearance();model.load_state_dict(torch.load(a.weights,map_location='cpu',weights_only=True))
detector=PatchPhotoDetector(model,confidence=.45);detector.warmup()
views=json.loads(a.views.read_text(encoding='utf-8'));rows=[]
for v in views:
    photo=Path(v['photo']);run=photo.parents[2]
    if json.loads((run/'run.json').read_text(encoding='utf-8'))['status']!='completed':raise ValueError('completed run only')
    boxes=detector(photo.read_bytes())
    nearby=[b for b in boxes if math.dist(b.center,v['projected'])<45.]
    rows.append(dict(uid=v['uid'],t=v['t'],photo=str(photo),
        nearby=[dict(category=b.category,confidence=b.confidence,margin=b.class_margin,center=b.center) for b in nearby],
        strong_true_count=sum(b.category=='true_vehicle' and b.confidence>=.95 and b.class_margin>=.9 for b in boxes)))
result=dict(scope='post-run approximate-region diagnostic only; not reviewed labels or competition score',
    weights_sha256=hashlib.sha256(a.weights.read_bytes()).hexdigest(),rows=rows,
    views_with_nearby_true=sum(any(b['category']=='true_vehicle' for b in r['nearby']) for r in rows),
    views_with_nearby_strong_true=sum(any(b['category']=='true_vehicle' and b['confidence']>=.95 and b['margin']>=.9 for b in r['nearby']) for r in rows),
    all_strong_true_boxes=sum(r['strong_true_count'] for r in rows))
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
print({k:v for k,v in result.items() if k!='rows'})
