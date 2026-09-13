"""Audit owner/partner agreement in completed public logs; never use online."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


NEW_FIELDS = ('pair_consistent', 'pair_residual_m', 'owner_reference_sample_s',
              'owner_reference_xy')
NUMBER_FIELDS = ('pair_residual_m', 'owner_reference_age_s', 'local_joint_s',
                 'max_local_joint_s', 'paired_samples')
MISSING = object()


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def field_state(value, kind):
    if value is MISSING:
        return 'missing'
    if value is None:
        return 'null'
    valid = (isinstance(value, bool) if kind == 'bool' else
             isinstance(value, (list, tuple)) and len(value) == 2 and all(number(x) for x in value)
             if kind == 'xy' else number(value))
    return 'known' if valid else 'invalid'


def role_for(uid, capture):
    if 'owner' not in capture:
        return 'unknown'
    owner = capture['owner']
    if owner is None:
        return 'unassigned'
    if uid == owner:
        return 'owner'
    if 'partner' not in capture:
        return 'unknown'
    return 'partner' if uid == capture['partner'] else 'third'


def bucket():
    return dict(samples=0, active_samples=0, phases=Counter(), own_visual=Counter(),
        pair_consistent=Counter(), fields={name: Counter() for name in NEW_FIELDS},
        numbers={name: dict(states=Counter(), values=[]) for name in NUMBER_FIELDS},
        spatial_rejected_samples=0)


def observe(metrics, capture, now):
    metrics['samples'] += 1
    phase = capture.get('phase', 'unknown')
    metrics['phases'][phase] += 1
    active = phase in ('OFFER', 'APPROACH', 'TRACK_PAIR', 'RECOVER')
    metrics['active_samples'] += active
    for name in ('own_visual', 'pair_consistent'):
        value = capture.get(name, MISSING)
        label = ('true' if value else 'false') if isinstance(value, bool) else 'unknown'
        metrics[name][label] += 1
    for name in NEW_FIELDS:
        kind = 'bool' if name == 'pair_consistent' else 'xy' if name.endswith('_xy') else 'number'
        metrics['fields'][name][field_state(capture.get(name, MISSING), kind)] += 1
    sample = capture.get('owner_reference_sample_s', MISSING)
    age = now-sample if number(now) and number(sample) else sample if sample is MISSING or sample is None else 'invalid'
    values = {name: capture.get(name, MISSING) for name in NUMBER_FIELDS}
    values['owner_reference_age_s'] = age
    for name, value in values.items():
        state = field_state(value, 'number')
        metrics['numbers'][name]['states'][state] += 1
        if state == 'known':
            metrics['numbers'][name]['values'].append(value)
    residual = capture.get('pair_residual_m')
    metrics['spatial_rejected_samples'] += bool(active and capture.get('pair_consistent') is False
                                               and number(residual) and residual > 25.)
    return age


def quantile(values, fraction):
    position = (len(values)-1)*fraction
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi]-values[lo])*(position-lo)


def coverage(counter):
    result = {name: counter[name] for name in ('known', 'missing', 'null', 'invalid')}
    result['unknown'] = result['missing']+result['null']+result['invalid']
    return result


def summarize(metrics):
    result = {name: metrics[name] for name in ('samples', 'active_samples', 'spatial_rejected_samples')}
    result['phase_samples'] = dict(metrics['phases'])
    for name in ('own_visual', 'pair_consistent'):
        result[name] = {label: metrics[name][label] for label in ('true', 'false', 'unknown')}
    result['new_field_coverage'] = {name: coverage(counts) for name, counts in metrics['fields'].items()}
    result['numeric_samples'] = {}
    for name, metric in metrics['numbers'].items():
        values = sorted(metric['values'])
        result['numeric_samples'][name] = dict(coverage(metric['states']),
            min=values[0] if values else None, p50=quantile(values, .5) if values else None,
            p90=quantile(values, .9) if values else None, max=values[-1] if values else None)
    return result


def partner_check(capture, age):
    reasons = []
    agreement = capture.get('pair_consistent', MISSING)
    if agreement is False:
        reasons.append('visible_partner_pair_inconsistent')
    if number(age) and age < -1e-9:
        reasons.append('visible_partner_owner_reference_from_future')
    elif number(age) and age > .8+1e-9:
        reasons.append('visible_partner_owner_reference_stale')
    residual = capture.get('pair_residual_m')
    if number(residual) and residual > 25.:
        reasons.append('visible_partner_residual_above_25m')
    if reasons:
        return 'failed', reasons
    reference_xy = capture.get('owner_reference_xy', MISSING)
    if (not isinstance(agreement, bool) or not number(age) or not number(residual)
            or field_state(reference_xy, 'xy') != 'known'):
        return 'unknown', []
    return 'passed', []


def analyze(run_dir):
    run_dir = Path(run_dir)
    manifest_bytes = (run_dir / 'run.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    # This check precedes every read of observation data, including legacy runs.
    if manifest.get('status') != 'completed':
        raise ValueError('The official run must be completed before agreement analysis')
    total, roles, agents = bucket(), {}, []
    checks = Counter(considered=0, passed=0, failed=0, unknown=0)
    examples = []
    for path in sorted((run_dir / 'observations').glob('*/observations.jsonl')):
        uid = path.parent.name
        data = path.read_bytes()
        metrics, agent_roles = bucket(), {}
        for line in data.decode('utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            capture = row.get('diagnostics', {}).get('capture') or {}
            now = row.get('score_sim_s', MISSING)
            role = role_for(uid, capture)
            for destination in (total, metrics, roles.setdefault(role, bucket()),
                                agent_roles.setdefault(role, bucket())):
                age = observe(destination, capture, now)
            # Owners and third aircraft are not subject to the partner claim
            # invariant. Unknown legacy fields do not become false/violations.
            if role == 'partner' and capture.get('own_visual') is True:
                verdict, reasons = partner_check(capture, age)
                checks['considered'] += 1
                checks[verdict] += 1
                if verdict == 'failed' and len(examples) < 8:
                    examples.append(dict(uid=uid, t=now if number(now) else None,
                        owner=capture.get('owner'), partner=capture.get('partner'),
                        mission=capture.get('mission'), phase=capture.get('phase'),
                        pair_consistent=capture.get('pair_consistent'),
                        pair_residual_m=capture.get('pair_residual_m'),
                        owner_reference_sample_s=capture.get('owner_reference_sample_s'),
                        owner_reference_age_s=age if number(age) else None, reasons=reasons))
        agents.append(dict(uid=uid, observation_sha256=hashlib.sha256(data).hexdigest(),
            **summarize(metrics), roles={name: summarize(value) for name, value in agent_roles.items()}))
    return dict(schema_version=1, run=str(run_dir.resolve()), run_status=manifest['status'],
        run_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        summary=summarize(total), roles={name: summarize(value) for name, value in roles.items()},
        agents=agents, visible_partner_checks=dict(checks), violation_examples=examples,
        limits='Completed public log samples only. Missing, null or invalid new fields are unknown, '
               'not false. Spatial rejection means active pair_consistent=False with residual>25m; '
               'other false samples may merely lack an independent view. Role buckets describe '
               'recorded assignments, not hidden target identity. Joint times and paired_samples '
               'are controller counters summarized by quantiles/max, never summed into official '
               'capture time. This tool does not infer source-writing causality or judge success.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(samples=result['summary']['samples'],
        agreement=result['summary']['pair_consistent'],
        visible_partner_checks=result['visible_partner_checks']), ensure_ascii=False))


if __name__ == '__main__':
    main()
