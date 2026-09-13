"""Mathematical limits and exact-source boundaries for delay diagnostics."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from analyze_capture_delay import (Unavailable, analyze, exact_image, interpolate_pose,
                                  pair_poses, error_profile, select_pairs, background_matches)
from analyze_capture_geometry import helpers, SUPPORTED_SOURCES


class CaptureDelayAnalysisTests(unittest.TestCase):
    def pose(self, t, turning=False):
        return np.array([27.+20*t/111320, 125., 500., 5*t*t if turning else 0., 0., -75., 50.])

    def snapshot(self, source, digest='a'*64, turning=False):
        times = np.arange(source-1.5, source+.001, .125)
        return dict(source_receipt_sim_s=source, source_image_sha256=digest, box=None,
            geometry=dict(last_time=source, last_digest=digest, last_pose=self.pose(source, turning).tolist(),
                size=[1024, 768], history_recent=[[float(t), self.pose(t, turning).tolist()] for t in times]))

    def correspondences(self, a, b):
        geometry = helpers()
        pixels = np.array([(x, y) for x in np.linspace(280, 740, 8) for y in np.linspace(210, 550, 8)])
        rays = geometry.world_rays(pixels, (1024, 768), a)
        ca, cb = geometry.relative_camera(a, a), geometry.relative_camera(b, a)
        points = ca+rays*((150.-ca[2])/rays[:, 2])[:, None]
        return pixels, geometry.reproject(points, (1024, 768), b, cb)

    def test_heading_pan_and_longitude_interpolate_shortest_arc(self):
        a, b = self.pose(0), self.pose(1)
        a[[1, 3, 4]], b[[1, 3, 4]] = [179., 350., 170.], [-179., 10., -170.]
        history = [(0., a), (1., b)]
        middle = interpolate_pose(history, .5)
        np.testing.assert_allclose(middle[[1, 3, 4]], [-180., 0., -180.])
        self.assertAlmostEqual(middle[0], (a[0]+b[0])/2)
        middle[0] = 99.
        self.assertNotEqual(a[0], 99.)
        with self.assertRaisesRegex(Unavailable, 'not_bracketed'):
            interpolate_pose(history, -.01)
        b[6] = 30.
        with self.assertRaisesRegex(Unavailable, 'fov_transition'):
            interpolate_pose(history, .5)

    def test_entire_delay_profile_rejects_fov_switch_and_missing_history(self):
        a, b = self.snapshot(2.), self.snapshot(2.5, 'b'*64)
        poses, _ = pair_poses(a, b)
        self.assertEqual(len(poses), 7)
        a['geometry']['history_recent'][6][1][6] = 30.
        with self.assertRaisesRegex(Unavailable, 'fov_transition'):
            pair_poses(a, b)
        a = self.snapshot(2.)
        a['geometry']['history_recent'] = a['geometry']['history_recent'][-3:]
        with self.assertRaisesRegex(Unavailable, 'not_bracketed'):
            pair_poses(a, b)

    def test_constant_velocity_and_attitude_make_common_delay_unidentifiable(self):
        a, b = self.snapshot(2.), self.snapshot(2.5, 'b'*64)
        poses, _ = pair_poses(a, b)
        pa, pb = self.correspondences(self.pose(1.5), self.pose(2.))
        profile = error_profile(pa, pb, (1024, 768), poses, helpers())
        self.assertTrue(all(row['status'] == 'profiled' for row in profile))
        # A true 0.5s delay cannot be inferred from constant-motion geometry.
        self.assertTrue(all(row['train_selected_height_m'] == 150. for row in profile))
        self.assertLess(max(row['validation_median_px'] for row in profile), 1e-6)

    def test_turn_acceleration_gives_delay_profile_but_no_automatic_calibration(self):
        a, b = self.snapshot(2., turning=True), self.snapshot(2.5, 'b'*64, turning=True)
        poses, _ = pair_poses(a, b)
        pa, pb = self.correspondences(self.pose(1.5, True), self.pose(2., True))
        profile = error_profile(pa, pb, (1024, 768), poses, helpers())
        chosen = min(profile, key=lambda row: row['validation_median_px'])
        self.assertEqual(chosen['delay_s'], .5)
        self.assertEqual(chosen['train_selected_height_m'], 150.)
        self.assertLess(chosen['validation_median_px'], 1e-8)
        self.assertGreater(profile[0]['validation_median_px'], .1)
        json.dumps(profile, allow_nan=False)

    def test_missing_exact_sources_never_bridge_to_nearby_stored_photos(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            rows = [self.snapshot(2.+i*.5, chr(97+i)*64) for i in range(3)]
            for row in (rows[0], rows[2]):
                (folder / (row['source_image_sha256']+'.image')).write_bytes(b'not an exact photo')
            selected = select_pairs(rows, folder, 4., 1)
            self.assertEqual(selected[0][0]['status'], 'unknown')
            self.assertEqual(selected[0][0]['inventory']['exact_source_image_missing'], 2)
            with self.assertRaisesRegex(Unavailable, 'hash_mismatch'):
                exact_image(folder, rows[0]['source_image_sha256'])
            (folder / (rows[1]['source_image_sha256']+'.image')).write_bytes(b'exists')
            chosen = select_pairs(rows, folder, 4., 1)[0]
            self.assertEqual(chosen[1], 0)  # pair ending at 2.5 nearest fixed midpoint 2
            self.assertEqual(chosen[2]['source_image_sha256'], rows[0]['source_image_sha256'])
            # A corrupt source-sequence row is retained as a gap, never bypassed.
            self.assertEqual(select_pairs([rows[0], None, rows[2]], folder, 4., 1)[0][0]['status'], 'unknown')

    def test_background_matching_recovers_known_image_translation(self):
        rng = np.random.default_rng(17)
        before = cv2.GaussianBlur(rng.integers(0, 256, (256, 320), dtype=np.uint8), (3, 3), 0)
        after = cv2.warpAffine(before, np.array([[1., 0., 3.], [0., 1., -2.]]), (320, 256),
                               borderMode=cv2.BORDER_REFLECT)
        pa, pb = background_matches(before, after)
        self.assertGreaterEqual(len(pa), 40)
        np.testing.assert_allclose(np.median(pb-pa, axis=0), [3., -2.], atol=.05)

    def test_incomplete_run_refused_and_empty_completed_coverage_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            manifest = run / 'run.json'
            manifest.write_text('{"status":"running"}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'completed'):
                analyze(run)
            manifest.write_text('{"status":"completed","duration_sim_s":600}', encoding='utf-8')
            (run / 'runner-call.json').write_text(json.dumps(dict(sources=SUPPORTED_SOURCES)), encoding='utf-8')
            folder = run / 'observations' / '20001'
            folder.mkdir(parents=True)
            (folder / 'geometry-inputs.jsonl').write_text('', encoding='utf-8')
            result = analyze(run)
            self.assertEqual(result['status_counts'], dict(unknown=4))
            self.assertFalse(result['automatically_calibrated'])
            self.assertIsNone(result['calibrated_delay_s'])
            json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
