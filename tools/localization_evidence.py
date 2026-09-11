"""Offline only: inspect already exported public photos, never online annotations."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw


def load_samples(run,uid):
    folder=run/'observations'/uid
    rows=[json.loads(s) for s in (folder/'observations.jsonl').read_text(encoding='utf-8').splitlines()]
    unique={}
    for r in rows:
        digest=r['photo_sha256']
        if digest and (folder/(digest+'.image')).exists():unique.setdefault(digest,r)
    return rows,list(unique.values())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    out=args.output.resolve(); run=args.run.resolve()
    if not out.is_relative_to(project):parser.error('write only inside project')
    out.mkdir(parents=True,exist_ok=False)
    catalog={}
    for folder in sorted((run/'observations').iterdir()):
        rows,samples=load_samples(run,folder.name)
        selected=[min(samples,key=lambda r:abs(r['score_sim_s']-t)) for t in (10,14,17,20,24,28,32,38)]
        canvas=Image.new('RGB',(1024,900),'#eeeeee');draw=ImageDraw.Draw(canvas)
        for i,r in enumerate(selected):
            x=(i%2)*512;y=(i//2)*225
            with Image.open(folder/(r['photo_sha256']+'.image')) as im:
                im=im.convert('RGB');im.thumbnail((256,192));canvas.paste(im,(x,y+30))
            own=r['own']
            draw.text((x,y),f"{folder.name} t={r['score_sim_s']:.2f} h={own['heading_deg']:.2f}\npan={own['gimbal_pan']} tilt={own['gimbal_tilt']} fov={own['gimbal_fov_deg']}",fill='black')
        canvas.save(out/(folder.name+'-overview.jpg'),quality=93)
        catalog[folder.name]=dict(samples=[dict(sim_s=r['score_sim_s'],own=r['own'],
            image=str(folder/(r['photo_sha256']+'.image')),time=r['time']) for r in samples],
            callback_count=len(rows))
    (out/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out)


if __name__=='__main__':main()
