"""Synthetic completed-run fixtures for the offline identity-memory analyzer."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from analyze_capture_identity import analyze


class CaptureIdentityAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'run'
        (self.run / 'observations' / 'a').mkdir(parents=True)
        self.write(self.run / 'run.json', dict(status='completed', last_sim_s=10.))
        (self.run / 'runner.log').write_text('[coop_decoy] first frame @ sim_time=500.000\n')

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def row(self, time, **capture):
        c = dict(phase='APPROACH', owner='a', partner='b', mission=1, own_visual=True)
        c.update(capture)
        return dict(score_sim_s=time, photo_sha256='current', boxes_photo_sha256='source',
            diagnostics=dict(capture=c, chosen_pixel=dict(category='true_vehicle'),
                             receipt_first_seen_sim_s=time-.3))

    def rows(self, *rows):
        (self.run / 'observations' / 'a' / 'observations.jsonl').write_text(
            '\n'.join(json.dumps(row) for row in rows), encoding='utf-8')

    def judge(self, times=(.9, 1.1, 1.3), labels=None, **extra):
        labels = labels or ['none'] * len(times)
        path = self.run / 'judge.json'
        axis = dict(clock='official score-relative seconds', formula='t = engine_sim_time - sim_t0',
                    sim_t0=500., origin_rounding_bound_s=.0005, official_last_sim_s=10.)
        axis.update(extra.pop('axis', {}))
        timeline = [dict(t=t, matches=dict(a=dict(is_effective=label=='effective_true',
                    was_misid=label=='decoy'))) for t, label in zip(times, labels)]
        self.write(path, dict(time_axis=axis, timeline=timeline, **extra))
        return path

    def test_old_logs_are_unknown_not_current_true(self):
        self.rows(self.row(1.))
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['states'], {'unknown': 1})
        self.assertEqual(a['identity_field_samples'], 0)
        self.assertEqual(a['identity_decoy_hits'], {'unknown': 1})

    def test_remembered_true_keeps_raw_decoy_category(self):
        row = self.row(1., identity_state='remembered_true', identity_last_true_s=.4,
                       identity_decoy_hits=1)
        row['diagnostics']['chosen_pixel']['category'] = 'decoy_vehicle'
        self.rows(row)
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['remembered_visible_raw_categories'], {'decoy_vehicle': 1})
        self.assertAlmostEqual(a['last_true_age_max_s'], .6)
        self.assertEqual(a['max_identity_decoy_hits'], 1)

    def test_missing_current_photo_with_fresh_cache_is_not_no_source(self):
        row = self.row(1., identity_state='remembered_true')
        row['photo_sha256'] = None
        self.rows(row)
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['photo_checks']['visible_without_current_but_fresh_cached_source'], 1)
        self.assertNotIn('visible_without_source_photo', a['photo_checks'])
        self.assertEqual(a['anomaly_examples'], [])

    def test_missing_source_and_chosen_pixel_are_logged(self):
        row = self.row(1., identity_state='remembered_true')
        row['photo_sha256'] = row['boxes_photo_sha256'] = None
        row['diagnostics']['chosen_pixel'] = None
        row['diagnostics']['receipt_first_seen_sim_s'] = None
        self.rows(row)
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['photo_checks']['visible_without_source_photo'], 1)
        self.assertEqual(a['photo_checks']['visible_without_chosen_pixel'], 1)

    def test_stale_source_is_separate_from_missing_provenance(self):
        row = self.row(1.)
        row.pop('boxes_photo_sha256')
        row['diagnostics']['receipt_first_seen_sim_s'] = .1
        self.rows(row)
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['photo_checks']['visible_source_photo_provenance_unknown'], 1)
        self.assertEqual(a['photo_checks']['visible_with_source_older_than_0_8_s'], 1)

    def test_repeated_release_samples_count_one_event(self):
        self.rows(self.row(1.), self.row(1.5, phase='RELEASE', reason='timeout', own_visual=False),
                  self.row(2., phase='RELEASE', reason='timeout', own_visual=False))
        a = analyze(self.run)['agents'][0]
        self.assertEqual(a['releases_by_reason'], {'timeout': 1})
        self.assertEqual(a['missions']['a:1']['release_events'], [dict(t=1.5, reason='timeout')])

    def test_normalized_bracket_alignment_and_none_label(self):
        self.rows(self.row(1., identity_state='remembered_true'),
                  self.row(1.1, identity_state='current_true'))
        a = analyze(self.run, self.judge(labels=['none', 'effective_true', 'decoy']))['agents'][0]
        self.assertEqual(a['judge_remembered_visible_coverage'], {'none': 1})
        self.assertEqual(a['judge_by_identity_state']['current_true'], {'effective_true': 1})
        self.assertAlmostEqual(a['max_judge_alignment_error_s'], .1)

    def test_sampling_gap_and_edges_are_not_filled(self):
        self.rows(self.row(.8), self.row(1.5), self.row(2.4))
        a = analyze(self.run, self.judge(times=(.9, 1.1, 1.3, 2.1, 2.3)))['agents'][0]
        self.assertEqual(a['judge_coverage'], {'unaligned': 3})
        self.assertEqual(a['judge_unaligned_reasons'], {'outside_recorded_span': 2, 'judge_sampling_gap': 1})

    def test_wrong_origin_rejected(self):
        self.rows(self.row(1.))
        with self.assertRaisesRegex(ValueError, 'origins disagree'):
            analyze(self.run, self.judge(axis=dict(sim_t0=-500.)))

    def test_unnormalized_judge_rejected(self):
        self.rows(self.row(1.))
        with self.assertRaisesRegex(ValueError, 'normalized'):
            analyze(self.run, self.judge(axis=dict(clock='raw engine')))

    def test_running_run_rejected_before_other_inputs_are_read(self):
        self.write(self.run / 'run.json', dict(status='running'))
        with self.assertRaisesRegex(ValueError, 'completed'):
            analyze(self.run, self.run / 'does-not-exist.json')

    def test_judge_declared_running_run_rejected(self):
        other = self.run.parent / 'other'
        other.mkdir()
        self.write(other / 'run.json', dict(status='running'))
        with self.assertRaisesRegex(ValueError, 'completed'):
            analyze(self.run, self.judge(run=str(other)))


if __name__ == '__main__':
    unittest.main()
