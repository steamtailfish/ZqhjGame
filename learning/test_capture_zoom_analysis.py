"""Public-only synthetic tests for completed-run zoom diagnostics."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from analyze_capture_zoom import PublicRows, analyze


class CaptureZoomAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run / 'observations' / 'a').mkdir(parents=True)
        (self.run / 'run.json').write_text(json.dumps(dict(status='completed')))

    def row(self, t, observed=50., requested=50., active=False, receipt=None, source=None):
        c = dict(phase='APPROACH' if active else 'SEARCH', owner='a' if active else None,
                 partner='b' if active else None, mission=1 if active else None,
                 own_visual=active, identity_state='current_true')
        return dict(score_sim_s=t, photo_sha256=f'photo{t}', boxes_photo_sha256=source,
            own=dict(gimbal_fov_deg=observed, gimbal_pan=0., gimbal_tilt=-80., heading_deg=90.),
            commands=[dict(verb='set_fov', params=dict(angle=requested))], boxes=[],
            diagnostics=dict(capture=c, receipt_first_seen_sim_s=receipt, geometry_state='PLANE_ESTIMATED',
                pixel_hits=3, pixel_identity_hits=2, motion_hits=2, fast_geo_hits=1,
                chosen_pixel=dict(x1=10,x2=22,y1=10,y2=17,category='true_vehicle',confidence=.97)))

    def rows(self, *rows):
        (self.run / 'observations' / 'a' / 'observations.jsonl').write_text(
            '\n'.join(json.dumps(r) for r in rows), encoding='utf-8')

    def test_running_run_is_rejected(self):
        (self.run / 'run.json').write_text(json.dumps(dict(status='running')))
        with self.assertRaisesRegex(ValueError, 'completed'):
            analyze(self.run)

    def test_constant_fov_has_no_zoom_transition(self):
        self.rows(self.row(0.), self.row(.5, active=True), self.row(1., active=True))
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['command_fov_counts'], {'50': 3})
        self.assertEqual(a['active_pair_related_transition_count'], 0)
        self.assertEqual(len(a['stable_fov_segments']), 1)

    def test_native_startup_fov_is_not_active_pair_zoom(self):
        self.rows(self.row(0., observed=30.), self.row(.5), self.row(1., active=True))
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['observed_fov_counts'], {'30': 1, '50': 2})
        self.assertEqual(a['active_pair_related_transition_count'], 0)
        self.assertEqual(a['observed_fov_transitions'][0]['context'], 'before_any_assignment')

    def test_enter_and_release_zoom_are_grouped_with_active_pair(self):
        release = self.row(1.5, observed=50.)
        release['diagnostics']['capture'].update(phase='RELEASE', owner='a', partner='b', mission=1)
        self.rows(self.row(0.), self.row(.5, observed=30., requested=30., active=True),
                  self.row(1., observed=30., requested=30., active=True), release)
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['active_pair_related_transition_count'], 2)
        self.assertEqual(a['by_membership']['active_owner']['observed_fov_counts'], {'30': 2})
        self.assertEqual(a['stable_fov_segments'][1]['sample_span_s'], .5)

    def test_box_source_fov_is_distinct_from_current_observed_fov(self):
        before = self.row(0., observed=50.)
        after = self.row(.5, observed=30., requested=30., active=True, receipt=0., source='photo0.0')
        public = PublicRows([before, after])
        snap = public.snapshot(after, 'a')
        self.assertEqual(snap['observed_own_fov_deg'], 30.)
        self.assertEqual(snap['source_photo_pose']['pose']['gimbal_fov_deg'], 50.)
        self.assertEqual(snap['selected_raw_box']['box_width_px'], 12)
        self.assertEqual(snap['source_receipt_age_s'], .5)

    def test_nearest_receipt_pose_must_not_be_mislabeled_as_exact(self):
        before = self.row(0.)
        after = self.row(.5, receipt=.1, source='photo0.0')
        match = PublicRows([before, after]).source_pose(after)
        self.assertEqual(match, dict(status='no_exact_receipt_sample', pose=None))

    def test_exact_timestamp_with_wrong_digest_is_unknown(self):
        before = self.row(0.)
        after = self.row(.5, receipt=0., source='different-photo')
        match = PublicRows([before, after]).source_pose(after)
        self.assertEqual(match, dict(status='receipt_sample_digest_mismatch', pose=None))

    def test_large_sample_gap_splits_stable_segments(self):
        self.rows(self.row(0.), self.row(.5), self.row(1.), self.row(4.), self.row(4.5))
        a = analyze(self.run)['agents'][0]
        self.assertEqual(len(a['stable_fov_segments']), 2)
        self.assertEqual(a['observed_fov_transitions'], [])

    def test_transition_window_marks_missing_offsets(self):
        rows = [self.row(0.), self.row(.5), self.row(1.)]
        window = PublicRows(rows).window(.5, 'a')
        self.assertEqual(len(window), 9)
        self.assertEqual(window[0]['status'], 'no_public_sample_within_window_tolerance')
        self.assertEqual(window[4]['sample']['t'], .5)

    def test_fov_command_need_not_be_emitted_at_every_public_sample(self):
        idle_control = self.row(.5)
        idle_control['commands'] = []
        self.rows(self.row(0.), idle_control)
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['samples_without_fov_command'], 1)
        self.assertEqual(a['command_fov_counts'], {'50': 1})
        self.assertEqual(a['observed_fov_counts'], {'50': 2})


if __name__ == '__main__':
    unittest.main()
