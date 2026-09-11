"""Train competition-adapted local guidance on recorded public observations."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT),str(PROJECT/'src')]

import torch
from learning.dataset import scene_from_records, split_datasets
from learning.guidance import GuidancePolicy, guidance_loss
from zqhj_features import FEATURE_VERSION


def evaluate(model,records,batch_size,device):
    totals = dict(mean_cost=0.,selected_cost=0.,oracle_candidate_cost=0.,score_loss=0.,eligible_fraction=0.)
    model.eval()
    with torch.no_grad():
        for start in range(0,len(records),batch_size):
            scene = scene_from_records(records[start:start+batch_size],device)
            result = guidance_loss(model,scene)
            n = scene.speed.shape[0]
            selected = result['scores'].argmax(1,keepdim=True)
            totals['mean_cost'] += result['costs'].mean().item()*n
            totals['selected_cost'] += result['costs'].gather(1,selected).mean().item()*n
            totals['oracle_candidate_cost'] += result['costs'].min(1).values.mean().item()*n
            totals['score_loss'] += result['score_loss'].item()*n
            totals['eligible_fraction'] += result['eligible'].float().mean().item()*n
    return {k:v/len(records) for k,v in totals.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train-data',type=Path,nargs='+',required=True)
    p.add_argument('--val-data',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=100,help='additional epochs when resuming')
    p.add_argument('--batch-size',type=int,default=64)
    p.add_argument('--lr',type=float,default=.001)
    p.add_argument('--seed',type=int,default=23)
    p.add_argument('--device',choices=('cpu','cuda','auto'),default='cpu')
    p.add_argument('--resume',type=Path)
    args = p.parse_args()
    if args.epochs <= 0 or args.batch_size <= 0 or not 0 < args.lr < 1:
        p.error('epochs/batch-size must be positive; lr must be in (0,1)')
    out = args.output.resolve()
    if not out.is_relative_to(PROJECT/'artifacts') or out.exists():
        p.error('--output must be a new directory inside ZqhjGame/artifacts')
    device = 'cuda' if args.device == 'auto' and torch.cuda.is_available() else args.device
    if device == 'auto':device = 'cpu'
    if device == 'cuda' and not torch.cuda.is_available():
        p.error('CUDA unavailable; use --device cpu or install a compatible CUDA build separately')
    train,valid,data_manifest = split_datasets(args.train_data,args.val_data)
    out.mkdir(parents=True)
    torch.set_num_threads(1)
    torch.manual_seed(args.seed)
    model = GuidancePolicy().to(device)
    optimizer = torch.optim.Adam(model.parameters(),lr=args.lr)
    rng = torch.Generator().manual_seed(args.seed)
    start_epoch = 0
    best = float('inf')
    if args.resume:
        checkpoint = torch.load(args.resume,map_location='cpu',weights_only=True)
        if checkpoint.get('feature_version') != FEATURE_VERSION or checkpoint.get('data_manifest') != data_manifest:
            raise ValueError('resume requires the same feature contract and recorded datasets')
        model.load_state_dict(checkpoint['state_dict'],strict=True)
        optimizer.load_state_dict(checkpoint['optimizer'])
        rng.set_state(checkpoint['shuffle_rng'])
        start_epoch = checkpoint['epoch']
        # Best in THIS run is compared against the resumed model, not an absent file.
    manifest = dict(feature_version=FEATURE_VERSION,started_utc=datetime.now(timezone.utc).isoformat(),
                    device=device,python=sys.version,torch=torch.__version__,config=vars(args)|{'output':str(out)},
                    data_manifest=data_manifest,train_samples=len(train),validation_samples=len(valid),
                    source_sha256={str(f.relative_to(PROJECT)):hashlib.sha256(f.read_bytes()).hexdigest()
                                   for f in [PROJECT/'learning/guidance.py',PROJECT/'learning/dataset.py',PROJECT/'src/zqhj_features.py',Path(__file__)]},
                    scope='local_planner_guidance_only_not_visual_identification_or_full_mission_training')
    started = time.perf_counter()
    manifest['before'] = evaluate(model,valid,args.batch_size,device)
    def save(name,epoch):
        torch.save(dict(feature_version=FEATURE_VERSION,state_dict={k:v.detach().cpu() for k,v in model.state_dict().items()},
                        optimizer=optimizer.state_dict(),shuffle_rng=rng.get_state(),epoch=epoch,data_manifest=data_manifest,
                        scope=manifest['scope'],validation=manifest.get('after',manifest['before'])),out/name)
    try:
        with (out/'metrics.jsonl').open('x',encoding='utf-8') as log:
            for epoch in range(start_epoch+1,start_epoch+args.epochs+1):
                model.train()
                order = torch.randperm(len(train),generator=rng).tolist()
                total,count = 0.,0
                for start in range(0,len(order),args.batch_size):
                    selected = [train[i] for i in order[start:start+args.batch_size]]
                    scene = scene_from_records(selected,device)
                    optimizer.zero_grad(set_to_none=True)
                    result = guidance_loss(model,scene)
                    if not torch.isfinite(result['loss']):raise RuntimeError('nonfinite training loss')
                    result['loss'].backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(),10.,error_if_nonfinite=True)
                    optimizer.step()
                    total += result['loss'].item()*len(selected)
                    count += len(selected)
                metrics = evaluate(model,valid,args.batch_size,device)
                manifest['after'] = metrics
                row = dict(epoch=epoch,training_loss=total/count,validation=metrics)
                log.write(json.dumps(row,allow_nan=False)+'\n');log.flush()
                if metrics['selected_cost'] < best:
                    best = metrics['selected_cost']
                    save('best.pt',epoch)
                save('last.pt',epoch)
                print(json.dumps(row),flush=True)
        manifest['status'] = 'completed'
    except BaseException as exc:
        manifest.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',error=repr(exc))
        raise
    finally:
        manifest['elapsed_seconds'] = time.perf_counter()-started
        (out/'training.json').write_text(json.dumps(manifest,indent=2,default=str,allow_nan=False),encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
