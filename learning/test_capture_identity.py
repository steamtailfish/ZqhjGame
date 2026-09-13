"""Identity memory regressions with raw detector outputs and public Agent inputs."""
from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'),
               str(Path(__file__).resolve().parents[2])]
from zqhj_capture import CaptureIdentity, CaptureMission, CaptureSearchAgent, APPROACH
from zqhj_photo_entry import PhotoEntryAgent
from zqhj_state import LocalFrame
from zqhj_vision import PixelBox
from zqhj_visual_geometry import GeoEstimate
from competition.sdk.core.observation import (
    AreaSpec, Detection, MissionBriefing, Observation, ScoreView, SelfView)


TRUE = PixelBox(504, 377, 519, 390, .99, 1024, 768, 'true_vehicle', .98)
DECOY = replace(TRUE, category='decoy_vehicle', confidence=.997, class_margin=.99)
WEAK = replace(TRUE, confidence=.65, class_margin=.30)


class CaptureIdentityMemoryTests(unittest.TestCase):
    def memory(self):
        return CaptureIdentity(('alpha', 1), (0., 0.), (8., 0.), 30., 1., 1., 'initial')

    def test_single_contradiction_preserves_raw_class_and_local_memory(self):
        memory = self.memory()
        self.assertTrue(memory.observe(DECOY, (4., 0.), 30., 1.5, 'decoy-1'))
        self.assertEqual(DECOY.category, 'decoy_vehicle')
        self.assertEqual(DECOY.confidence, .997)
        self.assertEqual(memory.last_true, 1.)
        self.assertEqual(memory.decoy_hits, 1)

    def test_repeated_digest_does_not_accumulate_evidence_or_velocity(self):
        memory = self.memory()
        memory.observe(DECOY, (4., 0.), 30., 1.5, 'same-photo')
        before = replace(memory)
        for now in (1.55, 1.65, 1.75):
            self.assertTrue(memory.observe(DECOY, (4., 0.), 30., now, 'same-photo'))
        self.assertEqual(memory, before)

    def test_three_contradictions_need_the_temporal_window(self):
        memory = self.memory()
        for now in (1.2, 1.4, 1.6):
            self.assertTrue(memory.observe(DECOY, (8*(now-1), 0.), 30., now, str(now)))
        self.assertFalse(memory.revoked)
        self.assertFalse(memory.observe(DECOY, (9.6, 0.), 30., 2.2, 'later'))
        self.assertTrue(memory.revoked)
        self.assertFalse(memory.observe(TRUE, (10., 0.), 30., 2.3, 'positive-after-revoke'))

    def test_fresh_weak_matches_do_not_extend_three_second_identity_budget(self):
        memory = self.memory()
        for now in (1.5, 2., 2.5, 3., 3.5, 4.):
            self.assertTrue(memory.observe(WEAK, (8*(now-1), 0.), 30., now, str(now)))
        self.assertEqual(memory.last_true, 1.)
        self.assertFalse(memory.fresh(4.01))
        self.assertFalse(memory.observe(WEAK, (24.08, 0.), 30., 4.01, 'expired'))

    def test_missing_samples_expire_even_before_identity_budget(self):
        memory = self.memory()
        self.assertTrue(memory.fresh(3.))
        self.assertFalse(memory.fresh(3.01))
        self.assertFalse(memory.matches((16.08, 0.), 30., 3.01))

    def test_position_and_projected_area_reject_an_unrelated_candidate(self):
        memory = self.memory()
        self.assertTrue(memory.matches((4., 0.), 30., 1.5))
        self.assertFalse(memory.matches((65., 0.), 30., 1.5))
        self.assertFalse(memory.matches((4., 0.), 9., 1.5))
        self.assertFalse(memory.matches((4., 0.), 90., 1.5))


class CaptureIdentityAgentTests(unittest.TestCase):
    def setUp(self):
        self.frame = LocalFrame(37., 121.)

    def observation(self, uid, now, photo=b'photo'):
        own = SelfView(uid, 37., 121., 500., 0., 22., 0., -90., 50.,
                       Detection(False, 0.), photo=photo)
        return Observation(own, (), MissionBriefing(uid, 3,
            AreaSpec(36.98, 37.02, 120.98, 121.02),
            score_view=ScoreView(total_score=0., dimension_scores=(), passed=False,
                                 n_destroyed=0, n_targets=3, sim_time=now)))

    def agent(self, uid='alpha', bind=True):
        a = CaptureSearchAgent(uid)
        a.reset(); a.frame = self.frame; a.enable_reports = True
        self.addCleanup(a.close_detector)
        own = self.observation(uid, 1.).self
        target = a.project_box(TRUE, own, 200., self.frame)
        a.capture.adopt(CaptureMission('alpha', 1, 'charlie', target, (0., 0.),
                                      200., 1., 1., 100., 1.), 1.)
        a.capture.phase = APPROACH
        a.capture.roster = ('alpha', 'bravo', 'charlie')
        if bind:
            a.photo_time = a.sensor_time = a.sensor_clock = 1.
            a.photo_digest = hashlib.sha256(b'initial').hexdigest()
            a.pixel_target = TRUE; a.pixel_hits = 4; a.pixel_identity_hits = 3
            a.pixel_track_id = 1; a.motion_verified_until = 8.
            a.pixel_pose = (0., -90., 0., 50.); a.pixel_own = own
            a.fast_geo_hits = 2
            a.geo_estimate = GeoEstimate(*self.frame.geo(*target), 80., 200., 1.,
                                        a.photo_digest, 1.)
            self.assertTrue(a.sight(own, self.frame, 1.).visible)
            self.assertIsNotNone(a.capture_identity)
        return a

    def feed(self, a, now, boxes, photo=None, decide=True):
        obs = self.observation(a.my_uid, now, str(now).encode() if photo is None else photo)
        a.detector = lambda raw: boxes
        # Exercise the real parent sensor's raw classification, association and
        # counters, without starting an asynchronous model or requiring a PNG.
        PhotoEntryAgent.sensor(a, obs, .5)
        commands = a.decide(obs, .5) if decide else []
        return obs, commands

    def test_raw_decoy_frame_keeps_bound_track_without_rewriting_detection(self):
        a = self.agent()
        _, commands = self.feed(a, 1.5, [DECOY])
        self.assertIs(a.pixel_target, DECOY)
        self.assertIs(a.boxes[0], DECOY)
        self.assertEqual(a.pixel_identity_hits, 0)
        self.assertTrue(a.capture.visible)
        self.assertEqual(a.capture_identity_state, 'remembered_true')
        self.assertFalse(any(c.verb == 'agent.report' for c in commands))

    def test_third_decoy_frame_revokes_identity_and_clears_previous_binding(self):
        a = self.agent()
        for now in (1.5, 2.):
            self.feed(a, now, [DECOY])
            self.assertTrue(a.capture.visible)
        self.feed(a, 2.5, [DECOY])
        self.assertTrue(a.capture_identity.revoked)
        self.assertIsNone(a.capture_bound)
        self.assertFalse(a.capture.visible)
        self.assertEqual(a.capture_identity_state, 'identity_revoked')
        # A later raw positive frame must rebuild evidence after revocation.
        self.feed(a, 3., [TRUE])
        self.assertFalse(a.capture.visible)
        self.assertIsNone(a.capture_bound)

    def test_absent_photo_never_produces_visual_from_memory(self):
        a = self.agent()
        self.feed(a, 1.5, [DECOY])
        self.assertTrue(a.capture.visible)
        self.feed(a, 2., [], photo=b'')
        self.assertIsNotNone(a.capture_identity)
        self.assertIsNone(a.pixel_target)
        self.assertFalse(a.capture.visible)
        self.assertEqual(a.capture.joint_s, 0.)

    def test_stale_photo_cannot_become_visible_from_an_old_binding(self):
        a = self.agent()
        self.assertIsNone(a.sight(self.observation('alpha', 1.81).self, self.frame, 1.81))
        a.decide(self.observation('alpha', 1.81), .5)
        self.assertFalse(a.capture.visible)

    def test_current_control_time_expiry_cannot_reuse_old_binding(self):
        a = self.agent()
        # Inference may finish after the source receipt was still inside the
        # memory window. A weak current positive is not a new confirmation.
        a.capture_identity.sample = 3.
        a.capture_identity.digest = 'older'
        a.photo_digest = 'late-result'; a.photo_time = 3.9
        weak_positive = replace(TRUE, confidence=.92, class_margin=.84)
        selected = a.filter_boxes([weak_positive], self.observation('alpha', 3.9).self, 3.9)
        self.assertEqual(selected, [weak_positive])
        a.pixel_target = weak_positive; a.pixel_identity_hits = 0
        sight = a.sight(self.observation('alpha', 4.2).self, self.frame, 4.2)
        self.assertTrue(sight is None or not sight.visible)
        self.assertIsNone(a.capture_bound)

    def test_unbound_partner_cannot_inherit_owner_identity_from_decoy(self):
        a = self.agent(uid='charlie', bind=False)
        self.feed(a, 1.5, [DECOY])
        self.assertIsNone(a.pixel_target)
        self.assertIsNone(a.capture_identity)
        self.assertIsNone(a.capture_bound)
        self.assertTrue(a.capture.ack)
        self.assertFalse(a.capture.visible)

    def test_far_background_is_not_selected_despite_high_true_probability(self):
        a = self.agent()
        distant = replace(TRUE, x1=704, x2=719, confidence=.999)
        point = a.project_box(distant, self.observation('alpha', 1.5).self, 200., self.frame)
        self.assertGreater(abs(point[0]-a.capture_identity.point[0]), 50.)
        self.feed(a, 1.5, [distant])
        self.assertIsNone(a.pixel_target)
        self.assertFalse(a.capture.visible)

    def test_associated_track_keeps_motion_when_pixel_lineage_restarts(self):
        a = self.agent()
        a.capture_identity.velocity = (8., 2.)
        a.pixel_track_id += 1
        moved = replace(DECOY, x1=519, x2=534, y1=373, y2=386)
        self.feed(a, 1.5, [moved])
        self.assertTrue(a.capture.visible)
        self.assertEqual(a.capture_bound, (a.capture.mission.key, a.pixel_track_id))
        self.assertGreater(a.capture_sight.velocity[0], 7.5)
        self.assertGreater(a.capture_sight.velocity[1], 1.5)

    def test_two_nearby_plausible_objects_revoke_inherited_identity(self):
        a = self.agent()
        left = replace(TRUE, x1=460, x2=475)
        right = replace(TRUE, x1=548, x2=563)
        self.feed(a, 1.5, [left, right])
        self.assertTrue(a.capture_identity.revoked)
        self.assertIsNone(a.capture_bound)
        self.assertIsNone(a.pixel_target)
        self.assertFalse(a.capture.visible)

    def test_strong_positive_recovers_tracking_without_shortcutting_report_hits(self):
        a = self.agent()
        self.feed(a, 1.5, [DECOY])
        obs, _ = self.feed(a, 2., [TRUE], decide=False)
        # Supply every other fast-report prerequisite. Only one new strong
        # identity hit has arrived since the raw negative classification.
        g = GeoEstimate(*self.frame.geo(*a.capture.mission.target), 80., 200., 2.,
                        a.photo_digest, 1.)
        a.geo_estimate = a.fast_geo = g; a.fast_geo_hits = 2
        a.motion_hits = 2; a.pixel_ground_speed_mps = 7.
        self.assertEqual(a.pixel_identity_hits, 1)
        commands = a.decide(obs, .5)
        self.assertTrue(a.capture.visible)
        self.assertEqual(a.capture_identity_state, 'current_true')
        self.assertEqual(a.capture_identity.decoy_hits, 0)
        self.assertEqual(a.capture_identity.last_true, 2.)
        self.assertEqual(a.pixel_identity_hits, 1)
        self.assertFalse(any(c.verb == 'agent.report' for c in commands))


if __name__ == '__main__':
    unittest.main()
