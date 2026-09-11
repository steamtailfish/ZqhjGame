"""Compare orientation robustness on the existing held-out fixture crops.

Rotations are derived validation views, not new scenes or competition scores.
"""
import argparse,json,sys
from pathlib import Path
from io import BytesIO
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from vision_support import load_detector,write,sha
p=argparse.ArgumentParser();p.add_argument('--weights',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--scale',type=float,default=1.);a=p.parse_args()
if not 0<a.scale<=1:raise ValueError('scale must be within (0,1]')
root=Path(__file__).resolve().parents[1]
records=[json.loads(s) for s in (root/'artifacts/vision/datasets/fixture-crops-v1/accepted.jsonl').read_text(encoding='utf-8').splitlines()]
records=[r for r in records if r['episode'] in ('true-height200','decoy-height200')]
def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)
results=[]
for path in a.weights:
    detector=load_detector(path,size=256,confidence=.45,device='cpu');angles=[]
    for rotation in range(4):
        total=found=correct=report_ready=0;matched_details=[]
        for row in records:
            im=Image.open(row['image']).convert('RGB');labels=[([b[k] for k in ('x1','y1','x2','y2')],b['category']) for b in row['boxes']]
            if a.scale<1:
                width,height=im.size;small=im.resize((round(width*a.scale),round(height*a.scale)),Image.Resampling.BILINEAR)
                sx,sy=small.width/width,small.height/height;left,top=(width-small.width)//2,(height-small.height)//2
                canvas=Image.new('RGB',im.size,(114,114,114));canvas.paste(small,(left,top));im=canvas
                labels=[([box[0]*sx+left,box[1]*sy+top,box[2]*sx+left,box[3]*sy+top],category) for box,category in labels]
            for _ in range(rotation):
                width,height=im.size;im=im.transpose(Image.Transpose.ROTATE_90)
                labels=[([box[1],width-box[2],box[3],width-box[0]],category) for box,category in labels]
            stream=BytesIO();im.save(stream,format='PNG');boxes=detector(stream.getvalue())
            for target,category in labels:
                total+=1;best=max(boxes,key=lambda b:iou(target,[b.x1,b.y1,b.x2,b.y2]),default=None)
                if best is None or iou(target,[best.x1,best.y1,best.x2,best.y2])<.3:continue
                found+=1;correct+=int(best.category==category)
                report_ready+=int(best.category==category=='true_vehicle' and best.confidence>=.9 and best.class_margin>=.6)
                matched_details.append(dict(actual=category,predicted=best.category,confidence=best.confidence,margin=best.class_margin))
        angles.append(dict(rotation_deg=rotation*90,targets=total,matched=found,correct_identity=correct,true_identity_gate=report_ready,matched_details=matched_details))
    results.append(dict(weights=str(path),sha256=sha(path),angles=angles))
write(a.output,dict(scope='Derived rotations of original held-out fixture crops; same-layout limitation remains',scale=a.scale,models=results));print(a.output)
