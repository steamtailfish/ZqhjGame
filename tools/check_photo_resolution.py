"""Offline resolution ablation on completed own-photo recordings.

Regions are diagnostic viewing locations, not accepted labels or training data.
"""
import argparse,json,sys,time,os
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_vision import PhotoDetector
import torch,cv2
runtime=Path(__file__).resolve().parents[1]/'artifacts/vision/.runtime-resolution'
runtime.mkdir(exist_ok=True)
(runtime/'Ultralytics').mkdir(exist_ok=True)
os.environ['YOLO_CONFIG_DIR']=str(runtime);os.environ['YOLO_OFFLINE']='true';os.environ['YOLO_AUTOINSTALL']='false'
from ultralytics import YOLO
p=argparse.ArgumentParser();p.add_argument('--views',type=Path,required=True);p.add_argument('--weights',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
torch.set_num_threads(4);cv2.setNumThreads(1);model=YOLO(str(a.weights));rows=[]
for size in (1024,1536,2048):
    detector=PhotoDetector(model.model.fuse(verbose=False),size=size,confidence=.25,names=tuple(model.names.values()));detector.warmup()
    for r in json.loads(a.views.read_text()):
        u,v=r['projected']
        if not 0<u<1024 or not 0<v<768:continue
        start=time.perf_counter();boxes=detector(Path(r['photo']).read_bytes());elapsed=time.perf_counter()-start
        near=[b for b in boxes if abs(b.center[0]-u)<25 and abs(b.center[1]-v)<25]
        rows.append(dict(size=size,photo=r['photo'],t=r['t'],inference_wall_s=elapsed,near_diagnostic_region=[asdict(b) for b in near],all_boxes=[asdict(b) for b in boxes]))
a.output.write_text(json.dumps(dict(scope='Offline resolution ablation, not official score or manual labels',rows=rows),indent=2),encoding='utf-8')
for size in (1024,1536,2048):
    selected=[r for r in rows if r['size']==size]
    print(size,[(round(r['t'],1),[(b['category'],round(b['confidence'],2)) for b in r['near_diagnostic_region']]) for r in selected],sum(r['inference_wall_s'] for r in selected)/len(selected))
