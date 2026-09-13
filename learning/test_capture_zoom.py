"""Camera zoom must preserve search coverage and independent capture evidence.

These checks exercise SDK commands and image/ground geometry, not competition
performance. Real photo/receipt-pose alignment still requires an official run.
"""
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import math
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT.parent)]

import cv2
import numpy as np

from competition.sdk.core.observation import (
    AreaSpec, Detection, Message, MissionBriefing, Observation, ScoreView, SelfView,
)
from zqhj_capture import (
    CaptureMission, CaptureSearchAgent, SEARCH, VERIFY, OFFER, APPROACH,
    TRACK, RECOVER, RELEASE,
)
from zqhj_comm import Packet, decode, encode
from zqhj_state import LocalFrame
from zqhj_vision import PixelBox
from zqhj_visual_geometry import MotionPlane


class CaptureZoomTests(unittest.TestCase):
    def setUp(self):
        self.frame = LocalFrame(37., 121.)
        self.positions = {'alpha': (0., -320.), 'bravo': (0., 2400.),
                          'charlie': (0., 360.)}

    def own(self, uid='alpha', xy=None, fov=50.):
        lat, lon = self.frame.geo(*(xy or self.positions[uid]))
        return SimpleNamespace(uid=uid, lat=lat, lon=lon, alt=500., heading_deg=0.,
                               speed=22., gimbal_pan=0., gimbal_tilt=-45.,
                               gimbal_fov_deg=fov)

    def agent(self, uid='alpha', mission=True):
        agent = CaptureSearchAgent(uid)
        agent.detector = lambda photo: []
        agent.reset()
        agent.frame = self.frame
        agent.enable_reports = True
        self.addCleanup(agent.close_detector)
        if mission:
            agent.capture.adopt(CaptureMission('alpha', 1, 'charlie', (0., 0.),
                (0., 0.), 200., 1., 1., 160., 1.), 1.)
            agent.capture.phase = APPROACH
        return agent

    def broadcast(self, uid, now, active=False):
        own = self.own(uid)
        lat, lon = self.frame.geo(0., 0.)
        packet = Packet(round(now * 10), now, own.lat, own.lon, own.heading_deg, own.speed,
            track_id=1 if active else 0, target_lat=lat if active else 0.,
            target_lon=lon if active else 0., hits=4 if active else 0,
            sigma_m=80., ground_m=200. if active else None,
            identity='true_vehicle' if active else 'unknown', capture=True,
            owner_slot=1 if active else 0, partner_slot=3 if active else 0,
            stage=OFFER if active else SEARCH, visible=active)
        return Message(uid, encode(packet), now)

    def observation(self, uid, now, messages=(), fov=50.):
        own = self.own(uid, fov=fov)
        return Observation(
            SelfView(uid, own.lat, own.lon, own.alt, own.heading_deg, own.speed,
                     own.gimbal_pan, own.gimbal_tilt, fov, Detection(False, 0.)),
            messages,
            MissionBriefing(uid, 3, AreaSpec(36.98, 37.02, 120.98, 121.02),
                            score_view=ScoreView(total_score=0., dimension_scores=(),
                                passed=False, n_destroyed=0, n_targets=3, sim_time=now)))

    def test_both_assigned_members_zoom_during_acquisition_tracking_and_recovery(self):
        for uid in ('alpha', 'charlie'):
            agent = self.agent(uid)
            for phase in (OFFER, APPROACH, TRACK, RECOVER):
                with self.subTest(uid=uid, phase=phase):
                    agent.capture.phase = phase
                    assignment = agent.capture.assignment(1.)
                    self.assertEqual(assignment.role, 'OBSERVE')
                    self.assertEqual(agent.camera_fov(self.own(uid), True), 30.)
                    self.assertFalse(agent.capture.visible)
                    self.assertIsNone(agent.capture_bound)

    def test_search_verify_release_and_third_aircraft_keep_wide_coverage(self):
        agent = self.agent(mission=False)
        for phase in (SEARCH, VERIFY, RELEASE):
            with self.subTest(scope='no_mission', phase=phase):
                agent.capture.phase = phase
                self.assertEqual(agent.camera_fov(self.own(), False), 50.)
        for uid in ('alpha', 'charlie'):
            agent = self.agent(uid)
            agent.capture.phase = RELEASE
            self.assertEqual(agent.capture.assignment(1.).role, 'SEARCH')
            self.assertEqual(agent.camera_fov(self.own(uid), False), 50.)
            # A stale formation flag must not keep a released camera zoomed.
            self.assertEqual(agent.camera_fov(self.own(uid), True), 50.)
            agent.capture.phase = APPROACH
            self.assertEqual(agent.camera_fov(self.own(uid), False), 50.)
        third = self.agent('bravo')
        for phase in (SEARCH, APPROACH, TRACK, RECOVER, RELEASE):
            with self.subTest(scope='third_aircraft', phase=phase):
                third.capture.phase = phase
                self.assertEqual(third.capture.assignment(1.).role, 'SEARCH')
                self.assertEqual(third.camera_fov(self.own('bravo'), False), 50.)
                self.assertEqual(third.camera_fov(self.own('bravo'), True), 50.)

    def test_zoom_is_stable_across_distance_time_and_pair_phase_changes(self):
        for uid in ('alpha', 'charlie'):
            agent = self.agent(uid)
            commanded = []
            for now, distance, phase in ((1., 1200., APPROACH), (1.5, 700., APPROACH),
                    (2., 360., TRACK), (2.5, 65., TRACK), (3., 500., RECOVER)):
                agent.clock.previous = now
                agent.capture.phase = phase
                own = self.own(uid, (0., -distance), commanded[-1] if commanded else 50.)
                commanded.append(agent.camera_fov(own, True))
            self.assertEqual(commanded, [30.] * len(commanded))
            self.assertTrue(all(abs(a-b) < .1 for a, b in zip(commanded, commanded[1:])))

    def test_sdk_partner_zoom_does_not_authorize_own_visual_or_target_report(self):
        agent = self.agent('charlie', mission=False)
        for now, fov in ((1., 50.), (1.6, 30.)):
            messages = (self.broadcast('alpha', now, active=True),
                        self.broadcast('bravo', now))
            commands = agent.decide(self.observation('charlie', now, messages, fov), .1)
            self.assertEqual([c.params['angle'] for c in commands if c.verb == 'set_fov'], [30.])
            self.assertEqual(agent.capture.phase, APPROACH)
            self.assertTrue(agent.capture.ack)
            self.assertFalse(agent.capture.visible)
            self.assertIsNone(agent.capture_bound)
            self.assertIsNone(agent.capture_identity)
            self.assertEqual(agent.capture.joint_s, 0.)
            self.assertFalse(any(c.verb == 'agent.report' for c in commands))
            packet = decode(next(c.params['payload'] for c in commands if c.verb == 'comm.broadcast'))
            self.assertFalse(packet.visible)

    def test_sdk_third_aircraft_stays_wide_after_receiving_another_pairs_offer(self):
        agent = self.agent('bravo', mission=False)
        messages = (self.broadcast('alpha', 1., active=True), self.broadcast('charlie', 1.))
        commands = agent.decide(self.observation('bravo', 1., messages), .1)
        self.assertEqual(agent.capture.mission.owner, 'alpha')
        self.assertEqual(agent.capture.phase, SEARCH)
        self.assertEqual([c.params['angle'] for c in commands if c.verb == 'set_fov'], [50.])
        self.assertFalse(agent.capture.visible)
        self.assertFalse(any(c.verb == 'agent.report' for c in commands))

    def test_ground_location_and_area_are_consistent_for_synchronized_zoom(self):
        own = self.own()
        wide = PixelBox(650., 320., 660., 328., .99, 1024, 768, 'true_vehicle', .98)
        scale = math.tan(math.radians(50./2))/math.tan(math.radians(30./2))
        cx, cy = (wide.width-1)/2., (wide.height-1)/2.
        zoomed = replace(wide, x1=cx+(wide.x1-cx)*scale, x2=cx+(wide.x2-cx)*scale,
                         y1=cy+(wide.y1-cy)*scale, y2=cy+(wide.y2-cy)*scale)
        narrow_own = SimpleNamespace(**{**vars(own), 'gimbal_fov_deg': 30.})
        wide_point = CaptureSearchAgent.project_box(wide, own, 200., self.frame)
        narrow_point = CaptureSearchAgent.project_box(zoomed, narrow_own, 200., self.frame)
        self.assertIsNotNone(wide_point)
        self.assertIsNotNone(narrow_point)
        self.assertLess(math.dist(wide_point, narrow_point), 1e-7)
        wide_area = CaptureSearchAgent.ground_box_area(wide, own, 200.)
        narrow_area = CaptureSearchAgent.ground_box_area(zoomed, narrow_own, 200.)
        self.assertGreater(wide_area, 0.)
        self.assertAlmostEqual(narrow_area / wide_area, 1., places=7)
        self.assertGreater(zoomed.x2-zoomed.x1, 1.7*(wide.x2-wide.x1))

    def test_motion_plane_rejects_transition_pair_then_accepts_equal_fov_pair_for_matching(self):
        geometry = MotionPlane()
        encoded, image = cv2.imencode('.png', np.zeros((96, 128), np.uint8))
        self.assertTrue(encoded)
        photo = image.tobytes()
        geometry.update(photo, self.own(fov=50.), 1., 'wide')
        with patch('zqhj_visual_geometry.cv2.goodFeaturesToTrack', return_value=None) as features:
            geometry.update(photo, self.own(xy=(0., -309.), fov=30.), 1.5, 'transition')
            self.assertEqual(geometry.status, 'PAIR_GAP')
            self.assertIsNone(geometry.homography)
            features.assert_not_called()
            geometry.update(photo, self.own(xy=(0., -298.), fov=30.), 2., 'narrow')
            features.assert_called_once()
            self.assertEqual(geometry.status, 'TEXTURE_LOW')
            # Equal FOV allows an image-pair attempt; blank test images cannot
            # establish geometry, so no valid plane is claimed here.
            self.assertEqual(len(geometry.fits), 0)


if __name__ == '__main__':
    unittest.main()
