"""Summarize completed capture experiments; never imported by an online Agent."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def visual_windows(rows, max_sample_gap=.8):
    """Consecutive positive public samples, with no assumed time after a sample."""
    windows=[];active=None
    for row in rows:
        capture=row.get('diagnostics',{}).get('capture',{})
        key=(capture.get('owner'),capture.get('mission'))
        now=row['score_sim_s']
        if (not capture.get('own_visual') or key[0] is None or
                capture.get('phase') not in ('OFFER','APPROACH','TRACK_PAIR','RECOVER')):
            active=None;continue
        if (active is None or active['mission']!=f'{key[0]}:{key[1]}' or
                not 0<now-active['last_s']<=max_sample_gap):
            active=dict(mission=f'{key[0]}:{key[1]}',first_s=now,last_s=now,
                        sample_span_s=0.,samples=0)
            windows.append(active)
        active['last_s']=now;active['samples']+=1
        active['sample_span_s']=now-active['first_s']
    return windows


def analyze(run_dir):
    run = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
    if run.get('status') != 'completed':
        raise ValueError('Complete the official run before analyzing it')
    evaluation_path = next((run_dir / 'official').glob('*.evaluation.json'))
    evaluation = json.loads(evaluation_path.read_text(encoding='utf-8'))
    agents = []
    for path in sorted((run_dir / 'observations').glob('*/observations.jsonl')):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        phases, events, missions = Counter(), [], {}
        previous = None
        max_joint = 0.
        visual = acknowledged = 0
        for row in rows:
            capture = row.get('diagnostics', {}).get('capture', {})
            if not capture:
                continue
            phase = capture['phase']
            phases[phase] += 1
            visual += bool(capture.get('own_visual'))
            acknowledged += bool(capture.get('acknowledged') and
                phase in ('APPROACH','TRACK_PAIR','RECOVER') and
                path.parent.name in (capture.get('owner'),capture.get('partner')))
            max_joint = max(max_joint, capture.get('max_local_joint_s', 0.))
            key = (capture.get('owner'), capture.get('mission'))
            state = (phase, key, capture.get('partner'), capture.get('reason'))
            if state != previous:
                events.append(dict(t=row['score_sim_s'], **capture,
                                   photo=row.get('boxes_photo_sha256')))
                previous = state
            if key[0] is not None:
                label = f'{key[0]}:{key[1]}'
                mission = missions.setdefault(label, dict(first_s=row['score_sim_s'],
                    last_s=row['score_sim_s'], own_visual_samples=0,
                    paired_samples=0, max_local_joint_s=0.))
                mission['last_s'] = row['score_sim_s']
                mission['own_visual_samples'] += bool(capture.get('own_visual'))
                mission['paired_samples'] += phase == 'TRACK_PAIR'
                mission['max_local_joint_s'] = max(mission['max_local_joint_s'],
                                                   capture.get('local_joint_s', 0.))
        windows=visual_windows(rows)
        agents.append(dict(uid=path.parent.name, samples=len(rows),
            phase_samples=dict(phases), own_visual_samples=visual,
            own_visual_windows=windows,
            longest_own_visual_sample_span_s=max((w['sample_span_s'] for w in windows),default=0.),
            acknowledged_samples=acknowledged, max_local_joint_s=max_joint,
            confirmation_evidence={key:max((r.get('diagnostics',{}).get(key,0)
                for r in rows),default=0) for key in
                ('pixel_identity_hits','motion_hits','fast_geo_hits')},
            last_vision_stats=rows[-1].get('diagnostics',{}).get('vision',{}) if rows else {},
            missions=missions, events=events))
    return dict(run=str(run_dir.resolve()),
        evaluation_sha256=hashlib.sha256(evaluation_path.read_bytes()).hexdigest(),
        official={k: evaluation[k] for k in ('total_score','n_reports','n_destroyed','penalty')},
        official_coop_ticks={k:v['coop_ticks'] for k,v in evaluation['per_target'].items()},
        agents=agents,
        limits='Public log samples may be sparse. Local joint seconds are visual heuristics, '
               'not the engine timer. Mission IDs are local associations, not true target IDs. '
               'Acknowledgment counts require an active member phase: raw flags may persist '
               'after the controller releases its mission. Visual windows only span consecutive '
               'positive public samples separated by at most 0.8 seconds; they do not prove '
               'continuous engine detection or extend past the last positive sample.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(official=result['official'], agents=[
        {k:v for k,v in agent.items() if k not in ('missions','events','own_visual_windows')} for agent in result['agents']]),
        ensure_ascii=False))


if __name__ == '__main__':
    main()
