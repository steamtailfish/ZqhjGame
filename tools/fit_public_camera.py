"""Offline camera hypotheses from static features and own public pose history.

No target annotations, simulator terrain, or geographic truth. A fitted plane
and time offset are estimates; this tool cannot certify capture timestamps.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np
from scipy.optimize import least_squares

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT/'src')]
from zqhj_localization import camera_basis
from localization_evidence import load_samples
from vision_support import output_dir,write,sha


class PoseHistory:
    keys=('lat','lon','alt','heading_deg','gimbal_pan','gimbal_tilt','gimbal_fov_deg')
    def __init__(self,rows):
        rows=[r for r in rows if r.get('score_sim_s') is not None]
        by_time={r['score_sim_s']:r['own'] for r in rows}
        self.times=np.array(sorted(by_time))
        self.values=np.array([[by_time[t][k] for k in self.keys] for t in self.times])
        for j in (3,4):self.values[:,j]=np.rad2deg(np.unwrap(np.deg2rad(self.values[:,j])))
        self.origin=self.values[0,:2]

    def pose(self,t):
        if t < self.times[0] or t > self.times[-1]:return None
        v=np.array([np.interp(t,self.times,self.values[:,j]) for j in range(7)])
        camera=np.array([(v[1]-self.origin[1])*111320*math.cos(math.radians(self.origin[0])),
                         (v[0]-self.origin[0])*111320,v[2]])
        return camera,v


def predict_pair(pair,history,parameters,yaw):
    ground,scale,lag=parameters
    camera,a=history.pose(pair['ta']-lag)
    other,b=history.pose(pair['tb']-lag)
    w,h=pair['size'];cx,cy=(w-1)/2,(h-1)/2
    fa=w/(2*math.tan(math.radians(a[6]/2)))*scale
    fb=w/(2*math.tan(math.radians(b[6]/2)))*scale
    f,r,d=np.array(camera_basis(a[4],a[5],a[3],yaw))
    rays=f[None,:]+(pair['a'][:,0:1]-cx)/fa*r+(pair['a'][:,1:2]-cy)/fa*d
    distances=(ground-camera[2])/np.minimum(rays[:,2],-.01)
    points=camera+rays*distances[:,None]
    f,r,d=np.array(camera_basis(b[4],b[5],b[3],yaw))
    relative=points-other
    z=np.maximum(relative@f,1.)
    return np.stack([cx+fb*(relative@r)/z,cy+fb*(relative@d)/z],axis=1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=output_dir(args.output);cv2.setNumThreads(1)
    summary=dict(source=str(args.run.resolve()),scope='offline fitted hypotheses only',online_approved=False,agents={})
    for folder in sorted((args.run/'observations').iterdir()):
        rows,samples=load_samples(args.run,folder.name)
        history=PoseHistory(rows)
        # Preserve transitions between FOV/tilt/pan settings for identifiability.
        samples=[r for r in samples if r.get('score_sim_s') is not None and r['score_sim_s']>3][::3]
        sift=cv2.SIFT_create(nfeatures=1600);features=[]
        for row in samples:
            path=folder/(row['photo_sha256']+'.image')
            if sha(path)!=row['photo_sha256']:raise ValueError('photo hash mismatch')
            gray=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_GRAYSCALE)
            keys,desc=sift.detectAndCompute(gray,None)
            features.append((row,gray.shape[::-1],keys,desc))
        pairs=[];bf=cv2.BFMatcher(cv2.NORM_L2)
        for i in range(len(features)-1):
            a,size,ka,da=features[i];b,_,kb,db=features[i+1]
            if da is None or db is None:continue
            matches=[x for x,y in bf.knnMatch(da,db,k=2) if x.distance<.7*y.distance]
            if len(matches)<20:continue
            pa=np.array([ka[m.queryIdx].pt for m in matches]);pb=np.array([kb[m.trainIdx].pt for m in matches])
            H,mask=cv2.findHomography(pa,pb,cv2.RANSAC,2.)
            if H is None:continue
            good=np.where(mask.ravel()!=0)[0]
            if len(good)<20:continue
            good=good[np.linspace(0,len(good)-1,min(100,len(good))).astype(int)]
            pair=dict(ta=a['score_sim_s'],tb=b['score_sim_s'],size=size,a=pa[good],b=pb[good])
            pair['homography_median_px']=float(np.median(np.linalg.norm(cv2.perspectiveTransform(pa[good,None].astype(np.float64),H)[:,0]-pb[good],axis=1)))
            pairs.append(pair)
        if len(pairs)<8:
            summary['agents'][folder.name]=dict(status='insufficient_pairs',pairs=len(pairs));continue
        train=[p for i,p in enumerate(pairs) if i%4!=3];val=[p for i,p in enumerate(pairs) if i%4==3]
        def errors(params,subset,yaw):return np.concatenate([(predict_pair(p,history,params,yaw)-p['b']).ravel() for p in subset])
        models=[]
        for yaw in ('heading_plus_pan','world_pan'):
            fits=[least_squares(errors,[150,scale,.2],bounds=([-300,.5,0],[450,2,2]),
                 args=(train,yaw),loss='soft_l1',f_scale=2.,max_nfev=100) for scale in (1.,.75)]
            fit=min(fits,key=lambda r:r.cost)
            tr=errors(fit.x,train,yaw).reshape(-1,2);va=errors(fit.x,val,yaw).reshape(-1,2)
            _,singular,_=np.linalg.svd(fit.jac,full_matrices=False)
            models.append(dict(yaw=yaw,ground_plane_estimate_m=float(fit.x[0]),horizontal_focal_multiplier=float(fit.x[1]),
                capture_lag_estimate_sim_s=float(fit.x[2]),train_median_px=float(np.median(np.linalg.norm(tr,axis=1))),
                validation_median_px=float(np.median(np.linalg.norm(va,axis=1))),
                validation_p90_px=float(np.quantile(np.linalg.norm(va,axis=1),.9)),
                jacobian_condition=float(singular[0]/max(1e-12,singular[-1])),converged=bool(fit.success)))
        record=dict(pairs=len(pairs),train_pairs=len(train),val_pairs=len(val),models=models,
            pair_evidence=[dict(ta=p['ta'],tb=p['tb'],matches=len(p['a']),homography_median_px=p['homography_median_px']) for p in pairs])
        summary['agents'][folder.name]=record
        print(folder.name,json.dumps(models),flush=True)
    write(out/'camera-fit.json',summary)


if __name__=='__main__':main()
