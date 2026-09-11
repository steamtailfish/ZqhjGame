"""Synthetic formula/guard tests only; never evidence of real-world accuracy."""
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_localization import CandidatePixel, ObservationClock, pixel_ray, project_candidate


class ClockTests(unittest.TestCase):
    def test_missing_first_and_no_per_agent_rezero(self):
        c=ObservationClock()
        self.assertFalse(c.update(None,None,3)['accept_new_sample'])
        r=c.update(127.5,b'image',4)
        self.assertEqual(r['observation_sim_s'],127.5)
        self.assertIsNone(r['elapsed_sim_s'])
        self.assertIsNone(r['capture_sim_s'])
        self.assertEqual(r['receipt_first_seen_sim_s'],127.5)

    def test_duplicate_gap_rewind_reset(self):
        c=ObservationClock(max_gap_s=1)
        self.assertTrue(c.update(20,b'a',1)['accept_new_sample'])
        self.assertIn('duplicate_observation_time',c.update(20,b'b',2)['reasons'])
        self.assertIn('observation_time_gap',c.update(25,b'c',3)['reasons'])
        self.assertTrue(c.update(25.1,b'd',4)['accept_new_sample'])
        self.assertIn('time_rewound',c.update(2,b'e',5)['reasons'])
        c.reset()
        r=c.update(125,b'e',7)
        self.assertEqual(r['observation_sim_s'],125)
        self.assertIsNone(r['elapsed_sim_s'])
        self.assertEqual(r['receipt_first_seen_wall_s'],7)

    def test_receipt_is_first_seen_not_capture_or_latest_callback(self):
        c=ObservationClock()
        c.update(3,b'a',50)
        r=c.update(3.1,b'a',51)
        self.assertEqual(r['receipt_first_seen_wall_s'],50)
        self.assertIn('same_photo_bytes',r['reasons'])
        self.assertIsNone(r['capture_wall_s'])

    def test_instances_do_not_share_clock(self):
        a,b=ObservationClock(),ObservationClock()
        a.update(50,b'a',1)
        self.assertIsNone(b.update(50,b'a',2)['elapsed_sim_s'])


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.own=dict(uid='u',lat=27.,lon=125.,alt=500.,heading_deg=0.,
            gimbal_pan=0.,gimbal_tilt=-90.,gimbal_fov_deg=50.)
        self.time=dict(observation_sim_s=10,photo_sha256='hash',capture_sim_s=None,reasons=[])
        self.candidate=CandidatePixel('offline_manual_photo','synthetic test, not real photo',511.5,383.5,1024,768,'hash','u')
        self.options=dict(fov_axis='horizontal',yaw_convention='world_pan',ground_alt_m=100.,
            height_source='synthetic known plane',calibration_evidence='synthetic only',
            stable_pose=True,uncropped=True,offline=True)

    def project(self,**kw):return project_candidate(self.candidate,self.own,self.time,**(self.options|kw))

    def test_nadir_center_returns_own_lat_lon(self):
        r=self.project()
        self.assertTrue(r['position_valid'])
        self.assertFalse(r['online_usable'])
        self.assertAlmostEqual(r['latitude'],27)
        self.assertAlmostEqual(r['longitude'],125)
        self.assertAlmostEqual(r['slant_range_m'],400)

    def test_right_down_and_yaw_rotation(self):
        a=pixel_ray(700,500,1024,768,50,'horizontal',0,-90,0,'world_pan')
        b=pixel_ray(700,500,1024,768,50,'horizontal',90,-90,0,'world_pan')
        self.assertGreater(a[0],0);self.assertLess(a[1],0)
        self.assertAlmostEqual(b[0],a[1]);self.assertAlmostEqual(b[1],-a[0])

    def test_oblique_center_uses_actual_500_minus_ground(self):
        self.own['gimbal_tilt']=-45
        r=self.project()
        self.assertAlmostEqual(r['local_north_m'],400)
        self.assertAlmostEqual(r['local_east_m'],0)

    def test_online_refuses_offline_pixel_and_unknown_capture_pose(self):
        r=self.project(offline=False)
        self.assertFalse(r['position_valid'])
        self.assertIn('offline_annotation_forbidden_online',r['invalid_reasons'])
        self.assertIn('capture_pose_alignment_unverified',r['invalid_reasons'])

    def test_capture_timestamp_alone_does_not_validate_current_pose(self):
        self.candidate=CandidatePixel('online_photo_detector','synthetic source',511.5,383.5,1024,768,'hash','u')
        self.time.update(capture_sim_s=9,pose_sim_s=10,capture_pose_verified=True)
        self.assertIn('capture_pose_alignment_unverified',self.project(offline=False)['invalid_reasons'])

    def test_unknown_ground_and_intrinsics_refused(self):
        self.assertFalse(self.project(ground_alt_m=None)['position_valid'])
        self.assertFalse(self.project(fov_axis='unknown')['position_valid'])
        self.assertFalse(self.project(yaw_convention='unknown')['position_valid'])
        self.assertFalse(self.project(calibration_evidence='')['position_valid'])

    def test_wrong_uid_hash_crop_and_unstable(self):
        self.own['uid']='other'
        self.assertIn('candidate_uid_mismatch',self.project()['invalid_reasons'])
        self.own['uid']='u';self.time['photo_sha256']='wrong'
        self.assertIn('candidate_photo_mismatch',self.project()['invalid_reasons'])
        self.time['photo_sha256']='hash'
        self.assertFalse(self.project(uncropped=False)['position_valid'])
        self.assertFalse(self.project(stable_pose=False)['position_valid'])

    def test_horizon_upward_height_and_range(self):
        for angle in (0,30,90):
            self.own['gimbal_tilt']=angle
            self.assertFalse(self.project()['position_valid'])
        self.own['gimbal_tilt']=-45
        self.assertFalse(self.project(ground_alt_m=501)['position_valid'])
        self.assertFalse(self.project(max_range_m=10)['position_valid'])

    def test_nonfinite_and_outside_pixels(self):
        self.own['alt']=float('nan')
        self.assertFalse(self.project()['position_valid'])
        self.own['alt']=500
        self.candidate=CandidatePixel('offline_manual_photo','test',-1,300,1024,768,'hash','u')
        self.assertFalse(self.project()['position_valid'])


if __name__=='__main__':unittest.main(verbosity=2)
