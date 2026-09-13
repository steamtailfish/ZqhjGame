"""Completed-run identity-memory diagnostics; never an Agent/training dependency."""
import argparse
import bisect
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median

from analyze_judge_trace import read_time_origin


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def completed_manifest(run):
    manifest = json.loads((run / 'run.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'completed':
        raise ValueError('official run must be completed before reading observations or judge analysis')
    return manifest


class JudgeAlignment:
    """Nearest bracketed sample, without filling a missing interval or extrapolating."""
    def __init__(self, run, manifest, path):
        data = json.loads(path.read_text(encoding='utf-8'))
        declared_run = data.get('run')
        if declared_run:
            declared = Path(declared_run).resolve()
            completed_manifest(declared)
            if declared != run.resolve():
                raise ValueError('judge analysis declares a different run')
        axis = data.get('time_axis', {})
        if (axis.get('clock') != 'official score-relative seconds' or
                axis.get('formula') != 't = engine_sim_time - sim_t0'):
            raise ValueError('judge analysis must contain a normalized official score time axis')
        origin = read_time_origin(run, manifest)
        precision = axis.get('origin_rounding_bound_s')
        if not finite(precision) or not 0 <= precision <= .001:
            raise ValueError('judge origin rounding bound is missing or unsupported')
        self.precision = precision + origin['origin_rounding_bound_s'] + 1e-8
        if not finite(axis.get('sim_t0')) or abs(axis['sim_t0']-origin['sim_t0']) > self.precision:
            raise ValueError('judge and completed-run time origins disagree')
        end = manifest.get('last_sim_s')
        if (not finite(end) or not finite(axis.get('official_last_sim_s')) or
                abs(end-axis['official_last_sim_s']) > self.precision):
            raise ValueError('judge analysis does not match the completed-run ending time')
        timeline = data.get('timeline', [])
        times = [row.get('t') for row in timeline]
        if any(not finite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError('judge sample times must be finite and strictly increasing')
        # The external recorder may retain a frame after the official run ends.
        self.rows = [row for row in timeline if 0 <= row['t'] <= end]
        self.times = [row['t'] for row in self.rows]
        intervals = [b-a for a, b in zip(self.times, self.times[1:])]
        self.nominal = median(intervals) if intervals else None
        self.max_gap = 1.5*self.nominal if self.nominal else None
        self.info = dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            association='declared run verified' if declared_run else
                'caller-supplied association; origin and official ending verified, source has no run identifier',
            samples_in_official_window=len(self.rows), excluded_outside_run_samples=len(timeline)-len(self.rows),
            first_sample_s=self.times[0] if self.times else None,
            last_sample_s=self.times[-1] if self.times else None,
            median_sample_interval_s=self.nominal, max_bracket_gap_s=self.max_gap,
            origin_comparison_tolerance_s=self.precision,
            rule='Exact timestamps match directly. Otherwise require bracketing samples with gap <= '
                 '1.5 * measured median interval, and nearest difference <= half the bracket gap plus '
                 'origin rounding tolerance. No extrapolation beyond recorded samples.',
            meaning='effective_true/decoy/none describe the engine-selected detection at a nearby sampled '
                    'time; none is not a classifier error. This is coverage diagnosis, not a confusion '
                    'matrix, capture timer, or training labels.')

    def match(self, uid, time):
        if not self.times:
            return None, 'no_judge_samples', None
        i = bisect.bisect_left(self.times, time)
        if i < len(self.times) and abs(self.times[i]-time) <= 1e-8:
            index = i
        elif i == 0 or i == len(self.times):
            return None, 'outside_recorded_span', None
        else:
            gap = self.times[i]-self.times[i-1]
            if gap > self.max_gap+self.precision:
                return None, 'judge_sampling_gap', None
            index = min((i-1, i), key=lambda j: abs(self.times[j]-time))
            if abs(self.times[index]-time) > gap/2+self.precision:
                return None, 'outside_alignment_tolerance', None
        match = self.rows[index].get('matches', {}).get(uid)
        if not isinstance(match, dict):
            return None, 'uav_missing_from_judge_sample', None
        if match.get('is_effective') is True:
            label = 'effective_true'
        elif match.get('was_misid') is True:
            label = 'decoy'
        elif match.get('is_effective') is False and match.get('was_misid') is False:
            label = 'none'
        else:
            return None, 'incomplete_judge_match', None
        return label, None, abs(self.times[index]-time)


def new_counts():
    return dict(samples=0, identity_field_samples=0, own_visual_samples=0,
        states=Counter(), visible_states=Counter(), remembered_visible_raw_categories=Counter(),
        identity_decoy_hits=Counter(), max_identity_decoy_hits=None,
        last_true_age_samples=0, last_true_age_min_s=None, last_true_age_max_s=None,
        photo_checks=Counter(), judge_coverage=Counter(), judge_visible_coverage=Counter(),
        judge_remembered_visible_coverage=Counter(), judge_unaligned_reasons=Counter(),
        judge_by_identity_state={},
        max_judge_alignment_error_s=None, anomaly_examples=[])


def accumulate(counts, row, alignment):
    d = row.get('diagnostics', {})
    c = d.get('capture') or {}
    time = row['score_sim_s']
    state = c.get('identity_state')
    known = isinstance(state, str) and bool(state)
    state = state if known else 'unknown'
    visible = c.get('own_visual') is True
    remembered = visible and state == 'remembered_true'
    pixel = d.get('chosen_pixel')
    category = pixel.get('category', 'unknown') if isinstance(pixel, dict) else 'no_chosen_pixel'
    counts['samples'] += 1
    counts['identity_field_samples'] += known
    counts['states'][state] += 1
    counts['own_visual_samples'] += visible
    if visible:
        counts['visible_states'][state] += 1
    if remembered:
        counts['remembered_visible_raw_categories'][str(category)] += 1
    hits = c.get('identity_decoy_hits')
    valid_hits = isinstance(hits, int) and not isinstance(hits, bool) and hits >= 0
    counts['identity_decoy_hits'][str(hits) if valid_hits else 'unknown'] += 1
    if valid_hits:
        counts['max_identity_decoy_hits'] = max(counts['max_identity_decoy_hits'] or 0, hits)
    last_true = c.get('identity_last_true_s')
    if finite(last_true):
        age = time-last_true
        counts['last_true_age_samples'] += 1
        lo, hi = counts['last_true_age_min_s'], counts['last_true_age_max_s']
        counts['last_true_age_min_s'] = age if lo is None else min(lo, age)
        counts['last_true_age_max_s'] = age if hi is None else max(hi, age)
    issues = []
    if visible:
        current_known = 'photo_sha256' in row
        current_present = bool(row.get('photo_sha256'))
        source_known = 'boxes_photo_sha256' in row
        source_present = bool(row.get('boxes_photo_sha256'))
        receipt = d.get('receipt_first_seen_sim_s')
        source_age = time-receipt if finite(receipt) else None
        if not current_known:
            counts['photo_checks']['visible_current_photo_provenance_unknown'] += 1
        elif not current_present:
            counts['photo_checks']['visible_without_current_photo'] += 1
        if not source_known:
            counts['photo_checks']['visible_source_photo_provenance_unknown'] += 1
        elif not source_present:
            issues.append('visible_without_source_photo')
        if pixel is None:
            issues.append('visible_without_chosen_pixel')
        if source_age is None:
            counts['photo_checks']['visible_source_age_unknown'] += 1
        elif source_age < -1e-8:
            issues.append('visible_with_future_source_time')
        elif source_age > .8+1e-8:
            issues.append('visible_with_source_older_than_0_8_s')
        if (source_present and pixel is not None and source_age is not None and 0 <= source_age <= .8+1e-8):
            counts['photo_checks']['visible_with_fresh_source_evidence'] += 1
            if current_known and not current_present:
                counts['photo_checks']['visible_without_current_but_fresh_cached_source'] += 1
        for issue in issues:
            counts['photo_checks'][issue] += 1
        if issues and len(counts['anomaly_examples']) < 12:
            counts['anomaly_examples'].append(dict(t=time, identity_state=state, issues=issues,
                raw_category=category, source_photo_age_s=source_age))
    if alignment is not None:
        label, reason, difference = alignment
        label = label or 'unaligned'
        counts['judge_coverage'][label] += 1
        counts['judge_by_identity_state'].setdefault(state, Counter())[label] += 1
        if visible:
            counts['judge_visible_coverage'][label] += 1
        if remembered:
            counts['judge_remembered_visible_coverage'][label] += 1
        if reason:
            counts['judge_unaligned_reasons'][reason] += 1
        if difference is not None:
            counts['max_judge_alignment_error_s'] = max(counts['max_judge_alignment_error_s'] or 0., difference)


def analyze(run, judge_path=None):
    run = Path(run)
    manifest = completed_manifest(run)  # Must precede every other input read.
    judge = JudgeAlignment(run, manifest, Path(judge_path)) if judge_path else None
    agents = []
    for path in sorted((run / 'observations').glob('*/observations.jsonl')):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        times = [row.get('score_sim_s') for row in rows]
        if any(not finite(t) for t in times) or any(b < a for a, b in zip(times, times[1:])):
            raise ValueError(f'public sample times must be finite and monotonic: {path}')
        uid = path.parent.name
        agent = new_counts()
        missions, releases, phases = {}, Counter(), Counter()
        previous_release = None
        for row in rows:
            time = row['score_sim_s']
            c = row.get('diagnostics', {}).get('capture') or {}
            aligned = judge.match(uid, time) if judge else None
            accumulate(agent, row, aligned)
            phase = c.get('phase', 'unknown')
            phases[phase] += 1
            owner, number = c.get('owner'), c.get('mission')
            key = f'{owner}:{number}' if owner is not None and number is not None else None
            release = (key, c.get('reason', 'unknown')) if phase == 'RELEASE' else None
            if release and release != previous_release:
                releases[release[1]] += 1
            if key:
                if key not in missions:
                    missions[key] = dict(first_s=time, last_s=time, partners=[], roles=Counter(),
                        phases=Counter(), release_events=[], identity=new_counts())
                mission = missions[key]
                mission['last_s'] = time
                partner = c.get('partner')
                if partner is not None and partner not in mission['partners']:
                    mission['partners'].append(partner)
                role = 'owner' if uid == owner else 'partner' if uid == partner else 'searching_third'
                mission['roles'][role] += 1
                mission['phases'][phase] += 1
                accumulate(mission['identity'], row, aligned)
                if release and release != previous_release:
                    mission['release_events'].append(dict(t=time, reason=release[1]))
            previous_release = release
        agent.update(uid=uid, phases=phases, releases_by_reason=releases, missions=missions,
            source_observations_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        agents.append(agent)
    return dict(run=str(run.resolve()), run_status=manifest['status'],
        run_manifest_sha256=hashlib.sha256((run / 'run.json').read_bytes()).hexdigest(),
        judge_alignment=judge.info if judge else None, agents=agents,
        limitations='Counts are recorded public samples, not elapsed time. Missing identity fields are unknown, '
            'including older v26 logs. Raw categories come from diagnostics.chosen_pixel, without relabeling '
            'the detector output. A missing current photo can coexist with a fresh cached source; this is '
            'counted separately from missing source evidence or stale/no-pixel visibility contradictions. '
            'Missing provenance is not proof that no photo existed. Anomaly examples are limited to 12 per '
            'agent or mission. Mission IDs are local associations. Optional judge coverage is a nearby '
            'engine detection observation and none is not classification error. No truth labels are emitted '
            'for training, and this tool never connects to a running engine.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--judge-analysis', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.run, args.judge_analysis)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(run=result['run'], agents=[dict(uid=a['uid'], samples=a['samples'],
        identity_field_samples=a['identity_field_samples'], states=a['states'],
        remembered_visible_raw_categories=a['remembered_visible_raw_categories'], photo_checks=a['photo_checks'],
        judge_visible_coverage=a['judge_visible_coverage'], releases=a['releases_by_reason'])
        for a in result['agents']]), ensure_ascii=False))


if __name__ == '__main__':
    main()
