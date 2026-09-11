"""Inspect detector-selected patches from completed public images; no auto labels."""
import argparse,json,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
p=argparse.ArgumentParser();p.add_argument('detections',type=Path);p.add_argument('output',type=Path);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True)
records=[];tiles=[]
for r in json.loads(a.detections.read_text(encoding='utf-8')):
    source=Path(r['photo']);im=Image.open(source).convert('RGB')
    for b in r['boxes']:
        if b['confidence']<.65:continue
        x=round((b['x1']+b['x2'])/2)-48;y=round((b['y1']+b['y2'])/2)-48;crop=im.crop((x,y,x+96,y+96));index=len(records);name=f'field-patch-{index:03d}';path=a.output/(name+'.png')
        image=Image.new('RGB',(256,256),(114,114,114));image.paste(crop,(80,80));image.save(path)
        records.append(dict(id=name,index=index,episode='score600-seed101',image=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source='completed_own_photo_detector_selection',source_photo=str(source),source_photo_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),crop_xyxy=[x,y,x+96,y+96],boxes=[dict(x1=b['x1']-x+80,y1=b['y1']-y+80,x2=b['x2']-x+80,y2=b['y2']-y+80,category=b['category'])],review_status='pending',reviewer=None,review_evidence=None))
        preview=crop.resize((192,192));d=ImageDraw.Draw(preview);d.rectangle(tuple((b[k]-(x if k.startswith('x') else y))*2 for k in ('x1','y1','x2','y2')),outline='red',width=1)
        tile=Image.new('RGB',(210,230),'white');tile.paste(preview,(9,20));d=ImageDraw.Draw(tile);d.text((4,2),f'{index:03d} t={r["t"]:.1f} {b["confidence"]:.2f}',fill='black');tiles.append(tile)
for page,start in enumerate(range(0,len(tiles),36)):
    sheet=Image.new('RGB',(1260,1380),'white')
    for i,tile in enumerate(tiles[start:start+36]):sheet.paste(tile,(i%6*210,i//6*230))
    sheet.save(a.output/f'review-{page}.png')
(a.output/'pending.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in records),encoding='utf-8');print(len(records),a.output)
