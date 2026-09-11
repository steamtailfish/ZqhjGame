"""Export a versioned learned controller into one SDK-loadable stdlib-only module."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import pprint
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT),str(PROJECT/'src')]

import torch
from learning.guidance import GuidancePolicy
from zqhj_features import FEATURE_VERSION
from zqhj_inference import EmbeddedPolicy


def export(checkpoint_path,output):
    output = Path(output).resolve()
    if not output.is_relative_to(PROJECT/'artifacts') or output.exists():
        raise ValueError('output must be a new .py file under ZqhjGame/artifacts')
    if output.suffix != '.py':raise ValueError('output suffix must be .py')
    checkpoint = torch.load(checkpoint_path,map_location='cpu',weights_only=True)
    if checkpoint.get('feature_version') != FEATURE_VERSION:
        raise ValueError('incompatible checkpoint; v0.2 35-feature smoke weights cannot be deployed')
    model = GuidancePolicy()
    model.load_state_dict(checkpoint['state_dict'],strict=True)
    weights = {k:v.detach().cpu().tolist() for k,v in model.state_dict().items()}
    EmbeddedPolicy(FEATURE_VERSION,weights)  # Shape and finite-value verification.
    names = ('zqhj_state','zqhj_comm','zqhj_cooperation','zqhj_planner','zqhj_features','zqhj_inference','zqhj_entry')
    chunks = ['# Generated competition control module. No vision model is included.\n']
    hashes = {}
    for name in names:
        path = PROJECT/'src'/f'{name}.py'
        source = path.read_text(encoding='utf-8')
        hashes[name] = hashlib.sha256(source.encode()).hexdigest()
        tree = ast.parse(source)
        removed = set()
        for node in tree.body:
            if isinstance(node,ast.ImportFrom) and node.module in names:
                removed.update(range(node.lineno,node.end_lineno+1))
        chunks.append('\n# Module: '+name+'\n'+''.join(line for i,line in enumerate(source.splitlines(keepends=True),1) if i not in removed))
    chunks.append('\n_AnalyticEntryAgent = EntryAgent\n\ndef _policy_weights():\n    return '+pprint.pformat(weights,width=120).replace('\n','\n    ')+'\n')
    chunks.append('\nclass EntryAgent(_AnalyticEntryAgent):\n'
                  '    def create_planner(self):\n'
                  '        return LearnedPlanner(EmbeddedPolicy(FEATURE_VERSION, _policy_weights()), PrimitivePlanner())\n')
    code = '\n'.join(chunks)
    ast.parse(code)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(code,encoding='utf-8')
    manifest = dict(feature_version=FEATURE_VERSION,checkpoint=str(Path(checkpoint_path).resolve()),
                    checkpoint_sha256=hashlib.sha256(Path(checkpoint_path).read_bytes()).hexdigest(),
                    submission_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),sources=hashes,
                    online_dependencies=['Python standard library','official competition SDK'],
                    sensor='SDK detection; no trained RGB real/decoy classifier in this export')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args = p.parse_args()
    print(json.dumps(export(args.checkpoint,args.output),indent=2))


if __name__ == '__main__':
    main()
