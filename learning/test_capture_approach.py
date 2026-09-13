"""Approach guidance contracts; no simulator or hidden target inputs.

Tests verify radial progress of the ideal guide and continued use of the safety
planner. They do not promise that a constrained aircraft can fly the ideal guide.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import math
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT.parent)]

from competition.sdk.core.observation import (
    AreaSpec, Detection, Message, MissionBriefing, Observation, ScoreView, SelfView,
)
from zqhj_capture import (
    CaptureMission, CaptureSearchAgent, SEARCH, OFFER, APPROACH, TRACK, RECOVER, RELEASE,
)
from zqhj_comm import Packet, encode
from zqhj_planner import Circle, PeerMotion, PrimitivePlanner, guide_heading
from zqhj_score_search import ScoreSearchAgent
from zqhj_state import LocalFrame, wrap


class CaptureApproachTests(unittest.TestCase):
    def setUp(self):
        self.frame = LocalFrame(37., 121.)
        self.target = (0., 0.)
        self.position = (0., 575.)
        self.velocity = (0., -22.)

    def own(self, uid='charlie', position=None):
        lat, lon = self.frame.geo(*(position or self.position))
        return SimpleNamespace(uid=uid, lat=lat, lon=lon, alt=500., heading_deg=180.,
                               speed=22., gimbal_pan=0., gimbal_tilt=-45., gimbal_fov_deg=30.)

    def agent(self, uid='charlie', phase=APPROACH):
        agent = CaptureSearchAgent(uid)
        agent.detector = lambda photo: []
        agent.reset()
        agent.frame = self.frame
        agent.clock.previous = 2.
        agent.capture.roster = ('alpha', 'bravo', 'charlie')
        agent.capture.adopt(CaptureMission('alpha', 1, 'charlie', self.target, (0., 0.),
                                         200., 1., 1., 160., 1.), 1.)
        agent.capture.phase = phase
        self.addCleanup(agent.close_detector)
        return agent

    def owner_packet(self, position=(0., -320.), now=2.):
        lat, lon = self.frame.geo(*position)
        return Packet(round(now*100), now, lat, lon, 90., 22., track_id=1,
            target_lat=37., target_lon=121., hits=4, sigma_m=80., ground_m=200.,
            identity='true_vehicle', capture=True, owner_slot=1, partner_slot=3,
            stage=APPROACH, visible=False)

    def guide(self, agent, position=None, formation=True, motions=(), obstacles=(), radius=360.):
        return agent.guidance(position or self.position, self.velocity, self.target,
                              motions, obstacles, formation, radius)

    def test_575m_partner_closes_radially_instead_of_entering_an_early_orbit(self):
        agent = self.agent()
        agent.radio.peers['alpha'] = self.owner_packet()
        heading = self.guide(agent)
        previous_orbit = ScoreSearchAgent.guidance(agent, self.position, self.velocity,
            self.target, (), (), True, 360.)
        # The owner is south of the target and this partner is north: the
        # opposite-side staging point lies directly between partner and target.
        self.assertAlmostEqual(wrap(heading-180.), 0., places=7)
        radial_progress = math.cos(math.radians(wrap(heading-180.)))
        old_radial_progress = math.cos(math.radians(wrap(previous_orbit-180.)))
        self.assertGreater(radial_progress-old_radial_progress, .4)
        agent.prepare_planner(self.own(), self.target, True, self.position)
        self.assertEqual(agent.planner.cruise_speed, 32.)
        self.assertEqual(agent.orbit_radius(self.own(), agent.capture.assignment(2.)), 360.)

    def test_410m_boundary_returns_to_orbit_and_slow_speed(self):
        agent = self.agent()
        agent.radio.peers['alpha'] = self.owner_packet(position=(-320., 0.))
        for distance, approaching, speed in ((410.001, True, 32.), (410., False, 18.),
                                            (409.999, False, 18.), (360., False, 18.)):
            position = (0., distance)
            with self.subTest(distance=distance):
                self.assertEqual(agent.partner_approaching(position, self.target), approaching)
                agent.prepare_planner(self.own(position=position), self.target, True, position)
                self.assertEqual(agent.planner.cruise_speed, speed)
                if not approaching:
                    expected = ScoreSearchAgent.guidance(agent, position, self.velocity,
                        self.target, (), (), True, 360.)
                    self.assertAlmostEqual(wrap(self.guide(agent, position)-expected), 0., places=7)

    def test_radius_argument_and_configured_margin_share_the_entry_boundary(self):
        agent = self.agent()
        agent.partner_orbit_radius = 450.
        self.assertFalse(agent.partner_approaching((0., 500.), self.target))
        self.assertTrue(agent.partner_approaching((0., 500.1), self.target))
        self.assertFalse(agent.partner_approaching((0., 370.), self.target, radius=320.))
        self.assertTrue(agent.partner_approaching((0., 370.1), self.target, radius=320.))

    def test_owner_third_and_nonapproach_phases_keep_existing_nearby_guidance(self):
        cases = [('alpha', APPROACH, True, 18., 320.), ('bravo', SEARCH, False, 35., 360.)]
        cases.extend(('charlie', phase, True, 18., 360.) for phase in (OFFER, TRACK, RECOVER, RELEASE))
        for uid, phase, formation, speed, radius in cases:
            with self.subTest(uid=uid, phase=phase):
                agent = self.agent(uid, phase)
                agent.radio.peers['alpha'] = self.owner_packet(position=(-320., 0.))
                self.assertFalse(agent.partner_approaching(self.position, self.target))
                expected = ScoreSearchAgent.guidance(agent, self.position, self.velocity,
                    self.target, (), (), formation, radius)
                self.assertAlmostEqual(wrap(self.guide(agent, formation=formation, radius=radius)-expected),
                                       0., places=7)
                agent.prepare_planner(self.own(uid), self.target, formation, self.position)
                self.assertEqual(agent.planner.cruise_speed, speed)
        search = self.agent()
        search.radio.peers['alpha'] = self.owner_packet(position=(-320., 0.))
        self.assertAlmostEqual(wrap(self.guide(search, formation=False)-guide_heading(
            self.position, self.velocity, self.target, formation=False)), 0., places=7)
        search.prepare_planner(self.own(), self.target, False, self.position)
        self.assertEqual(search.planner.cruise_speed, 35.)

    def test_fresh_owner_staging_uses_opposite_side_and_preserves_safety_inputs(self):
        agent = self.agent()
        # At the inclusive age boundary the owner's public west-side pose is
        # still usable; staging should be east, not at the owner's position.
        agent.radio.peers['alpha'] = self.owner_packet(position=(-320., 0.), now=.5)
        motions = (PeerMotion(600., 200., -10., 0., .1),)
        obstacles = (Circle(-500., 300., 80.),)
        expected = guide_heading(self.position, self.velocity, (360., 0.),
                                 motions, obstacles, formation=False)
        result = self.guide(agent, motions=motions, obstacles=obstacles)
        self.assertAlmostEqual(wrap(result-expected), 0., places=6)
        direct = guide_heading(self.position, self.velocity, self.target, motions, obstacles, formation=False)
        self.assertGreater(abs(wrap(result-direct)), 20.)

    def test_missing_stale_or_future_owner_pose_uses_public_target_for_approach(self):
        for peer_time in (None, .49, 2.01):
            with self.subTest(peer_time=peer_time):
                agent = self.agent()
                if peer_time is not None:
                    agent.radio.peers['alpha'] = self.owner_packet(position=(-320., 0.), now=peer_time)
                expected = guide_heading(self.position, self.velocity, self.target, formation=False)
                self.assertAlmostEqual(wrap(self.guide(agent)-expected), 0., places=7)
                self.assertAlmostEqual(wrap(self.guide(agent)-180.), 0., places=7)

    def test_sdk_approach_still_routes_navigation_through_the_primitive_safety_planner(self):
        agent = self.agent()
        agent.clock.previous = None
        own = self.own()
        message = Message('alpha', encode(self.owner_packet()), 2.)
        observation = Observation(SelfView('charlie', own.lat, own.lon, own.alt,
            own.heading_deg, own.speed, own.gimbal_pan, own.gimbal_tilt,
            own.gimbal_fov_deg, Detection(False, 0.)), (message,),
            MissionBriefing('charlie', 3, AreaSpec(36.98, 37.02, 120.98, 121.02),
                score_view=ScoreView(total_score=0., dimension_scores=(), passed=False,
                    n_destroyed=0, n_targets=3, sim_time=2.)))
        self.assertIsInstance(agent.planner, PrimitivePlanner)
        with patch.object(agent.planner, 'plan', wraps=agent.planner.plan) as plan:
            commands = agent.decide(observation, .1)
        plan.assert_called_once()
        self.assertEqual(agent.capture.phase, APPROACH)
        self.assertEqual(agent.planner.cruise_speed, 32.)
        args, kwargs = plan.call_args
        self.assertEqual(len(args[4]), 1)  # Legal peer motion still enters clearance checks.
        self.assertIsNotNone(args[5])     # Public mission bounds are preserved.
        self.assertLess(math.dist(args[7], self.target), .03)
        self.assertEqual(kwargs['radius'], 360.)
        destination = next(c.params for c in commands if c.verb == 'set_destination')
        waypoint = self.frame.xy(destination['latitude'], destination['longitude'])
        self.assertAlmostEqual(math.dist(self.position, waypoint), 300., places=5)
        self.assertFalse(agent.capture.visible)
        self.assertFalse(any(c.verb == 'agent.report' for c in commands))


if __name__ == '__main__':
    unittest.main()
