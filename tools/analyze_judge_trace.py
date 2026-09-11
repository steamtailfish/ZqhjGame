"""Post-run judging-input diagnosis; never an Agent dependency."""
import argparse,json,math,sys
from pathlib import Path
from collections import Counter,defaultdict
from dataclasses import asdict
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from competition.sdk._vendored.uav_target_map import UavDetection,resolve_uav_to_target
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('trace',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if json.loads((a.run/'run.json').read_text()).get('status')!='completed':raise ValueError('official run must finish before truth analysis')
trace=json.loads(a.trace.read_text(encoding='utf-8'));rows=trace['rows'];counts=defaultdict(Counter);timeline=[];coverage=defaultdict(Counter)
for row in rows:
    entities=row['entities'];true={e['uid']:(e['lat'],e['lon']) for e in entities if e['kind']=='ground_vehicle'}
    decoys={e['uid']:(e['lat'],e['lon']) for e in entities if e['kind']=='decoy_vehicle'}
    uavs=[e for e in entities if e['kind']=='uav'];inputs=[]
    for e in uavs:
        d=(e['gimbal'] or {}).get('detection') or {};pos=d.get('target_position') or {}
        inputs.append(UavDetection(e['uid'],bool(d.get('detected')),pos.get('latitude'),pos.get('longitude'),str(d.get('target_type','')),bool(d.get('misid_flag')),e['status']=='destroyed',float(d.get('confidence',0))))
        gim=e['gimbal'] or {};fov=float(gim.get('fov',gim.get('fov_deg',30)))
        for convention in ('heading_plus_pan','world_pan'):
            yaw=math.radians(float(gim.get('pan_angle',0))+(e['heading'] if convention=='heading_plus_pan' else 0))
            tilt=math.radians(float(gim.get('tilt_angle',0)))
            ray=(math.cos(tilt)*math.sin(yaw),math.cos(tilt)*math.cos(yaw),math.sin(tilt));angles=[]
            for target in entities:
                if target['kind']!='ground_vehicle':continue
                delta=((target['lon']-e['lon'])*111320*math.cos(math.radians(e['lat'])),(target['lat']-e['lat'])*111320,target['alt']-e['alt'])
                norm=math.sqrt(sum(v*v for v in delta))
                angle=math.degrees(math.acos(max(-1,min(1,sum(v*w for v,w in zip(ray,delta))/max(norm,1e-9)))))
                angles.append(angle)
            coverage[e['uid']][convention+'_frames_with_true_in_cone']+=int(bool(angles) and min(angles)<=fov/2)
    matches=resolve_uav_to_target(inputs,true,decoys);groups=defaultdict(list)
    for uid,m in matches.items():
        label=('true:'+m.target_uid if m.is_effective else 'decoy:'+str(m.decoy_uid) if m.was_misid else 'none')
        counts[uid][label]+=1
        if m.is_effective:groups[m.target_uid].append(uid)
    timeline.append(dict(t=row['engine_sim_time'],matches={k:asdict(v) for k,v in matches.items()},cooperative={k:v for k,v in groups.items() if len(v)>=2}))
result=dict(scope=trace['scope'],trace_span_s=rows[-1]['engine_sim_time']-rows[0]['engine_sim_time'] if rows else 0,
    sampled_frames=len(rows),per_uav_matches={k:dict(v) for k,v in counts.items()},
    approximate_geometric_cone_coverage={k:dict(v) for k,v in coverage.items()},
    sampled_cooperative_frames=sum(bool(r['cooperative']) for r in timeline),timeline=timeline,
    limitations='Partial 5Hz external diagnostic, not official cumulative timer. Geometric cone is an approximation, ignores occlusion and does not establish calibrated image alignment or the engine exact FOV predicate.')
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='timeline'},ensure_ascii=False))
