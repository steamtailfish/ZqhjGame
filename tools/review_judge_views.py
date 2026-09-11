"""Post-run photo inspection at closest true-target viewing directions.

Uses judge truth ONLY for diagnostic annotations, never training labels.
"""
import argparse,json,math,sys
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_localization import camera_basis
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('trace',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
run=json.loads((a.run/'run.json').read_text());assert run['status']=='completed'
trace=json.loads(a.trace.read_text(encoding='utf-8'))['rows'];tiles=[];details=[]
for uid in ('20001','20002','20003'):
    folder=a.run/'observations'/uid;logs=[json.loads(s) for s in (folder/'observations.jsonl').read_text(encoding='utf-8').splitlines()]
    # Align clocks from nearest own-position observations, not an assumed epoch.
    offsets=[]
    for row in trace[::max(1,len(trace)//20)]:
        e=next(e for e in row['entities'] if e['uid']==uid)
        r=min(logs,key=lambda r:(r['own']['lat']-e['lat'])**2+(r['own']['lon']-e['lon'])**2)
        offsets.append(row['engine_sim_time']-r['score_sim_s'])
    offset=sorted(offsets)[len(offsets)//2];candidates=[]
    for row in trace:
        e=next(e for e in row['entities'] if e['uid']==uid);g=e['gimbal'];basis=camera_basis(g['pan_angle'],g['tilt_angle'],e['heading'],'heading_plus_pan')
        for target in row['entities']:
            if target['kind']!='ground_vehicle':continue
            rel=((target['lon']-e['lon'])*111320*math.cos(math.radians(e['lat'])),(target['lat']-e['lat'])*111320,target['alt']-e['alt'])
            dot=sum(x*y for x,y in zip(rel,basis[0]));norm=math.sqrt(sum(x*x for x in rel))
            angle=math.degrees(math.acos(max(-1,min(1,dot/max(norm,1e-9)))))
            candidates.append((angle,row['engine_sim_time']-offset,row,e,target,rel,basis))
    picked=[]
    for c in sorted(candidates,key=lambda c:c[0]):
        if any(abs(c[1]-q[1])<20 for q in picked):continue
        picked.append(c)
        if len(picked)==2:break
    for angle,t,row,e,target,rel,basis in picked:
        available=[r for r in logs if (folder/(str(r.get('photo_sha256'))+'.image')).is_file()]
        r=min(available,key=lambda r:abs(r['score_sim_s']-t));path=folder/(r['photo_sha256']+'.image')
        im=Image.open(path).convert('RGB');im.thumbnail((512,384))
        tile=Image.new('RGB',(512,440),'white');tile.paste(im);d=ImageDraw.Draw(tile)
        d.text((5,386),f"{uid} t~{t:.1f}s photo={r['score_sim_s']:.1f}s",fill='black')
        d.text((5,404),f"Closest true angle {angle:.1f} deg; target {target['uid']}",fill='black')
        detection=e['gimbal'].get('detection') or {};d.text((5,422),f"engine detected={detection.get('detected')} type={detection.get('target_type')}",fill='black')
        tiles.append(tile);details.append(dict(uid=uid,approximate_public_time=t,photo_time=r['score_sim_s'],angle=angle,source_photo=str(path),target=target,own=e,clock_offset_estimate=offset))
sheet=Image.new('RGB',(1024,440*((len(tiles)+1)//2)),'white')
for i,tile in enumerate(tiles):sheet.paste(tile,((i%2)*512,(i//2)*440))
a.output.parent.mkdir(parents=True,exist_ok=True);sheet.save(a.output)
a.output.with_suffix('.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
print(a.output)
