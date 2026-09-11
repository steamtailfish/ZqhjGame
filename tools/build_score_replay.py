"""Build a bounded, self-contained replay of completed own-observation logs."""
import argparse,base64,json,math
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageDraw
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
run=json.loads((a.run/'run.json').read_text());assert run['status']=='completed'
evaluation=json.loads(next((a.run/'official').glob('*.evaluation.json')).read_text())
end=int(run['last_sim_s']);coop=sum(v['coop_ticks'] for v in evaluation['per_target'].values())
def encoded(im):
    stream=BytesIO();im.save(stream,format='JPEG',quality=42);return 'data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode()
agents=[]
for log in sorted((a.run/'observations').glob('*/observations.jsonl')):
    rows=[json.loads(s) for s in log.read_text(encoding='utf-8').splitlines()];points=[];photos=[]
    for r in rows:
        o=r['own'];d=r['diagnostics'];points.append([round(r['score_sim_s'],2),round((o['lon']-125)*111320*math.cos(math.radians(27)),1),round((o['lat']-27)*111320,1),d['state'],d['public_peer_count']])
    eligible=[r for r in rows if r.get('boxes_photo_sha256') and (log.parent/(r['boxes_photo_sha256']+'.image')).is_file()]
    used=set()
    samples=(5,20,40,55,65,75,85,100,120,150,175) if end<=200 else [end*i/10 for i in range(11)]
    for t in samples:
        r=min(eligible,key=lambda r:abs(r['score_sim_s']-t));digest=r['boxes_photo_sha256']
        if digest in used:continue
        used.add(digest);im=Image.open(log.parent/(digest+'.image')).convert('RGB');b=r['diagnostics'].get('chosen_pixel');crop=None;label='无跟踪框'
        if b:
            u,v=(b['x1']+b['x2'])/2,(b['y1']+b['y2'])/2;x,y=int(u)-64,int(v)-64
            crop=im.crop((x,y,x+128,y+128));ImageDraw.Draw(crop).rectangle((b['x1']-x,b['y1']-y,b['x2']-x,b['y2']-y),outline='red',width=2)
            ImageDraw.Draw(im).rectangle((b['x1'],b['y1'],b['x2'],b['y2']),outline='red',width=3)
            label=f"{b['category']} {b['confidence']:.2f}"
        im.thumbnail((384,288));photos.append(dict(t=r['score_sim_s'],label=label,full=encoded(im),crop=encoded(crop) if crop else None))
    agents.append(dict(uid=log.parent.name,rows=points,photos=photos))
template=(Path(__file__).parent/'score_replay_template.html').read_text(encoding='utf-8')
text=template.replace('__REPLAY_DATA__',json.dumps(dict(agents=agents),ensure_ascii=False,separators=(',',':')))
text=text.replace('__MAX_TIME__',str(end)).replace('__RUN_TITLE__',f"{run['duration_sim_s']:g}秒实测回放 · 官方{evaluation['total_score']:g}分 · 真目标协同跟踪{coop}拍")
assert len(text.encode())<1_000_000
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text,encoding='utf-8');print(a.output,len(text.encode()))
