"""Causal local-plane estimates from own images and own motion only.

Outputs explicitly remain uncertain estimates. They do not claim a verified
capture timestamp, calibrated probability, terrain datum or target identity.
The strict capture-aligned projector is a separate, unchanged API.
"""
from collections import deque
from dataclasses import dataclass
import math

import cv2
import numpy as np

from zqhj_localization import camera_basis


@dataclass(frozen=True)
class GeoEstimate:
    latitude: float
    longitude: float
    uncertainty_m: float
    ground_plane_m: float
    receipt_sim_s: float
    image_sha256: str
    fit_residual_px: float
    capture_verified: bool = False
    source: str = 'own_rgb_motion_plane_estimate'


def pose_values(own):
    return np.array([own.lat,own.lon,own.alt,own.heading_deg,own.gimbal_pan,own.gimbal_tilt,own.gimbal_fov_deg],dtype=float)


def relative_camera(values,origin):
    return np.array([(values[1]-origin[1])*111320*math.cos(math.radians(origin[0])),
                     (values[0]-origin[0])*111320,values[2]])


def rotation_change(a,b):
    # Heading and relative pan can cancel: assess actual optical yaw.
    return max(abs((a[3]+a[4]-b[3]-b[4]+180)%360-180),abs(a[5]-b[5]))


def world_rays(pixels,size,pose):
    w,h=size;focal=w/(2*math.tan(math.radians(pose[6]/2)))
    f,r,d=np.array(camera_basis(pose[4],pose[5],pose[3],'heading_plus_pan'))
    return f+(pixels[:,0:1]-(w-1)/2)/focal*r+(pixels[:,1:2]-(h-1)/2)/focal*d


def reproject(points,size,pose,camera):
    w,h=size;focal=w/(2*math.tan(math.radians(pose[6]/2)))
    f,r,d=np.array(camera_basis(pose[4],pose[5],pose[3],'heading_plus_pan'))
    rel=points-camera;z=np.maximum(rel@f,1.)
    return np.stack([(w-1)/2+focal*(rel@r)/z,(h-1)/2+focal*(rel@d)/z],axis=1)


class MotionPlane:
    def __init__(self):
        self.previous=None;self.history=deque(maxlen=100)
        self.fits=deque(maxlen=10);self.status='NEED_MOTION'
        self.last_digest=None;self.last_pose=None;self.last_time=None;self.size=None
        self.last_residual=None
        self.fit_center=None
        self.homography=None;self.pair_old_digest=None

    def observe_pose(self,own,now):
        values=pose_values(own)
        if not np.isfinite(values).all():return
        if self.history and now<self.history[-1][0]:self.__init__()
        if not self.history or now>self.history[-1][0]:self.history.append((now,values))

    def stable(self,now):
        recent=[p for t,p in self.history if 0 <= now-t <= 1.5]
        if len(recent)<3 or self.history[-1][0]-self.history[0][0]<1.:return False
        return all(rotation_change(p,recent[-1]) <= 5. and abs(p[6]-recent[-1][6])<.1 for p in recent)

    def update(self,photo,own,now,digest):
        self.observe_pose(own,now)
        if digest==self.last_digest:return
        gray=cv2.imdecode(np.frombuffer(photo,np.uint8),cv2.IMREAD_GRAYSCALE)
        if gray is None:return
        pose=pose_values(own);size=gray.shape[::-1]
        old=self.previous
        self.previous=(gray,pose,now,digest)
        self.homography=None;self.pair_old_digest=None
        self.last_digest=digest;self.last_pose=pose;self.last_time=now;self.size=size
        if old is None:self.status='POSE_CHANGING';return
        before,a,ta,old_digest=old
        if before.shape!=gray.shape or not .4 <= now-ta <= 2. or abs(pose[6]-a[6])>.1:
            self.status='PAIR_GAP';return
        camera=relative_camera(a,a);other=relative_camera(pose,a)
        pa=cv2.goodFeaturesToTrack(before,maxCorners=250,qualityLevel=.02,minDistance=18)
        if pa is None or len(pa)<30:self.status='TEXTURE_LOW';return
        pb,status,_=cv2.calcOpticalFlowPyrLK(before,gray,pa,None,winSize=(31,31),maxLevel=4)
        back,reverse,_=cv2.calcOpticalFlowPyrLK(gray,before,pb,None,winSize=(31,31),maxLevel=4)
        good=(status[:,0]>0)&(reverse[:,0]>0)&(np.linalg.norm(pa[:,0]-back[:,0],axis=1)<1.)
        pa,pb=pa[good,0].astype(float),pb[good,0].astype(float)
        if len(pa)<30:self.status='MATCHES_LOW';return
        H,mask=cv2.findHomography(pa,pb,cv2.RANSAC,2.)
        if H is None:self.status='HOMOGRAPHY_FAILED';return
        pa,pb=pa[mask[:,0]>0],pb[mask[:,0]>0]
        if len(pa)<30:self.status='INLIERS_LOW';return
        self.homography=H;self.pair_old_digest=old_digest
        # Image motion is useful for association even during a camera slew.
        # Ground-depth fitting still requires settled receipt poses.
        if not self.stable(now):self.status='POSE_CHANGING';return
        if np.linalg.norm(other[:2]-camera[:2])<6.:
            self.status='BASELINE_SMALL';return
        rays=world_rays(pa,size,a)
        if np.any(rays[:,2]>-.2):self.status='OBLIQUE_RAYS';return
        def residual(z,subset=slice(None)):
            points=camera+rays[subset]*((z-camera[2])/rays[subset,2])[:,None]
            return np.linalg.norm(reproject(points,size,pose,other)-pb[subset],axis=1)
        # Alternating feature points are withheld from the depth fit.
        candidates=np.arange(-200.,min(420.,pose[2]-60.),20.)
        z=min(candidates,key=lambda z:np.median(residual(z,slice(None,None,2))))
        z=min(np.arange(z-20,z+20.1,2.),key=lambda z:np.median(residual(z,slice(None,None,2))))
        validation=residual(z,slice(1,None,2));median=float(np.median(validation))
        p90=float(np.quantile(validation,.9));self.last_residual=median
        if median>4. or p90>10. or not -200<z<420:
            self.status='PLANE_REJECTED';return
        self.fits.append((now,float(z),median,p90))
        self.fit_center=pose[:2].copy()
        self.status='PLANE_ESTIMATED'

    def locate(self,box,now,digest):
        if (self.last_pose is None or digest!=self.last_digest or not 0<=now-self.last_time<=1.
                or self.status not in ('PLANE_ESTIMATED','POSE_CHANGING','PLANE_REJECTED')):
            return None
        fits=[f for f in self.fits if 0<=now-f[0]<=8.]
        if len(fits)<3 or fits[-1][0]-fits[0][0]<1.:return None
        if now-fits[-1][0]>4.:return None
        # A camera rotation does not instantly invalidate a recently fitted
        # local ground plane. Bound reuse in time and distance, and include
        # rotation uncertainty below rather than discarding every servo frame.
        if self.fit_center is not None:
            distance=math.hypot((self.last_pose[0]-self.fit_center[0])*111320,
                (self.last_pose[1]-self.fit_center[1])*111320*math.cos(math.radians(self.fit_center[0])))
            if distance>120:return None
        ground=float(np.median([f[1] for f in fits]))
        spread=float(np.median(np.abs(np.array([f[1] for f in fits])-ground)))
        if spread>20:return None
        ray=world_rays(np.array([box.center]),self.size,self.last_pose)[0]
        if ray[2]>=-.35 or not -90<=self.last_pose[5]<=-40:return None
        offset=ray*((ground-self.last_pose[2])/ray[2])
        if np.linalg.norm(offset[:2])>800:return None
        # Conservative engineering budget, not covariance: <=1 s assumed lag,
        # focal-model error, local canopy/ground difference, and fit variation.
        recent=[p for t,p in self.history if 0<=now-t<=1.5]
        rotation=max((rotation_change(p,self.last_pose) for p in recent),default=5.)/1.5
        horizontal=float(np.linalg.norm(offset[:2]))
        angular_error=(horizontal+self.last_pose[2]-ground)*math.tan(math.radians(rotation))
        uncertainty=40.+.1*horizontal+2*spread+25*float(np.linalg.norm(ray[:2])/abs(ray[2]))+angular_error
        if uncertainty>150:return None
        lat=self.last_pose[0]+offset[1]/111320
        lon=self.last_pose[1]+offset[0]/(111320*math.cos(math.radians(self.last_pose[0])))
        return GeoEstimate(float(lat),float(lon),uncertainty,ground,self.last_time,digest,
                           max(f[2] for f in fits))
