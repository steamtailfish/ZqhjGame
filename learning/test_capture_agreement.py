"""Independent owner/partner evidence and navigation authority regressions.

Radio cases pass through the real bounded codec. Synthetic positions exercise
association contracts only; they are not evidence of official capture success.
"""
from dataclasses import replace
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
    CaptureCoordinator, CaptureMission, CaptureSearchAgent, CaptureSight,
    SEARCH, APPROACH, TRACK, RELEASE,
)
from zqhj_comm import Packet, decode, encode
from zqhj_state import LocalFrame


class CaptureAgreementTests(unittest.TestCase):
    def setUp(self):
        self.frame = LocalFrame(37., 121.)
        self.positions = {'alpha': (0., -320.), 'bravo': (1000., 1000.),
                          'charlie': (0., 360.)}

    def own(self, uid):
        lat, lon = self.frame.geo(*self.positions[uid])
        return SimpleNamespace(uid=uid, lat=lat, lon=lon, alt=500., heading_deg=0.,
                               speed=22., gimbal_pan=0., gimbal_tilt=-45.,
                               gimbal_fov_deg=30.)

    def coordinator(self, uid, velocity=(0., 0.)):
        coordinator = CaptureCoordinator(uid)
        coordinator.roster = ('alpha', 'bravo', 'charlie')
        coordinator.adopt(CaptureMission('alpha', 7, 'charlie', (0., 0.),
            velocity, 200., 1., 1., 160., 1.), 1.)
        coordinator.phase = APPROACH
        return coordinator

    def sight(self, sample, point=(0., 0.), velocity=(0., 0.), visible=True):
        return CaptureSight(point, velocity, 200., sample, 80., True, visible)

    def packet(self, uid, now, sample=None, point=(0., 0.), velocity=(0., 0.),
               visible=True, mission=7):
        sample = now if sample is None else sample
        own = self.own(uid)
        lat, lon = self.frame.geo(*point)
        packet = Packet(round(now * 100), now, own.lat, own.lon, own.heading_deg,
            own.speed, track_id=mission, target_lat=lat, target_lon=lon,
            age_s=max(0., now-sample), hits=4, sigma_m=80., ground_m=200.,
            identity='true_vehicle', capture=True, owner_slot=1, partner_slot=3,
            stage=APPROACH, visible=visible, target_vx=velocity[0], target_vy=velocity[1])
        return decode(encode(packet))

    def assert_origin(self, point):
        self.assertLess(math.dist(point, (0., 0.)), .03)

    def test_wrong_partner_points_cannot_move_owner_center_or_accumulate_joint_time(self):
        for separation in (35., 50.):
            owner = self.coordinator('alpha')
            for now in (1.5, 2., 2.5):
                wrong = self.packet('charlie', now, point=(separation, 0.))
                owner.step(self.own('alpha'), {'charlie': wrong}, self.frame, now,
                           self.sight(now))
                self.assert_origin(owner.mission.target)
                self.assert_origin(owner.owner_fix.target)
                self.assertTrue(owner.visible)
                self.assertTrue(owner.ack)
                self.assertFalse(owner.pair_consistent)
                self.assertGreater(owner.pair_residual, 34.)
                self.assertEqual(owner.joint_s, 0.)
                self.assertEqual(owner.pair_frames, 0)
            # Even fresh partner images cannot extend the missing owner's lease.
            seen = owner.mission.last_seen
            owner.step(self.own('alpha'), {'charlie': self.packet('charlie', 11.,
                point=(separation, 0.))}, self.frame, 11., None)
            self.assertEqual(owner.mission.last_seen, seen)
            self.assertEqual(owner.phase, RELEASE)
            self.assertEqual(owner.reason, 'visual_recovery_timeout')

    def test_wrong_local_partner_track_is_not_visible_and_cannot_move_its_mission(self):
        for separation in (35., 50.):
            partner = self.coordinator('charlie')
            for now in (1.5, 2., 2.5):
                partner.step(self.own('charlie'), {'alpha': self.packet('alpha', now)},
                    self.frame, now, self.sight(now, (separation, 0.)))
                self.assert_origin(partner.mission.target)
                self.assert_origin(partner.owner_fix.target)
                self.assertFalse(partner.visible)
                self.assertFalse(partner.pair_consistent)
                self.assertEqual(partner.joint_s, 0.)
                self.assertEqual(partner.pair_frames, 0)

    def test_nonvisible_owner_echo_cannot_become_an_independent_anchor(self):
        partner = self.coordinator('charlie')
        for now in (1.5, 2., 2.5):
            echo = self.packet('alpha', now, point=(40., 0.), visible=False)
            partner.step(self.own('charlie'), {'alpha': echo}, self.frame, now,
                         self.sight(now, (40., 0.)))
            # Navigation can consume an owner's update, but that is not a new
            # owner sighting and cannot validate a partner seeing the echo point.
            self.assertLess(math.dist(partner.mission.target, (40., 0.)), .03)
            self.assertIsNone(partner.owner_fix)
            self.assertIsNone(partner.owner_reference(now))
            self.assertFalse(partner.visible)
            self.assertEqual(partner.joint_s, 0.)
            self.assertEqual(partner.mission.last_seen, 1.)

    def test_repeated_quantized_owner_sample_does_not_renew_fix_or_recovery_lease(self):
        partner = self.coordinator('charlie')
        original_fix = None
        reconstructed_samples = []
        for now in (1., 1.06, 1.19, 1.27, 1.38, 1.49, 1.62, 1.75, 1.87, 2., 9.1):
            repeated = self.packet('alpha', now, sample=1.)
            reconstructed_samples.append(repeated.time_s-repeated.age_s)
            partner.step(self.own('charlie'), {'alpha': repeated}, self.frame, now,
                         self.sight(now))
            if original_fix is None:
                original_fix = partner.owner_fix
            self.assertIs(partner.owner_fix, original_fix)
            self.assertEqual(partner.mission.last_seen, 1.)
            if now > 1.8:
                self.assertIsNone(partner.owner_reference(now))
                self.assertFalse(partner.visible)
        self.assertLessEqual(max(reconstructed_samples)-min(reconstructed_samples), .11)
        self.assertEqual(partner.phase, RELEASE)
        self.assertEqual(partner.reason, 'visual_recovery_timeout')

    def test_async_moving_sightings_align_before_comparison_and_can_accumulate(self):
        partner = self.coordinator('charlie', velocity=(25., 0.))
        for now in (1.5, 2., 2.5, 3.):
            sample = now-.5
            owner_point = (25.*(sample-1.), 0.)
            # Same moving trajectory with a constant 15 m measurement offset.
            # Raw positions differ by 27.5 m; after aligning source times the
            # independent residual is 15 m and falls inside the 25 m gate.
            local_point = (25.*(now-1.)+15., 0.)
            owner = self.packet('alpha', now, sample=sample,
                                point=owner_point, velocity=(25., 0.))
            partner.step(self.own('charlie'), {'alpha': owner}, self.frame, now,
                         self.sight(now, local_point, (25., 0.)))
            self.assertGreater(math.dist(owner_point, local_point), 25.)
            self.assertAlmostEqual(partner.pair_residual, 15., delta=.06)
            self.assertTrue(partner.visible)
            self.assertTrue(partner.pair_consistent)
            self.assertEqual(partner.phase, TRACK)
            self.assertLess(math.dist(partner.mission.target, owner_point), .06)
        self.assertAlmostEqual(partner.joint_s, 1.5)
        self.assertEqual(partner.pair_frames, 4)

    def test_raw_nearby_points_are_rejected_if_time_aligned_tracks_disagree(self):
        partner = self.coordinator('charlie', velocity=(-25., 0.))
        owner = self.packet('alpha', 1.7, sample=1., velocity=(-25., 0.))
        partner.step(self.own('charlie'), {'alpha': owner}, self.frame, 1.7,
                     self.sight(1.7, (12., 0.), (-25., 0.)))
        self.assertAlmostEqual(partner.pair_residual, 29.5, delta=.03)
        self.assertFalse(partner.visible)
        self.assertFalse(partner.pair_consistent)
        self.assertEqual(partner.joint_s, 0.)

    def test_third_aircraft_and_third_sender_cannot_claim_pair_membership(self):
        third = self.coordinator('bravo')
        peers = {uid: self.packet(uid, 1.5) for uid in ('alpha', 'charlie')}
        third.step(self.own('bravo'), peers, self.frame, 1.5, self.sight(1.5))
        self.assertEqual(third.phase, SEARCH)
        self.assertFalse(third.visible)
        self.assertEqual(third.joint_s, 0.)
        partner = self.coordinator('charlie')
        spoof = self.packet('bravo', 1.5)  # Same fields, SDK sender is not owner.
        partner.step(self.own('charlie'), {'bravo': spoof}, self.frame, 1.5,
                     self.sight(1.5))
        self.assertIsNone(partner.owner_fix)
        self.assertFalse(partner.visible)
        self.assertEqual(partner.joint_s, 0.)

    def test_old_mission_stale_owner_and_future_packet_cannot_supply_anchor(self):
        invalid = (
            self.packet('alpha', 2., mission=6),
            self.packet('alpha', 2., sample=1.),
            self.packet('alpha', 2.1, sample=2.1),
        )
        for owner in invalid:
            partner = self.coordinator('charlie')
            partner.step(self.own('charlie'), {'alpha': owner}, self.frame, 2.,
                         self.sight(2.))
            self.assertEqual(partner.mission.key, ('alpha', 7))
            self.assertIsNone(partner.owner_fix)
            self.assertFalse(partner.visible)
            self.assertEqual(partner.joint_s, 0.)
            self.assertEqual(partner.mission.last_seen, 1.)

    def test_stale_or_future_local_sighting_cannot_match_a_fresh_owner(self):
        for sample in (1., 2.1):
            partner = self.coordinator('charlie')
            partner.step(self.own('charlie'), {'alpha': self.packet('alpha', 2.)},
                         self.frame, 2., self.sight(sample))
            self.assertIsNotNone(partner.owner_reference(2.))
            self.assertFalse(partner.visible)
            self.assertFalse(partner.pair_consistent)
            self.assertEqual(partner.joint_s, 0.)

    def test_adopting_new_mission_clears_the_previous_owner_reference(self):
        partner = self.coordinator('charlie')
        partner.step(self.own('charlie'), {'alpha': self.packet('alpha', 1.5)},
                     self.frame, 1.5, self.sight(1.5))
        self.assertTrue(partner.visible)
        partner.adopt(replace(partner.mission, number=8), 1.6)
        self.assertIsNone(partner.owner_fix)
        self.assertIsNone(partner.owner_reference(1.6))
        partner.step(self.own('charlie'), {'alpha': self.packet('alpha', 2., mission=7)},
                     self.frame, 2., self.sight(2.))
        self.assertFalse(partner.visible)
        self.assertEqual(partner.joint_s, 0.)

    def test_sdk_broadcast_uses_owner_center_when_local_partner_sighting_disagrees(self):
        agent = CaptureSearchAgent('charlie')
        agent.detector = lambda photo: []
        agent.reset()
        agent.frame = self.frame
        agent.capture = self.coordinator('charlie')
        agent.enable_reports = True
        self.addCleanup(agent.close_detector)
        for now in (1.5, 2.):
            own = self.own('charlie')
            message = Message('alpha', encode(self.packet('alpha', now)), now)
            observation = Observation(SelfView('charlie', own.lat, own.lon, own.alt,
                own.heading_deg, own.speed, own.gimbal_pan, own.gimbal_tilt,
                own.gimbal_fov_deg, Detection(False, 0.)), (message,),
                MissionBriefing('charlie', 3, AreaSpec(36.98, 37.02, 120.98, 121.02),
                    score_view=ScoreView(total_score=0., dimension_scores=(), passed=False,
                        n_destroyed=0, n_targets=3, sim_time=now)))
            wrong_sight = self.sight(now, (45., 0.))
            with patch.object(agent, 'sight', return_value=wrong_sight):
                commands = agent.decide(observation, .1)
            outgoing = decode(next(c.params['payload'] for c in commands
                                   if c.verb == 'comm.broadcast'))
            self.assertIs(agent.capture_sight, wrong_sight)
            self.assertFalse(outgoing.visible)
            self.assert_origin(self.frame.xy(outgoing.target_lat, outgoing.target_lon))
            self.assert_origin(agent.capture.mission.target)
            self.assertFalse(agent.diagnostics['capture']['own_visual'])
            self.assertFalse(agent.diagnostics['capture']['pair_consistent'])
            self.assertFalse(any(c.verb == 'agent.report' for c in commands))


if __name__ == '__main__':
    unittest.main()
