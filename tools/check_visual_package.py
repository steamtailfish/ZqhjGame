"""Isolated import, private-instance and no-callback-file-I/O package check."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from dataclasses import replace
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
# Only the read-only SDK root is added. Never add src or tests for this check.
sys.path.insert(0,str(PROJECT.parent))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('agent',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();path=args.agent.resolve();out=args.output.resolve()
    if not out.is_relative_to(PROJECT/'artifacts') or out.exists():
        raise ValueError('output must be a new project artifact file')
    manifest=json.loads((path.parent/'manifest.json').read_text())
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest(path)==manifest['agent_sha256']
    assert digest(path.parent/'vision.pt')==manifest['vision_sha256']
    spec=importlib.util.spec_from_file_location('isolated_visual_submission',path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    from competition.sdk.core.observation import AreaSpec,Detection,MissionBriefing,Observation,ScoreView,SelfView
    agents=[module.EntryAgent(uid) for uid in ('alpha','beta','gamma')]
    for a in agents:a.reset()
    assert len({id(a.detector.model) for a in agents})==3
    source=PROJECT/'artifacts/vision/fixtures/true-v2/observations/20002/62c13d88321f8e68637990aca8d0ec440b10194091b18397110322f876452299.image'
    photo=source.read_bytes();counts=[]
    for a in agents:
        obs=Observation(SelfView(a.my_uid,37.,121.,500.,0.,22.,0.,-80.,50.,Detection(False,0.),photo=photo),(),
            MissionBriefing(a.my_uid,3,AreaSpec(36.98,37.02,120.98,121.02),score_view=ScoreView(0.,(),False,0,3,1.)))
        with (patch('builtins.open',side_effect=AssertionError('callback file IO')),
              patch('io.open',side_effect=AssertionError('callback file IO')),
              patch('os.open',side_effect=AssertionError('callback file IO'))):
            assert a.sensor(obs,.1)==[]
            if getattr(a,'_pending',None) is not None:
                a._pending.result(timeout=20)
                obs=replace(obs,briefing=replace(obs.briefing,score_view=replace(obs.briefing.score_view,sim_time=1.1)))
                assert a.sensor(obs,.1)==[]
            commands=a.decide(obs,.1)
        assert a.vision_stats['inferences']==1 and a.vision_stats['failures']==0
        assert commands and a.enable_reports==manifest.get('reports_enabled',False)
        counts.append({'uid':a.my_uid,'commands':len(commands),'boxes':len(a.boxes)})
        if hasattr(a,'close_detector'):a.close_detector()
    assert not any(name.startswith('zqhj_') for name in sys.modules)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(dict(status='passed',agent_sha256=digest(path),vision_sha256=manifest['vision_sha256'],
        agents=counts,private_models=True,callback_open_forbidden=True,
        blocked_python_io=['builtins.open','io.open','os.open'],project_modules_imported=False,
        scope='isolated package import and synthetic SDK observation, not real competition score'),indent=2))
    print(out)


if __name__=='__main__':main()
