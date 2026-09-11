"""Train only from reviewed fixture identities and reviewed background crops."""
import argparse,json,sys,random,time,hashlib
from pathlib import Path
import numpy as np
import cv2,torch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_patch_vision import VehicleAppearance,vehicle_patch,vehicle_proposals
p=argparse.ArgumentParser();p.add_argument('--reviewed',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--steps',type=int,default=600)
p.add_argument('--appearance-jitter',action='store_true');p.add_argument('--min-resolution',type=int,default=14);p.add_argument('--threads',type=int,default=4);a=p.parse_args()
if not 8<=a.min_resolution<=64 or not 1<=a.threads<=8:raise ValueError('bounded resolution and thread count required')
a.output.mkdir(exist_ok=False,parents=True);torch.set_num_threads(a.threads);cv2.setNumThreads(1);torch.manual_seed(41);rng=np.random.default_rng(41)
train=[[],[],[]];val=[]
for r in map(json.loads,a.reviewed.read_text(encoding='utf-8').splitlines()):
    if r.get('review_status')!='accepted':raise ValueError('manual review required')
    if 'augmentation' in r:continue
    im=np.array(Image.open(r['image']).convert('RGB'))
    heldout=r['episode'] in ('true-height200','decoy-height200')
    if r['boxes']:
        for b in r['boxes']:
            label=('true_vehicle','decoy_vehicle').index(b['category']);patch=vehicle_patch(im,[b[k] for k in ('x1','y1','x2','y2')])
            if heldout:val.append((patch,label))
            else:train[label].append(patch)
    else:
        boxes=vehicle_proposals(im)
        boxes=sorted(boxes,key=lambda b:(b[0]+b[2]-im.shape[1])**2+(b[1]+b[3]-im.shape[0])**2)[:3]
        if not boxes:boxes=[(im.shape[1]/2-16,im.shape[0]/2-16,im.shape[1]/2+16,im.shape[0]/2+16)]
        train[2].extend(vehicle_patch(im,b) for b in boxes)
print('train',list(map(len,train)),'validation',len(val),flush=True)
def augment(im):
    im=cv2.warpAffine(im,cv2.getRotationMatrix2D((31.5,31.5),float(rng.uniform(0,360)),float(rng.uniform(.8,1.15))),(64,64),borderMode=cv2.BORDER_REFLECT_101)
    if rng.random()<.5:im=im[:,::-1]
    resolution=int(rng.integers(a.min_resolution,65));im=cv2.resize(cv2.resize(im,(resolution,resolution)),(64,64))
    im=np.clip(im.astype(np.float32)*rng.uniform(.75,1.3)+rng.uniform(-8,8),0,255)
    if a.appearance_jitter:
        gray=im@np.array([.299,.587,.114],dtype=np.float32)
        saturation=0. if rng.random()<.25 else rng.uniform(.2,1.5)
        im=gray[...,None]+saturation*(im-gray[...,None])
        im=np.clip((im-128)*rng.uniform(.6,1.5)+128+rng.uniform(-12,12,size=(1,1,3)),0,255)
        im=255*(im/255)**rng.uniform(.65,1.5)
    return im
model=VehicleAppearance();optimizer=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.005);start=time.perf_counter()
for step in range(a.steps):
    labels=np.arange(48)%3;patches=[augment(train[label][int(rng.integers(len(train[label])))]) for label in labels]
    x=torch.tensor(np.stack(patches).transpose(0,3,1,2).copy()).float()/255;y=torch.tensor(labels).long()
    model.train();loss=torch.nn.functional.cross_entropy(model(x),y);optimizer.zero_grad();loss.backward();optimizer.step()
    if step%100==0:print(step,float(loss.detach()),flush=True)
model.eval()
with torch.inference_mode():
    x=torch.tensor(np.stack([v[0] for v in val]).transpose(0,3,1,2).copy()).float()/255;prob=model(x).softmax(1);correct=int((prob.argmax(1)==torch.tensor([v[1] for v in val])).sum())
torch.save(model.state_dict(),a.output/'appearance.pt')
result=dict(steps=a.steps,appearance_jitter=a.appearance_jitter,min_resolution=a.min_resolution,threads=a.threads,elapsed_s=time.perf_counter()-start,train_counts=list(map(len,train)),validation=dict(correct=correct,total=len(val),probabilities=prob.tolist(),labels=[v[1] for v in val]),source=str(a.reviewed.resolve()),source_sha256=hashlib.sha256(a.reviewed.read_bytes()).hexdigest(),weights_sha256=hashlib.sha256((a.output/'appearance.pt').read_bytes()).hexdigest(),scope='Reviewed local appearance, heldout controlled layout only; not competition score')
(a.output/'training.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(correct,len(val),a.output,flush=True)
