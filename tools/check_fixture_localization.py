"""Offline motion-plane error on manually reviewed fixed fixture vehicles.

Fixture coordinates are used only as an offline reference, never fed to the estimator.
Nearest-object matching is optimistic; this is not field calibration.
"""
import argparse,json,math,sys,statistics
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_visual_geometry import MotionPlane
from vision_support import write
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];review=[json.loads(s) for s in (root/'artifacts/vision/datasets/fixture-crops-v1/accepted.jsonl').read_text(encoding='utf-8').splitlines()];results=[]
for episode in ('true-v2','decoy-v1','true-height200','decoy-height200'):
    fixture=root/'artifacts/vision/fixtures'/episode;folder=fixture/'observations/20002'
    scene=json.loads((fixture/'fixture-scene.json').read_text(encoding='utf-8'))
    references=[(e['params']['initial_latitude'],e['params']['initial_longitude']) for e in scene['entities'] if e['type']!='FixedWingUAV']
    labels={}
    for r in review:
        if r['episode']!=episode:continue
        x,y=r['crop_xyxy'][:2]
        for b in r['boxes']:labels.setdefault(r['source_photo_sha256'],[]).append(((b['x1']+b['x2'])/2+x,(b['y1']+b['y2'])/2+y))
    g=MotionPlane();seen=set();records=[];attempts=0
    for r in map(json.loads,(folder/'observations.jsonl').read_text(encoding='utf-8').splitlines()):
        now=r['score_sim_s'];digest=r.get('photo_sha256');path=folder/(str(digest)+'.image')
        if now is None:continue
        own=SimpleNamespace(**r['own']);g.observe_pose(own,now)
        if digest in seen or not path.is_file():continue
        seen.add(digest);g.update(path.read_bytes(),own,now,digest)
        for center in labels.get(digest,[]):
            attempts+=1;estimate=g.locate(SimpleNamespace(center=center),now,digest)
            if estimate is None:continue
            error=min(math.hypot((estimate.latitude-lat)*111320,(estimate.longitude-lon)*111320*math.cos(math.radians(lat))) for lat,lon in references)
            records.append(dict(t=now,nearest_reference_error_m=error,uncertainty_m=estimate.uncertainty_m,ground_m=estimate.ground_plane_m))
    results.append(dict(episode=episode,reviewed_attempts=attempts,estimates=len(records),
        median_error_m=statistics.median(r['nearest_reference_error_m'] for r in records) if records else None,
        max_error_m=max((r['nearest_reference_error_m'] for r in records),default=None),records=records))
write(a.output,dict(scope='Controlled fixed placements, reviewed pixels and own pose; optimistic nearest-reference matching; not field accuracy',episodes=results))
print(json.dumps([{k:v for k,v in r.items() if k!='records'} for r in results]))
