"""Learning-venv tests: photo isolation, stale input, servo and detector contracts."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT.parent),str(PROJECT/'src'),str(PROJECT/'tests')]
sys.path.insert(0,str(PROJECT/'tools'))
import torch
from PIL import Image
from test_guided_agent import observation
from zqhj_vision import PhotoDetector, PixelBox, center_gimbal
from zqhj_photo_entry import PhotoEntryAgent


def frame(t=0.,photo=b'photo'):
    obs=observation(t=t)
    return replace(obs,self=replace(obs.self,photo=photo))


def agent(detector=None):
    a=PhotoEntryAgent('alpha')
    a.detector=detector or (lambda p:[PixelBox(750,300,850,400,.8,1024,768)])
    a.reset();return a


class VisionTests(unittest.TestCase):
    def test_never_consumes_sdk_geographic_detection(self):
        a=agent()
        for t in (0.,.5,1.):
            a.sensor(frame(t,str(t).encode()),.1)
            commands=a.decide(frame(t),.1)
            self.assertEqual(len(a.bank.tracks),0)
            self.assertFalse(a.diagnostics['reports_enabled'])
        self.assertEqual(a.vision_stats['servo_commands'],2)

    def test_distinct_instances_and_reset(self):
        a,b=agent(),agent()
        a.sensor(frame(),.1)
        self.assertEqual(b.vision_stats['inferences'],0)
        a.reset();self.assertEqual(a.pixel_hits,0);self.assertIsNone(a.pixel_target)

    def test_missing_bad_and_rewound_time(self):
        a=agent();self.assertEqual(a.sensor(frame(None),.1),[])
        a.sensor(frame(10),.1);a.sensor(frame(1,b'new'),.1)
        self.assertEqual(a.vision_stats['inferences'],1)
        a.sensor(frame(2,None),.1);self.assertIsNone(a.pixel_target)

    def test_same_photo_does_not_reinforce_or_stay_fresh(self):
        a=agent();a.sensor(frame(0,b'a'),.1);a.sensor(frame(.5,b'b'),.1)
        for t in (1.,1.5,2.):a.sensor(frame(t,b'b'),.1)
        self.assertEqual(a.vision_stats['inferences'],2)
        self.assertEqual(a.pixel_hits,2)
        self.assertEqual(a.aim_gimbal(frame().self,2,30,-65),(0.,-80.))

    def test_callback_exception_suppresses_sdk_fallback(self):
        def bad(p):raise RuntimeError('decode failed')
        a=agent(bad);self.assertEqual(a.sensor(frame(),.1),[])
        self.assertEqual(a.vision_stats['failures'],1)
        self.assertIsNone(a.pixel_target)

    def test_large_gap_does_not_confirm_pixel_track(self):
        a=agent();a.sensor(frame(0,b'a'),.1);a.sensor(frame(5,b'b'),.1)
        self.assertEqual(a.pixel_hits,1)

    def test_pixel_servo_bounded_and_directional(self):
        box=PixelBox(900,600,1000,700,.9,1024,768)
        pan,tilt=center_gimbal(box,0,-65)
        self.assertTrue(0 < pan <= 3)
        self.assertTrue(-68 <= tilt < -65)
        self.assertGreaterEqual(center_gimbal(box,0,-88)[1],-89)

    def test_identity_and_file_io_unavailable(self):
        a=agent()
        with patch('builtins.open',side_effect=AssertionError('online file IO forbidden')):
            a.sensor(frame(),.1);a.decide(frame(),.1)
        self.assertEqual(a.diagnostics['identity'],'unknown')
        self.assertIsNone(a.diagnostics['capture_sim_s'])

    def test_raw_forward_nms_and_coordinate_restore(self):
        class Model(torch.nn.Module):
            def forward(self,x):
                # 100x50 image becomes 640x320 with top padding 160.
                return torch.tensor([[[320.,321.],[320.,320.],[128.,128.],[64.,64.],[.9,.8]]])
        d=PhotoDetector(Model(),size=640);stream=BytesIO();Image.new('RGB',(100,50)).save(stream,format='PNG')
        boxes=d(stream.getvalue());self.assertEqual(len(boxes),1)
        self.assertAlmostEqual(boxes[0].x1,40);self.assertAlmostEqual(boxes[0].y1,20)
        self.assertAlmostEqual(boxes[0].x2,60);self.assertAlmostEqual(boxes[0].y2,30)

    def test_malformed_and_multiclass_model_rejected(self):
        class Model(torch.nn.Module):
            def forward(self,x):return torch.zeros(1,6,10)
        d=PhotoDetector(Model());stream=BytesIO();Image.new('RGB',(100,50)).save(stream,format='PNG')
        with self.assertRaises(ValueError):d(stream.getvalue())
        with self.assertRaises(Exception):d(b'broken JPEG')

    def test_two_class_scores_preserve_identity_and_margin(self):
        class Model(torch.nn.Module):
            def forward(self,x):return torch.tensor([[[320.],[320.],[128.],[64.],[.96],[.03]]])
        d=PhotoDetector(Model(),size=640,names=('true_vehicle','decoy_vehicle'))
        stream=BytesIO();Image.new('RGB',(100,50)).save(stream,format='PNG')
        box=d(stream.getvalue())[0]
        self.assertEqual(box.category,'true_vehicle');self.assertGreater(box.class_margin,.9)

    def test_geo_observation_consumed_once(self):
        a=agent();d=SimpleNamespace(target_lat=37.,target_lon=121.,uncertainty_m=75.,source='own_rgb_motion_plane_estimate')
        a.pending_geo=[d]
        self.assertEqual(a.perception_candidates(frame().self),[d])
        self.assertEqual(a.perception_candidates(frame().self),[])

    def test_navigation_waypoint_uses_own_pose_and_planned_heading(self):
        from zqhj_state import LocalFrame
        a=agent();f=LocalFrame(37.,121.);own=frame().self
        command=a.navigation_commands(own,SimpleNamespace(heading=90.,speed=22.),f)[0]
        self.assertEqual(command.verb,'set_destination')
        self.assertEqual(command.params['loiter_radius'],0.)
        x,y=f.xy(command.params['latitude'],command.params['longitude'])
        ox,oy=f.xy(own.lat,own.lon)
        self.assertAlmostEqual(x-ox,300.,places=6);self.assertAlmostEqual(y-oy,0.,places=6)

    def test_reports_need_repeated_identity_evidence(self):
        from zqhj_state import TrackBank,LocalFrame
        b=TrackBank();f=LocalFrame(37.,121.)
        d=SimpleNamespace(target_lat=37.,target_lon=121.,uncertainty_m=75.,source='own_rgb_motion_plane_estimate',identity='true_vehicle')
        for t in (0.,.5,1.):b.update([d],f,t)
        self.assertEqual(b.tracks[1].identity_hits,3)
        b.update([d],f,1.);self.assertEqual(b.tracks[1].identity_hits,3)
        d.identity='unknown';b.update([d],f,1.5)
        self.assertEqual(b.tracks[1].identity_hits,0)
        self.assertGreaterEqual(b.tracks[1].sigma_m,75.)

    def test_unreviewed_predictions_cannot_be_training_labels(self):
        from vision_cli import reviewed_records
        fake=SimpleNamespace(read_text=lambda **kw:'{"review_status":"unreviewed"}')
        with self.assertRaisesRegex(ValueError,'explicit accepted review'):
            reviewed_records(fake)

    def test_report_requires_current_matching_identity_location_and_owner(self):
        from zqhj_state import LocalFrame
        from zqhj_visual_geometry import GeoEstimate
        from competition.sdk.core.commands import set_speed
        def prepared():
            a=agent();a.enable_reports=True;a.frame=LocalFrame(37.,121.)
            a.clock.previous=10.;a.coordinator.key=('alpha',1)
            a.diagnostics={'state':'OBSERVE','members':('alpha','beta')}
            a.bank.tracks[1]=SimpleNamespace(source='own_rgb_motion_plane_estimate',
                identity='true_vehicle',identity_hits=8,sample_s=10.,predict=lambda t:(0.,0.))
            a.photo_digest='fresh';a.photo_time=10.
            a.pixel_target=PixelBox(400,300,430,340,.95,1024,768,'true_vehicle',.8)
            a.geo_estimate=GeoEstimate(37.,121.,70.,150.,10.,'fresh',2.)
            return a
        with patch('zqhj_photo_entry.EntryAgent.decide',return_value=[set_speed(20.)]):
            a=prepared();commands=a.decide(frame(10.),.1)
            self.assertEqual(a.report_count,1);self.assertEqual(len(commands),2)
            a.decide(frame(10.),.1);self.assertEqual(a.report_count,1)
            changes=[lambda a:setattr(a,'enable_reports',False),
                lambda a:setattr(a,'photo_time',8.),
                lambda a:setattr(a,'photo_digest','different'),
                lambda a:setattr(a,'geo_estimate',replace(a.geo_estimate,longitude=121.01)),
                lambda a:setattr(a,'geo_estimate',replace(a.geo_estimate,receipt_sim_s=8.)),
                lambda a:setattr(a,'pixel_target',replace(a.pixel_target,class_margin=.1)),
                lambda a:setattr(a.bank.tracks[1],'identity_hits',7),
                lambda a:setattr(a.bank.tracks[1],'identity','decoy_vehicle'),
                lambda a:setattr(a.coordinator,'key',('beta',1)),
                lambda a:a.diagnostics.update(state='ACQUIRE')]
            for change in changes:
                a=prepared();change(a);a.decide(frame(10.),.1)
                self.assertEqual(a.report_count,0)

    def test_episode_split_and_positive_example_guards(self):
        from vision_cli import dataset
        args=SimpleNamespace(reviewed=None,val_episode=['val'],output=None)
        row=lambda ep,h,boxes:dict(episode=ep,sha256=h,boxes=boxes)
        with patch('vision_cli.reviewed_records',return_value=[row('val','a',[{}])]):
            with self.assertRaisesRegex(ValueError,'different complete episodes'):dataset(args)
        with patch('vision_cli.reviewed_records',return_value=[row('train','a',[{}]),row('val','a',[{}])]):
            with self.assertRaisesRegex(ValueError,'leaks'):dataset(args)
        with patch('vision_cli.reviewed_records',return_value=[row('train','a',[]),row('val','b',[{}])]):
            with self.assertRaisesRegex(ValueError,'positive'):dataset(args)


if __name__=='__main__':unittest.main()
