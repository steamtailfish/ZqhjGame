"""Verify standalone Agent import/reset/commands without project src or PyTorch."""
import argparse
import ast
import importlib.util
import json
import math
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
SIM_ROOT = PROJECT.parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--submission',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args = p.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(PROJECT/'artifacts') or output.exists():
        p.error('output must be a new JSON file under project artifacts')
    source = args.submission.read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.ImportFrom) and node.module and node.module.startswith(('zqhj','learning','torch')):
            raise AssertionError('export still depends on development/learning modules')
        if isinstance(node,ast.Import) and any(n.name.startswith(('zqhj','learning','torch')) for n in node.names):
            raise AssertionError('export still depends on development/learning modules')
    # Official package is the only workspace import root; intentionally no src/.
    sys.path[:] = [str(SIM_ROOT)]+[s for s in sys.path if s and str(PROJECT) not in str(Path(s).resolve())]
    from competition.sdk.core.observation import AreaSpec, Detection, MissionBriefing, Observation, ScoreView, SelfView
    from competition.sdk.scenarios.coop_decoy.agent import CoopAgent
    spec = importlib.util.spec_from_file_location('isolated_submission',args.submission.resolve())
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert issubclass(module.EntryAgent,CoopAgent)
    agents = [module.EntryAgent(uid) for uid in ('alpha','bravo','charlie')]
    count = 0
    for a in agents:
        a.configure({});a.reset()
        own = SelfView(a.my_uid,37.,121.,500.,0.,22.,0.,-60.,50.,Detection(False,0.))
        briefing = MissionBriefing(a.my_uid,3,AreaSpec(36.98,37.02,120.98,121.02),
                                  score_view=ScoreView(0.,(),False,0,3,10.))
        obs = Observation(own,(),briefing)
        commands = a.decide(obs,.1)
        assert commands and a.diagnostics['neural_selected'] == 1
        for c in commands:
            count += 1
            if c.verb == 'comm.broadcast':assert len(c.params['payload'].encode('utf-8')) <= 50
            for value in c.params.values():
                if isinstance(value,(int,float)):assert math.isfinite(value)
        assert a.decide(obs,.1) == []
    assert len({id(a.planner.policy.weights) for a in agents}) == 3
    for a in agents:
        a.reset()
        assert not a.bank.tracks and a.planner.selected_count == 0
    assert 'torch' not in sys.modules
    result = dict(status='passed',instances=3,commands_checked=count,torch_imported=False,
                  project_source_imported=False,scope='isolated import and synthetic command verification only')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
