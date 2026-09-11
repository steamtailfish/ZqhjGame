"""Offline synthetic gradient/training smoke; no competition engine or task routes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
# Import paths are owned by offline entrypoints, never modified by online modules.
sys.path[:0] = [str(PROJECT),str(PROJECT/'src')]

import torch
from learning.guidance import GuidancePolicy, guidance_loss, synthetic_scene
from learning.test_guidance import GuidanceTests
from learning.test_competition_adapter import AdapterTests


def metrics(model,scene):
    with torch.no_grad():
        r = guidance_loss(model,scene)
        selected = r['scores'].argmax(dim=1,keepdim=True)
        selected_cost = r['costs'].gather(1,selected).mean().item()
        return dict(mean_cost=r['costs'].mean().item(),best_candidate_cost=r['costs'].min(1).values.mean().item(),
                    score_selected_cost=selected_cost,score_loss=r['score_loss'].item(),
                    eligible_fraction=r['eligible'].float().mean().item())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steps',type=int,default=40)
    parser.add_argument('--seed',type=int,default=23)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if not 1 <= args.steps <= 200:
        parser.error('verification only: steps must be in [1,200]')
    out = args.output or PROJECT/'artifacts'/'learning'/datetime.now().strftime('%Y%m%d-%H%M%S')
    if not out.is_absolute():
        out = PROJECT/out
    out = out.resolve()
    if not out.is_relative_to(PROJECT/'artifacts') or out.exists():
        parser.error('output must be a NEW directory under ZqhjGame/artifacts')
    out.mkdir(parents=True)
    started = time.perf_counter()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(args.seed)
    run = dict(scope='synthetic_gradient_and_training_smoke_only',started_utc=datetime.now(timezone.utc).isoformat(),
               python=sys.version,python_executable=sys.executable,torch=torch.__version__,platform=platform.platform(),
               seed=args.seed,steps=args.steps,device='cpu',real_engine=False,uses_competition_map=False,
               source_sha256={str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in [PROJECT/'learning/guidance.py',PROJECT/'learning/test_guidance.py',Path(__file__)]},
               limitations=['No RGB/depth encoder, real dataset or real flight validation',
                            'Synthetic weights are not loaded by EntryAgent',
                            'Sampled costs are not hard safety guarantees'])
    code = 1
    try:
        with (out/'tests.log').open('w',encoding='utf-8') as stream:
            tests = unittest.TextTestRunner(stream=stream,verbosity=2).run(
                unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(GuidanceTests),
                                    unittest.defaultTestLoader.loadTestsFromTestCase(AdapterTests)]))
        run['tests'] = dict(run=tests.testsRun,failures=len(tests.failures),errors=len(tests.errors))
        if not tests.wasSuccessful():
            raise RuntimeError('gradient/behavior tests failed; inspect tests.log')
        # Tests intentionally seed their own models; reset the experiment seed afterwards.
        torch.manual_seed(args.seed)
        model = GuidancePolicy()
        train = synthetic_scene(32,args.seed+1)
        validation = synthetic_scene(32,args.seed+10001)
        run['before'] = dict(train=metrics(model,train),heldout=metrics(model,validation))
        optimizer = torch.optim.Adam(model.parameters(),lr=.002)
        history = []
        for step in range(args.steps):
            optimizer.zero_grad(set_to_none=True)
            result = guidance_loss(model,train)
            if not torch.isfinite(result['loss']):
                raise RuntimeError('nonfinite loss')
            result['loss'].backward()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(),10.,error_if_nonfinite=True)
            optimizer.step()
            history.append(dict(step=step+1,loss=result['loss'].item(),
                                trajectory_loss=result['trajectory_loss'].item(),
                                score_loss=result['score_loss'].item(),grad_norm=norm.item()))
        model.eval()
        run['after'] = dict(train=metrics(model,train),heldout=metrics(model,validation))
        run['history'] = history
        torch.save({'state_dict':model.state_dict(),'scope':run['scope'],'seed':args.seed},out/'synthetic-smoke.pt')
        run['checkpoint_sha256'] = hashlib.sha256((out/'synthetic-smoke.pt').read_bytes()).hexdigest()
        run['dependencies'] = subprocess.check_output([sys.executable,'-B','-m','pip','freeze'],text=True).splitlines()
        run['status'] = 'passed'
        code = 0
    except Exception as exc:
        run.update(status='failed',error=repr(exc))
    finally:
        run['elapsed_seconds'] = time.perf_counter()-started
        (out/'run.json').write_text(json.dumps(run,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:run[k] for k in ('status','tests','before','after','error') if k in run},indent=2))
    print('EVIDENCE='+str(out/'run.json'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
