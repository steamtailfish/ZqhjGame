"""Small offline checks for completed-run agreement audits and legacy unknowns."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from analyze_capture_agreement import analyze, NEW_FIELDS


class CaptureAgreementAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run / 'run.json').write_text(json.dumps(dict(status='completed')), encoding='utf-8')

    def rows(self, uid, *captures):
        path = self.run / 'observations' / uid / 'observations.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(json.dumps(dict(score_sim_s=2.,
            diagnostics=dict(capture=capture))) for capture in captures), encoding='utf-8')

    def capture(self, **changes):
        result = dict(owner='alpha', partner='charlie', mission=1, phase='APPROACH',
            own_visual=True, pair_consistent=True, pair_residual_m=12.,
            owner_reference_sample_s=1.5, owner_reference_xy=[0., 0.],
            local_joint_s=.5, max_local_joint_s=.5, paired_samples=2)
        result.update(changes)
        return result

    def test_unfinished_run_rejected_before_observations_are_read(self):
        (self.run / 'run.json').write_text('{"status":"running"}', encoding='utf-8')
        path = self.run / 'observations' / 'charlie' / 'observations.jsonl'
        path.parent.mkdir(parents=True)
        path.write_text('not valid JSON', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'completed'):
            analyze(self.run)

    def test_legacy_missing_fields_are_unknown_not_false_or_violations(self):
        legacy = self.capture()
        for name in NEW_FIELDS:
            del legacy[name]
        self.rows('charlie', legacy)
        result = analyze(self.run)
        self.assertEqual(result['summary']['pair_consistent'], dict(true=0, false=0, unknown=1))
        for field in NEW_FIELDS:
            self.assertEqual(result['summary']['new_field_coverage'][field]['missing'], 1)
            self.assertEqual(result['summary']['new_field_coverage'][field]['unknown'], 1)
        self.assertEqual(result['visible_partner_checks'], dict(considered=1, passed=0, failed=0, unknown=1))
        self.assertEqual(result['violation_examples'], [])

    def test_partner_invariants_do_not_apply_to_owner_or_third(self):
        self.rows('alpha', self.capture(pair_consistent=False, owner_reference_sample_s=0.))
        self.rows('bravo', self.capture(pair_consistent=False, owner_reference_sample_s=0.))
        self.rows('charlie', self.capture(), self.capture(pair_consistent=False, pair_residual_m=40.),
                  self.capture(owner_reference_sample_s=1.), self.capture(owner_reference_sample_s=2.1))
        result = analyze(self.run)
        self.assertEqual(result['visible_partner_checks'], dict(considered=4, passed=1, failed=3, unknown=0))
        self.assertEqual(result['roles']['owner']['samples'], 1)
        self.assertEqual(result['roles']['third']['samples'], 1)
        self.assertEqual(result['roles']['partner']['spatial_rejected_samples'], 1)
        self.assertTrue(all(row['uid'] == 'charlie' for row in result['violation_examples']))

    def test_missing_reference_remains_unknown_and_null_is_distinguished(self):
        self.rows('charlie', self.capture(owner_reference_sample_s=None),
                  self.capture(pair_residual_m=None, owner_reference_xy=None))
        result = analyze(self.run)
        self.assertEqual(result['visible_partner_checks'], dict(considered=2, passed=0, failed=0, unknown=2))
        metric = result['summary']['numeric_samples']['owner_reference_age_s']
        self.assertEqual((metric['known'], metric['null'], metric['unknown']), (1, 1, 1))
        self.assertEqual(metric['max'], .5)

    def test_agreement_flag_needs_residual_and_reference_coordinates_to_pass(self):
        incomplete = [self.capture(pair_residual_m=value) for value in (None, 'invalid')]
        incomplete.extend(self.capture(owner_reference_xy=value) for value in (None, [0.], ['x', 0.]))
        missing_reference = self.capture()
        del missing_reference['owner_reference_xy']
        incomplete.append(missing_reference)
        self.rows('charlie', *incomplete,
            self.capture(pair_consistent=False, pair_residual_m=None, owner_reference_xy=None),
            self.capture(pair_residual_m=40., owner_reference_xy=None))
        result = analyze(self.run)
        self.assertEqual(result['visible_partner_checks'],
                         dict(considered=8, passed=0, failed=2, unknown=6))
        self.assertEqual(len(result['violation_examples']), 2)

    def test_examples_are_bounded_and_joint_counters_are_not_added(self):
        self.rows('charlie', *(self.capture(pair_consistent=False, pair_residual_m=i+30.,
                  local_joint_s=float(i), max_local_joint_s=float(i), paired_samples=i+1)
                  for i in range(12)))
        result = analyze(self.run)
        self.assertEqual(result['visible_partner_checks']['failed'], 12)
        self.assertEqual(len(result['violation_examples']), 8)
        metric = result['summary']['numeric_samples']['local_joint_s']
        self.assertEqual(metric['max'], 11.)
        self.assertEqual(metric['p50'], 5.5)
        self.assertNotIn('sum', metric)
        self.assertEqual(result['summary']['numeric_samples']['paired_samples']['max'], 12)


if __name__ == '__main__':
    unittest.main()
