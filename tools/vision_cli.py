"""Prepare/review/train a candidate detector using exported public RGB only."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT/'src')]
from vision_support import VISION, environment, load_detector, output_dir, sha, write


def init(args):
    import shutil
    source=PROJECT.parent/'examples/yolotrack/target_vehicle_yolov8s.pt'
    expected='b907ba4368af75411ec802d43607e58ccb85cf4075fe580b6c7a2045015ea31c'
    if sha(source)!=expected:raise ValueError('bundled weights changed; inspect architecture/classes before adopting')
    target=VISION/'weights/base_vehicle.pt';target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and sha(target)!=expected:raise ValueError('existing project weights differ; will not overwrite')
    if not target.exists():shutil.copy2(source,target)
    provenance=target.with_suffix('.provenance.json')
    if not provenance.exists():
        write(provenance,dict(source=str(source),sha256=expected,classes=['TargetVehicle'],
              training_library='ultralytics 8.4.77',purpose='candidate detector; not real/decoy classification'))
    print(target)


def scan(args):
    from PIL import Image, ImageDraw
    detector=load_detector(args.weights,size=args.size,confidence=args.confidence,device=args.device)
    out=output_dir(args.output)
    previews=out/'previews';previews.mkdir()
    files=[]
    for source in args.source:
        root=source.resolve()
        if not root.is_relative_to(PROJECT/'artifacts'):raise ValueError('source must be project-exported public observations')
        for log in sorted(root.glob('observations/*/observations.jsonl')):
            seen=set()
            for line in log.read_text(encoding='utf-8').splitlines():
                row=json.loads(line);digest=row.get('photo_sha256')
                path=log.parent/(str(digest)+'.image')
                if not digest or digest in seen or not path.is_file():continue
                seen.add(digest)
                files.append((root.name,log.parent.name,row,path,digest))
    if not files:raise ValueError('no exported public photos found')
    rows=[];started=time.perf_counter()
    for i,(episode,uid,row,path,digest) in enumerate(files):
        photo=path.read_bytes()
        if hashlib.sha256(photo).hexdigest()!=digest:raise ValueError('image hash mismatch')
        before=time.perf_counter();boxes=detector(photo);latency=time.perf_counter()-before
        fixture=path.parents[2]/'fixture-manifest.json'
        provenance='controlled_render_fixture_public_photo' if fixture.exists() else 'official_public_self_photo_export'
        item=dict(id=f'{episode}-{uid}-{digest}',episode=episode,uid=uid,image=str(path),sha256=digest,
                  observation_sim_s=row.get('score_sim_s'),capture_sim_s=None,
                  source=provenance,boxes=[asdict(b) for b in boxes],
                  review_status='unreviewed',reviewer=None,identity='unknown',latency_s=latency)
        rows.append(item)
        if boxes:
            with Image.open(path) as im:
                im=im.convert('RGB');draw=ImageDraw.Draw(im)
                for n,b in enumerate(boxes):
                    draw.rectangle((b.x1,b.y1,b.x2,b.y2),outline='red',width=2)
                    draw.text((b.x1,max(0,b.y1-14)),f'{n}: {b.category} {b.confidence:.2f}',fill='red')
                im.save(previews/(item['id']+'.jpg'))
        if (i+1)%50==0:print(f'{i+1}/{len(files)} photos, {sum(bool(r["boxes"]) for r in rows)} with candidates',flush=True)
    with (out/'candidates.jsonl').open('w',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    summary=dict(images=len(rows),images_with_candidates=sum(bool(r['boxes']) for r in rows),
                 boxes=sum(len(r['boxes']) for r in rows),weights=str(args.weights.resolve()),
                 weights_sha256=sha(args.weights),elapsed_s=time.perf_counter()-started,
                 mean_inference_s=sum(r['latency_s'] for r in rows)/len(rows),
                 args={k:str(v) for k,v in vars(args).items()},labels='unreviewed proposals; not training ground truth')
    write(out/'scan.json',summary);print(json.dumps(summary,indent=2))


def reviewed_records(path):
    rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
    if not rows:raise ValueError('empty review manifest')
    ids=set()
    for row in rows:
        if row.get('review_status')!='accepted' or not row.get('reviewer') or not row.get('review_evidence'):
            raise ValueError('every image must have explicit accepted review, reviewer and review_evidence')
        if row.get('source') not in ('official_public_self_photo_export','controlled_render_fixture_public_photo'):raise ValueError('unsupported image provenance')
        if not row.get('episode') or row['id'] in ids:raise ValueError('missing episode or duplicate id')
        ids.add(row['id'])
        image=Path(row['image']).resolve()
        if not image.is_relative_to(PROJECT/'artifacts') or sha(image)!=row['sha256']:raise ValueError('image path/hash mismatch')
        from PIL import Image
        with Image.open(image) as im:w,h=im.size
        for b in row['boxes']:
            import math
            coords=[b[k] for k in ('x1','y1','x2','y2')]
            if not all(isinstance(v,(float,int)) and math.isfinite(v) for v in coords):raise ValueError('nonfinite box')
            x1,y1,x2,y2=coords
            if b.get('category') not in ('vehicle_candidate','true_vehicle','decoy_vehicle') or not 0 <= x1 < x2 <= w or not 0 <= y1 < y2 <= h:
                raise ValueError('invalid candidate bounding box')
        row['width'],row['height']=w,h
    return rows


def dataset(args):
    rows=reviewed_records(args.reviewed)
    task=getattr(args,'task','candidates')
    names={0:'vehicle_candidate'} if task=='candidates' else {0:'true_vehicle',1:'decoy_vehicle'}
    if task=='identity' and any(b['category'] not in names.values() for r in rows for b in r['boxes']):
        raise ValueError('identity dataset requires visually reviewed true_vehicle/decoy_vehicle boxes')
    validation=set(args.val_episode)
    episodes={r['episode'] for r in rows}
    if not validation or not validation < episodes:raise ValueError('train and validation need different complete episodes')
    splits={s:[r for r in rows if (r['episode'] in validation)==(s=='val')] for s in ('train','val')}
    if {r['sha256'] for r in splits['train']} & {r['sha256'] for r in splits['val']}:
        raise ValueError('same image content leaks across train and validation')
    if any(not any(r['boxes'] for r in group) for group in splits.values()):
        raise ValueError('each split needs reviewed positive vehicle examples')
    if task=='identity' and any({b['category'] for r in group for b in r['boxes']}!=set(names.values()) for group in splits.values()):
        raise ValueError('both identities must occur in both episode-isolated splits')
    out=output_dir(args.output)
    for split,group in splits.items():
        (out/'images'/split).mkdir(parents=True);(out/'labels'/split).mkdir(parents=True)
        for i,r in enumerate(group):
            from PIL import Image
            name=f'{i:06d}'
            with Image.open(r['image']) as im:im.convert('RGB').save(out/'images'/split/(name+'.png'))
            lines=[]
            for b in r['boxes']:
                x1,y1,x2,y2=[b[k] for k in ('x1','y1','x2','y2')];w,h=r['width'],r['height']
                label=0 if task=='candidates' else list(names.values()).index(b['category'])
                lines.append(f'{label} {(x1+x2)/2/w:.9f} {(y1+y2)/2/h:.9f} {(x2-x1)/w:.9f} {(y2-y1)/h:.9f}')
            (out/'labels'/split/(name+'.txt')).write_text('\n'.join(lines),encoding='utf-8')
    import yaml
    (out/'data.yaml').write_text(yaml.safe_dump(dict(path=str(out),train='images/train',val='images/val',names=names)),encoding='utf-8')
    write(out/'manifest.json',dict(source=str(args.reviewed.resolve()),source_sha256=sha(args.reviewed),
         train_episodes=sorted(episodes-validation),val_episodes=sorted(validation),counts={k:len(v) for k,v in splits.items()},
         files={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()},scope=task))
    print(out/'data.yaml')


def train(args):
    environment()
    # Only consume datasets prepared by this tool, with unchanged data/labels.
    data=args.data.resolve();manifest=json.loads((data.parent/'manifest.json').read_text(encoding='utf-8'))
    if not data.is_relative_to(VISION/'datasets'):raise ValueError('dataset must be in project vision/datasets')
    for relative,digest in manifest['files'].items():
        p=(data.parent/relative).resolve()
        if not p.is_relative_to(data.parent) or sha(p)!=digest:raise ValueError('prepared dataset changed')
    if args.epochs<=0 or args.batch<=0:raise ValueError('positive epochs and batch required')
    out=output_dir(args.output)
    from ultralytics import YOLO, settings
    settings.update({'sync':False,'runs_dir':str(VISION/'runs'),'datasets_dir':str(VISION/'datasets'),'weights_dir':str(VISION/'weights')})
    if not args.weights.is_file():raise ValueError('local starting weights missing')
    model=YOLO(str(args.weights.resolve()))
    started=time.perf_counter()
    model.train(data=str(data),epochs=args.epochs,batch=args.batch,imgsz=args.size,device=args.device,
                project=str(out),name='fit',workers=0,seed=args.seed,deterministic=True,
                amp=False,plots=False,cache=False,optimizer='AdamW',lr0=args.lr,
                freeze=args.freeze,close_mosaic=0,degrees=args.degrees,flipud=args.flipud,
                exist_ok=False,pretrained=True)
    write(out/'training.json',dict(data=str(data),data_manifest_sha256=sha(data.parent/'manifest.json'),
         starting_weights_sha256=sha(args.weights),elapsed_s=time.perf_counter()-started,
         args={k:str(v) for k,v in vars(args).items()},scope=manifest.get('scope','candidates')))


def main():
    if len(sys.argv)>1 and sys.argv[1] in ('run','verify','fixture','export'):
        import runpy
        command=sys.argv[1]
        script=PROJECT/({'verify':'learning/test_vision.py','export':'tools/export_visual.py'}.get(command,'tools/run_perception_probe.py'))
        sys.argv=[str(script),*(['--probe','vision' if command=='run' else 'fixture'] if command in ('run','fixture') else []),*sys.argv[2:]]
        runpy.run_path(str(script),run_name='__main__');return
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init',help='copy and verify bundled vehicle weights into this project')
    sub.add_parser('run',help='launch UE and three own-photo Agents; run --help lists options')
    sub.add_parser('verify',help='run photo/servo/data guards in the learning environment')
    sub.add_parser('fixture',help='controlled RGB training fixture; never a competition evaluation')
    sub.add_parser('export',help='export a self-contained Agent module and local vision model')
    s=sub.add_parser('scan');s.add_argument('--source',type=Path,nargs='+',required=True)
    s.add_argument('--output',type=Path,required=True)
    s=sub.add_parser('dataset');s.add_argument('--reviewed',type=Path,required=True)
    s.add_argument('--task',choices=['candidates','identity'],default='candidates')
    s.add_argument('--val-episode',action='append',required=True);s.add_argument('--output',type=Path,required=True)
    s=sub.add_parser('train');s.add_argument('--data',type=Path,required=True);s.add_argument('--output',type=Path,required=True)
    s.add_argument('--epochs',type=int,default=50);s.add_argument('--batch',type=int,default=8);s.add_argument('--seed',type=int,default=73)
    s.add_argument('--lr',type=float,default=.0001);s.add_argument('--freeze',type=int,default=0)
    s.add_argument('--degrees',type=float,default=0.);s.add_argument('--flipud',type=float,default=0.)
    for name in ('scan','train'):
        s=sub.choices[name];s.add_argument('--weights',type=Path,default=VISION/'weights/base_vehicle.pt')
        s.add_argument('--size',type=int,default=1024);s.add_argument('--device',default='cpu')
    sub.choices['scan'].add_argument('--confidence',type=float,default=.25)
    args=p.parse_args();globals()[args.command](args)


if __name__=='__main__':main()
