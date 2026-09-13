"""Synthetic public-control checks; no live run or simulator access."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import math

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT/'tools'))
from analyze_capture_orbit import analyze
from zqhj_comm import Packet, encode
from zqhj_state import LocalFrame


class CaptureOrbitAnalysisTests(unittest.TestCase):
    def setUp(self):
        archive = PROJECT/'.local-archive'
        archive.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='orbit-analysis-', dir=archive)
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        (self.run/'run.json').write_text(json.dumps(dict(status='completed', last_sim_s=100.)))
        for uid in ('a', 'b', 'c'):
            folder = self.run/'observations'/uid
            folder.mkdir(parents=True)
        self.folder = self.run/'observations'/'b'
        self.frame = LocalFrame(27., 125.)

    def row(self, t, heading=0., requested=-3., mode='orbit_arc', broadcast=True, navigation=True, radius=360.):
        lat, lon = self.frame.geo(radius, 0.)
        direction = math.radians(heading+requested*.5)
        waypoint = self.frame.geo(radius+300*math.sin(direction), 300*math.cos(direction))
        commands = []
        if navigation:
            commands.append(dict(verb='set_destination', params=dict(latitude=waypoint[0], longitude=waypoint[1], speed=18.)))
        if broadcast:
            packet = Packet(1, t, lat, lon, heading % 360, 18., track_id=1, target_lat=27., target_lon=125.,
                capture=True, ground_m=150., owner_slot=1, partner_slot=2, stage=3, identity='true_vehicle')
            commands.append(dict(verb='comm.broadcast', params=dict(payload=encode(packet))))
        return dict(score_sim_s=t, own=dict(uid='b', lat=lat, lon=lon, speed=18., heading_deg=heading),
            commands=commands, public_briefing=dict(mission_area=dict(lat_min=26.98, lat_max=27.02, lon_min=124.98, lon_max=125.02)),
            diagnostics=dict(plan_feasible=True, clearance_m=100.,
                capture=dict(owner='a', partner='b', mission=1, phase='APPROACH', planner_goal_mode=mode)))

    def analyze_rows(self, rows):
        (self.folder/'control-events.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        (self.folder/'observations.jsonl').write_text(json.dumps(rows[0])+'\n' if rows else '')
        return next(a for a in analyze(self.run)['agents'] if a['uid'] == 'b')

    def test_active_run_rejected_before_control_file_read(self):
        (self.run/'run.json').write_text(json.dumps(dict(status='running')))
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('opened controls before guard')):
            with self.assertRaisesRegex(ValueError, 'completed'):
                analyze(self.run)

    def test_requested_and_actual_rates_wrap_at_north_and_radio_only_does_not_count(self):
        a = self.analyze_rows([self.row(0., 1.), self.row(.25, .3, navigation=False),
                               self.row(.5, 359.5, mode='straight')])
        arc = a['modes']['orbit_arc']
        self.assertEqual(a['navigation_events'], 2)
        self.assertEqual(a['non_navigation_events'], 1)
        self.assertEqual(arc['navigation_commands'], 1)
        self.assertAlmostEqual(arc['requested_yaw_rate_deg_s']['median'], -3., places=5)
        self.assertAlmostEqual(arc['actual_yaw_rate_deg_s']['median'], -3., places=5)
        self.assertAlmostEqual(arc['observed_over_requested_turn_rate']['median'], 1., places=5)
        self.assertEqual(arc['known_command_hold_s'], .5)
        self.assertEqual(a['arc_episodes'][0]['sample_span_s'], 0.)

    def test_no_next_control_or_large_gap_is_not_assumed_continuous(self):
        a = self.analyze_rows([self.row(0.), self.row(.5), self.row(1.), self.row(4.), self.row(4.5)])
        self.assertEqual(len(a['arc_episodes']), 2)
        arc = a['modes']['orbit_arc']
        self.assertEqual(arc['known_command_hold_s'], 1.5)
        self.assertEqual(arc['response_status']['duplicate_time_or_control_gap'], 1)
        self.assertEqual(arc['response_status']['no_next_navigation_sample'], 1)

    def test_unknown_point_and_mode_stay_unknown(self):
        first = self.row(0., broadcast=False)
        first['diagnostics']['capture'].pop('planner_goal_mode')
        a = self.analyze_rows([first])
        self.assertNotIn('orbit_arc', a['modes'])
        self.assertEqual(a['modes']['unknown']['range_to_public_point_m']['unknown'], 1)
        self.assertIsNone(a['modes']['unknown']['range_to_public_point_m']['min'])

    def test_missing_control_events_does_not_fall_back_to_sparse_claims(self):
        (self.folder/'observations.jsonl').write_text(json.dumps(self.row(0.)))
        a = next(a for a in analyze(self.run)['agents'] if a['uid'] == 'b')
        self.assertEqual(a['status'], 'no_control_events_recorded')
        self.assertEqual(a['modes'], {})

    def test_public_radius_change_and_recorder_loss_are_visible(self):
        (self.folder/'capture-recording.json').write_text(json.dumps(dict(dropped={'event_count_capacity': 3}, wrapper_dropped={})))
        a = self.analyze_rows([self.row(0., radius=360.), self.row(.5, radius=350.)])
        arc = a['modes']['orbit_arc']
        self.assertAlmostEqual(arc['range_to_public_point_m']['min'], 350., places=5)
        self.assertAlmostEqual(arc['radius_change_per_interval_m']['median'], -10., places=5)
        self.assertEqual(a['recorder_dropped'], {'event_count_capacity': 3})


if __name__ == '__main__':
    unittest.main()
