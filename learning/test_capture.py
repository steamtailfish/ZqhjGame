"""Public-message tests of recruitment, own visual confirmation and loss handling."""
from pathlib import Path
import math,sys,unittest
from dataclasses import replace
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parents[2])]
from zqhj_capture import (CaptureCoordinator,CaptureMission,CaptureSight,CaptureSearchAgent,
                         SEARCH,VERIFY,OFFER,APPROACH,TRACK,RECOVER,RELEASE)
from zqhj_comm import Packet,encode,decode
from zqhj_state import LocalFrame
from zqhj_vision import PixelBox
from zqhj_visual_geometry import GeoEstimate
from zqhj_score_search import ScoreSearchAgent
from zqhj_localization import camera_basis
from competition.sdk.core.observation import AreaSpec,Detection,Message,MissionBriefing,Observation,ScoreView,SelfView


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

    def camera_agent(self,uid='alpha',target=(0.,0.)):
        a=CaptureSearchAgent(uid);a.reset();a.frame=self.frame
        self.addCleanup(a.close_detector)
        a.capture.adopt(CaptureMission('alpha',1,'charlie',target,(0.,0.),200.,
                                     1.,1.,100.,1.),1.)
        a.capture.phase=APPROACH
        return a

    def assert_camera_hits(self,own,orientation,target,ground=200.):
        # Check the resulting world ray's ground intersection, independently
        # of the controller's bearing/tilt calculation.
        ray,_,_=camera_basis(*orientation,own.heading_deg,'heading_plus_pan')
        self.assertLess(ray[2],0.)
        distance=(ground-own.alt)/ray[2]
        x,y=self.frame.xy(own.lat,own.lon)
        hit=(x+ray[0]*distance,y+ray[1]*distance)
        self.assertLess(math.dist(hit,target),1e-5)

    def test_confirmed_camera_compensates_turns_across_heading_wrap(self):
        a=self.camera_agent(target=(250.,-100.));own=self.own('alpha')
        previous=None
        for heading in (165.,179.,181.,210.,350.,359.,1.,30.):
            with self.subTest(heading=heading):
                own.heading_deg=heading
                orientation=a.aim_gimbal(own,1.,0.,-80.,formation=True)
                self.assert_camera_hits(own,orientation,a.capture.mission.target)
                self.assertGreaterEqual(orientation[0],-180.)
                self.assertLessEqual(orientation[0],180.)
                if previous:
                    old_heading,old_pan=previous
                    residual=(heading-old_heading+orientation[0]-old_pan+180.)%360.-180.
                    self.assertAlmostEqual(residual,0.,places=7)
                previous=heading,orientation[0]
                own.gimbal_pan,own.gimbal_tilt=orientation

    def test_confirmed_camera_updates_for_current_aircraft_translation(self):
        a=self.camera_agent();own=self.own('alpha');orientations=[]
        for x,y in ((0.,-320.),(160.,-200.),(250.,100.)):
            own.lat,own.lon=self.frame.geo(x,y)
            orientation=a.aim_gimbal(own,1.,0.,-80.,formation=True)
            self.assert_camera_hits(own,orientation,(0.,0.))
            orientations.append(orientation)
            own.gimbal_pan,own.gimbal_tilt=orientation
        self.assertGreater(abs(orientations[1][0]-orientations[0][0]),20.)
        self.assertNotAlmostEqual(orientations[1][1],orientations[0][1])

    def test_near_nadir_pan_change_keeps_world_ground_point(self):
        a=self.camera_agent(target=(50.,-320.));own=self.own('alpha')
        for heading in (0.,90.,180.,270.):
            own.heading_deg=heading
            orientation=a.aim_gimbal(own,1.,0.,-80.,formation=True)
            self.assertLess(orientation[1],-80.)
            self.assert_camera_hits(own,orientation,(50.,-320.))
            own.gimbal_pan,own.gimbal_tilt=orientation

    def test_partner_aims_broadcast_point_without_claiming_visual_or_report(self):
        owner=CaptureCoordinator('alpha')
        owner.step(self.own('alpha'),self.initial_peers(),self.frame,0.,self.sight(0.))
        a=CaptureSearchAgent('charlie');a.reset();a.frame=self.frame
        self.addCleanup(a.close_detector)
        own=self.own('charlie')
        messages=(Message('alpha',encode(self.message(owner,.5)),.5),
                  Message('bravo',encode(self.message(CaptureCoordinator('bravo'),.5)),.5))
        obs=Observation(SelfView('charlie',own.lat,own.lon,500.,90.,22.,0.,-80.,50.,Detection(False,0.)),
            messages,MissionBriefing('charlie',3,AreaSpec(36.98,37.02,120.98,121.02),
                                     score_view=ScoreView(.5,(),False,0,3,1.)))
        commands=a.decide(obs,.1)
        camera=next(c.params for c in commands if c.verb=='component.gimbal_tracking.set_orientation')
        self.assert_camera_hits(own,(camera['pan'],camera['tilt']),(0.,0.))
        self.assertGreater(abs(camera['pan']-own.gimbal_pan),60.)
        self.assertEqual(a.capture.phase,APPROACH)
        self.assertTrue(a.capture.ack)
        self.assertFalse(a.capture.visible)
        self.assertIsNone(a.capture_bound)
        self.assertEqual(a.capture.joint_s,0.)
        self.assertFalse(any(c.verb=='agent.report' for c in commands))

    def test_repeated_pixel_frame_does_not_integrate_camera_error(self):
        a=self.camera_agent(target=(250.,-100.));own=self.own('alpha')
        a.pixel_target=PixelBox(850,650,870,670,.99,1024,768,'true_vehicle',.95)
        a.pixel_hits=8;a.pixel_identity_hits=8;a.pixel_track_id=1
        a.pixel_pose=(0.,-80.,90.,50.);a.pixel_own=self.own('alpha')
        a.photo_time=1.;a.photo_digest='same-public-photo';a.motion_verified_until=8.
        a.capture.visible=True
        orientations=[]
        for now in (1.,1.2,1.4,1.6):
            orientation=a.aim_gimbal(own,now,0.,-80.,formation=True)
            self.assert_camera_hits(own,orientation,a.capture.mission.target)
            orientations.append(orientation)
            own.gimbal_pan,own.gimbal_tilt=orientation
        self.assertTrue(all(v==orientations[0] for v in orientations))
        self.assertEqual(a.photo_digest,'same-public-photo')
        self.assertEqual(a.pixel_hits,8)

    def test_unassigned_aircraft_preserves_search_camera_during_pair(self):
        a=self.camera_agent(uid='bravo',target=(250.,-100.))
        baseline=ScoreSearchAgent('bravo');baseline.reset()
        self.addCleanup(baseline.close_detector)
        own=self.own('bravo')
        for phase in (SEARCH,RELEASE):
            with self.subTest(phase=phase):
                a.capture.phase=phase
                self.assertEqual(a.aim_gimbal(own,1.,25.,-60.,formation=False),
                                 baseline.aim_gimbal(own,1.,25.,-60.,formation=False))

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
