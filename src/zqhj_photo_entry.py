"""Public-photo controller with conservative pixel servo and honest geometry gates."""
import hashlib
import math
import time
from dataclasses import asdict
from types import SimpleNamespace

from zqhj_entry import EntryAgent
from zqhj_vision import center_gimbal
from zqhj_search import StripSearch
from zqhj_visual_geometry import MotionPlane
from zqhj_cooperation import Assignment
from zqhj_localization import pixel_ray,camera_basis
from competition.sdk.core.commands import report_target,fly_to


class PhotoEntryAgent(EntryAgent):
    """Launcher injects each instance's warmed detector before reset.

    Always suppress SDK detections, including when decide is called directly.
    Optional motion-plane outputs are explicitly uncertain geographic estimates.
    """
    def reset(self):
        super().reset()
        self.photo_digest = None
        self.photo_time = -math.inf
        self.sensor_time = -math.inf
        self.sensor_clock = -math.inf
        self.boxes = []
        self.pixel_hits = 0
        self.pixel_target = None
        self.pixel_pose = None
        self.vision_stats = dict(inferences=0,frames_with_candidates=0,failures=0,
                                 repeated=0,missing=0,servo_commands=0,
                                 inference_wall_s=0.,max_inference_wall_s=0.)
        self.vision_state = 'WAIT_PHOTO'
        self.last_vision_error = None
        self.coverage=StripSearch(self.my_uid)
        self.geometry=MotionPlane()
        self.geo_estimate=None;self.pending_geo=[]
        self.report_count=0
        self.pixel_motion_px=None;self.motion_hits=0;self.motion_time=-math.inf
        self.motion_verified_until=-math.inf
        self.pixel_identity_hits=0;self.fast_geo_hits=0
        self.pixel_ground_speed_mps=None;self.fast_geo=None;self.fast_report_count=0

    def perception_candidates(self, own):
        # No SDK simulated detection can enter our geographic track bank.
        pending=self.pending_geo;self.pending_geo=[]
        return pending

    def eligible_boxes(self,boxes):return boxes

    def search_goal(self,position,bounds):
        return self.coverage.goal(position,bounds,self.radio.peers)

    def navigation_commands(self,own,plan,frame):
        # Real-engine runs showed persistent default circling with set_heading
        # alone. Use the SDK destination interface already exercised by probes.
        # This waypoint is reconstructed from our plan, never a hidden target.
        x,y=frame.xy(own.lat,own.lon);h=math.radians(plan.heading)
        lat,lon=frame.geo(x+300*math.sin(h),y+300*math.cos(h))
        return [fly_to(lat,lon,speed=plan.speed,loiter_radius=0.)]

    def sensor(self, obs, dt):
        score=obs.briefing.score_view
        now=getattr(score,'sim_time',None)
        if now is None or not math.isfinite(now) or now < 0 or obs.self.uid != self.my_uid:
            self.vision_state='INVALID_OBSERVATION';return []
        if now < self.sensor_clock:
            self.reset()
        self.sensor_clock=now
        if getattr(self,'enable_geometry',False):self.geometry.observe_pose(obs.self,now)
        photo=obs.self.photo
        if not photo:
            self.vision_stats['missing']+=1
            self.pixel_target=None;self.boxes=[];self.pixel_hits=0
            self.vision_state='WAIT_PHOTO';return []
        if now-self.sensor_time < .5-1e-9:return []
        digest=hashlib.sha256(photo).hexdigest()
        if digest == self.photo_digest:
            self.vision_stats['repeated']+=1
            self.vision_state='REPEATED_PHOTO'
            return []
        if now-self.photo_time > 1.:
            self.pixel_target=None;self.pixel_hits=0
        previous_digest=self.photo_digest;previous_photo_time=self.photo_time
        self.sensor_time=now;self.photo_digest=digest;self.photo_time=now
        started=time.perf_counter()
        try:
            boxes=self.detector(photo)
        except Exception as exc:
            # SDK falls back to its default detector on an uncaught sensor error.
            # Catch here and return [] explicitly, keeping all inputs photo-only.
            self.vision_stats['failures']+=1
            self.last_vision_error=f'{type(exc).__name__}: {exc}'[:240]
            self.boxes=[];self.pixel_target=None;self.pixel_hits=0
            self.vision_state='DETECTOR_ERROR';return []
        finally:
            elapsed=time.perf_counter()-started
            self.vision_stats['inference_wall_s']+=elapsed
            self.vision_stats['max_inference_wall_s']=max(self.vision_stats['max_inference_wall_s'],elapsed)
        self.vision_stats['inferences']+=1
        self.boxes=boxes
        boxes=self.eligible_boxes(boxes)
        if getattr(self,'enable_geometry',False):
            try:self.geometry.update(photo,obs.self,now,digest)
            except Exception:self.geometry.status='GEOMETRY_ERROR'
        previous=self.pixel_target
        static_pixel=None
        if boxes:
            self.vision_stats['frames_with_candidates']+=1
            if previous is not None:
                expected=previous.center
                H=self.geometry.homography
                if H is not None and self.geometry.pair_old_digest==previous_digest:
                    u,v=previous.center;z=H[2,0]*u+H[2,1]*v+H[2,2]
                    if abs(z)>1e-6:expected=((H[0,0]*u+H[0,1]*v+H[0,2])/z,(H[1,0]*u+H[1,1]*v+H[1,2])/z)
                elif self.pixel_pose is not None:
                    p,t,h,fov=self.pixel_pose
                    ray=pixel_ray(*previous.center,previous.width,previous.height,fov,'horizontal',p,t,h,'heading_plus_pan')
                    forward,right,down=camera_basis(obs.self.gimbal_pan,obs.self.gimbal_tilt,obs.self.heading_deg,'heading_plus_pan')
                    z=sum(x*y for x,y in zip(ray,forward))
                    if z>.1:
                        focal=previous.width/(2*math.tan(math.radians(obs.self.gimbal_fov_deg/2)))
                        expected=((previous.width-1)/2+focal*sum(x*y for x,y in zip(ray,right))/z,
                                  (previous.height-1)/2+focal*sum(x*y for x,y in zip(ray,down))/z)
                chosen=min(boxes,key=lambda b:math.dist(b.center,expected))
                matched=(chosen.width==previous.width and chosen.height==previous.height and
                         math.dist(chosen.center,expected) < .15*chosen.width)
            else:
                chosen=max(boxes,key=lambda b:b.confidence);matched=False
            self.pixel_hits=self.pixel_hits+1 if matched else 1
            self.pixel_target=chosen
            self.pixel_motion_px=None
            H=self.geometry.homography
            if matched and H is not None and self.geometry.pair_old_digest==previous_digest:
                u,v=previous.center
                divisor=H[2,0]*u+H[2,1]*v+H[2,2]
                if abs(divisor)>1e-6:
                    static=((H[0,0]*u+H[0,1]*v+H[0,2])/divisor,
                            (H[1,0]*u+H[1,1]*v+H[1,2])/divisor)
                    static_pixel=static
                    self.pixel_motion_px=math.dist(chosen.center,static)
                    moving=2.5<=self.pixel_motion_px<=.12*chosen.width
                    self.motion_hits=self.motion_hits+1 if moving and now-self.motion_time<=1.5 else int(moving)
                    self.motion_time=now
                    if self.motion_hits>=2:self.motion_verified_until=now+8.
            elif not matched or now-self.motion_time>1.5:self.motion_hits=0
            if not matched:self.motion_verified_until=-math.inf
            strong=(chosen.category=='true_vehicle' and chosen.confidence>=.95 and chosen.class_margin>=.9)
            self.pixel_identity_hits=self.pixel_identity_hits+1 if matched and strong else int(strong)
            self.pixel_pose=(obs.self.gimbal_pan,obs.self.gimbal_tilt,obs.self.heading_deg,obs.self.gimbal_fov_deg)
            self.vision_state='PIXEL_TRACK' if self.pixel_hits >= 2 else 'PIXEL_CANDIDATE'
        else:
            self.pixel_target=None;self.pixel_hits=0;self.vision_state='NO_CANDIDATE'
            self.pixel_motion_px=None;self.motion_hits=0
            self.motion_verified_until=-math.inf
            self.pixel_identity_hits=0
        self.geo_estimate=None
        if getattr(self,'enable_geometry',False) and self.pixel_hits>=2:
            self.geo_estimate=self.geometry.locate(self.pixel_target,now,digest)
            if self.geo_estimate is not None:
                g=self.geo_estimate
                box=self.pixel_target
                identity=(box.category if box.category in ('true_vehicle','decoy_vehicle')
                          and box.confidence>=getattr(self,'identity_confidence',.9)
                          and box.class_margin>=getattr(self,'identity_margin',.6) else 'unknown')
                if (not getattr(self,'require_candidate_motion',False) or
                        (identity=='true_vehicle' and self.motion_hits>=2 and now-self.motion_time<=.6)):
                    self.pending_geo=[SimpleNamespace(target_lat=g.latitude,target_lon=g.longitude,
                        uncertainty_m=g.uncertainty_m,source=g.source,identity=identity,ground_m=g.ground_plane_m)]
        # A short high-confidence pixel track may have only two usable ground
        # estimates before recentering the camera. Verify displacement against
        # the static background in the same image/plane instead of waiting for
        # the navigation track's separate confirmation window.
        self.pixel_ground_speed_mps=None
        g=self.geo_estimate;b=self.pixel_target
        if g is not None and b is not None and static_pixel is not None and .4<=now-previous_photo_time<=1.:
            points=[]
            for u,v in (b.center,static_pixel):
                ray=pixel_ray(u,v,b.width,b.height,obs.self.gimbal_fov_deg,'horizontal',
                    obs.self.gimbal_pan,obs.self.gimbal_tilt,obs.self.heading_deg,'heading_plus_pan')
                if ray[2]>=-.35:break
                scale=(g.ground_plane_m-obs.self.alt)/ray[2]
                points.append((ray[0]*scale,ray[1]*scale))
            if len(points)==2:self.pixel_ground_speed_mps=math.dist(*points)/(now-previous_photo_time)
        fast_ok=(g is not None and b is not None and self.pixel_identity_hits>=2 and self.motion_hits>=2
            and self.pixel_ground_speed_mps is not None and 3.5<=self.pixel_ground_speed_mps<=18.
            and g.uncertainty_m<=getattr(self,'fast_report_uncertainty_limit',90.) and obs.self.gimbal_tilt<=-70.)
        old_fast=self.fast_geo
        consistent=(old_fast is not None and 0<now-old_fast.receipt_sim_s<=1.
            and math.hypot((g.latitude-old_fast.latitude)*111320,
                (g.longitude-old_fast.longitude)*111320*math.cos(math.radians(g.latitude)))
                <=10.+35.*(now-old_fast.receipt_sim_s)) if fast_ok else False
        self.fast_geo_hits=(self.fast_geo_hits+1 if fast_ok and old_fast is not None
            and consistent else int(fast_ok))
        self.fast_geo=g if fast_ok else None
        return []

    def aim_gimbal(self, own, now, pan, tilt, formation=False):
        motion_ok=(not getattr(self,'require_candidate_motion',False) or
                   now<=self.motion_verified_until)
        if motion_ok and self.pixel_target is not None and self.pixel_hits >= 2 and 0 <= now-self.photo_time <= 1.:
            if math.isfinite(own.gimbal_pan) and math.isfinite(own.gimbal_tilt):
                self.vision_stats['servo_commands']+=1
                if self.pixel_pose is not None:
                    # A held frame specifies one world bearing. Repeated control
                    # ticks must not integrate the same old image error again.
                    p,t,h,fov=self.pixel_pose;b=self.pixel_target
                    ray=pixel_ray(*b.center,b.width,b.height,fov,'horizontal',p,t,h,'heading_plus_pan')
                    yaw=math.degrees(math.atan2(ray[0],ray[1]))
                    elevation=math.degrees(math.atan2(ray[2],math.hypot(ray[0],ray[1])))
                    return (yaw-own.heading_deg+180)%360-180,max(-89.,min(-15.,elevation))
                return center_gimbal(self.pixel_target,own.gimbal_pan,own.gimbal_tilt)
        if formation:
            assignment=getattr(self,'assignment',None)
            if assignment and assignment.ground_m is not None and assignment.target is not None:
                position=self.frame.xy(own.lat,own.lon)
                distance=max(1.,math.dist(position,assignment.target))
                tilt=-math.degrees(math.atan2(max(60.,own.alt-assignment.ground_m),distance))
            return pan,tilt
        # Near-nadir coverage gives more consistent scale and less tree occlusion.
        return 0.,-80.

    def decide(self, obs, dt):
        commands=super().decide(obs,dt)
        self.diagnostics.update(perception='own_public_rgb',vision_state=self.vision_state,
            vision=dict(self.vision_stats),vision_error=self.last_vision_error,pixel_hits=self.pixel_hits,
            localization='capture_alignment_and_height_unverified',identity='unknown',
            capture_sim_s=None,receipt_first_seen_sim_s=self.photo_time if math.isfinite(self.photo_time) else None,
            reports_enabled=False)
        self.diagnostics.update(geometry_mode='estimated' if getattr(self,'enable_geometry',False) else 'disabled',
            chosen_pixel=asdict(self.pixel_target) if self.pixel_target is not None else None,
            geometry_state=self.geometry.status,
            geo_estimate=asdict(self.geo_estimate) if self.geo_estimate is not None else None,
            search_strip=self.coverage.index,search_laps=self.coverage.laps)
        now=self.clock.previous
        independent=getattr(self,'independent_reports',False)
        key=((self.my_uid,self.coordinator.local_id) if self.coordinator.local_id is not None else None) if independent else self.coordinator.key
        report_track=self.bank.tracks.get(key[1]) if key and key[0]==self.my_uid else None
        self.diagnostics['report_candidate']=dict(local_track_id=self.coordinator.local_id,
            selected_owner=key[0] if key else None,
            identity=report_track.identity if report_track else None,
            identity_hits=report_track.identity_hits if report_track else 0,
            age_s=now-report_track.sample_s if report_track and now is not None else None,
            source=report_track.source if report_track else None)
        if (commands and obs.self.uid==self.my_uid and obs.self.status=='active'
                and getattr(self,'enable_reports',False) and getattr(self,'report_from_geo_bank',True)
                and now is not None and key and key[0]==self.my_uid):
            track=self.bank.tracks.get(key[1])
            if (track and track.source=='own_rgb_motion_plane_estimate' and track.identity=='true_vehicle'
                    and track.identity_hits>=getattr(self,'report_min_hits',8) and self.geo_estimate is not None
                    and (not getattr(self,'require_report_motion',False) or
                         (self.motion_hits>=2 and 0<=now-self.motion_time<=.6))
                    and self.geo_estimate.uncertainty_m<=getattr(self,'report_uncertainty_limit',80.) and self.pixel_target is not None
                    and self.pixel_target.category=='true_vehicle'
                    and self.pixel_target.confidence>=getattr(self,'identity_confidence',.9)
                    and self.pixel_target.class_margin>=getattr(self,'identity_margin',.6)
                    and 0<=now-self.photo_time<=.6
                    and self.geo_estimate.image_sha256==self.photo_digest
                    and 0<=now-self.geo_estimate.receipt_sim_s<=.6
                    and math.dist(track.predict(now),self.frame.xy(self.geo_estimate.latitude,
                                  self.geo_estimate.longitude))<=80):
                assignment=Assignment(self.diagnostics['state'],key[0],key[1],track.predict(now),
                                      self.diagnostics['members'],key[0])
                position=self.reporter.position(assignment,self.my_uid,now,identified=True,
                                                fresh=0<=now-track.sample_s<=.6,require_observe=not independent)
                if position is not None:
                    commands.append(report_target(*self.frame.geo(*position)));self.report_count+=1
        g=self.fast_geo
        if (commands and getattr(self,'fast_pixel_reports',False) and getattr(self,'enable_reports',False)
                and obs.self.uid==self.my_uid and obs.self.status=='active' and now is not None
                and g is not None and self.fast_geo_hits>=2 and self.pixel_hits>=4
                and self.pixel_identity_hits>=getattr(self,'fast_report_identity_hits',4)
                and g is self.geo_estimate and self.pixel_target is not None
                and self.pixel_target.category=='true_vehicle' and self.pixel_target.confidence>=.95
                and self.pixel_target.class_margin>=.9 and self.motion_hits>=2
                and self.pixel_ground_speed_mps is not None and 3.5<=self.pixel_ground_speed_mps<=18.
                and g.uncertainty_m<=getattr(self,'fast_report_uncertainty_limit',90.)
                and g.image_sha256==self.photo_digest and 0<=now-g.receipt_sim_s<=.6):
            candidate=self.frame.xy(g.latitude,g.longitude)
            assignment=Assignment('OBSERVE',self.my_uid,0,candidate,(self.my_uid,),self.my_uid)
            position=self.reporter.position(assignment,self.my_uid,now,identified=True,fresh=True,require_observe=False)
            if position is not None:
                commands.append(report_target(*self.frame.geo(*position)))
                self.report_count+=1;self.fast_report_count+=1
        self.diagnostics.update(reports_enabled=bool(getattr(self,'enable_reports',False)),reports_sent=self.report_count,
            independent_reports=independent,identity_confidence=getattr(self,'identity_confidence',.9),
            identity_margin=getattr(self,'identity_margin',.6))
        self.diagnostics.update(pixel_motion_px=self.pixel_motion_px,motion_hits=self.motion_hits,
            require_report_motion=getattr(self,'require_report_motion',False),
            pixel_identity_hits=self.pixel_identity_hits,pixel_ground_speed_mps=self.pixel_ground_speed_mps,
            fast_geo_hits=self.fast_geo_hits,fast_reports_sent=self.fast_report_count)
        return commands


import cv2
