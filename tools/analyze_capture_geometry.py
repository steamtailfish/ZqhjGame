"""Explain locate snapshots from completed runs; never execute the online agent."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
# This diagnostic duplicates guard order. Updating these hashes requires a
# deliberate formula/guard review and comparison against MotionPlane.locate.
SUPPORTED_SOURCES = {
    'src/zqhj_visual_geometry.py': '4cf5bc3f3000b7fafd2d87dbcff14d92170ddf0a55c32d0f4d16ed2fb1fc3f20',
    'src/zqhj_localization.py': 'b39d44d240d4d4062766ebcfc440116941a8d3b6452d798eeb63218480b0c122',
}
MISSING = object()


def verify_sources(recorded=None):
    """Refuse unsupported local helpers or an unmatched recorded source version."""
    normalized = None if recorded is None else {k.replace('\\', '/'): v for k, v in recorded.items()}
    for name, expected in SUPPORTED_SOURCES.items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f'Unsupported local source hash: {name}; review diagnostic formulas first')
        if normalized is not None and normalized.get(name) != expected:
            raise ValueError(f'Recorded source hash missing or mismatched: {name}')
    return dict(SUPPORTED_SOURCES)


def helpers():
    sys.path.insert(0, str(ROOT / 'src')) if str(ROOT / 'src') not in sys.path else None
    import zqhj_visual_geometry as geometry
    import zqhj_localization as localization
    for module in (geometry, localization):
        if Path(module.__file__).resolve() != (ROOT / 'src' / f'{module.__name__}.py').resolve():
            raise ValueError(f'Unexpected imported helper: {module.__name__}')
    return geometry


def number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


class Incomplete(ValueError):
    pass


def field(mapping, name):
    if not isinstance(mapping, dict) or name not in mapping:
        raise Incomplete(f'missing {name}')
    return mapping[name]


def numeric(value, name):
    if not number(value):
        raise Incomplete(f'invalid {name}')
    return value


def vector(value, length, name):
    if not isinstance(value, (list, tuple)) or len(value) != length or not all(number(x) for x in value):
        raise Incomplete(f'invalid {name}')
    return np.array(value, dtype=float)


def output_check(snapshot, expected):
    actual = snapshot.get('geo_estimate', MISSING)
    if actual is MISSING:
        return 'unknown'
    if expected is None:
        return 'match' if actual is None else 'mismatch'
    if actual is None:
        return 'mismatch'
    if not isinstance(actual, dict) or any(k not in actual for k in expected):
        return 'unknown'
    for name, value in expected.items():
        other = actual[name]
        if number(value):
            if not number(other):
                return 'unknown'
            if not math.isclose(value, other, rel_tol=1e-10, abs_tol=1e-9):
                return 'mismatch'
        elif value != other:
            return 'mismatch'
    return 'match'


def _classify(snapshot, geometry_module):
    values = {}

    def done(reason, estimate=None):
        outcome = 'not_called' if reason == 'NOT_CALLED' else 'located' if reason == 'LOCATED' else 'rejected'
        return dict(outcome=outcome, reason=reason, values=values,
                    recomputed_geo_estimate=estimate, recorded_output_check=output_check(snapshot, estimate))

    try:
        enabled = field(snapshot, 'enabled')
        hits = numeric(field(snapshot, 'pixel_hits'), 'pixel_hits')
        called = field(snapshot, 'locate_called')
        if not isinstance(enabled, bool) or not isinstance(called, bool) or called != bool(enabled and hits >= 2):
            raise Incomplete('inconsistent locate precondition marker')
        if not called:
            return done('NOT_CALLED')
        state = field(snapshot, 'geometry')
        pose = field(state, 'last_pose')
        if pose is None:
            return done('NO_POSE')
        digest = field(snapshot, 'source_image_sha256')
        if not isinstance(digest, str) or not digest:
            raise Incomplete('invalid source_image_sha256')
        if digest != field(state, 'last_digest'):
            return done('DIGEST_MISMATCH')
        now = numeric(field(snapshot, 'source_receipt_sim_s'), 'source_receipt_sim_s')
        last_time = numeric(field(state, 'last_time'), 'last_time')
        values['source_age_s'] = now-last_time
        if not 0 <= now-last_time <= 1.:
            return done('SOURCE_AGE_OUT_OF_RANGE')
        status = field(state, 'status')
        if not isinstance(status, str):
            raise Incomplete('invalid status')
        values['update_state'] = status
        if status not in ('PLANE_ESTIMATED', 'POSE_CHANGING', 'PLANE_REJECTED'):
            return done('UPDATE_STATE_BLOCKED')
        raw_fits = field(state, 'fits')
        if not isinstance(raw_fits, list) or len(raw_fits) > 10:
            raise Incomplete('invalid fits')
        fits = []
        for fit in raw_fits:
            if not isinstance(fit, (list, tuple)) or len(fit) != 4:
                raise Incomplete('invalid fit row')
            if 0 <= now-numeric(fit[0], 'fit time') <= 8.:
                fits.append(fit)
        values['fits_count'] = len(fits)
        if len(fits) < 3:
            return done('INSUFFICIENT_RECENT_FITS')
        values['fit_span_s'] = fits[-1][0]-fits[0][0]
        if values['fit_span_s'] < 1.:
            return done('FIT_SPAN_TOO_SHORT')
        values['latest_fit_age_s'] = now-fits[-1][0]
        if values['latest_fit_age_s'] > 4.:
            return done('LATEST_FIT_TOO_OLD')
        pose = vector(pose, 7, 'last_pose')
        center = field(state, 'fit_center')
        if center is not None:
            center = vector(center, 2, 'fit_center')
            distance = math.hypot((pose[0]-center[0])*111320,
                (pose[1]-center[1])*111320*math.cos(math.radians(center[0])))
            values['fit_center_distance_m'] = distance
            if distance > 120:
                return done('FIT_CENTER_TOO_FAR')
        heights = [numeric(f[1], 'fit ground') for f in fits]
        ground = float(np.median(heights))
        spread = float(np.median(np.abs(np.array(heights)-ground)))
        values.update(ground_m=ground, ground_spread_m=spread)
        if spread > 20:
            return done('GROUND_SPREAD_TOO_LARGE')
        box = field(snapshot, 'box')
        x1, y1, x2, y2 = (numeric(field(box, name), f'box.{name}') for name in ('x1', 'y1', 'x2', 'y2'))
        size = vector(field(state, 'size'), 2, 'size')
        if min(size) <= 0 or not 0 < pose[6] < 180:
            raise Incomplete('degenerate projection input')
        ray = geometry_module.world_rays(np.array([[(x1+x2)/2, (y1+y2)/2]]), size, pose)[0]
        if not np.isfinite(ray).all():
            raise Incomplete('nonfinite ray')
        values.update(ray_z=float(ray[2]), tilt_deg=float(pose[5]))
        if ray[2] >= -.35:
            return done('RAY_TOO_SHALLOW')
        if not -90 <= pose[5] <= -40:
            return done('TILT_OUT_OF_RANGE')
        offset = ray*((ground-pose[2])/ray[2])
        horizontal = float(np.linalg.norm(offset[:2]))
        values['horizontal_m'] = horizontal
        if horizontal > 800:
            return done('HORIZONTAL_RANGE_TOO_LARGE')
        history = field(state, 'history_recent')
        if not isinstance(history, list) or len(history) > 100:
            raise Incomplete('invalid history_recent')
        recent = []
        for item in history:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise Incomplete('invalid history row')
            if 0 <= now-numeric(item[0], 'history time') <= 1.5:
                recent.append(vector(item[1], 7, 'history pose'))
        rotation = max((geometry_module.rotation_change(p, pose) for p in recent), default=5.)/1.5
        angular_error = (horizontal+pose[2]-ground)*math.tan(math.radians(rotation))
        uncertainty = 40.+.1*horizontal+2*spread+25*float(np.linalg.norm(ray[:2])/abs(ray[2]))+angular_error
        values.update(rotation_deg_per_s=rotation, angular_error_m=angular_error, uncertainty_m=uncertainty)
        if not all(number(v) for v in (horizontal, rotation, angular_error, uncertainty)):
            raise Incomplete('nonfinite projection result')
        if uncertainty > 150:
            return done('UNCERTAINTY_TOO_LARGE')
        lat = pose[0]+offset[1]/111320
        lon = pose[1]+offset[0]/(111320*math.cos(math.radians(pose[0])))
        residual = max(numeric(f[2], 'fit residual') for f in fits)
        estimate = asdict(geometry_module.GeoEstimate(float(lat), float(lon), uncertainty, ground,
                                                     last_time, digest, residual))
        if not number(estimate['latitude']) or not number(estimate['longitude']):
            raise Incomplete('nonfinite coordinates')
        return done('LOCATED', estimate)
    except (Incomplete, ArithmeticError) as error:
        return dict(outcome='unknown', reason='UNKNOWN', detail=str(error), values=values,
                    recomputed_geo_estimate=None, recorded_output_check='unknown')


def classify_snapshot(snapshot):
    """Local synthetic use; run analysis additionally checks recorded hashes."""
    verify_sources()
    return _classify(snapshot, helpers())


def bucket():
    return dict(samples=0, outcomes=Counter(), reasons=Counter(), output_checks=Counter(),
                source_start_s=None, source_end_s=None)


def observe(metrics, result, source_time):
    metrics['samples'] += 1
    metrics['outcomes'][result['outcome']] += 1
    metrics['reasons'][result['reason']] += 1
    metrics['output_checks'][result['recorded_output_check']] += 1
    if number(source_time):
        metrics['source_start_s'] = source_time if metrics['source_start_s'] is None else min(metrics['source_start_s'], source_time)
        metrics['source_end_s'] = source_time if metrics['source_end_s'] is None else max(metrics['source_end_s'], source_time)


def analyze(run_dir, *, bin_seconds=30.):
    run_dir = Path(run_dir)
    manifest_bytes = (run_dir / 'run.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    # No observation/source log is read before the official completion check.
    if manifest.get('status') != 'completed':
        raise ValueError('The official run must be completed before geometry analysis')
    if not number(bin_seconds) or bin_seconds <= 0:
        raise ValueError('bin_seconds must be finite and positive')
    runner_bytes = (run_dir / 'runner-call.json').read_bytes()
    sources = json.loads(runner_bytes).get('sources')
    if not isinstance(sources, dict):
        raise ValueError('Recorded source hash map is missing')
    verified = verify_sources(sources)
    geometry_module = helpers()
    paths = sorted((run_dir / 'observations').glob('*/geometry-inputs.jsonl'))
    if not paths:
        raise ValueError('No geometry-inputs.jsonl: locate inputs are unavailable, not known rejections')
    total, agents, examples, example_keys = bucket(), [], [], set()
    for path in paths:
        uid, metrics, timeline = path.parent.name, bucket(), {}
        data = path.read_bytes()
        for line_number, line in enumerate(data.decode('utf-8').splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                result = _classify(row, geometry_module)
            except json.JSONDecodeError:
                row = {}
                result = dict(outcome='unknown', reason='UNKNOWN', detail='invalid JSON line',
                              values={}, recomputed_geo_estimate=None, recorded_output_check='unknown')
            source_time = row.get('source_receipt_sim_s') if isinstance(row, dict) else None
            key = math.floor(source_time/bin_seconds) if number(source_time) else 'unknown'
            for destination in (total, metrics, timeline.setdefault(key, bucket())):
                observe(destination, result, source_time)
            example_key = (uid, result['reason'], result['recorded_output_check'])
            if example_key not in example_keys and len(examples) < 8:
                example_keys.add(example_key)
                examples.append(dict(uid=uid, line=line_number, source_receipt_sim_s=source_time,
                    recorded_at_s=row.get('recorded_at_s') if isinstance(row, dict) else None, **result))
        agents.append(dict(uid=uid, geometry_inputs_sha256=hashlib.sha256(data).hexdigest(), **metrics,
            timeline=[dict(bin_start_s=k*bin_seconds if isinstance(k, int) else None,
                           bin_end_s=(k+1)*bin_seconds if isinstance(k, int) else None, **v)
                      for k, v in sorted(timeline.items(), key=lambda item: (item[0] == 'unknown', item[0]))]))
    return dict(schema_version=1, run=str(run_dir.resolve()), run_status='completed',
        run_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        runner_call_sha256=hashlib.sha256(runner_bytes).hexdigest(),
        analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        verified_sources=verified, bin_seconds=bin_seconds, summary=total, agents=agents, examples=examples,
        limits='Completed own-observation snapshots only; no official truth or policy execution. '
        'NOT_CALLED is inferred from the recorded enabled/hit precondition, not a call trace. '
        'Reasons follow the supported locate guard order. LOCATED means the recorded inputs '
        'produce an estimate; output_checks separately compare that estimate with the recorded output. '
        'Missing or invalid required inputs are UNKNOWN. Homography is unused by locate. '
        'Time bins use source receipt time, not capture time or callback time. These are sample '
        'counts, not durations or official success. The first eight distinct agent/reason/check '
        'examples are retained; snapshot caps or wrapper errors may omit later inputs.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bin-seconds', type=float, default=30.)
    args = parser.parse_args()
    result = analyze(args.run, bin_seconds=args.bin_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(result['summary'], ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
