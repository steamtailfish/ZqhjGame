"""Audit exact public perception inputs from a completed capture run.

python tools/analyze_capture_loss_inputs.py RUN --output review.json
No Agent, simulator, judge trace or evaluation is loaded. Geometry guard reasons
reuse analyze_capture_geometry and its checked source-version contract.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

import analyze_capture_geometry as geometry_analysis


ACTIVE = {'OFFER', 'APPROACH', 'TRACK_PAIR', 'RECOVER'}
number = geometry_analysis.number


def capture(row):
    return (row.get('diagnostics') or {}).get('capture') or {}


def source_key(digest, receipt):
    if isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) and number(receipt):
        return digest, receipt
    return None


def observation_key(row):
    return source_key(row.get('boxes_photo_sha256'),
                      (row.get('diagnostics') or {}).get('receipt_first_seen_sim_s'))


def rows(path):
    if not path.is_file():
        return [], dict(status='missing', path=str(path))
    data = path.read_bytes()
    records, malformed, invalid_time = [], 0, 0
    for line_no, line in enumerate(data.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('not an object')
            if 'score_sim_s' in row and not number(row['score_sim_s']):
                invalid_time += 1
                continue
            records.append((line_no, row))
        except (json.JSONDecodeError, ValueError):
            malformed += 1
    return records, dict(status='available', path=str(path), sha256=hashlib.sha256(data).hexdigest(),
                         records=len(records), malformed_lines=malformed, invalid_time_lines=invalid_time)


def strong(box):
    return (isinstance(box, dict) and box.get('category') == 'true_vehicle'
            and number(box.get('confidence')) and box['confidence'] >= .9
            and number(box.get('class_margin')) and box['class_margin'] >= .8)


def motion_evidence(row):
    """A current residual witness proves validity; do not invent the 8s lease."""
    d = row.get('diagnostics') or {}
    now, receipt = row.get('score_sim_s'), d.get('receipt_first_seen_sim_s')
    until = d.get('motion_verified_until')
    if number(until) and number(now):
        return dict(valid=now <= until, basis='recorded_motion_verified_until', until_s=until)
    box = d.get('chosen_pixel') or {}
    residual, hits, width = d.get('pixel_motion_px'), d.get('motion_hits'), box.get('width')
    if (number(now) and number(receipt) and 0 <= now-receipt <= .8+1e-9
            and number(residual) and number(hits) and number(width)
            and hits >= 2 and 2.5 <= residual <= .12*width):
        return dict(valid=True, basis='fresh_recorded_current_frame_motion_witness',
                    residual_px=residual, motion_hits=hits, source_age_s=now-receipt)
    return dict(valid=None, basis='motion_lease_not_recorded_and_no_current_frame_witness')


def unique(index, key):
    records = index.get(key, [])
    return records[0] if len(records) == 1 else None


def index_records(records, key_fn):
    result = defaultdict(list)
    for line, row in records:
        key = key_fn(row)
        if key is not None:
            result[key].append((line, row))
    return result


def load_agent(folder):
    observations, obs_info = rows(folder / 'observations.jsonl')
    snapshots, geo_info = rows(folder / 'geometry-inputs.jsonl')
    controls, control_info = rows(folder / 'control-events.jsonl')
    recording_path = folder / 'capture-recording.json'
    recording_data = recording_path.read_bytes() if recording_path.is_file() else None
    recording = json.loads(recording_data) if recording_data is not None else {}
    frames = list(enumerate(recording.get('key_frames', []), 1))
    geo_index = index_records(snapshots, lambda r: source_key(r.get('source_image_sha256'), r.get('source_receipt_sim_s')))
    obs_index = index_records(observations, observation_key)
    frame_index = index_records(frames, lambda r: source_key(r.get('source_photo_sha256'), r.get('source_receipt_s')))
    # Geometry snapshots enumerate processed sources; legacy sparse observations
    # cannot establish adjacency or a calibrated receipt pose.
    keys = sorted(set(geo_index) if snapshots else set(obs_index), key=lambda k: (k[1], k[0]))
    return dict(uid=folder.name, folder=folder, observations=observations, snapshots=snapshots,
        controls=controls, geo_index=geo_index, obs_index=obs_index, frame_index=frame_index,
        keys=keys, by_receipt=index_records([(i, dict(key=k)) for i, k in enumerate(keys)], lambda r: r['key'][1]),
        provenance=dict(observations=obs_info, geometry_inputs=geo_info, control_events=control_info,
            capture_recording=dict(status='available' if recording else 'missing',
                path=str(recording_path), dropped=recording.get('dropped'),
                sha256=hashlib.sha256(recording_data).hexdigest() if recording_data is not None else None,
                limits=recording.get('limits'), retained=recording.get('retained'),
                wrapper_dropped=recording.get('wrapper_dropped'))),
        stream_basis='geometry_input_processed_sources' if snapshots else 'legacy_sparse_observation_sources')


def event_candidates(agent):
    result, unknown_motion, seen = [], 0, set()

    def add(kind, row, line, origin, key):
        if not number(row.get('score_sim_s')):
            return
        c = capture(row)
        # Many controls refer to the same processed image. Retain the first
        # observed transition/source combination without pretending a new image.
        signature = kind, c.get('owner'), c.get('mission'), key
        if signature in seen:
            return
        seen.add(signature)
        result.append(dict(kind=kind, uid=agent['uid'], key=key, row=row, line=line,
                           origin=origin, event_sim_s=row.get('score_sim_s')))

    for line, row in agent['observations']:
        d = row.get('diagnostics') or {}
        raw = [b for b in row.get('boxes', []) if strong(b)]
        evidence = motion_evidence(row)
        if raw and d.get('geo_estimate', 'missing') is None:
            if evidence['valid'] is True:
                add('strong_true_motion_without_geo', row, line, 'observations.jsonl', observation_key(row))
            elif evidence['valid'] is None:
                unknown_motion += 1
        c = capture(row)
        if (c.get('owner') == agent['uid'] and c.get('phase') in ACTIVE
                and not c.get('own_visual') and d.get('chosen_pixel') is None
                and row.get('boxes') and number(c.get('identity_last_true_s'))):
            add('owner_raw_candidates_without_selected_box', row, line, 'observations.jsonl', observation_key(row))

    # New controls have denser phase evidence; use sparse observations only when
    # the complete-control recorder is absent. Empty command batches are absent
    # in either stream, so these remain recorded transitions, not exact tick loss.
    stream = agent['controls'] if agent['controls'] else agent['observations']
    origin = 'control-events.jsonl' if agent['controls'] else 'observations.jsonl'
    previous = None
    for line, row in sorted((item for item in stream if number(item[1].get('score_sim_s'))),
                            key=lambda item: item[1]['score_sim_s']):
        c = capture(row)
        if (previous and c.get('owner') == agent['uid'] and c.get('phase') in ACTIVE
                and c.get('mission') == capture(previous).get('mission')
                and c.get('owner') == capture(previous).get('owner')
                and capture(previous).get('own_visual') is True and c.get('own_visual') is False):
            key = observation_key(row)
            if key is None:
                receipt = (row.get('diagnostics') or {}).get('receipt_first_seen_sim_s')
                match = unique(agent['by_receipt'], receipt)
                key = match[1]['key'] if match else None
            add('owner_visual_lost', row, line, origin, key)
        previous = row
    return result, unknown_motion


def source_detail(agent, key, geometry_module, cache):
    if key is None:
        return dict(status='missing_source_key')
    digest, receipt = key
    result = dict(key=dict(uid=agent['uid'], digest=digest, source_receipt_s=receipt),
                  capture_pose_calibrated=False)
    path = agent['folder'] / (digest + '.image')
    if path not in cache:
        cache[path] = ('missing' if not path.is_file() else
            'hash_verified' if hashlib.sha256(path.read_bytes()).hexdigest() == digest else 'hash_mismatch')
    result['image'] = dict(path=str(path.resolve()), status=cache[path])
    frame = unique(agent['frame_index'], key)
    pose = frame[1].get('source_receipt_pose') if frame else None
    exact = bool(frame and frame[1].get('receipt_pose_status') == 'exact_receipt_time_and_digest_match'
                 and isinstance(pose, dict) and str(pose.get('uid')) == agent['uid'])
    result['receipt_pose'] = dict(status='exact_recorded_receipt' if exact else 'missing_or_nonunique_exact_receipt',
                                  value=pose if exact else None, key_frame_index=frame[0] if frame else None)
    snap = unique(agent['geo_index'], key)
    if snap is None:
        result['geometry'] = dict(status='missing_or_nonunique_exact_snapshot', reason='UNKNOWN')
    else:
        line, snapshot = snap
        classified = geometry_analysis._classify(snapshot, geometry_module)
        state = snapshot.get('geometry') or {}
        old_digest = state.get('pair_old_digest')
        old_keys = [k for k in agent['keys'] if k[0] == old_digest and k[1] < receipt]
        result['geometry'] = dict(status='exact_snapshot', line=line,
            recorded_at_s=snapshot.get('recorded_at_s'), **classified,
            input_pose=state.get('last_pose'),
            homography=dict(matrix=state.get('homography'), old_digest=old_digest,
                new_digest=state.get('last_digest'), new_digest_matches_source=state.get('last_digest') == digest,
                old_source_key=dict(digest=old_keys[0][0], source_receipt_s=old_keys[0][1]) if len(old_keys) == 1 else None,
                old_source_status='unique_exact_digest' if len(old_keys) == 1 else 'missing_or_ambiguous'))
    return result


def make_example(agent, event, geometry_module, image_cache, control_limit):
    key, row = event['key'], event['row']
    index = agent['keys'].index(key) if key in agent['keys'] else None
    before = agent['keys'][index-1] if index is not None and index > 0 else None
    after = agent['keys'][index+1] if index is not None and index+1 < len(agent['keys']) else None
    d = row.get('diagnostics') or {}
    matched_observation = ((event['line'], row) if event['origin'] == 'observations.jsonl'
                           and key is not None and observation_key(row) == key
                           else unique(agent['obs_index'], key))
    raw_row = matched_observation[1] if matched_observation else row
    raw_d = raw_row.get('diagnostics') or {}
    details = dict(previous_recorded_source=source_detail(agent, before, geometry_module, image_cache),
                   current=source_detail(agent, key, geometry_module, image_cache),
                   next_recorded_source=source_detail(agent, after, geometry_module, image_cache))
    current_time = key[1] if key else event['event_sim_s']
    start = before[1] if before else current_time
    end = max(after[1] if after else current_time, event['event_sim_s'])+.5
    controls = []
    for line, control in agent['controls']:
        t = control.get('score_sim_s')
        if not number(t) or not start <= t <= end:
            continue
        commands = [c for c in control.get('commands', []) if isinstance(c, dict)
                    and isinstance(c.get('verb'), str) and not c['verb'].startswith('comm.')]
        if commands:
            controls.append(dict(line=line, score_sim_s=t, own=control.get('own'), commands=commands))
    retained = controls if len(controls) <= control_limit else [controls[round(i*(len(controls)-1)/(control_limit-1))]
                                                              for i in range(control_limit)]
    return dict(kind=event['kind'], uid=event['uid'], event_sim_s=event['event_sim_s'],
        observed_at=dict(log=event['origin'], line=event['line']), capture=capture(row),
        source_key_resolution=('missing' if key is None else 'recorded_digest_and_receipt'
            if event['origin'] == 'observations.jsonl' else 'unique_geometry_source_at_exact_recorded_receipt'
            if agent['snapshots'] else 'unique_observation_source_at_exact_recorded_receipt'),
        diagnostics={k: d.get(k) for k in ('pixel_hits', 'pixel_identity_hits', 'motion_hits', 'geometry_state', 'chosen_pixel')},
        raw_strong_true=[b for b in raw_row.get('boxes', []) if strong(b)],
        raw_boxes=raw_row.get('boxes'), raw_observation_status='exact_source_match' if matched_observation else 'missing_exact_observation',
        motion_evidence=motion_evidence(raw_row), strong_selected=strong(raw_d.get('chosen_pixel')),
        filter_reason='not_directly_recorded; no world-gate reason is inferred from an empty selected box',
        source_stream_basis=agent['stream_basis'], sources=details,
        returned_controls=dict(status='available' if agent['controls'] else 'missing',
            interval_s=[start, end], total=len(controls), omitted=len(controls)-len(retained), events=retained))


def analyze(run_dir, *, max_examples=12, per_kind_per_uav=2, control_limit=8):
    run_dir = Path(run_dir)
    data = (run_dir / 'run.json').read_bytes()
    if json.loads(data).get('status') != 'completed':
        raise ValueError('Only run.json status=completed may be audited')
    if (any(not isinstance(n, int) or isinstance(n, bool) or n < 1
            for n in (max_examples, per_kind_per_uav, control_limit)) or control_limit < 2):
        raise ValueError('example limits must be positive and control_limit >= 2')
    folders = sorted(p for p in (run_dir / 'observations').iterdir() if p.is_dir()) if (run_dir / 'observations').is_dir() else []
    has_geometry = any((p / 'geometry-inputs.jsonl').is_file() for p in folders)
    verified, module = None, None
    if has_geometry:
        runner = json.loads((run_dir / 'runner-call.json').read_bytes())
        sources = runner.get('sources')
        if not isinstance(sources, dict):
            raise ValueError('Recorded source hash map is missing')
        verified = geometry_analysis.verify_sources(sources)
        module = geometry_analysis.helpers()
    agents = [load_agent(folder) for folder in folders]
    candidates, unknown_motion, groups = [], 0, defaultdict(list)
    for agent in agents:
        events, unknown = event_candidates(agent)
        unknown_motion += unknown
        for event in events:
            candidates.append((agent, event))
            groups[(agent['uid'], event['kind'])].append((agent, event))
    bounded = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda item: item[1]['event_sim_s'])
        n = min(per_kind_per_uav, len(group))
        bounded.extend(group[:1] if n == 1 else [group[round(i*(len(group)-1)/(n-1))] for i in range(n)])
    # Round-robin agents so a long first aircraft does not consume every example.
    queues = defaultdict(list)
    for item in bounded:
        queues[item[0]['uid']].append(item)
    selected = []
    while any(queues.values()) and len(selected) < max_examples:
        for uid in sorted(queues):
            if queues[uid] and len(selected) < max_examples:
                selected.append(queues[uid].pop(0))
    cache = {}
    examples = [make_example(a, e, module, cache, control_limit) for a, e in selected]
    return dict(schema_version=1, run=str(run_dir.resolve()), run_status='completed',
        run_manifest_sha256=hashlib.sha256(data).hexdigest(),
        analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), verified_geometry_sources=verified,
        summary=dict(candidate_events=len(candidates), kinds=dict(Counter(e['kind'] for _, e in candidates)),
            examples=len(examples), omitted_examples=len(candidates)-len(examples),
            strong_no_geo_samples_with_unknown_motion=unknown_motion,
            selected_current_image_statuses=dict(Counter(e['sources']['current'].get('image', {}).get('status', 'missing_source_key') for e in examples)),
            selected_geometry_reasons=dict(Counter(e['sources']['current'].get('geometry', {}).get('reason', 'UNKNOWN') for e in examples))),
        agents=[dict(uid=a['uid'], source_stream_basis=a['stream_basis'], recorded_sources=len(a['keys']),
                     provenance=a['provenance']) for a in agents], examples=examples,
        limits='Completed public own-input logs only. Motion validity uses explicit expiry if recorded, otherwise a '
        'fresh residual/hit witness; historical 8s validity is UNKNOWN. Raw strong class need not be the selected '
        'object; strong_selected distinguishes that case. Geometry reasons reuse the version-checked locate '
        'analyzer; filtering reasons are not recorded. Source/image/pose joins require exact digest and receipt '
        'time, never nearest photos or poses. Adjacent recorded sources may omit frames due to recorder caps. '
        'H keys/matrix are recorded inputs, not a new proof of identity or capture timing. Controls are returned '
        'commands, not proof of engine execution; bounded intervals may omit events from the example. '
        'Sampled loss transitions and example counts are not durations or scores.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-examples', type=int, default=12)
    parser.add_argument('--per-kind-per-uav', type=int, default=2)
    args = parser.parse_args()
    result = analyze(args.run, max_examples=args.max_examples, per_kind_per_uav=args.per_kind_per_uav)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(result['summary'], ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
