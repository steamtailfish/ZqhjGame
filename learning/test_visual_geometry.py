from types import SimpleNamespace
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import unittest
import numpy as np
from zqhj_visual_geometry import MotionPlane,world_rays,reproject,relative_camera,rotation_change


class GeometryTests(unittest.TestCase):
    def test_body_turn_cancelled_by_pan_keeps_optical_yaw(self):
        a=np.array([27.,125.,500.,10.,-20.,-70.,50.]);b=a.copy()
        b[3]+=25;b[4]-=25
        self.assertAlmostEqual(rotation_change(a,b),0.)
        b[5]+=7
        self.assertAlmostEqual(rotation_change(a,b),7.)
    def test_cached_plane_expires_by_age_and_distance(self):
        g=MotionPlane();g.last_pose=np.array([27.,125.,500.,0.,0.,-80.,35.])
        g.last_time=4.;g.last_digest='p';g.size=(1024,768);g.status='POSE_CHANGING'
        g.fit_center=g.last_pose[:2].copy()
        for t in (1.,2.,3.):g.fits.append((t,150.,1.,2.))
        b=SimpleNamespace(center=(511.5,383.5))
        self.assertIsNotNone(g.locate(b,4.,'p'))
        g.last_pose[0]+=121./111320
        self.assertIsNone(g.locate(b,4.,'p'))
        g.last_pose[0]=27.;g.last_time=7.1
        self.assertIsNone(g.locate(b,7.1,'p'))

    def test_known_plane_roundtrip(self):
        pose=np.array([27,125,500,33,15,-80,50.])
        pixels=np.array([[510.,380.],[300.,200.],[800.,550.]])
        rays=world_rays(pixels,(1024,768),pose)
        camera=relative_camera(pose,pose)
        points=camera+rays*((150-camera[2])/rays[:,2])[:,None]
        np.testing.assert_allclose(reproject(points,(1024,768),pose,camera),pixels,atol=1e-9)

    def test_capture_claim_is_never_fabricated(self):
        g=MotionPlane();g.last_pose=np.array([27,125,500,0,0,-80,50.])
        g.last_time=3.;g.last_digest='photo';g.size=(1024,768);g.status='PLANE_ESTIMATED'
        for t in (0.,.5,1.,1.5,2.,2.5,3.):g.history.append((t,g.last_pose.copy()))
        for t in (1.,2.,3.):g.fits.append((t,150.,1.,2.))
        b=SimpleNamespace(center=(511.5,383.5))
        e=g.locate(b,3.,'photo');self.assertIsNotNone(e)
        self.assertFalse(e.capture_verified);self.assertGreaterEqual(e.uncertainty_m,40.)
        self.assertIsNone(g.locate(b,5.,'photo'));self.assertIsNone(g.locate(b,3.,'other'))

    def test_turns_and_inconsistent_planes_reject(self):
        g=MotionPlane();g.last_pose=np.array([27,125,500,0,0,-80,50.]);g.last_time=3.
        g.last_digest='p';g.size=(1024,768);g.status='PLANE_ESTIMATED'
        for t in (0.,.5,1.,1.5,2.,2.5,3.):g.history.append((t,g.last_pose.copy()))
        for t,z in ((1,20),(2,150),(3,300)):g.fits.append((t,z,1.,2.))
        self.assertIsNone(g.locate(SimpleNamespace(center=(500,380)),3,'p'))
        g.history[-2][1][3]=30
        self.assertFalse(g.stable(3.))


if __name__=='__main__':unittest.main()
