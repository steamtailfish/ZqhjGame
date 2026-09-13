"""Inspect camera zoom in completed public logs; never opens a live run or images."""
import argparse
import bisect
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median


ACTIVE = ('OFFER', 'APPROACH', 'TRACK_PAIR', 'RECOVER')
FOV_TOLERANCE = .1
RECEIPT_TOLERANCE = 1e-6


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fov_key(value):
    return format(float(value), '.6g') if finite(value) else 'unknown'


def capture(row):
    return row.get('diagnostics', {}).get('capture') or {}


def membership(row, uid):
    c = capture(row)
    phase = c.get('phase', 'unknown')
    owner, partner = c.get('owner'), c.get('partner')
    assigned = owner is not None and c.get('mission') is not None
    if assigned and uid in (owner, partner):
        if phase in ACTIVE:
            return 'active_owner' if uid == owner else 'active_partner'
        return 'released_member' if phase == 'RELEASE' else 'inactive_member'
    return 'searching_third' if assigned else 'unassigned'


def command_fovs(row):
    return [command.get('params', {}).get('angle') for command in row.get('commands', [])
            if command.get('verb') == 'set_fov']


class PublicRows:
    def __init__(self, rows):
        self.rows = rows
        self.times = [row.get('score_sim_s') for row in rows]
        if any(not finite(t) for t in self.times) or any(b < a for a, b in zip(self.times, self.times[1:])):
            raise ValueError('public times must be finite and monotonic')
        gaps = [b-a for a, b in zip(self.times, self.times[1:]) if b > a]
        self.cadence = median(gaps) if gaps else None
        self.window_tolerance = min(.5, .6*self.cadence) if self.cadence else 1e-6
        self.max_segment_gap = max(1., 2*self.cadence) if self.cadence else 1.

    def source_pose(self, row):
        d = row.get('diagnostics', {})
        receipt = d.get('receipt_first_seen_sim_s')
        if not finite(receipt):
            return dict(status='receipt_time_missing', pose=None)
        start = bisect.bisect_left(self.times, receipt-RECEIPT_TOLERANCE)
        end = bisect.bisect_right(self.times, receipt+RECEIPT_TOLERANCE)
        if end-start != 1:
            return dict(status='no_exact_receipt_sample' if end == start else 'ambiguous_receipt_sample', pose=None)
        source = self.rows[start]
        digest = row.get('boxes_photo_sha256')
        if not digest or not source.get('photo_sha256'):
            return dict(status='source_digest_missing', pose=None)
        if source['photo_sha256'] != digest:
            return dict(status='receipt_sample_digest_mismatch', pose=None)
        own = source.get('own', {})
        return dict(status='exact_receipt_time_and_digest_match', sample_s=source['score_sim_s'],
            receipt_time_error_s=source['score_sim_s']-receipt, photo_sha256=digest,
            pose={key: own.get(key) for key in ('lat', 'lon', 'alt', 'heading_deg', 'gimbal_pan',
                                               'gimbal_tilt', 'gimbal_fov_deg')},
            meaning='Recorded source receipt pose, not verified camera capture pose.')

    def snapshot(self, row, uid):
        d = row.get('diagnostics', {})
        c = capture(row)
        time = row['score_sim_s']
        raw = d.get('chosen_pixel')
        box = None
        if isinstance(raw, dict):
            box = {key: raw.get(key) for key in ('category', 'confidence', 'class_margin', 'width', 'height')}
            box['box_width_px'] = raw['x2']-raw['x1'] if finite(raw.get('x2')) and finite(raw.get('x1')) else None
            box['box_height_px'] = raw['y2']-raw['y1'] if finite(raw.get('y2')) and finite(raw.get('y1')) else None
        receipt = d.get('receipt_first_seen_sim_s')
        return dict(t=time, membership=membership(row, uid), phase=c.get('phase', 'unknown'),
            owner=c.get('owner'), partner=c.get('partner'), mission=c.get('mission'),
            command_fov_deg=command_fovs(row), observed_own_fov_deg=row.get('own', {}).get('gimbal_fov_deg'),
            selected_raw_box=box, raw_candidate_count=len(row.get('boxes') or []),
            identity_state=c.get('identity_state', 'unknown'), own_visual=c.get('own_visual'),
            source_receipt_s=receipt, source_receipt_age_s=time-receipt if finite(receipt) else None,
            source_photo_pose=self.source_pose(row),
            geometry_state=d.get('geometry_state', 'unknown'),
            hits={key: d.get(key) for key in ('pixel_hits', 'pixel_identity_hits', 'motion_hits', 'fast_geo_hits')})

    def window(self, time, uid):
        result = []
        for offset in range(-4, 5):
            wanted = time+offset
            i = bisect.bisect_left(self.times, wanted)
            indices = [j for j in (i-1, i) if 0 <= j < len(self.rows)]
            best = min(indices, key=lambda j: abs(self.times[j]-wanted)) if indices else None
            if best is None or abs(self.times[best]-wanted) > self.window_tolerance:
                result.append(dict(requested_offset_s=offset, status='no_public_sample_within_window_tolerance'))
                continue
            result.append(dict(requested_offset_s=offset, actual_offset_s=self.times[best]-time,
                alignment_error_s=self.times[best]-wanted, status='sampled', sample=self.snapshot(self.rows[best], uid)))
        return result


def analyze(run):
    run = Path(run)
    manifest_path = run / 'run.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status') != 'completed':
        raise ValueError('official run must be completed before reading any public observations')
    agents = []
    for path in sorted((run / 'observations').glob('*/observations.jsonl')):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        public = PublicRows(rows)
        uid = path.parent.name
        commands, observed, by_membership = Counter(), Counter(), {}
        source_status = Counter()
        transitions, segments = [], []
        previous, segment = None, None
        ever_assigned = False
        for row in rows:
            time = row['score_sim_s']
            c = capture(row)
            role = membership(row, uid)
            fov = row.get('own', {}).get('gimbal_fov_deg')
            commands.update(fov_key(v) for v in command_fovs(row))
            observed[fov_key(fov)] += 1
            group = by_membership.setdefault(role, dict(samples=0, samples_without_fov_command=0, command_fov_counts=Counter(),
                observed_fov_counts=Counter(), own_visual_samples=0))
            group['samples'] += 1
            group['samples_without_fov_command'] += not bool(command_fovs(row))
            group['command_fov_counts'].update(fov_key(v) for v in command_fovs(row))
            group['observed_fov_counts'][fov_key(fov)] += 1
            group['own_visual_samples'] += c.get('own_visual') is True
            source_status[public.source_pose(row)['status']] += 1
            previous_fov = previous.get('own', {}).get('gimbal_fov_deg') if previous else None
            changed = (previous is not None and finite(fov) and finite(previous_fov)
                       and abs(fov-previous_fov) > FOV_TOLERANCE)
            if changed:
                active = role in ('active_owner', 'active_partner') or membership(previous, uid) in ('active_owner', 'active_partner')
                context = 'active_pair_related' if active else 'after_assignment' if ever_assigned else 'before_any_assignment'
                transitions.append(dict(observed_at_s=time, previous_observed_at_s=previous['score_sim_s'],
                    from_fov_deg=previous_fov, to_fov_deg=fov, context=context,
                    previous_membership=membership(previous, uid), membership=role,
                    observation_gap_s=time-previous['score_sim_s'],
                    windows=public.window(time, uid)))
            if c.get('owner') is not None and c.get('mission') is not None:
                ever_assigned = True
            same_segment = (segment is not None and time-segment['last_s'] <= public.max_segment_gap
                            and finite(fov) and finite(segment['first_observed_fov_deg'])
                            and abs(fov-segment['first_observed_fov_deg']) <= FOV_TOLERANCE)
            if not same_segment:
                segment = dict(first_s=time, last_s=time, sample_span_s=0., samples=0,
                    first_observed_fov_deg=fov, min_observed_fov_deg=fov if finite(fov) else None,
                    max_observed_fov_deg=fov if finite(fov) else None,
                    phases=Counter(), memberships=Counter(), own_visual_samples=0,
                    geometry_states=Counter(), max_hits={})
                segments.append(segment)
            segment['last_s'] = time
            segment['sample_span_s'] = time-segment['first_s']
            segment['samples'] += 1
            if finite(fov):
                segment['min_observed_fov_deg'] = min(segment['min_observed_fov_deg'], fov)
                segment['max_observed_fov_deg'] = max(segment['max_observed_fov_deg'], fov)
            segment['phases'][c.get('phase', 'unknown')] += 1
            segment['memberships'][role] += 1
            segment['own_visual_samples'] += c.get('own_visual') is True
            d = row.get('diagnostics', {})
            segment['geometry_states'][d.get('geometry_state', 'unknown')] += 1
            for key in ('pixel_hits', 'pixel_identity_hits', 'motion_hits', 'fast_geo_hits'):
                if finite(d.get(key)):
                    segment['max_hits'][key] = max(segment['max_hits'].get(key, 0), d[key])
            previous = row
        agents.append(dict(uid=uid, samples=len(rows), command_fov_counts=commands,
            samples_without_fov_command=sum(not command_fovs(row) for row in rows),
            observed_fov_counts=observed, by_membership=by_membership,
            source_pose_lookup_counts=source_status, observed_fov_transitions=transitions,
            active_pair_related_transition_count=sum(t['context'] == 'active_pair_related' for t in transitions),
            stable_fov_segments=segments, median_public_sample_interval_s=public.cadence,
            window_sample_tolerance_s=public.window_tolerance, max_stable_segment_sample_gap_s=public.max_segment_gap,
            source_observations_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return dict(run=str(run.resolve()), status=manifest['status'],
        run_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(), agents=agents,
        definitions=dict(fov_change_tolerance_deg=FOV_TOLERANCE, exact_source_receipt_tolerance_s=RECEIPT_TOLERANCE,
            windows='Nearest logged public sample to each requested offset -4..+4 seconds. '
                    'Tolerance is min(0.5s, 0.6*median positive public interval); absent samples are explicit.',
            stable_segment='Successive observed FOVs remain within0.1deg of the first segment FOV, '
                'with no gap over max(1s, 2*median public interval). Phase and membership counts are grouped inside.',
            native_startup='Initial native FOV can differ from the first requested FOV. Pre-assignment '
                'transitions are shown separately from active-pair zoom.'),
        limitations='Commands, observed own-camera FOV and box-source receipt-pose FOV are distinct. '
            'A source pose is reported only for one timestamp match within1e-6s with matching photo digest; '
            'otherwise it is unknown. Even an exact receipt-pose match is not capture-time calibration. '
            'Transition times are sampled observations, not exact actuator times. Stable segment spans do '
            'not prove uninterrupted imagery or detection. Box dimensions/category/confidence are raw logged '
            'values, without relabeling or treating zoom as identity/capture. No images, judge truths, live '
            'engine, or training data are read.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(run=result['run'], agents=[dict(uid=a['uid'], samples=a['samples'],
        command_fov_counts=a['command_fov_counts'], observed_fov_counts=a['observed_fov_counts'],
        samples_without_fov_command=a['samples_without_fov_command'],
        active_pair_related_transitions=a['active_pair_related_transition_count'],
        all_observed_transitions=len(a['observed_fov_transitions']), stable_fov_segments=len(a['stable_fov_segments']))
        for a in result['agents']]), ensure_ascii=False))


if __name__ == '__main__':
    main()
