"""Offline selected-box review, only after a completed run."""
import argparse,json
from pathlib import Path
from PIL import Image,ImageDraw
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
assert json.loads((a.run/'run.json').read_text())['status']=='completed'
tiles=[]
for log in sorted((a.run/'observations').glob('*/observations.jsonl')):
    rows=[json.loads(s) for s in log.read_text().splitlines()]
    eligible=[r for r in rows if r['diagnostics'].get('chosen_pixel') and (log.parent/(str(r.get('boxes_photo_sha256'))+'.image')).is_file()]
    for r in eligible[::max(1,len(eligible)//12)][:12]:
        b=r['diagnostics']['chosen_pixel'];img=Image.open(log.parent/(r['boxes_photo_sha256']+'.image')).convert('RGB')
        u,v=(b['x1']+b['x2'])/2,(b['y1']+b['y2'])/2
        x,y=int(u)-96,int(v)-96;img=img.crop((x,y,x+192,y+192))
        d=ImageDraw.Draw(img);d.rectangle((b['x1']-x,b['y1']-y,b['x2']-x,b['y2']-y),outline='red',width=2)
        tile=Image.new('RGB',(240,230),'white');tile.paste(img,(24,0));d=ImageDraw.Draw(tile)
        d.text((3,194),f"{log.parent.name} t={r['score_sim_s']:.1f} hits={r['diagnostics']['pixel_hits']}",fill='black')
        d.text((3,209),f"{b['category']} {b['confidence']:.2f}",fill='black');tiles.append(tile)
sheet=Image.new('RGB',(240*6,230*((len(tiles)+5)//6)),'white')
for i,t in enumerate(tiles):sheet.paste(t,((i%6)*240,(i//6)*230))
a.output.parent.mkdir(parents=True,exist_ok=True);sheet.save(a.output)
