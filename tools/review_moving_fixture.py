"""Propose controlled-fixture patches for explicit manual image review.

Never accepts model predictions as labels. Outputs pending records and sheets.
"""
import argparse,json,sys,hashlib,math
from pathlib import Path
import numpy as np,torch,cv2
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_patch_vision import VehicleAppearance,vehicle_proposals,vehicle_patch
p=argparse.ArgumentParser();p.add_argument('fixture',type=Path);p.add_argument('output',type=Path);p.add_argument('--appearance',type=Path,required=True)
p.add_argument('--times',nargs='+',type=float,default=[12.,18.,23.]);a=p.parse_args()
assert json.loads((a.fixture/'run.json').read_text())['status']=='completed'
a.output.mkdir(exist_ok=False,parents=True);torch.set_num_threads(4);cv2.setNumThreads(1)
model=VehicleAppearance();model.load_state_dict(torch.load(a.appearance,weights_only=True));model.eval();records=[];tiles=[]
kind=json.loads((a.fixture/'fixture-manifest.json').read_text())['kind'];category='true_vehicle' if kind=='true' else 'decoy_vehicle'
for uid in ('20001','20002','20003'):
    folder=a.fixture/'observations'/uid;rows=list(map(json.loads,(folder/'observations.jsonl').read_text().splitlines()))
    available=[r for r in rows if (folder/(str(r.get('photo_sha256'))+'.image')).is_file()]
    for wanted in a.times:
        r=min(available,key=lambda r:abs(r['score_sim_s']-wanted));source=folder/(r['photo_sha256']+'.image');im=Image.open(source).convert('RGB');rgb=np.array(im);boxes=vehicle_proposals(rgb)
        if not boxes:continue
        patches=np.stack([vehicle_patch(rgb,b) for b in boxes]).transpose(0,3,1,2).copy()
        with torch.inference_mode():prob=model(torch.tensor(patches).float()/255).softmax(1).numpy();rank=np.argsort(prob[:,:2].max(1))[::-1][:18]
        for j in rank:
            b=boxes[j];x,y=round((b[0]+b[2])/2)-48,round((b[1]+b[3])/2)-48;crop=im.crop((x,y,x+96,y+96));index=len(records);name=f'{a.fixture.name}-{index:03d}'
            image=Image.new('RGB',(256,256),(114,114,114));image.paste(crop,(80,80));path=a.output/(name+'.png');image.save(path)
            relative=dict(x1=b[0]-x+80,y1=b[1]-y+80,x2=b[2]-x+80,y2=b[3]-y+80,category=category)
            records.append(dict(id=name,index=index,episode=a.fixture.name,uid=uid,image=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source='controlled_moving_fixture_own_photo',source_photo=str(source),source_photo_sha256=r['photo_sha256'],observation_sim_s=r['score_sim_s'],crop_xyxy=[x,y,x+96,y+96],boxes=[relative],review_status='pending',reviewer=None,review_evidence=None,label_source='fixture class hint; bounding box and physical vehicle require manual review'))
            preview=crop.resize((144,144));d=ImageDraw.Draw(preview);d.rectangle(tuple((v-(x if k%2==0 else y))*1.5 for k,v in enumerate(b)),outline='red',width=1)
            tile=Image.new('RGB',(160,180),'white');tile.paste(preview,(8,20));d=ImageDraw.Draw(tile);d.text((4,2),f'{index:03d} {uid} {r["score_sim_s"]:.1f}',fill='black');tiles.append(tile)
for page,start in enumerate(range(0,len(tiles),36)):
    sheet=Image.new('RGB',(960,1080),'white')
    for i,tile in enumerate(tiles[start:start+36]):sheet.paste(tile,(i%6*160,i//6*180))
    sheet.save(a.output/f'review-{page}.png')
(a.output/'pending.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in records),encoding='utf-8');print(len(records),a.output)
