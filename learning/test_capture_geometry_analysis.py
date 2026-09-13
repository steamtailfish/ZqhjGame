"""Compare offline first-exit diagnosis with the real locate implementation."""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
from zqhj_visual_geometry import MotionPlane
from capture_geometry_recording import geometry_snapshot
from analyze_capture_geometry import analyze, classify_snapshot, SUPPORTED_SOURCES


@dataclass
class Box:
    x1: float = 500.
    y1: float = 372.
    x2: float = 523.
    y2: float = 395.

    @property
    def center(self):
        return (self.x1+self.x2)/2, (self.y1+self.y2)/2


class CaptureGeometryAnalysisTests(unittest.TestCase):
    def geometry(self):
        geometry = MotionPlane()
        geometry.last_pose = np.array([27., 125., 500., 0., 0., -90., 50.])
        geometry.last_time = 3.
        geometry.last_digest = 'photo'
        geometry.size = (1024, 768)
        geometry.status = 'PLANE_ESTIMATED'
        geometry.fit_center = geometry.last_pose[:2].copy()
        geometry.fits.extend((t, 150., 1., 2.) for t in (1., 2., 3.))
        geometry.history.extend((t, geometry.last_pose.copy()) for t in (1.5, 2., 2.5, 3.))
        return geometry

    def compare(self, expected, geometry=None, *, now=3., digest='photo', box=None):
        geometry = geometry or self.geometry()
        box = box or Box()
        actual = geometry.locate(box, now, digest)
        snapshot = geometry_snapshot(geometry, source_time=now, source_digest=digest,
            box=box, pixel_hits=2, enabled=True, geo_estimate=actual)
        # The diagnostic only sees the serialized state, not the live object.
        snapshot = json.loads(json.dumps(snapshot, allow_nan=False))
        with patch.object(MotionPlane, 'locate', side_effect=AssertionError('must not call locate')):
            result = classify_snapshot(snapshot)
        self.assertEqual(result['reason'], expected)
        self.assertEqual(result['recorded_output_check'], 'match')
        self.assertEqual(actual is not None, result['outcome'] == 'located')
        json.dumps(result, allow_nan=False)
        return result, snapshot

    def test_initial_guards_short_circuit_in_original_order(self):
        geometry = self.geometry()
        geometry.last_pose = None
        self.compare('NO_POSE', geometry, digest='wrong')
        self.compare('DIGEST_MISMATCH', now=99., digest='wrong')
        for now, reason in ((2.999, 'SOURCE_AGE_OUT_OF_RANGE'), (4., 'LOCATED'),
                            (4.000001, 'SOURCE_AGE_OUT_OF_RANGE')):
            with self.subTest(now=now):
                self.compare(reason, now=now)
        geometry = self.geometry()
        geometry.status = 'PAIR_GAP'
        geometry.fits.clear()
        self.compare('UPDATE_STATE_BLOCKED', geometry)

    def test_fit_count_span_age_and_ground_spread_boundaries(self):
        cases = [([(2., 150.), (3., 150.)], 3., 'INSUFFICIENT_RECENT_FITS'),
                 ([(2.001, 150.), (2.5, 150.), (3., 150.)], 3., 'FIT_SPAN_TOO_SHORT'),
                 ([(2., 150.), (2.5, 150.), (3., 150.)], 3., 'LOCATED'),
                 ([(1., 150.), (2., 150.), (3., 150.)], 7., 'LOCATED'),
                 ([(1., 150.), (2., 150.), (3., 150.)], 7.000001, 'LATEST_FIT_TOO_OLD'),
                 ([(1., 130.), (2., 150.), (3., 170.)], 3., 'LOCATED'),
                 ([(1., 129.99), (2., 150.), (3., 170.01)], 3., 'GROUND_SPREAD_TOO_LARGE')]
        for fits, now, reason in cases:
            with self.subTest(reason=reason, now=now, fits=fits):
                geometry = self.geometry()
                geometry.fits = deque([(t, z, 1., 2.) for t, z in fits], maxlen=10)
                geometry.last_time = now
                self.compare(reason, geometry, now=now)

    def test_distance_ray_tilt_range_and_uncertainty_rejections(self):
        for meters, reason in ((119.999, 'LOCATED'), (120.001, 'FIT_CENTER_TOO_FAR')):
            geometry = self.geometry()
            geometry.last_pose[0] += meters/111320
            self.compare(reason, geometry)
        geometry = self.geometry()
        geometry.last_pose[5] = -10.
        self.compare('RAY_TOO_SHALLOW', geometry)  # also invalid tilt, ray must win
        geometry = self.geometry()
        geometry.last_pose[5] = -100.
        self.compare('TILT_OUT_OF_RANGE', geometry)
        geometry = self.geometry()
        geometry.last_pose[5] = -40.
        geometry.last_pose[2] = 1000.
        self.compare('HORIZONTAL_RANGE_TOO_LARGE', geometry)
        geometry = self.geometry()
        geometry.history[-1][1][3] = 45.
        self.compare('UNCERTAINTY_TOO_LARGE', geometry)

    def test_missing_inputs_are_unknown_but_known_early_rejects_remain_known(self):
        _, snapshot = self.compare('LOCATED')
        for where, key in (('geometry', 'fits'), ('geometry', 'history_recent'),
                           ('geometry', 'fit_center'), ('geometry', 'last_pose'), (None, 'box')):
            row = deepcopy(snapshot)
            del (row[where] if where else row)[key]
            with self.subTest(key=key):
                self.assertEqual(classify_snapshot(row)['reason'], 'UNKNOWN')
        snapshot['geometry']['last_pose'] = None
        del snapshot['box']
        self.assertEqual(classify_snapshot(snapshot)['reason'], 'NO_POSE')
        snapshot['enabled'], snapshot['locate_called'] = False, False
        del snapshot['geometry']
        snapshot['geo_estimate'] = None
        self.assertEqual(classify_snapshot(snapshot)['reason'], 'NOT_CALLED')
        snapshot['locate_called'] = True
        self.assertEqual(classify_snapshot(snapshot)['reason'], 'UNKNOWN')

    def test_output_comparison_distinguishes_missing_null_and_numeric_disagreement(self):
        _, snapshot = self.compare('LOCATED')
        row = deepcopy(snapshot)
        del row['geo_estimate']
        self.assertEqual(classify_snapshot(row)['recorded_output_check'], 'unknown')
        for value in (None, dict(snapshot['geo_estimate'], latitude=0.)):
            row['geo_estimate'] = value
            result = classify_snapshot(row)
            self.assertEqual(result['reason'], 'LOCATED')
            self.assertEqual(result['recorded_output_check'], 'mismatch')
        row['geo_estimate'] = dict(snapshot['geo_estimate'], latitude=None)
        self.assertEqual(classify_snapshot(row)['recorded_output_check'], 'unknown')

    def test_completion_and_source_versions_checked_before_input_log_read(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            manifest = run / 'run.json'
            manifest.write_text('{"status":"running"}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'completed'):
                analyze(run)
            manifest.write_text('{"status":"completed"}', encoding='utf-8')
            runner = run / 'runner-call.json'
            for sources in ({}, dict(SUPPORTED_SOURCES, **{'src/zqhj_visual_geometry.py': 'wrong'})):
                runner.write_text(json.dumps(dict(sources=sources)), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'source hash'):
                    analyze(run)

    def test_uid_source_time_bins_unknowns_and_examples_are_bounded(self):
        _, valid = self.compare('LOCATED')
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'run.json').write_text('{"status":"completed"}', encoding='utf-8')
            # Windows recorder uses backslash-relative paths.
            (run / 'runner-call.json').write_text(json.dumps(dict(sources={
                k.replace('/', '\\'): v for k, v in SUPPORTED_SOURCES.items()})), encoding='utf-8')
            for i in range(10):
                folder = run / 'observations' / str(20001+i)
                folder.mkdir(parents=True)
                rows = [dict(valid, recorded_at_s=90.),
                        dict(enabled=False, pixel_hits=0, locate_called=False,
                             source_receipt_sim_s=31., recorded_at_s=90., geo_estimate=None), {}]
                (folder / 'geometry-inputs.jsonl').write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
            result = analyze(run)
            self.assertEqual(result['summary']['outcomes'], dict(located=10, not_called=10, unknown=10))
            self.assertEqual(len(result['examples']), 8)
            self.assertEqual([x['bin_start_s'] for x in result['agents'][0]['timeline']], [0., 30., None])
            self.assertEqual(result['agents'][0]['timeline'][0]['reasons'], dict(LOCATED=1))
            json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
