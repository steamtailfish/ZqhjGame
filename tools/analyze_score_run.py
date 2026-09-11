"""Post-run public-observation diagnostics; official score remains authoritative."""
import argparse,json,math,bisect,ast
from collections import Counter
from pathlib import Path
from vision_support import write,sha
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
run=json.loads((a.run/'run.json').read_text(encoding='utf-8'))
if run.get('status')!='completed' or 'finished_utc' not in run:raise ValueError('completed run required')
thresholds={'identity_confidence':.9,'identity_margin':.6}
call=json.loads((a.run/'runner-call.json').read_text(encoding='utf-8'))
submission=Path(call['submission']) if call.get('submission') else None
if submission and submission.is_file() and sha(submission)==call['controller_sha256']:
    tree=ast.parse(submission.read_text(encoding='utf-8'))
    distributed=any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DISTRIBUTED_SEARCH' for t in n.targets) and isinstance(n.value,ast.Constant) and n.value.value is True for n in tree.body)
    if distributed:
        for cls in (n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ScoreSearchAgent'):
            for n in cls.body:
                if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant):
                    for target in n.targets:
                        if isinstance(target,ast.Name) and target.id in thresholds:thresholds[target.id]=float(n.value.value)
logs={f.parent.name:[json.loads(s) for s in f.read_text(encoding='utf-8').splitlines()] for f in sorted((a.run/'observations').glob('*/observations.jsonl'))}
agents=[]
for uid,rows in logs.items():
    photos={r['boxes_photo_sha256']:r for r in rows if r.get('boxes_photo_sha256')}
    frames=list(photos.values());ds=[r['diagnostics'] for r in frames]
    agents.append(dict(uid=uid,recorded_unique_inference_photos=len(frames),
        two_peers_fraction=sum(r['diagnostics']['public_peer_count']==2 for r in rows)/len(rows),
        chosen_classes=dict(Counter(d['chosen_pixel']['category'] if d.get('chosen_pixel') else 'none' for d in ds)),
        identity_threshold_frames=sum(bool(d.get('chosen_pixel') and d['chosen_pixel']['category']=='true_vehicle' and d['chosen_pixel']['confidence']>=d.get('identity_confidence',thresholds['identity_confidence']) and d['chosen_pixel']['class_margin']>=d.get('identity_margin',thresholds['identity_margin'])) for d in ds),
        geometry_frames=sum(d.get('geo_estimate') is not None for d in ds),
        motion_verified_frames=sum(d.get('motion_hits',0)>=2 for d in ds),
        motion_and_geometry_frames=sum(d.get('motion_hits',0)>=2 and d.get('geo_estimate') is not None for d in ds),
        motion_geometry_identity_frames=sum(bool(d.get('motion_hits',0)>=2 and d.get('geo_estimate') is not None
            and d.get('chosen_pixel') and d['chosen_pixel']['category']=='true_vehicle'
            and d['chosen_pixel']['confidence']>=d.get('identity_confidence',thresholds['identity_confidence'])
            and d['chosen_pixel']['class_margin']>=d.get('identity_margin',thresholds['identity_margin'])) for d in ds),
        max_pixel_track_frames=max((d.get('pixel_hits',0) for d in ds),default=0),
        max_report_identity_hits=max((d.get('report_candidate',{}).get('identity_hits',0) for d in ds),default=0),
        geometry_states=dict(Counter(d.get('geometry_state','missing') for d in ds)),
        roles=dict(Counter(r['diagnostics']['state'] for r in rows)),
        last=r['diagnostics'] if not rows else rows[-1]['diagnostics']))
pairs=[];uids=sorted(logs)
for i,uid in enumerate(uids):
    for other in uids[i+1:]:
        b=logs[other];times=[r['score_sim_s'] for r in b];distances=[];common=[]
        for r in logs[uid]:
            t=r['score_sim_s'];j=bisect.bisect_left(times,t)
            choices=[b[k] for k in (j-1,j) if 0<=k<len(b)]
            q=min(choices,key=lambda q:abs(q['score_sim_s']-t))
            if abs(q['score_sim_s']-t)>.3:continue
            x,y=r['own'],q['own'];distances.append(math.hypot((x['lat']-y['lat'])*111320,(x['lon']-y['lon'])*111320*math.cos(math.radians(x['lat']))))
            dr,dq=r['diagnostics'],q['diagnostics']
            same=(dr['state']=='OBSERVE' and dq['state']=='OBSERVE' and dr['owner']==dq['owner'] and dr['candidate']==dq['candidate'])
            common.append((t,same))
        start=last=None;longest=0.
        for t,same in common:
            if not same:start=last=None;continue
            if last is None or t-last>1.:start=t
            longest=max(longest,t-start);last=t
        pairs.append(dict(uids=[uid,other],matched_records=len(distances),minimum_logged_separation_m=min(distances) if distances else None,
                          longest_same_candidate_observe_s=longest))
evaluation=next((a.run/'official').glob('*.evaluation.json'));score=json.loads(evaluation.read_text(encoding='utf-8'))
write(a.output,dict(run=str(a.run.resolve()),evaluation_sha256=sha(evaluation),scores={k:score[k] for k in ('total_score','penalty','n_destroyed','n_reports')},
    physical_coop_ticks={k:v['coop_ticks'] for k,v in score['per_target'].items()},agents=agents,pairs=pairs,
    limits='Logged positions are nearest-time samples, not a safety proof. Common OBSERVE is controller intent, not physical K=2. Only official evaluation establishes score.'))
print(a.output)
