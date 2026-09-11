"""Completed-run diagnostic: render regions near actual judge-effective targets.

Ground truth is only an offline annotation, not training labels or Agent input.
"""
import argparse,json,math,sys
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_localization import camera_basis
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('trace',type=Path);p.add_argument('analysis',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
assert json.loads((a.run/'run.json').read_text())['status']=='completed'
trace=json.loads(a.trace.read_text())['rows'];timeline=json.loads(a.analysis.read_text())['timeline'];tiles=[];details=[]
for uid in ('20001','20002','20003'):
    folder=a.run/'observations'/uid;logs=list(map(json.loads,(folder/'observations.jsonl').read_text().splitlines()))
    offsets=[]
    for row in trace[::max(1,len(trace)//30)]:
        e=next(e for e in row['entities'] if e['uid']==uid)
        r=min(logs,key=lambda r:(r['own']['lat']-e['lat'])**2+(r['own']['lon']-e['lon'])**2)
        offsets.append(row['engine_sim_time']-r['score_sim_s'])
    offset=sorted(offsets)[len(offsets)//2]
    effective=[r for r in timeline if r['matches'][uid]['is_effective']]
    picked=[]
    for r in effective:
        if picked and r['t']-picked[-1]['t']<3:continue
        picked.append(r)
    available=[r for r in logs if (folder/(str(r.get('photo_sha256'))+'.image')).is_file()]
    for effective in picked[:12]:
        t=effective['t']-offset;r=min(available,key=lambda r:abs(r['score_sim_s']-t))
        row=min(trace,key=lambda row:abs(row['engine_sim_time']-offset-r['score_sim_s']))
        target=next(e for e in row['entities'] if e['uid']==effective['matches'][uid]['target_uid'])
        own=r['own'];path=folder/(r['photo_sha256']+'.image');im=Image.open(path).convert('RGB');w,h=im.size
        basis=camera_basis(own['gimbal_pan'],own['gimbal_tilt'],own['heading_deg'],'heading_plus_pan')
        rel=((target['lon']-own['lon'])*111320*math.cos(math.radians(own['lat'])),(target['lat']-own['lat'])*111320,target['alt']-own['alt'])
        forward=sum(x*y for x,y in zip(rel,basis[0]));focal=w/(2*math.tan(math.radians(own['gimbal_fov_deg']/2)))
        u=(w-1)/2+focal*sum(x*y for x,y in zip(rel,basis[1]))/max(1,forward)
        v=(h-1)/2+focal*sum(x*y for x,y in zip(rel,basis[2]))/max(1,forward)
        crop=im.crop((int(u)-128,int(v)-128,int(u)+128,int(v)+128))
        tile=Image.new('RGB',(420,310),'white');tile.paste(crop,(0,0));small=im.copy();small.thumbnail((160,120));tile.paste(small,(260,0))
        d=ImageDraw.Draw(tile);d.ellipse((123,123,133,133),outline='red',width=1)
        d.text((4,262),f'{uid} t={r["score_sim_s"]:.1f} true={target["uid"]}',fill='black')
        d.text((4,280),'Estimated projection only; NOT a manual label',fill='black');tiles.append(tile)
        details.append(dict(uid=uid,t=r['score_sim_s'],photo=str(path),projected=[u,v],target_uid=target['uid'],offset=offset))
sheet=Image.new('RGB',(420*3,310*max(1,math.ceil(len(tiles)/3))),'white')
for i,tile in enumerate(tiles):sheet.paste(tile,(i%3*420,i//3*310))
a.output.parent.mkdir(parents=True,exist_ok=True);sheet.save(a.output);a.output.with_suffix('.json').write_text(json.dumps(details,indent=2),encoding='utf-8')
print(a.output)
