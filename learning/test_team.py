from pathlib import Path
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_vision import frame
from zqhj_team import TeamPhotoEntryAgent
from zqhj_comm import Packet,encode,decode
from zqhj_planner import PrimitivePlanner
from zqhj_state import LocalFrame
from zqhj_cooperation import Coordinator,Assignment
from zqhj_vision import PixelBox


class TeamTests(unittest.TestCase):
    def test_held_image_bearing_does_not_integrate_error(self):
        a=TeamPhotoEntryAgent('alpha');a.detector=lambda p:[];a.reset()
        try:
            own=frame().self;a.pixel_target=PixelBox(700,350,740,390,.9,1024,768)
            a.pixel_hits=3;a.photo_time=1.;a.pixel_pose=(0.,-60.,0.,35.)
            # Exercise the parent servo directly, independent of search policy.
            from zqhj_photo_entry import PhotoEntryAgent
            first=PhotoEntryAgent.aim_gimbal(a,own,1.,0.,-60.)
            own=SimpleNamespace(**{**vars(own),'gimbal_pan':first[0],'gimbal_tilt':first[1]})
            second=PhotoEntryAgent.aim_gimbal(a,own,1.1,0.,-60.)
            self.assertEqual(first,second)
            own.heading_deg+=15
            third=PhotoEntryAgent.aim_gimbal(a,own,1.2,0.,-60.)
            self.assertAlmostEqual((third[0]-second[0]+180)%360-180,-15.)
        finally:a.close_detector()

    def test_extended_packet_roundtrip_and_byte_limit(self):
        p=Packet(7,100,27,125,350,22,1,27.001,125.002,.5,8,100.,155.,'true_vehicle')
        payload=encode(p);self.assertEqual(len(payload),45);self.assertLessEqual(len(payload.encode()),50)
        q=decode(payload);self.assertEqual(q.ground_m,155.);self.assertEqual(q.identity,'true_vehicle')
        self.assertIsNone(decode(payload[:-1]))

    def test_candidate_grace_uses_measurement_time(self):
        c=Coordinator('alpha');f=LocalFrame(27.,125.)
        p=Packet(1,10,27,125,0,22,1,27.001,125,0.,4,60.,150.)
        a=c.assign(None,{'beta':p},f,10.);self.assertEqual(a.ground_m,150.)
        a=c.assign(None,{},f,15.);self.assertEqual(a.target,f.xy(27.001,125.))
        self.assertIsNone(c.assign(None,{},f,18.1).target)

    def test_remote_assignment_cannot_be_overridden_by_unrelated_pixel(self):
        a=TeamPhotoEntryAgent('alpha');a.detector=lambda p:[];a.reset()
        try:
            a.frame=LocalFrame(37.,121.);a.assignment=Assignment('OBSERVE','beta',1,(0.,500.),('alpha','beta'),'beta',150.)
            a.pixel_target=PixelBox(950,700,990,740,.9,1024,768);a.pixel_hits=3;a.photo_time=1.
            pan,tilt=a.aim_gimbal(frame().self,1.,20.,-50.,formation=True)
            self.assertEqual(pan,20.);self.assertLess(tilt,0.)
        finally:a.close_detector()


if __name__=='__main__':unittest.main()
