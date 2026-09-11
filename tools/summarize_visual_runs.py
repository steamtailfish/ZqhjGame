"""Summarize completed public-photo logs and unmodified official evaluations."""
import argparse
from collections import Counter
import json
from pathlib import Path
from vision_support import output_dir,write,sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',nargs='+',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    out=output_dir(args.output);results=[]
    for folder in args.runs:
        run=json.loads((folder/'run.json').read_text(encoding='utf-8'))
        if 'finished_utc' not in run:raise ValueError('only completed recordings may be analyzed')
        eval_path=next((folder/'official').glob('*.evaluation.json'))
        evaluation=json.loads(eval_path.read_text(encoding='utf-8'))
        agents=[]
        for log in sorted((folder/'observations').glob('*/observations.jsonl')):
            rows=[json.loads(s) for s in log.read_text(encoding='utf-8').splitlines()]
            d=rows[-1]['diagnostics'];speeds=[]
            for a,b in zip(rows,rows[1:]):
                dt=b['score_sim_s']-a['score_sim_s']
                if dt>0:speeds.append(abs((b['own']['heading_deg']-a['own']['heading_deg']+180)%360-180)/dt)
            agents.append(dict(uid=log.parent.name,rows=len(rows),vision=d['vision'],
                neural_selected=d['neural_selected'],neural_fallback=d['neural_fallback'],
                geometry_states=dict(Counter(r['diagnostics'].get('geometry_state','disabled') for r in rows)),
                geo_estimates=sum(r['diagnostics'].get('geo_estimate') is not None for r in rows),
                max_tracks=max(r['diagnostics']['tracks'] for r in rows),
                roles=dict(Counter(r['diagnostics']['state'] for r in rows)),
                max_public_peers=max(r['diagnostics']['public_peer_count'] for r in rows),
                mean_abs_heading_rate_deg_s=sum(speeds)/len(speeds) if speeds else None,
                reports_sent=d.get('reports_sent',0)))
        result=dict(run=folder.name,run_status=run['status'],last_sim_s=run.get('last_sim_s'),
            elapsed_wall_s=run['elapsed_wall_s'],official_evaluation=str(eval_path.resolve()),
            evaluation_sha256=sha(eval_path),
            scores={k:evaluation[k] for k in ('total_score','penalty','n_destroyed','n_reports','passed')},agents=agents)
        results.append(result);print(folder.name,result['scores'],flush=True)
    write(out/'summary.json',results)


if __name__=='__main__':main()
