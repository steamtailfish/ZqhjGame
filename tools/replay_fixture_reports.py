"""Open-loop public-photo replay with synthetic teammate broadcasts.

No engine score is computed. Commands do not affect recorded images.
This checks whether the exported pipeline can produce visually grounded reports.
"""
import argparse,json,sys,importlib.util
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from competition.sdk.core.observation import SelfView,Detection,Observation,MissionBriefing,ScoreView,AreaSpec,Message
p=argparse.ArgumentParser();p.add_argument('--submission',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--uid',default='20002');a=p.parse_args()
spec=importlib.util.spec_from_file_location('replayed_submission',a.submission);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
agent=m.EntryAgent(a.uid);agent.reset();agent.enable_reports=True
folder=a.fixture/'observations'/a.uid;rows=[json.loads(s) for s in (folder/'observations.jsonl').read_text(encoding='utf-8').splitlines()]
last_photo=None;reports=[];records=[]
try:
    for r in rows:
        now=r['score_sim_s'];path=folder/(str(r.get('photo_sha256'))+'.image')
        if now is None:continue
        if path.is_file():last_photo=path.read_bytes()
        if last_photo is None:continue
        own=SelfView(**r['own'],photo=last_photo,detection=Detection(False,0.))
        peer=m.Packet(int(now*10),now,own.lat+.004,own.lon+.004,0.,22.)
        obs=Observation(own,(Message('20001' if a.uid!='20001' else '20002',m.encode(peer),now),),MissionBriefing(a.uid,3,
            AreaSpec(26.98,27.02,124.98,125.02),score_view=ScoreView(0.,(),False,0,3,now)))
        agent.sensor(obs,.1)
        if agent._pending is not None:
            agent._pending.result(timeout=20);agent.sensor(obs,.1)
        commands=agent.decide(obs,.1)
        reports.extend(dict(t=now,params=c.params) for c in commands if c.verb=='agent.report')
        if agent.pixel_target is not None:records.append(dict(t=now,category=agent.pixel_target.category,confidence=agent.pixel_target.confidence,
            hits=agent.pixel_hits,geo=agent.geo_estimate is not None,role=agent.diagnostics.get('state'),
            motion_hits=getattr(agent,'motion_hits',None),pixel_motion_px=getattr(agent,'pixel_motion_px',None),
            report_candidate=agent.diagnostics.get('report_candidate'),photo_digest=agent.photo_digest,
            chosen_pixel=agent.diagnostics.get('chosen_pixel'),geo_estimate=agent.diagnostics.get('geo_estimate')))
finally:agent.close_detector()
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(dict(scope='open-loop own-photo replay; synthetic peer broadcast; no engine score and no closed-loop validation',
    reports=reports,candidates=records,diagnostics=agent.diagnostics),ensure_ascii=False,indent=2),encoding='utf-8')
print(f'{len(reports)} replay reports; {len(records)} candidate records; NOT a competition score')
