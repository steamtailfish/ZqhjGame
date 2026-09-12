"""Offline time-axis regression tests; never connects to a running engine."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from analyze_judge_trace import analyze, read_time_origin


class JudgeTraceTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)

    def manifest(self, **extra):
        value = dict(status='completed', last_sim_s=300.)
        value.update(extra)
        (self.run / 'run.json').write_text(json.dumps(value), encoding='utf-8')
        return value

    def log(self, value):
        (self.run / 'runner.log').write_text(
            f'[coop_decoy] first frame @ sim_time={value}\n', encoding='utf-8')

    def trace(self, *times):
        return dict(scope='synthetic offline regression',
                    rows=[dict(engine_sim_time=t, entities=[]) for t in times])

    def test_negative_origin_preserves_partial_start_and_raw_time(self):
        self.manifest()
        self.log('-43210.000')
        result = analyze(self.run, self.trace(-43208.75, -42910.1))
        self.assertAlmostEqual(result['timeline'][0]['t'], 1.25)
        self.assertAlmostEqual(result['timeline'][-1]['t'], 299.9)
        self.assertEqual(result['timeline'][0]['engine_sim_time'], -43208.75)
        self.assertEqual(result['time_axis']['sim_t0'], -43210.)
        self.assertEqual(result['time_axis']['outside_run_frames'], 0)
        self.assertEqual(result['sampled_frames'], 2)

    def test_positive_origin_is_subtracted(self):
        self.manifest()
        self.log('1234.500')
        self.assertEqual(analyze(self.run, self.trace(1240.))['timeline'][0]['t'], 5.5)

    def test_precise_structured_origin_with_rounded_log(self):
        manifest = self.manifest(sim_t0=123.4564)
        self.log('123.456')
        origin = read_time_origin(self.run, manifest)
        self.assertEqual(origin['sim_t0'], 123.4564)
        self.assertEqual(origin['source'], 'run.json:sim_t0')

    def test_missing_origin_fails_instead_of_zeroing_partial_trace(self):
        self.manifest()
        with self.assertRaisesRegex(ValueError, 'origin|first-frame'):
            analyze(self.run, self.trace(-100., -50.))

    def test_conflicting_starts_fail(self):
        manifest = self.manifest(sim_t0=5.)
        self.log('6.000')
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            read_time_origin(self.run, manifest)

    def test_trace_from_another_run_fails(self):
        self.manifest()
        self.log('1000.000')
        with self.assertRaisesRegex(ValueError, 'does not overlap'):
            analyze(self.run, self.trace(-100., -50.))

    def test_unfinished_run_remains_blocked(self):
        self.manifest(status='running')
        self.log('0.000')
        with self.assertRaisesRegex(ValueError, 'must finish'):
            analyze(self.run, self.trace(1.))

    def test_clock_rewind_is_rejected(self):
        self.manifest()
        self.log('0.000')
        with self.assertRaisesRegex(ValueError, 'monotonic'):
            analyze(self.run, self.trace(2., 1.))

    def test_post_run_tail_is_preserved_and_marked(self):
        self.manifest(last_sim_s=299.96)
        self.log('1000.000')
        result = analyze(self.run, self.trace(1299.9, 1300.1))
        self.assertEqual(result['sampled_frames'], 2)
        self.assertEqual(result['time_axis']['outside_run_frames'], 1)
        self.assertAlmostEqual(result['timeline'][-1]['t'], 300.1)


if __name__ == '__main__':
    unittest.main()
