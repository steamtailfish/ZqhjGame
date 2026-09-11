"""Offline manual-pixel correspondence and conditional geometry; no truth or models."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zqhj_localization import CandidatePixel,pixel_ray,project_candidate
from localization_evidence import load_samples


def ncc(template,search):
    """Normalized patch correlation, not a semantic detector or probability."""
    h,w=template.shape; H,W=search.shape
    shape=(1<<(H+h-2).bit_length(),1<<(W+w-2).bit_length())
    t=template-template.mean()
    corr=np.fft.irfft2(np.fft.rfft2(search,s=shape)*np.conj(np.fft.rfft2(t,s=shape)),s=shape)
    corr=corr[:H-h+1,:W-w+1]
    def sums(a):
        ii=np.pad(a,((1,0),(1,0))).cumsum(0).cumsum(1)
        return ii[h:,w:]-ii[:-h,w:]-ii[h:,:-w]+ii[:-h,:-w]
    variance=np.maximum(sums(search*search)-sums(search)**2/(h*w),1e-10)
    scores=corr/np.sqrt(variance*np.sum(t*t))
    iy,ix=np.unravel_index(np.argmax(scores),scores.shape)
    def subpixel(a,b,c):
        denom=a-2*b+c
        return float(.5*(a-c)/denom) if abs(denom)>1e-10 else 0.
    dx=subpixel(scores[iy,ix-1],scores[iy,ix],scores[iy,ix+1]) if 0<ix<scores.shape[1]-1 else 0
    dy=subpixel(scores[iy-1,ix],scores[iy,ix],scores[iy+1,ix]) if 0<iy<scores.shape[0]-1 else 0
    return ix+dx,iy+dy,float(scores[iy,ix])


def local_camera(own,origin):
    return np.array([(own['lon']-origin['lon'])*111320*math.cos(math.radians(origin['lat'])),
        (own['lat']-origin['lat'])*111320,own['alt']])


def triangulate(frames,pixels,axis,yaw):
    origin=frames[0]['own']; A=[];b=[];rays=[];cams=[]
    for frame,pixel in zip(frames,pixels):
        own=frame['own']
        ray=np.array(pixel_ray(*pixel,1024,768,own['gimbal_fov_deg'],axis,
                              own['gimbal_pan'],own['gimbal_tilt'],own['heading_deg'],yaw))
        camera=local_camera(own,origin); M=np.eye(3)-np.outer(ray,ray)
        A.append(M);b.append(M@camera);rays.append(ray);cams.append(camera)
    A=np.vstack(A);b=np.concatenate(b)
    p,_,rank,singular=np.linalg.lstsq(A,b,rcond=None)
    miss=[float(np.linalg.norm(np.cross(p-c,r))) for c,r in zip(cams,rays)]
    return dict(point_enu=p.tolist(),rank=int(rank),condition_number=float(singular[0]/singular[-1]),
                baseline_m=float(np.linalg.norm(cams[-1]-cams[0])),ray_miss_m=miss)


def reprojection(frame,point,origin,axis,yaw):
    from zqhj_localization import camera_basis
    own=frame['own'];rel=np.array(point)-local_camera(own,origin)
    f,r,d=map(np.array,camera_basis(own['gimbal_pan'],own['gimbal_tilt'],own['heading_deg'],yaw))
    focal=(1024 if axis=='horizontal' else 768)/(2*math.tan(math.radians(own['gimbal_fov_deg']/2)))
    return np.array([511.5+focal*np.dot(rel,r)/np.dot(rel,f),383.5+focal*np.dot(rel,d)/np.dot(rel,f)])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run=args.run.resolve();out=args.output.resolve()
    project=Path(__file__).resolve().parents[1]
    if not out.is_relative_to(project):parser.error('output outside project')
    out.mkdir(parents=True,exist_ok=False)
    result=dict(source_run=str(run),scope='offline manual landmark geometry, not vehicle identification',
        candidate_definition='Visible static image feature, no claim it is a competition target',
        online_candidate_available=False,capture_time_available=False,features={})
    # Offline annotations made after visually inspecting these real, public photos.
    # They are never imported by an Agent. Coordinates are not online constants.
    manual=[('20001',(155,211),'right-angle corner on visible dark-region boundary',[(155,402),(155,532)]),
            ('20003',(570,149),'distinct ring-texture junction used only to check image axes',[(560,343),(552,472)])]
    for uid,point,label,centers in manual:
        rows,samples=load_samples(run,uid)
        frames=[min(samples,key=lambda r:abs(r['score_sim_s']-t)) for t in (10,14,17)]
        paths=[run/'observations'/uid/(r['photo_sha256']+'.image') for r in frames]
        images=[]
        for path in paths:
            with Image.open(path) as im:
                if im.size!=(1024,768):raise ValueError('this offline experiment requires original 1024x768 frames')
                images.append(np.array(im.convert('L'),dtype=float))
        u,v=point;half=20;template=images[0][v-half:v+half+1,u-half:u+half+1]
        pixels=[list(map(float,point))];scores=[None]
        for im,center in zip(images[1:],centers):
            x,y=center;radius=65
            crop=im[y-radius:y+radius+1,x-radius:x+radius+1]
            dx,dy,score=ncc(template,crop)
            pixels.append([x-radius+dx+half,y-radius+dy+half]);scores.append(score)
        records=[]
        canvas=Image.new('RGB',(1024,900),'#eeeeee');draw=ImageDraw.Draw(canvas)
        for i,(frame,path,pixel,score) in enumerate(zip(frames,paths,pixels,scores)):
            with Image.open(path) as original:
                original=original.convert('RGB');mark=ImageDraw.Draw(original)
                x,y=pixel;mark.ellipse((x-12,y-12,x+12,y+12),outline='red',width=3)
                mark.line((x-20,y,x+20,y),fill='yellow',width=2)
                mark.line((x,y-20,x,y+20),fill='yellow',width=2)
                original.resize((768,576)).save(out/f'{uid}-frame{i}-annotated.jpg',quality=94)
                thumb=original.resize((512,384));canvas.paste(thumb,((i%2)*512,(i//2)*450+45))
                draw.text(((i%2)*512+5,(i//2)*450+5),f'{uid} t={frame["score_sim_s"]:.3f}\npixel=({x:.2f},{y:.2f}) NCC={score}',fill='black')
            records.append(dict(image=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                pixel=pixel,source='offline_manual_photo' if i==0 else 'offline_template_correspondence',
                ncc_similarity_not_probability=score,own=frame['own'],time=frame['time']))
        canvas.save(out/(uid+'-correspondence.jpg'),quality=94)
        hypotheses={}
        for axis in ('horizontal','vertical'):
            for yaw in ('world_pan','heading_plus_pan'):
                fit=triangulate(frames[:2],pixels[:2],axis,yaw)
                predicted=reprojection(frames[2],fit['point_enu'],frames[0]['own'],axis,yaw)
                fit.update(heldout_predicted_pixel=predicted.tolist(),heldout_observed_pixel=pixels[2],
                    heldout_error_px=float(np.linalg.norm(predicted-pixels[2])))
                hypotheses[axis+'/'+yaw]=fit
        stable_rows=[r for r in rows if r['score_sim_s'] is not None and frames[0]['score_sim_s']-1<=r['score_sim_s']<=frames[-1]['score_sim_s']]
        stability={k:max(r['own'][k] for r in stable_rows)-min(r['own'][k] for r in stable_rows)
            for k in ('heading_deg','gimbal_pan','gimbal_tilt','gimbal_fov_deg','alt','speed')}
        result['features'][uid]=dict(label=label,records=records,stability_range=stability,hypotheses=hypotheses)
        if uid=='20001':
            # Candidate sample 3 correspondence has been visually checked against sample 1.
            candidate=CandidatePixel('offline_template_correspondence',label+'; manually seeded from real photo; patch correspondence requires visual review',
                *pixels[2],1024,768,frames[2]['photo_sha256'],uid)
            cases={}
            for axis in ('horizontal','vertical'):
                fit=hypotheses[axis+'/heading_plus_pan']
                stable=stability['heading_deg']<.1 and stability['gimbal_tilt']==0 and stability['gimbal_fov_deg']==0
                valid_fit=(min(scores[1:])>.85 and fit['rank']==3 and fit['condition_number']<100 and
                           fit['baseline_m']>20 and fit['heldout_error_px']<5)
                options=dict(fov_axis=axis,yaw_convention='heading_plus_pan',ground_alt_m=fit['point_enu'][2],
                    height_source='local landmark plane inferred from first TWO same-UAV public-photo rays; conditional FOV hypothesis',
                    calibration_evidence='records + first-two-frame triangulation + held-out third-frame reprojection',
                    stable_pose=stable and valid_fit,uncropped=True,offline=True)
                cases[axis]=project_candidate(candidate,frames[2]['own'],frames[2]['time'],**options)
                if axis=='horizontal':
                    cases['online_rejection']=project_candidate(candidate,frames[2]['own'],frames[2]['time'],**(options|dict(offline=False)))
                    cases['unknown_height_rejection']=project_candidate(candidate,frames[2]['own'],frames[2]['time'],**(options|dict(ground_alt_m=None)))
                    cases['unstable_pose_rejection']=project_candidate(candidate,frames[2]['own'],frames[2]['time'],**(options|dict(stable_pose=False)))
            result['candidate_cases']=cases
    (out/'geometry-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({u:{k:v for k,v in f.items() if k!='records'} for u,f in result['features'].items()},indent=2))
    print(json.dumps(result.get('candidate_cases'),indent=2))


if __name__=='__main__':main()
