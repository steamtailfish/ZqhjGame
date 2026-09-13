"""Bounded post-run exposure-delay/plane profiles from exact own-image pairs.

This is a conditional geometry diagnostic, never an automatic calibration.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from analyze_capture_geometry import helpers, number, verify_sources


DELAYS = tuple(i*.125 for i in range(7))
HEIGHTS = tuple(float(i) for i in range(-200, 420, 10))
MAX_PAIRS = 12
MIN_FEATURES = 40


class Unavailable(ValueError):
    pass


def wrap(angle):
    return (angle+180.) % 360.-180.


def pose_history(snapshot):
    state = snapshot.get('geometry') or {}
    source = snapshot.get('source_receipt_sim_s')
    if not number(source) or state.get('last_digest') != snapshot.get('source_image_sha256'):
        raise Unavailable('source_pose_digest_unknown_or_mismatched')
    if not number(state.get('last_time')) or abs(state['last_time']-source) > 1e-6:
        raise Unavailable('source_pose_time_unknown_or_mismatched')
    history = state.get('history_recent')
    if not isinstance(history, list) or len(history) > 100:
        raise Unavailable('pose_history_unavailable')
    result = []
    for item in history:
        if (not isinstance(item, (list, tuple)) or len(item) != 2 or not number(item[0])
                or not isinstance(item[1], (list, tuple)) or len(item[1]) != 7
                or not all(number(value) for value in item[1])):
            raise Unavailable('pose_history_invalid')
        if not 0 <= source-item[0] <= 1.5+1e-8:
            raise Unavailable('pose_history_outside_recorded_window')
        if result and item[0] <= result[-1][0]:
            raise Unavailable('pose_history_not_strictly_ordered')
        result.append((item[0], np.array(item[1], dtype=float)))
    if not result:
        raise Unavailable('pose_history_empty')
    # Do not manufacture a current pose when the recorded history is incomplete.
    if abs(result[-1][0]-source) > 1e-6:
        raise Unavailable('source_pose_absent_from_history')
    last = state.get('last_pose')
    if not isinstance(last, list) or len(last) != 7 or not all(number(v) for v in last):
        raise Unavailable('last_pose_invalid')
    if not np.allclose(result[-1][1], last, rtol=0, atol=1e-8):
        raise Unavailable('source_pose_history_disagrees')
    return result


def interpolate_pose(history, when):
    """Linear receipt-pose interpolation, shortest arcs for lon/heading/pan."""
    if not history or when < history[0][0]-1e-8 or when > history[-1][0]+1e-8:
        raise Unavailable('exposure_hypothesis_not_bracketed')
    for t, pose in history:
        if abs(t-when) <= 1e-8:
            return pose.copy()
    for (ta, a), (tb, b) in zip(history, history[1:]):
        if ta < when < tb:
            if abs(a[6]-b[6]) >= .1:
                raise Unavailable('fov_transition')
            delta = b-a
            for axis in (1, 3, 4):
                delta[axis] = wrap(delta[axis])
            pose = a+delta*((when-ta)/(tb-ta))
            for axis in (1, 3, 4):
                pose[axis] = wrap(pose[axis])
            return pose
    raise Unavailable('exposure_hypothesis_not_bracketed')


def pair_poses(a, b):
    ta, tb = a.get('source_receipt_sim_s'), b.get('source_receipt_sim_s')
    if not number(ta) or not number(tb) or not .4 <= tb-ta <= 2.:
        raise Unavailable('source_pair_gap_outside_0.4_to_2_seconds')
    ha, hb = pose_history(a), pose_history(b)
    # All delay candidates must see the same FOV; a switch is not interpolated.
    window = [pose for t, pose in ha+hb if ta-max(DELAYS)-1e-8 <= t <= tb+1e-8]
    if max(pose[6] for pose in window)-min(pose[6] for pose in window) >= .1:
        raise Unavailable('fov_transition_in_delay_window')
    result = []
    for delay in DELAYS:
        result.append((delay, interpolate_pose(ha, ta-delay), interpolate_pose(hb, tb-delay)))
    gaps = [tb-ta for history in (ha, hb) for (ta, _), (tb, _) in zip(history, history[1:])]
    return result, max(gaps, default=0.)


def exact_image(folder, digest):
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise Unavailable('source_digest_invalid')
    path = folder / f'{digest}.image'
    if not path.is_file():
        raise Unavailable('exact_source_image_missing')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise Unavailable('source_image_hash_mismatch')
    gray = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise Unavailable('source_image_decode_failed')
    return gray


def target_mask(shape, box):
    mask = np.full(shape, 255, np.uint8)
    if isinstance(box, dict) and all(number(box.get(k)) for k in ('x1', 'y1', 'x2', 'y2')):
        # Exclude the known target box and a fixed border. Other moving objects
        # are only suppressed by FB matching/consensus, not known to be static.
        x1, y1 = max(0, math.floor(box['x1'])-16), max(0, math.floor(box['y1'])-16)
        x2, y2 = min(shape[1], math.ceil(box['x2'])+17), min(shape[0], math.ceil(box['y2'])+17)
        mask[y1:y2, x1:x2] = 0
    return mask


def background_matches(before, after, box_a=None, box_b=None):
    if before.shape != after.shape:
        raise Unavailable('source_image_size_changed')
    pa = cv2.goodFeaturesToTrack(before, maxCorners=250, qualityLevel=.02, minDistance=18,
                                 mask=target_mask(before.shape, box_a))
    if pa is None or len(pa) < MIN_FEATURES:
        raise Unavailable('insufficient_background_features')
    pb, status, _ = cv2.calcOpticalFlowPyrLK(before, after, pa, None, winSize=(31, 31), maxLevel=4)
    if pb is None or status is None:
        raise Unavailable('forward_lk_failed')
    back, reverse, _ = cv2.calcOpticalFlowPyrLK(after, before, pb, None, winSize=(31, 31), maxLevel=4)
    if back is None or reverse is None:
        raise Unavailable('backward_lk_failed')
    good = ((status[:, 0] > 0) & (reverse[:, 0] > 0)
            & np.isfinite(pb[:, 0]).all(axis=1) & np.isfinite(back[:, 0]).all(axis=1)
            & (np.linalg.norm(pa[:, 0]-back[:, 0], axis=1) < 1.))
    pa, pb = pa[good, 0].astype(float), pb[good, 0].astype(float)
    mask_b = target_mask(after.shape, box_b)
    inside = ((pb[:, 0] >= 0) & (pb[:, 0] < after.shape[1])
              & (pb[:, 1] >= 0) & (pb[:, 1] < after.shape[0]))
    pa, pb = pa[inside], pb[inside]
    keep = mask_b[pb[:, 1].astype(int), pb[:, 0].astype(int)] > 0
    pa, pb = pa[keep], pb[keep]
    if len(pa) < MIN_FEATURES:
        raise Unavailable('insufficient_fb_matches')
    cv2.setRNGSeed(0)
    homography, inliers = cv2.findHomography(pa, pb, cv2.RANSAC, 2.)
    if homography is None or inliers is None:
        raise Unavailable('background_ransac_failed')
    pa, pb = pa[inliers[:, 0] > 0], pb[inliers[:, 0] > 0]
    if len(pa) < MIN_FEATURES:
        raise Unavailable('insufficient_background_consensus')
    return pa, pb


def error_profile(pa, pb, size, poses, geometry_module):
    """Choose height on even features, report odd-feature errors for each delay."""
    if len(pa) != len(pb) or len(pa) < MIN_FEATURES:
        raise Unavailable('insufficient_profile_features')
    profile = []
    for delay, a, b in poses:
        camera = geometry_module.relative_camera(a, a)
        other = geometry_module.relative_camera(b, a)
        baseline = float(np.linalg.norm(other[:2]-camera[:2]))
        item = dict(delay_s=delay, baseline_m=baseline)
        if baseline < 6.:
            profile.append(dict(item, status='unknown', reason='baseline_below_6m'))
            continue
        rays = geometry_module.world_rays(pa, size, a)
        if not np.isfinite(rays).all() or np.any(rays[:, 2] >= -.2):
            profile.append(dict(item, status='unknown', reason='oblique_or_invalid_rays'))
            continue
        costs = []
        for height in HEIGHTS:
            if height > min(a[2], b[2])-60.:
                continue
            points = camera+rays*((height-camera[2])/rays[:, 2])[:, None]
            residuals = np.linalg.norm(geometry_module.reproject(points, size, b, other)-pb, axis=1)
            if np.isfinite(residuals).all():
                costs.append((float(np.median(residuals[::2])), height, residuals))
        if not costs:
            profile.append(dict(item, status='unknown', reason='height_scan_unavailable'))
            continue
        train, height, residuals = min(costs, key=lambda cost: (cost[0], cost[1]))
        profile.append(dict(item, status='profiled', train_selected_height_m=height,
            train_median_px=train, validation_median_px=float(np.median(residuals[1::2])),
            validation_p90_px=float(np.quantile(residuals[1::2], .9)),
            height_at_scan_edge=height in (costs[0][1], costs[-1][1])))
    return profile


def analyze_pair(folder, a, b, geometry_module):
    try:
        poses, gap = pair_poses(a, b)
        before = exact_image(folder, a.get('source_image_sha256'))
        after = exact_image(folder, b.get('source_image_sha256'))
        for row, gray in ((a, before), (b, after)):
            if row['geometry'].get('size') != list(gray.shape[::-1]):
                raise Unavailable('recorded_and_decoded_size_disagree')
        pa, pb = background_matches(before, after, a.get('box'), b.get('box'))
        profile = error_profile(pa, pb, before.shape[::-1], poses, geometry_module)
        valid = [item for item in profile if item['status'] == 'profiled']
        return dict(status='profiled' if valid else 'unknown', reason=None if valid else 'no_valid_delay_profile',
            background_consensus_features=len(pa), training_features=len(pa[::2]),
            validation_features=len(pa[1::2]), max_recorded_pose_gap_s=gap, profile=profile,
            validation_profile_span_px=(max(item['validation_median_px'] for item in valid)
                                       -min(item['validation_median_px'] for item in valid)) if valid else None)
    except (Unavailable, cv2.error) as error:
        return dict(status='unknown', reason=str(error), profile=[])


def select_pairs(rows, folder, duration, slots):
    """Predeclared time coverage, exact-file availability, never residual ranking."""
    bins = [[] for _ in range(slots)]
    inventory = [Counter() for _ in range(slots)]
    # Adjacency is in the recorded source sequence. Never bridge a missing row.
    for index, (a, b) in enumerate(zip(rows, rows[1:])):
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        t = b.get('source_receipt_sim_s')
        if not number(t) or not 0 <= t <= duration:
            continue
        slot = min(slots-1, int(t*slots/duration))
        inventory[slot]['consecutive_pairs'] += 1
        ta = a.get('source_receipt_sim_s')
        da, db = a.get('source_image_sha256'), b.get('source_image_sha256')
        if not number(ta) or not .4 <= t-ta <= 2. or da == db:
            inventory[slot]['invalid_pair_gap_or_repeated_digest'] += 1
            continue
        digests = (da, db)
        if not all(isinstance(d, str) and len(d) == 64 and all(c in '0123456789abcdef' for c in d) for d in digests):
            inventory[slot]['invalid_digest'] += 1
            continue
        if not all((folder / f'{d}.image').is_file() for d in digests):
            inventory[slot]['exact_source_image_missing'] += 1
            continue
        inventory[slot]['exact_image_pair_available'] += 1
        midpoint = (slot+.5)*duration/slots
        bins[slot].append((abs(t-midpoint), index, a, b))
    selected = []
    for slot, candidates in enumerate(bins):
        item = dict(slot=slot, slot_start_s=slot*duration/slots, slot_end_s=(slot+1)*duration/slots,
                    inventory=dict(inventory[slot]))
        if candidates:
            _, index, a, b = min(candidates, key=lambda c: (c[0], c[1]))
            selected.append((item, index, a, b))
        else:
            selected.append((dict(item, status='unknown', reason='no_exact_consecutive_image_pair'), None, None, None))
    return selected


def analyze(run_dir):
    run_dir = Path(run_dir)
    manifest_bytes = (run_dir / 'run.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('status') != 'completed':
        raise ValueError('The official run must be completed before exposure-delay analysis')
    runner_bytes = (run_dir / 'runner-call.json').read_bytes()
    sources = json.loads(runner_bytes).get('sources')
    if not isinstance(sources, dict):
        raise ValueError('Recorded source hashes unavailable')
    verified = verify_sources(sources)
    geometry_module = helpers()
    duration = manifest.get('duration_sim_s')
    if not number(duration) or duration <= 0:
        raise ValueError('Completed requested duration required for fixed time slots')
    paths = sorted((run_dir / 'observations').glob('*/geometry-inputs.jsonl'))
    if not paths or len(paths) > MAX_PAIRS:
        raise ValueError('Geometry source sequences unavailable or unsupported agent count')
    slots = min(4, MAX_PAIRS//len(paths))
    results, input_hashes = [], {}
    for path in paths:
        data = path.read_bytes()
        input_hashes[path.parent.name] = hashlib.sha256(data).hexdigest()
        rows = []
        for line in data.decode('utf-8').splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append(None)  # preserve the gap; never pair across it
        for slot, index, a, b in select_pairs(rows, path.parent, duration, slots):
            item = dict(uid=path.parent.name, **slot)
            if a is not None:
                item.update(source_sequence_indices=[index, index+1],
                    source_receipt_times_s=[a['source_receipt_sim_s'], b['source_receipt_sim_s']],
                    source_image_sha256=[a['source_image_sha256'], b['source_image_sha256']],
                    **analyze_pair(path.parent, a, b, geometry_module))
            results.append(item)
    status_counts = dict(Counter(item['status'] for item in results))
    return dict(schema_version=1, run=str(run_dir.resolve()), run_status='completed',
        run_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        runner_call_sha256=hashlib.sha256(runner_bytes).hexdigest(), verified_sources=verified,
        geometry_inputs_sha256=input_hashes,
        analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        delay_candidates_s=DELAYS, height_candidates_m=HEIGHTS, selection=dict(
            rule='Up to four equal requested-time slots per UID; nearest slot midpoint among '
                 'adjacent processed source records with both exact digest image files. '
                 'No replacement after pose, hash, feature or geometry failure.',
            maximum_pairs=MAX_PAIRS, slots_per_uid=slots), status_counts=status_counts, pairs=results,
        calibrated_delay_s=None, automatically_calibrated=False,
        limits='Own completed public records only; no judge, target truth, nearby-image substitution '
        'or online policy changes. Common delay is scanned per pair jointly with unknown plane height; '
        'all delay candidates are reported, no calibration constant is chosen. Receipt-pose '
        'interpolation assumes motion between sparse samples and cannot recover exposure timestamps '
        'or instantaneous gimbal jumps. Constant motion can make delay unidentifiable. Height, '
        'parallax, dynamic objects and camera model errors can mimic delay. RANSAC consensus is '
        'only a background hypothesis; odd-feature validation shares this consensus selection '
        'and is not an independent scene test. Missing snapshots/images and key-photo recording '
        'bias limit coverage. Scan-edge heights and flat/conflicting profiles weaken identifiability. '
        'These profiles cannot alone establish that timing dominates identity loss or official capture.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(result['status_counts']))


if __name__ == '__main__':
    main()
