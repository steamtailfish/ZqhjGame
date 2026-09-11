"""Behavioral regression of public inputs, communication and planner constraints."""
from dataclasses import replace
import math
import unittest

from competition.sdk.core.observation import (AreaSpec, CommStats, Detection, Message,
    MissionBriefing, Observation, ScoreView, SelfView)
from zqhj_comm import Packet, Radio, decode, encode
from zqhj_cooperation import Assignment, Reporter
from zqhj_entry import EntryAgent, VisualEntryAgent
from zqhj_planner import Circle, PeerMotion, PrimitivePlanner, guide_heading, segment_distance
from zqhj_state import LocalFrame, SimClock, StatsDelta, TrackBank, detections, wrap


def observation(uid='alpha', t=0., x=-500., y=0., detected=True, inbox=()):
    frame = LocalFrame(37.,121.)
    lat,lon = frame.geo(x,y)
    d = Detection(detected,.8,37.,121.) if detected else Detection(False,0.)
    own = SelfView(uid,lat,lon,500.,0.,22.,0.,-65.,50.,d)
    score = ScoreView(0.,(),False,0,3,t) if t is not None else None
    briefing = MissionBriefing(uid,3,AreaSpec(36.98,37.02,120.98,121.02),score_view=score)
    return Observation(own,tuple(inbox),briefing)


class StateTests(unittest.TestCase):
    def test_clock_uses_public_time_not_dt(self):
        c = SimClock()
        self.assertEqual(c.step(observation(t=None).briefing),(None,'missing'))
        self.assertEqual(c.step(observation(t=52).briefing),(52,'first'))
        self.assertEqual(c.step(observation(t=52).briefing),(52,'duplicate'))
        self.assertEqual(c.step(observation(t=55).briefing),(55,'advance'))
        self.assertEqual(c.step(observation(t=1).briefing),(1,'rewind'))

    def test_detection_shapes_and_bad_values(self):
        own = observation().self
        self.assertEqual(len(detections(own)),1)
        good = own.detection
        invalid = replace(good,target_lat=float('nan'))
        self.assertEqual(detections(replace(own,detections=(good,good,invalid))),[good])
        self.assertEqual(detections(replace(own,detection=replace(good,confidence=2))),[])

    def test_track_outlier_missing_expiry_and_duplicate(self):
        bank,frame = TrackBank(),LocalFrame(37.,121.)
        d = observation().self.detection
        for t in (0.,.25,.5):
            bank.update([d],frame,t)
        track = bank.tracks[1]
        self.assertTrue(track.ready(.5))
        bank.update([d],frame,.5)
        self.assertEqual(track.hits,3)
        far = replace(d,target_lat=37.02)
        bank.update([far],frame,.75)
        self.assertEqual(len(bank.tracks),2)
        self.assertLess(math.hypot(track.vx,track.vy),25.01)
        bank.update([],frame,4.)
        self.assertFalse(bank.tracks)

    def test_stats_are_differences(self):
        s = StatsDelta()
        self.assertEqual(s.update(CommStats(sent=50))['sent'],0)
        self.assertEqual(s.update(CommStats(sent=52))['sent'],2)
        self.assertEqual(s.update(CommStats(sent=52))['sent'],0)
        self.assertEqual(s.update(CommStats(sent=1))['sent'],1)


class RadioTests(unittest.TestCase):
    def test_packet_round_trip_and_limit(self):
        p = Packet(65535,599.95,-84.123456,179.999999,359.999,40,65535,84.,-179.,1.21,500,100.)
        payload = encode(p)
        self.assertEqual(len(payload.encode('utf-8')),41)
        out = decode(payload)
        self.assertEqual(out.seq,65535)
        self.assertAlmostEqual(out.lat,p.lat,places=6)
        self.assertGreaterEqual(out.age_s,p.age_s)
        self.assertLessEqual(out.time_s,p.time_s)
        self.assertIsNone(decode('Z'+'!'*40))
        self.assertIsNone(decode('中'*50))

    def test_duplicate_reorder_self_future_and_expiry(self):
        radio = Radio('alpha')
        p = Packet(2,10,37,121,0,22)
        msg = Message('bravo',encode(p),10)
        radio.receive([msg,Message('alpha',encode(p),10)],10)
        radio.receive([msg,Message('bravo',encode(replace(p,seq=1,lat=38)),10)],10.5)
        self.assertEqual(set(radio.peers),{'bravo'})
        self.assertEqual(radio.peers['bravo'].seq,2)
        future = Message('charlie',encode(replace(p,time_s=20)),10)
        radio.receive([future],10.5)
        self.assertNotIn('charlie',radio.peers)
        radio.receive([msg],14)
        self.assertFalse(radio.peers)

    def test_sequence_wrap(self):
        r = Radio('alpha')
        p = Packet(65535,10,37,121,0,22)
        r.receive([Message('bravo',encode(p),10)],10)
        r.receive([Message('bravo',encode(replace(p,seq=0)),10)],10)
        self.assertEqual(r.peers['bravo'].seq,0)

    def test_rate_uses_sim_time_and_no_catchup_burst(self):
        r,frame,own = Radio('alpha'),LocalFrame(37,121),observation().self
        times = [i/10 for i in range(21)]
        sent = [t for t in times if r.send(own,None,frame,t) is not None]
        self.assertEqual(sent,[0.,.5,1.,1.5,2.])
        self.assertIsNotNone(r.send(own,None,frame,100))
        self.assertIsNone(r.send(own,None,frame,100))


class PlannerTests(unittest.TestCase):
    def test_swept_distance_catches_between_sample_collision(self):
        self.assertEqual(segment_distance((-100.,0.),(100.,0.)),0.)

    def test_guide_attraction_and_inside_ring_repulsion(self):
        outside = guide_heading((0,0),(0,0),(1000,0),formation=True)
        inside = guide_heading((0,0),(0,0),(100,0),formation=True)
        self.assertGreater(math.sin(math.radians(outside)),0)
        self.assertLess(math.sin(math.radians(inside)),0)

    def test_planner_constraints_and_obstacle(self):
        planner = PrimitivePlanner()
        p = planner.plan((0.,0.),0.,22.,90.,bounds=(-1000,1000,-1000,1000),
                         obstacles=(Circle(0,180,40),))
        self.assertTrue(p.feasible)
        self.assertLessEqual(abs(wrap(p.heading)),15.)
        self.assertLessEqual(abs(p.speed-22.),2.5)
        self.assertTrue(15 <= p.speed <= 40)
        self.assertEqual(len(p.path),17)
        for _,x,y in p.path:
            self.assertGreater(math.hypot(x,y-180),90.)

    def test_impossible_separation_is_explicit(self):
        p = PrimitivePlanner().plan((0,0),0,22,0,peers=(PeerMotion(1,0,0,22),))
        self.assertFalse(p.feasible)
        self.assertLess(p.clearance_m,0)
        self.assertEqual(p.reason,'no_feasible_primitive')
        self.assertGreaterEqual(p.speed,15.)


class AgentTests(unittest.TestCase):
    def agent(self, uid='alpha', cls=EntryAgent):
        a = cls(uid)
        a.configure({})
        a.reset()
        return a

    def test_missing_duplicate_reset_and_instance_isolation(self):
        a,b = self.agent(),self.agent('bravo')
        self.assertEqual(a.decide(observation(t=None),500),[])
        self.assertTrue(a.decide(observation(),500))
        self.assertEqual(a.decide(observation(),500),[])
        self.assertFalse(b.bank.tracks)
        a.decide(observation(t=2),.1)
        self.assertEqual(a.decide(observation(t=1),.1),[])
        self.assertFalse(a.bank.tracks)
        self.assertEqual(a.diagnostics['state'],'TIME_REWIND')
        a.reset()
        self.assertIsNone(a.frame)

    def test_visual_fails_closed_and_no_unverified_reports(self):
        a = self.agent(cls=VisualEntryAgent)
        self.assertEqual(a.sensor(observation(),.1),[])
        reporter = Reporter()
        assignment = Assignment('OBSERVE','alpha',1,(0,0),('alpha','bravo'),'alpha')
        self.assertIsNone(reporter.position(assignment,'alpha',20,fresh=True))
        self.assertEqual(reporter.position(assignment,'alpha',20,fresh=True,identified=True),(0,0))
        self.assertIsNone(reporter.position(assignment,'alpha',20.5,fresh=True,identified=True))
        self.assertIsNone(reporter.position(assignment,'bravo',22,fresh=True,identified=True))

    def test_two_observers_converge_only_through_broadcast(self):
        agents = {uid:self.agent(uid) for uid in ('alpha','bravo','charlie')}
        inbox = []
        positions = {'alpha':(-600.,0.),'bravo':(600.,0.),'charlie':(0.,1200.)}
        counts = {uid:0 for uid in agents}
        for i in range(31):
            now = i/10
            next_inbox = []
            for uid,a in agents.items():
                obs = observation(uid,now,*positions[uid],detected=uid!='charlie',inbox=inbox)
                commands = a.decide(obs,.1)
                self.assertFalse(any(c.verb == 'agent.report' for c in commands))
                for c in commands:
                    if c.verb == 'comm.broadcast':
                        counts[uid] += 1
                        next_inbox.append(Message(uid,c.params['payload'],now))
            inbox = (inbox+next_inbox)[-32:]
        self.assertEqual(agents['alpha'].diagnostics['owner'],'alpha')
        self.assertEqual(agents['bravo'].diagnostics['owner'],'alpha')
        self.assertEqual(agents['alpha'].diagnostics['state'],'OBSERVE')
        self.assertEqual(agents['bravo'].diagnostics['state'],'OBSERVE')
        self.assertEqual(agents['charlie'].diagnostics['state'],'SEARCH')
        self.assertTrue(all(n == 7 for n in counts.values()))


if __name__ == '__main__':
    unittest.main()
