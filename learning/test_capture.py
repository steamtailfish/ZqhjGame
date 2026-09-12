"""Public-message tests of recruitment, own visual confirmation and loss handling."""
from pathlib import Path
import sys,unittest
from dataclasses import replace
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parents[2])]
from zqhj_capture import (CaptureCoordinator,CaptureSight,CaptureSearchAgent,
                         SEARCH,VERIFY,OFFER,APPROACH,TRACK,RECOVER,RELEASE)
from zqhj_comm import Packet,encode,decode
from zqhj_state import LocalFrame
from zqhj_vision import PixelBox
from zqhj_visual_geometry import GeoEstimate
from zqhj_score_search import ScoreSearchAgent
from competition.sdk.core.observation import AreaSpec,Detection,MissionBriefing,Observation,ScoreView,SelfView


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.frame=LocalFrame(37.,121.)
        self.positions={'alpha':(0.,-320.),'bravo':(0.,2400.),'charlie':(0.,360.)}

    def own(self,uid):
        lat,lon=self.frame.geo(*self.positions[uid])
        return SimpleNamespace(uid=uid,lat=lat,lon=lon,heading_deg=90.,speed=22.,alt=500.,
                               gimbal_pan=0.,gimbal_tilt=-80.,gimbal_fov_deg=50.)

    def message(self,c,now,sight=None):
        own=self.own(c.uid);m=c.mission
        target=m.target if m else (0.,0.);sample=m.sample if m else now
        if c.visible and sight:target=sight.target;sample=sight.sample
        lat,lon=self.frame.geo(*target)
        return decode(encode(Packet(round(now*10),now,own.lat,own.lon,own.heading_deg,22.,
            track_id=m.number if m else 0,target_lat=lat,target_lon=lon,age_s=max(0.,now-sample),
            hits=3 if m else 0,ground_m=200.,identity='true_vehicle' if m else 'unknown',capture=True,
            owner_slot=c.slot(m.owner) if m else 0,partner_slot=c.slot(m.partner) if m else 0,
            stage=c.phase,visible=c.visible)))

    def initial_peers(self):
        return {uid: self.message(CaptureCoordinator(uid),0.) for uid in ('bravo','charlie')}

    def sight(self,now,confirmed=True,visible=True,target=(0.,0.)):
        return CaptureSight(target,(0.,0.),200.,now,80.,confirmed,visible)

    def test_packet_49_bytes_and_checked_fields(self):
        p=Packet(1,599.9,37.,121.,359.9,40.,capture=True,owner_slot=3,partner_slot=2,
                 stage=TRACK,visible=True,target_vx=-24.5,target_vy=25.)
        payload=encode(p);self.assertEqual(len(payload.encode('utf-8')),49)
        self.assertEqual(decode(payload),p)
        with self.assertRaises(ValueError):encode(replace(p,stage=7))
        self.assertIsNone(decode(payload[:-1]))

    def test_unconfirmed_pixel_hold_does_not_recruit(self):
        c=CaptureCoordinator('alpha')
        assignment=c.step(self.own('alpha'),self.initial_peers(),self.frame,0.,self.sight(0.,False))
        self.assertEqual(c.phase,VERIFY);self.assertIsNone(c.mission)
        self.assertEqual(assignment.role,'SEARCH')

    def test_nearest_feasible_partner_not_lowest_uid(self):
        c=CaptureCoordinator('alpha')
        c.step(self.own('alpha'),self.initial_peers(),self.frame,0.,self.sight(0.))
        self.assertEqual(c.mission.partner,'charlie');self.assertEqual(c.phase,OFFER)
        self.assertEqual(c.joint_s,0.)

    def test_unconfirmed_visual_hold_has_deadline(self):
        c=CaptureCoordinator('alpha')
        for now in (0.,4.,8.5):
            c.step(self.own('alpha'),{},self.frame,now,self.sight(now,False))
        self.assertEqual(c.phase,SEARCH);self.assertIsNone(c.mission)

    def test_join_budget_accounts_for_distance(self):
        self.positions['charlie']=(0.,4000.)
        c=CaptureCoordinator('alpha')
        c.step(self.own('alpha'),self.initial_peers(),self.frame,0.,self.sight(0.))
        self.assertGreater(c.mission.deadline,90.)

    def test_unacknowledged_partner_is_reassigned(self):
        c=CaptureCoordinator('alpha');peers=self.initial_peers()
        c.step(self.own('alpha'),peers,self.frame,0.,self.sight(0.))
        peers={uid:replace(p,time_s=9.) for uid,p in peers.items()}
        c.step(self.own('alpha'),peers,self.frame,9.,self.sight(9.))
        self.assertEqual(c.mission.partner,'bravo')

    def simulate(self,seconds,partner_seen=lambda t:t>=5.,all_confirm=False):
        agents={uid:CaptureCoordinator(uid) for uid in self.positions}
        packets={uid:self.message(c,0.) for uid,c in agents.items()};history=[]
        for i in range(round(seconds*2)+1):
            now=i*.5;next_packets={}
            for uid,c in agents.items():
                sight=(self.sight(now) if uid=='alpha' or all_confirm else
                       self.sight(now,False) if uid=='charlie' and partner_seen(now) else None)
                c.step(self.own(uid),{u:p for u,p in packets.items() if u!=uid},self.frame,now,sight)
                next_packets[uid]=self.message(c,now,sight)
            packets=next_packets
            history.append((now,agents['alpha'].joint_s,agents['alpha'].phase))
        return agents,history

    def test_arrival_ack_without_own_view_never_counts(self):
        agents,history=self.simulate(20.,lambda t:False)
        self.assertTrue(agents['alpha'].ack)
        self.assertEqual(agents['alpha'].joint_s,0.)
        self.assertEqual(agents['charlie'].phase,APPROACH)
        self.assertEqual(agents['bravo'].phase,SEARCH)

    def test_unconfirmed_identity_keeps_search_flight(self):
        obs=Observation(SelfView('alpha',37.,121.,500.,0.,35.,0.,-80.,50.,Detection(False,0.)),(),
            MissionBriefing('alpha',3,AreaSpec(36.98,37.02,120.98,121.02),
                            score_view=ScoreView(1.2,(),False,0,3,1.)))
        agents=[ScoreSearchAgent('alpha'),CaptureSearchAgent('alpha')]
        try:
            controls=[]
            for a in agents:
                a.reset();a.pixel_target=PixelBox(500,370,520,390,.99,1024,768,'true_vehicle',.95)
                a.pixel_hits=3;a.pixel_identity_hits=3;a.photo_time=1.;a.photo_digest='unverified'
                commands=a.decide(obs,.1)
                controls.append([(c.verb,c.params) for c in commands if not c.verb.startswith('comm.')])
            self.assertEqual(agents[1].capture.phase,VERIFY)
            self.assertIsNone(agents[1].capture.mission)
            self.assertEqual(controls[0],controls[1])
        finally:
            for a in agents:a.close_detector()

    def test_own_visual_confirmation_starts_pair_not_travel_time(self):
        agents,history=self.simulate(15.)
        self.assertTrue(all(joint==0 for t,joint,_ in history if t<5.))
        self.assertGreater(agents['alpha'].joint_s,8.)
        self.assertLess(agents['alpha'].joint_s,11.)
        self.assertEqual(agents['bravo'].phase,SEARCH)

    def test_long_visual_gap_resets_timer(self):
        agents,history=self.simulate(15.,lambda t:5.<=t<10.)
        self.assertEqual(agents['alpha'].joint_s,0.)
        self.assertEqual(agents['alpha'].phase,RECOVER)

    def test_camera_verification_hold_is_bounded_and_ends_on_geometry(self):
        a=CaptureSearchAgent('alpha');a.reset();a.frame=self.frame
        own=self.own('alpha')
        try:
            a.pixel_target=PixelBox(700,600,720,620,.99,1024,768,'true_vehicle',.95)
            a.pixel_hits=3;a.pixel_track_id=1;a.pixel_identity_hits=3
            a.photo_time=1.;a.motion_verified_until=8.;a.fast_geo_hits=1
            self.assertEqual(a.aim_gimbal(own,1.,0.,-80.),(own.gimbal_pan,own.gimbal_tilt))
            a.fast_geo_hits=2
            self.assertNotEqual(a.aim_gimbal(own,1.2,0.,-80.),(own.gimbal_pan,own.gimbal_tilt))
            a.fast_geo_hits=0;a.photo_time=2.6
            self.assertNotEqual(a.aim_gimbal(own,2.6,0.,-80.),(own.gimbal_pan,own.gimbal_tilt))
        finally:a.close_detector()

    def test_completed_local_window_releases_without_claiming_judge(self):
        agents,history=self.simulate(34.)
        self.assertGreaterEqual(agents['alpha'].max_joint_s,25.)
        self.assertTrue(any(phase==RELEASE for _,_,phase in history))
        self.assertEqual(agents['alpha'].phase,SEARCH)
        self.assertIsNone(agents['alpha'].mission)

    def test_simultaneous_discoveries_converge(self):
        agents,_=self.simulate(8.,all_confirm=True)
        self.assertEqual({a.mission.owner for a in agents.values()},{'alpha'})
        self.assertEqual(agents['bravo'].phase,SEARCH)

    def test_expired_broadcast_cannot_authorize_pair(self):
        c=CaptureCoordinator('alpha');peers=self.initial_peers()
        c.step(self.own('alpha'),peers,self.frame,0.,self.sight(0.))
        p=replace(peers['charlie'],owner_slot=1,partner_slot=3,stage=TRACK,visible=True,
                  track_id=c.mission.number,identity='true_vehicle',age_s=0.)
        for t in (2.,2.5,3.):c.step(self.own('alpha'),{'charlie':p},self.frame,t,self.sight(t))
        self.assertEqual(c.joint_s,0.)

    def test_visual_confirmation_requires_same_target_and_pixel_lineage(self):
        a=CaptureSearchAgent('alpha');a.reset();a.frame=self.frame
        try:
            a.capture.step(self.own('alpha'),self.initial_peers(),self.frame,0.,self.sight(0.))
            a.pixel_target=PixelBox(500,370,520,390,.99,1024,768,'true_vehicle',.95)
            a.pixel_hits=4;a.pixel_identity_hits=3;a.pixel_track_id=1;a.motion_verified_until=8.
            a.photo_time=1.;a.photo_digest='one';a.fast_geo_hits=2
            a.geo_estimate=GeoEstimate(*self.frame.geo(0.,0.),80.,200.,1.,'one',1.)
            self.assertTrue(a.sight(self.own('alpha'),self.frame,1.).visible)
            a.pixel_track_id=2;a.pixel_identity_hits=1;a.geo_estimate=None
            self.assertFalse(a.sight(self.own('alpha'),self.frame,1.).visible)
            a.pixel_identity_hits=3
            a.geo_estimate=GeoEstimate(*self.frame.geo(900.,900.),80.,200.,1.,'one',1.)
            self.assertFalse(a.sight(self.own('alpha'),self.frame,1.).visible)
        finally:a.close_detector()


if __name__=='__main__':unittest.main()
