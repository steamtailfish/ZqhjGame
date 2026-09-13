"""Synthetic public-data checks for approach attribution and missing-data boundaries."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from analyze_capture_approach import analyze
from zqhj_comm import Packet, encode
from zqhj_state import LocalFrame


class CaptureApproachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run/'run.json').write_text(json.dumps(dict(status='completed', last_sim_s=100)))
        for uid in ('a', 'b', 'c'):
            p = self.run/'observations'/uid
            p.mkdir(parents=True)
            (p/'observations.jsonl').write_text('')
        self.frame = LocalFrame(27, 125)

    def row(self, t, distance, phase='APPROACH', owner='a', partner='b', point=0., broadcast=True):
        lat, lon = self.frame.geo(point-distance, 0.)
        target_lat, target_lon = self.frame.geo(point, 0.)
        p = Packet(1, t, lat, lon, 90., 32., track_id=1, target_lat=target_lat,
            target_lon=target_lon, ground_m=150., capture=True, identity='true_vehicle',
            owner_slot=('a', 'b', 'c').index(owner)+1, partner_slot=('a', 'b', 'c').index(partner)+1,
            stage=3)
        commands = [dict(verb='set_destination', params=dict(speed=32.))]
        if broadcast:
            commands.append(dict(verb='comm.broadcast', params=dict(payload=encode(p))))
        return dict(score_sim_s=t, own=dict(uid='b', lat=lat, lon=lon, speed=32., heading_deg=90.),
            public_briefing=dict(mission_area=dict(lat_min=26.98, lat_max=27.02, lon_min=124.98, lon_max=125.02)),
            commands=commands, diagnostics=dict(plan_feasible=True, clearance_m=123., cruise_speed=32.,
                capture=dict(owner=owner, partner=partner, mission=1, phase=phase, own_visual=False)))

    def run_rows(self, rows):
        (self.run/'observations'/'b'/'observations.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        return next(a for a in analyze(self.run)['agents'] if a['uid'] == 'b')

    def test_active_run_rejected_before_any_observation_open(self):
        (self.run/'run.json').write_text(json.dumps(dict(status='running')))
        original = Path.read_bytes
        def guarded(path):
            if path.name == 'observations.jsonl':
                raise AssertionError('active observations opened')
            return original(path)
        with patch.object(Path, 'read_bytes', guarded), self.assertRaisesRegex(ValueError, 'completed'):
            analyze(self.run)

    def test_inward_crossings_and_duration_are_sample_brackets(self):
        a = self.run_rows([self.row(0., 760., phase='SEARCH'), self.row(.5, 720.),
            self.row(1., 680.), self.row(1.5, 620.), self.row(2., 390.), self.row(2.5, 380., phase='RELEASE')])
        s = a['approach_segments'][0]
        self.assertEqual(s['sample_span_s'], 1.5)
        self.assertEqual(s['duration_upper_bound_s'], 2.5)
        for threshold in ('410', '650', '700'):
            self.assertEqual(s['thresholds_m'][threshold]['inward_crossings'], 1)
        self.assertEqual(s['thresholds_m']['410']['crossings'][0]['bracket_s'], [1.5, 2.])

    def test_missing_broadcast_does_not_imply_crossing_or_zero_distance(self):
        a = self.run_rows([self.row(0., 750.), self.row(.5, 600., broadcast=False), self.row(1., 390.)])
        s = a['approach_segments'][0]
        self.assertEqual(s['range_to_broadcast_point_m']['unknown'], 1)
        self.assertEqual(s['radial_progress']['adjacent_pairs'], 0)
        self.assertEqual(s['thresholds_m']['410']['inward_crossings'], 0)
        self.assertEqual(s['thresholds_m']['410']['first_sample_at_or_below_s'], 1.)

    def test_task_and_role_changes_cannot_merge_approach_segments(self):
        a = self.run_rows([self.row(0., 750.), self.row(.5, 730.),
            self.row(1., 700., partner='c'), self.row(1.5, 690., partner='c'),
            self.row(2., 500., owner='c', partner='b')])
        self.assertEqual([s['role'] for s in a['approach_segments']], ['partner', 'third', 'partner'])
        self.assertEqual(len(a['missions']), 2)
        self.assertEqual(set(a['missions'][0]['roles']), {'partner', 'third'})

    def test_cached_planning_diagnostics_do_not_count_as_new_plans(self):
        second = self.row(.5, 680.)
        second['commands'] = [c for c in second['commands'] if c['verb'] == 'comm.broadcast']
        second['diagnostics'].update(plan_feasible=False, clearance_m=-999.)
        s = self.run_rows([self.row(0., 700.), second])['approach_segments'][0]
        self.assertEqual(s['planning'], {'feasible': 1})
        self.assertEqual(s['clearance_m']['min'], 123.)
        self.assertEqual(s['actual_speed_mps']['known'], 2)

    def test_public_point_update_is_separated_from_own_motion(self):
        # Aircraft stays at x=-700. Public nominated point moves from x=0 to x=-100.
        s = self.run_rows([self.row(0., 700.), self.row(.5, 600., point=-100.)])['approach_segments'][0]
        progress = s['radial_progress']
        self.assertAlmostEqual(progress['own_displacement_toward_previous_point_m'], 0., places=6)
        self.assertAlmostEqual(progress['moving_or_updated_point_contribution_m'], 100., delta=.2)
        self.assertAlmostEqual(progress['net_range_reduction_m'], 100., delta=.2)

    def test_large_gap_splits_duration_and_no_crossing_is_inferred(self):
        a = self.run_rows([self.row(0., 750.), self.row(.5, 740.), self.row(1., 730.),
                           self.row(8., 350.), self.row(8.5, 340.)])
        self.assertEqual(len(a['approach_segments']), 2)
        self.assertIsNone(a['approach_segments'][0]['exit_bracket_s'])
        self.assertEqual(a['partner_approach_sample_span_s'], 1.5)

    def test_mismatched_public_mission_packet_is_unknown(self):
        r = self.row(0., 750.)
        r['diagnostics']['capture']['mission'] = 2
        s = self.run_rows([r])['approach_segments'][0]
        self.assertIsNone(s['range_to_broadcast_point_m']['min'])
        self.assertEqual(s['source_counts'], {'broadcast_mission_or_roster_mismatch': 1})

    def test_received_owner_proxy_requires_sender_mission_and_freshness(self):
        r = self.row(1., 750., broadcast=False)
        payload = next(c['params']['payload'] for c in self.row(.5, 750.)['commands'] if c['verb'] == 'comm.broadcast')
        r['inbox'] = [dict(sender_uid='a', payload=payload, recv_time=.6)]
        s = self.run_rows([r])['approach_segments'][0]
        self.assertEqual(s['source_counts'], {'fresh_owner_broadcast_received_by_this_agent_proxy': 1})
        self.assertAlmostEqual(s['range_to_broadcast_point_m']['min'], 750., delta=.2)
        for update in (dict(sender_uid='c'), dict(recv_time=2.)):
            r['inbox'][0].update(sender_uid='a', recv_time=.6)
            r['inbox'][0].update(update)
            self.assertIsNone(self.run_rows([r])['approach_segments'][0]['range_to_broadcast_point_m']['min'])
        r['inbox'][0].update(sender_uid='a', recv_time=.6)
        r['score_sim_s'] = 3.
        self.assertIsNone(self.run_rows([r])['approach_segments'][0]['range_to_broadcast_point_m']['min'])

    def test_missing_speed_and_clearance_remain_unknown(self):
        r = self.row(0., 750.)
        r['own']['speed'] = None
        r['diagnostics'].update(clearance_m=None, plan_feasible=None)
        s = self.run_rows([r])['approach_segments'][0]
        self.assertEqual(s['actual_speed_mps']['unknown'], 1)
        self.assertIsNone(s['actual_speed_mps']['min'])
        self.assertEqual(s['clearance_m']['unknown'], 1)
        self.assertEqual(s['planning'], {'unknown': 1})
        self.assertIsNone(s['radial_progress']['net_range_reduction_m'])


if __name__ == '__main__':
    unittest.main()
