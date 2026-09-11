from pathlib import Path
import sys,unittest
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_vision import frame
from zqhj_score_search import ScoreSearchAgent
from zqhj_state import LocalFrame,Track
from zqhj_visual_geometry import GeoEstimate
from zqhj_vision import PixelBox
from zqhj_photo_entry import PhotoEntryAgent
from types import SimpleNamespace
import numpy as np
from zqhj_comm import Packet,encode
from competition.sdk.core.observation import Message


class ScoreSearchTests(unittest.TestCase):
    def prepared(self,hits=4,confidence=.75,age=.2,uncertainty=90):
        a=ScoreSearchAgent('alpha');a.detector=lambda p:[];a.reset()
        a.enable_reports=True;a.enable_geometry=True;a.frame=LocalFrame(37.,121.)
        a.report_from_geo_bank=True
        now=10.;lat,lon=a.frame.geo(0.,100.)
        a.bank.tracks[1]=Track(1,0.,100.,0.,0.,now-age,7.,hits=5,
            source='own_rgb_motion_plane_estimate',identity='true_vehicle',identity_hits=hits,ground_m=150.)
        a.pixel_target=PixelBox(500,370,520,390,confidence,1024,768,'true_vehicle',.5)
        a.pixel_hits=5;a.photo_digest='p';a.photo_time=now-age
        a.geo_estimate=GeoEstimate(lat,lon,uncertainty,150.,now-age,'p',1.)
        a.motion_hits=2;a.motion_time=now-age
        peer=Packet(1,now,37.005,121.005,0.,22.)
        obs=replace(frame(now),comm_inbox=(Message('bravo',encode(peer),now),))
        return a,obs

    def test_verified_fresh_visual_track_can_report(self):
        a,obs=self.prepared()
        try:
            reports=[c for c in a.decide(obs,.1) if c.verb=='agent.report']
            self.assertEqual(len(reports),1)
            self.assertAlmostEqual(reports[0].params['lat'],a.geo_estimate.latitude)
        finally:a.close_detector()

    def test_weak_stale_or_uncertain_track_cannot_report(self):
        for kwargs in ({'hits':3},{'confidence':.6},{'age':1.},{'uncertainty':111}):
            a,obs=self.prepared(**kwargs)
            try:self.assertFalse(any(c.verb=='agent.report' for c in a.decide(obs,.1)))
            finally:a.close_detector()

    def test_local_report_is_not_blocked_by_another_pair_assignment(self):
        a,obs=self.prepared()
        peer=Packet(1,10.,37.005,121.005,0.,22.,track_id=1,
                    target_lat=37.01,target_lon=121.01,hits=5,identity='true_vehicle')
        obs=replace(obs,comm_inbox=(Message('0001',encode(peer),10.),
                    Message('0002',encode(replace(peer,track_id=0)),10.)))
        try:
            reports=[c for c in a.decide(obs,.1) if c.verb=='agent.report']
            self.assertEqual(a.diagnostics['state'],'SEARCH')
            self.assertEqual(len(reports),1)
            self.assertAlmostEqual(reports[0].params['lat'],a.geo_estimate.latitude)
        finally:a.close_detector()

    def test_static_background_evidence_blocks_report(self):
        a,obs=self.prepared();a.motion_hits=0
        try:self.assertFalse(any(c.verb=='agent.report' for c in a.decide(obs,.1)))
        finally:a.close_detector()

    def test_camera_hold_does_not_authorize_stale_motion_report(self):
        a,obs=self.prepared();a.motion_time=8.;a.motion_verified_until=16.
        try:self.assertFalse(any(c.verb=='agent.report' for c in a.decide(obs,.1)))
        finally:a.close_detector()

    def test_camera_recentering_is_bounded(self):
        a,obs=self.prepared();a.motion_verified_until=18.
        a.pixel_target=PixelBox(760,300,780,320,.99,1024,768,'true_vehicle',.9)
        a.pixel_pose=(0.,-80.,0.,50.)
        own=replace(obs.self,gimbal_pan=0.,gimbal_tilt=-80.,heading_deg=0.)
        try:
            pan,tilt=a.aim_gimbal(own,10.,0.,-80.)
            self.assertLessEqual(abs(pan),6.)
            self.assertLessEqual(abs(tilt+80.),3.)
            self.assertGreater(pan,0.)
        finally:a.close_detector()

    def test_precise_pixel_track_can_report_before_navigation_track_is_ready(self):
        a,obs=self.prepared();a.bank.tracks.clear();a.report_from_geo_bank=False
        a.fast_geo=a.geo_estimate;a.fast_geo_hits=2;a.pixel_identity_hits=4
        a.pixel_target=replace(a.pixel_target,confidence=.99,class_margin=.95);a.pixel_ground_speed_mps=7.
        try:
            reports=[c for c in a.decide(obs,.1) if c.verb=='agent.report']
            self.assertEqual(len(reports),1)
            self.assertIsNone(a.coordinator.local_id)
            self.assertAlmostEqual(reports[0].params['lat'],a.fast_geo.latitude)
            self.assertEqual(a.fast_report_count,1)
        finally:a.close_detector()

    def test_fast_report_requires_both_repeated_geometry_and_identity(self):
        for geo_hits,identity_hits,age in ((1,4,.2),(2,2,.2),(2,4,1.)):
            a,obs=self.prepared(age=age);a.bank.tracks.clear();a.report_from_geo_bank=False
            a.fast_geo=a.geo_estimate;a.fast_geo_hits=geo_hits;a.pixel_identity_hits=identity_hits
            a.pixel_target=replace(a.pixel_target,confidence=.99,class_margin=.95);a.pixel_ground_speed_mps=7.
            try:self.assertFalse(any(c.verb=='agent.report' for c in a.decide(obs,.1)))
            finally:a.close_detector()

    def test_image_translation_does_not_reset_an_existing_track(self):
        class ImageMotion:
            homography=None;pair_old_digest=None;status='POSE_CHANGING'
            digest=None
            def observe_pose(self,*args):pass
            def update(self,photo,own,now,digest):
                self.pair_old_digest=self.digest;self.digest=digest
                self.homography=np.array([[1.,0.,250.],[0.,1.,0.],[0.,0.,1.]]) if self.pair_old_digest else None
            def locate(self,*args):return None
        a=PhotoEntryAgent('alpha');a.reset();a.enable_geometry=True;a.geometry=ImageMotion()
        a.detector=lambda p:[PixelBox(90 if p==b'a' else 340,190,110 if p==b'a' else 360,210,.99,1024,768,'true_vehicle',.9)]
        for now,photo in ((10.,b'a'),(10.6,b'b')):
            obs=frame(now);a.sensor(replace(obs,self=replace(obs.self,photo=photo)),.1)
        self.assertEqual(a.pixel_hits,2)
        self.assertAlmostEqual(a.pixel_motion_px,0.)
        self.assertEqual(a.motion_hits,0)

    def test_search_uses_distinct_broadcast_discovered_strips(self):
        agents=[ScoreSearchAgent(u) for u in ('alpha','bravo','charlie')]
        try:
            goals=[]
            for a in agents:
                a.reset();a.radio.peers={u:None for u in ('alpha','bravo','charlie') if u!=a.my_uid}
                goals.append(a.search_goal((0,0),(-2000,2000,-2000,2000)))
            self.assertEqual(len(set(goals)),3)
        finally:
            for a in agents:a.close_detector()


if __name__=='__main__':unittest.main()
