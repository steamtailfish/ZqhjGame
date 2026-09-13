"""Search, visual acquisition and acknowledged two-aircraft observation.

Only local RGB estimates and authenticated-by-SDK sender identities are used.
The local joint timer is an estimate, never a claim about the hidden judge.
"""
from dataclasses import dataclass
import math

from zqhj_comm import Packet, encode
from zqhj_cooperation import Assignment
from zqhj_localization import pixel_ray
from zqhj_planner import guide_heading
from zqhj_score_search import ScoreSearchAgent
from zqhj_state import wrap


SEARCH, VERIFY, OFFER, APPROACH, TRACK, RECOVER, RELEASE = range(7)
CAPTURE_PHASES = ('SEARCH','VERIFY','OFFER','APPROACH','TRACK_PAIR','RECOVER','RELEASE')


@dataclass
class CaptureSight:
    target: tuple
    velocity: tuple
    ground: float
    sample: float
    sigma: float
    confirmed: bool = False
    visible: bool = False


@dataclass
class CaptureMission:
    owner: str
    number: int
    partner: str | None
    target: tuple
    velocity: tuple
    ground: float
    sample: float
    created: float
    deadline: float
    last_seen: float
    sigma: float = 110.

    @property
    def key(self):return self.owner,self.number

    def predict(self,now):
        dt=max(0.,min(3.,now-self.sample))
        return tuple(self.target[i]+self.velocity[i]*dt for i in (0,1))


@dataclass
class CaptureIdentity:
    """Short local identity memory; never rewrites classifier output."""
    key: tuple
    point: tuple
    velocity: tuple
    area: float
    sample: float
    last_true: float
    digest: str
    decoy_hits: int = 0
    decoy_since: float | None = None
    revoked: bool = False

    def fresh(self,now):
        return (not self.revoked and 0<=now-self.sample<=2.
                and 0<=now-self.last_true<=3.)

    def predict(self,now):
        dt=max(0.,min(2.,now-self.sample))
        return tuple(self.point[i]+self.velocity[i]*dt for i in (0,1))

    def matches(self,point,area,now):
        return (self.fresh(now) and math.dist(point,self.predict(now))<=25.
                and self.area>0 and .35<=area/self.area<=2.85)

    def observe(self,box,point,area,now,digest):
        if digest==self.digest:return self.fresh(now)
        if now<=self.sample or not self.matches(point,area,now):return False
        positive=(box.category=='true_vehicle' and box.confidence>=.9 and box.class_margin>=.8)
        contradiction=(box.category=='decoy_vehicle' and box.confidence>=.9 and box.class_margin>=.8)
        if contradiction:
            if not self.decoy_hits:self.decoy_since=now
            self.decoy_hits+=1
        else:self.decoy_hits=0;self.decoy_since=None
        if self.decoy_hits>=3 and now-self.decoy_since>=1.-1e-9:
            self.revoked=True;return False
        if positive:self.last_true=now
        dt=now-self.sample;measured=tuple((point[i]-self.point[i])/dt for i in (0,1))
        if math.hypot(*measured)<=25.:
            self.velocity=tuple(.7*self.velocity[i]+.3*measured[i] for i in (0,1))
        self.point=point;self.area=area;self.sample=now;self.digest=digest
        return True


class CaptureCoordinator:
    def __init__(self,uid):
        self.uid=uid;self.roster=None;self.mission=None;self.sequence=0
        self.phase=SEARCH;self.visible=False;self.ack=False
        self.joint_s=0.;self.max_joint_s=0.;self.last_both=None;self.previous_both=False
        self.last_step=None;self.release_until=-math.inf;self.cooldowns=[]
        self.last_selection=-math.inf
        self.verify_since=None;self.verify_point=None
        self.reason='search';self.attempts=0;self.pair_frames=0;self.sight=None
        self.owner_fix=None;self.pair_residual=None;self.pair_consistent=False

    def slot(self,uid):return self.roster.index(uid)+1 if self.roster and uid in self.roster else 0

    def uid_at(self,slot):
        return self.roster[slot-1] if self.roster and 1<=slot<=len(self.roster) else None

    def packet_key(self,p):
        owner=self.uid_at(p.owner_slot)
        return (owner,p.track_id) if p.capture and owner and p.track_id else None

    @staticmethod
    def eta(own,target,frame):
        position=frame.xy(own.lat,own.lon)
        bearing=math.degrees(math.atan2(target[0]-position[0],target[1]-position[1]))
        heading=getattr(own,'heading_deg',getattr(own,'heading',0.))
        return max(0.,math.dist(position,target)-350.)/32.+abs(wrap(bearing-heading))/20.

    def adopt(self,mission,now):
        self.mission=mission;self.joint_s=0.;self.last_both=None;self.previous_both=False
        self.ack=False;self.attempts+=1;self.reason='visual_mission'
        self.last_selection=now
        self.owner_fix=None;self.pair_residual=None;self.pair_consistent=False

    @staticmethod
    def aligned_distance(a,b):
        # Compare independent observations at one time, not either observation
        # with a mission point which may already have absorbed that observation.
        when=max(a.sample,b.sample)
        pa=tuple(a.target[i]+a.velocity[i]*(when-a.sample) for i in (0,1))
        pb=tuple(b.target[i]+b.velocity[i]*(when-b.sample) for i in (0,1))
        return math.dist(pa,pb)

    def owner_reference(self,now):
        fix=self.owner_fix
        return fix if fix and 0<=now-fix.sample<=.8+1e-9 else None

    def same_owner_target(self,sight,now):
        owner=self.owner_reference(now)
        if owner is None or sight is None or not 0<=now-sight.sample<=.8+1e-9:return False
        return self.aligned_distance(owner,sight)<=25.

    def finish(self,now,reason):
        if self.mission:
            self.cooldowns.append((self.mission.predict(now),now+60.))
        self.phase=RELEASE;self.release_until=now+2.;self.reason=reason
        self.visible=False;self.previous_both=False

    def step(self,own,peers,frame,now,sight):
        dt=0. if self.last_step is None else max(0.,min(.75,now-self.last_step))
        self.last_step=now;self.sight=sight;self.visible=False
        self.pair_residual=None;self.pair_consistent=False
        roster=tuple(sorted({self.uid,*peers}))
        if self.roster is None and len(roster)==3:self.roster=roster
        self.cooldowns=[item for item in self.cooldowns if item[1]>now]
        fresh={uid:p for uid,p in peers.items() if 0<=now-p.time_s<=1.5}
        if self.phase==RELEASE:
            if now<self.release_until:return self.assignment(now)
            self.mission=None;self.phase=SEARCH;self.joint_s=0.
        offers={}
        for uid,p in fresh.items():
            key=self.packet_key(p)
            if (key and key[0]==uid and p.stage in (OFFER,APPROACH,TRACK,RECOVER)
                    and p.identity=='true_vehicle' and now-p.time_s+p.age_s<=8.
                    and p.ground_m is not None and self.uid_at(p.partner_slot)!=uid):
                offers[key]=(uid,p)
        m=self.mission
        # Only an unacknowledged owner resolves simultaneous offers by UID.
        # An accepted pair holds its lease; a later discovery cannot steal it.
        candidates=list(offers)
        if m:candidates.append(m.key)
        winning=min(candidates,default=None)
        if winning in offers and (m is None or (m.owner==self.uid and not self.ack and winning<m.key)):
            owner,p=offers[winning];target=frame.xy(p.target_lat,p.target_lon)
            self.adopt(CaptureMission(owner,p.track_id,self.uid_at(p.partner_slot),target,
                (p.target_vx,p.target_vy),p.ground_m,p.time_s-p.age_s,now,now+160.,now,p.sigma_m),now)
            m=self.mission
        if m is None and sight and sight.confirmed and self.roster:
            if not any(math.dist(sight.target,p)<150 for p,_ in self.cooldowns):
                available=[(self.eta(p,sight.target,frame),uid) for uid,p in fresh.items()
                           if uid in self.roster and (not p.capture or p.stage in (SEARCH,VERIFY,RELEASE))]
                if available:
                    eta,partner=min(available);self.sequence=self.sequence%65535+1
                    self.adopt(CaptureMission(self.uid,self.sequence,partner,sight.target,sight.velocity,
                        sight.ground,sight.sample,now,now+max(45.,min(160.,eta+35.)),now,sight.sigma),now)
                    m=self.mission
        if m is None:
            hold=sight is not None and not any(math.dist(sight.target,p)<150 for p,_ in self.cooldowns)
            if hold:
                if self.verify_point is None or math.dist(self.verify_point,sight.target)>150.:
                    self.verify_point=sight.target;self.verify_since=now
                elif now-self.verify_since>8.:
                    self.cooldowns.append((sight.target,now+20.));hold=False
            elif sight is None:self.verify_point=None;self.verify_since=None
            self.phase=VERIFY if hold else SEARCH;self.reason='own_pixel_acquisition' if hold else 'search'
            return self.assignment(now)
        owner_packet=fresh.get(m.owner) if m.owner!=self.uid else None
        if owner_packet and self.packet_key(owner_packet)==m.key:
            if owner_packet.stage==RELEASE:
                self.finish(now,'owner_released');return self.assignment(now)
            m.partner=self.uid_at(owner_packet.partner_slot)
        members=(m.owner,m.partner)
        self.visible=(self.uid in members and sight is not None and sight.visible
                      and 0<=now-sight.sample<=.8
                      and math.dist(sight.target,m.predict(now))<=160.)
        views={self.uid:sight} if self.visible else {}
        for uid in members:
            p=fresh.get(uid)
            if (p and self.packet_key(p)==m.key and p.visible and p.identity=='true_vehicle'
                    and p.ground_m is not None and 0<=now-p.time_s+p.age_s<=.8):
                point=frame.xy(p.target_lat,p.target_lon)
                if math.dist(point,m.predict(now))<=160.:
                    views[uid]=CaptureSight(point,(p.target_vx,p.target_vy),p.ground_m,p.time_s-p.age_s,p.sigma_m)
        owner_view=views.get(m.owner)
        new_owner_view=False
        if owner_view:
            # This anchor is never learned from partner points or a relayed
            # owner packet with visible=False. Source-time quantization can
            # move a repeated radio sample by 0.1s, below this update spacing.
            if self.owner_fix is None or owner_view.sample-self.owner_fix.sample>.25:
                self.owner_fix=owner_view;new_owner_view=True
        partner_view=views.get(m.partner)
        reference=self.owner_reference(now)
        if reference and partner_view:
            self.pair_residual=self.aligned_distance(reference,partner_view)
            self.pair_consistent=self.same_owner_target(partner_view,now)
        if self.uid==m.partner:self.visible=self.visible and self.pair_consistent
        # v29 deliberately keeps navigation authority with the discovering
        # aircraft. Partner handoff needs separate evidence and is not enabled.
        if new_owner_view:
            newest=owner_view
            if newest.sample>m.sample:
                m.target=newest.target;m.velocity=newest.velocity;m.sample=newest.sample;m.ground=newest.ground
                m.sigma=newest.sigma
            m.last_seen=max(m.last_seen,newest.sample)
        # Owner broadcasts are also useful during approach even before this
        # aircraft can make its own independent visual confirmation.
        if owner_packet and self.packet_key(owner_packet)==m.key and owner_packet.time_s-owner_packet.age_s>m.sample:
            point=frame.xy(owner_packet.target_lat,owner_packet.target_lon)
            if math.dist(point,m.predict(now))<=160.:
                m.target=point;m.sample=owner_packet.time_s-owner_packet.age_s
                m.velocity=(owner_packet.target_vx,owner_packet.target_vy)
        partner_packet=fresh.get(m.partner)
        partner_ack=(partner_packet is not None and self.packet_key(partner_packet)==m.key
                     and partner_packet.stage in (APPROACH,TRACK,RECOVER)
                     and self.uid_at(partner_packet.partner_slot)==m.partner)
        if self.uid==m.partner:self.ack=True
        elif self.uid==m.owner:self.ack=partner_ack
        if self.uid==m.owner and not self.ack and now-self.last_selection>8.:
            alternatives=[(self.eta(p,m.predict(now),frame),uid) for uid,p in fresh.items()
                          if uid!=m.partner and uid in self.roster and p.stage in (SEARCH,VERIFY)]
            if alternatives:
                eta,m.partner=min(alternatives)
                m.deadline=now+max(45.,min(160.,eta+35.));self.last_selection=now
                self.reason='unacknowledged_partner_reassigned'
        both=(self.visible and owner_view is not None and partner_view is not None
              and self.pair_consistent and self.ack and self.uid in members)
        if both:
            if self.previous_both:self.joint_s+=dt
            self.last_both=now;self.max_joint_s=max(self.max_joint_s,self.joint_s);self.pair_frames+=1
        elif self.last_both is not None and now-self.last_both>2.:
            self.joint_s=0.
        self.previous_both=both
        if self.uid==m.owner and self.joint_s>=25.:
            self.finish(now,'local_joint_window_complete_not_judge_confirmation')
        elif now-m.last_seen>8.:
            self.finish(now,'visual_recovery_timeout')
        elif now>=m.deadline and self.last_both is None:
            self.finish(now,'join_deadline')
        elif now-m.created>200.:
            self.finish(now,'bounded_attempt')
        elif self.uid not in members:self.phase=SEARCH
        elif both:self.phase=TRACK
        elif self.last_both is not None:self.phase=RECOVER
        elif self.uid==m.owner:self.phase=APPROACH if self.ack else OFFER
        else:self.phase=APPROACH
        return self.assignment(now)

    def assignment(self,now):
        m=self.mission
        if self.phase==VERIFY and self.sight:
            # Classification alone must not turn the aircraft: the resulting
            # pose change interrupts motion-plane verification and can make a
            # static background proposal steer the entire search route.
            return Assignment('SEARCH',self.uid,0,None,(),None)
        if m:
            members=(m.owner,m.partner) if m.partner else (m.owner,)
            role='OBSERVE' if self.uid in members and self.phase!=RELEASE else 'SEARCH'
            return Assignment(role,m.owner,m.number,m.predict(now),members,m.owner,m.ground)
        return Assignment('SEARCH',None,None,None,(),None)


class CaptureSearchAgent(ScoreSearchAgent):
    def reset(self):
        super().reset();self.capture=CaptureCoordinator(self.my_uid)
        self.capture_bound=None;self.last_capture_fix=None;self.capture_sight=None
        self.capture_camera_track=None;self.capture_camera_until=-math.inf
        self.capture_identity=None;self.capture_identity_match=None
        self.capture_identity_state='unconfirmed'

    @staticmethod
    def project_box(box,own,ground,frame):
        ray=pixel_ray(*box.center,box.width,box.height,own.gimbal_fov_deg,'horizontal',
                      own.gimbal_pan,own.gimbal_tilt,own.heading_deg,'heading_plus_pan')
        if ray[2]>=-.2 or own.alt-ground<60:return None
        scale=(ground-own.alt)/ray[2]
        if math.hypot(ray[0]*scale,ray[1]*scale)>1200:return None
        x,y=frame.xy(own.lat,own.lon)
        return x+ray[0]*scale,y+ray[1]*scale

    def filter_boxes(self,boxes,own,now):
        m=self.capture.mission
        self.capture_identity_match=None
        if not m or self.my_uid not in (m.owner,m.partner) or self.capture.phase==RELEASE:
            self.capture_identity=None
            return super().filter_boxes(boxes,own,now)
        memory=self.capture_identity
        if memory and memory.key==m.key and memory.fresh(now):
            candidates=[]
            for b in boxes:
                if b.category not in ('true_vehicle','decoy_vehicle') or b.confidence<.55:continue
                point=self.project_box(b,own,m.ground,self.frame)
                area=self.ground_box_area(b,own,m.ground)
                if point is not None and memory.matches(point,area,now):
                    candidates.append((math.dist(point,memory.predict(now)),b,point,area))
            candidates.sort(key=lambda item:item[0])
            if not candidates:return []
            best=candidates[0]
            # Two spatially distinct, similarly plausible objects must not
            # inherit one identity. Overlapping contour fragments may agree.
            if any(c[0]-best[0]<6. and math.dist(c[2],best[2])>10. for c in candidates[1:]):
                memory.revoked=True;self.capture_bound=None;return []
            _,b,point,area=best
            self.capture_identity_match=(m.key,self.photo_digest,b,point,area)
            return [b]
        if memory:self.capture_bound=None
        self.capture_identity=None
        boxes=super().filter_boxes(boxes,own,now)
        selected=[]
        for b in boxes:
            point=self.project_box(b,own,m.ground,self.frame)
            if point is not None and math.dist(point,m.predict(now))<=160.:selected.append(b)
        return selected

    @staticmethod
    def ground_box_area(box,own,ground):
        points=[]
        for u,v in ((box.x1,box.y1),(box.x2,box.y1),(box.x1,box.y2)):
            ray=pixel_ray(u,v,box.width,box.height,own.gimbal_fov_deg,'horizontal',
                          own.gimbal_pan,own.gimbal_tilt,own.heading_deg,'heading_plus_pan')
            if ray[2]>=-.2:return 0.
            scale=(ground-own.alt)/ray[2];points.append((ray[0]*scale,ray[1]*scale))
        a,b,c=points
        return abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))

    def sight(self,own,frame,now):
        b=self.pixel_target;g=self.geo_estimate;m=self.capture.mission
        self.capture_identity_state='no_fresh_visual'
        memory=self.capture_identity
        if memory and (m is None or memory.key!=m.key or not memory.fresh(now)):
            self.capture_bound=None;self.capture_identity_match=None
        if b is None or not 0<=now-self.photo_time<=.8:return None
        positive=(b.category=='true_vehicle' and b.confidence>=.9 and b.class_margin>=.8)
        match=self.capture_identity_match;memory=self.capture_identity
        associated=(m is not None and memory is not None and memory.key==m.key
                    and match is not None and match[:3]==(m.key,self.photo_digest,b)
                    and memory.fresh(now))
        if not associated and (not positive or self.pixel_hits<2):return None
        camera=self.pixel_own or own
        valid_geo=(g is not None and g.image_sha256==self.photo_digest
                   and 0<=now-g.receipt_sim_s<=.8 and g.uncertainty_m<=150.)
        ground=g.ground_plane_m if valid_geo else m.ground if m else camera.alt-350.
        point=frame.xy(g.latitude,g.longitude) if valid_geo else self.project_box(b,camera,ground,frame)
        if point is None:return None
        if associated:
            point=match[3];ground=m.ground
            if not memory.observe(b,point,match[4],self.photo_time,self.photo_digest):
                self.capture_bound=None;self.capture_identity_state='identity_revoked';return None
            self.capture_bound=(m.key,self.pixel_track_id)
            self.capture_identity_state='current_true' if positive else 'remembered_true'
        strong=(positive and self.pixel_hits>=2 and self.pixel_identity_hits>=3
                and now<=self.motion_verified_until)
        if m and strong and math.dist(point,m.predict(now))<=80.:
            self.capture_bound=(m.key,self.pixel_track_id)
            if not associated:
                self.capture_identity=CaptureIdentity(m.key,point,m.velocity,
                    self.ground_box_area(b,camera,ground),self.photo_time,self.photo_time,self.photo_digest)
            self.capture_identity_state='current_true'
        bound=(m is not None and self.capture_bound==(m.key,self.pixel_track_id))
        visible=bound and math.dist(point,m.predict(now))<=160.
        confirmed=(strong and valid_geo and self.fast_geo_hits>=2 and g.uncertainty_m<=110.)
        velocity=memory.velocity if associated else (0.,0.)
        previous=self.last_capture_fix
        if not associated and previous and previous[0]==self.pixel_track_id:
            elapsed=self.photo_time-previous[1]
            velocity=previous[3]
            if .4<=elapsed<=2.:
                measured=tuple((point[i]-previous[2][i])/elapsed for i in (0,1))
                if math.hypot(*measured)<=25:
                    velocity=tuple(.7*velocity[i]+.3*measured[i] for i in (0,1))
        if previous is None or self.photo_time>previous[1]:
            self.last_capture_fix=(self.pixel_track_id,self.photo_time,point,velocity)
        return CaptureSight(point,velocity,ground,self.photo_time,
                            g.uncertainty_m if valid_geo else 150.,confirmed,visible)

    def coordinate(self,own,local,peers,frame,now):
        self.capture_sight=self.sight(own,frame,now)
        return self.capture.step(own,peers,frame,now,self.capture_sight)

    def communication_payload(self,own,local,frame,now):
        if now-self.radio.last_send<.5-1e-9:return None
        c=self.capture;m=c.mission;s=self.capture_sight
        active=m is not None
        target=m.target if active else (0.,0.)
        sample=m.sample if active else now
        velocity=m.velocity if active else (0.,0.)
        if c.visible and s:target,sample,velocity=s.target,s.sample,s.velocity
        lat,lon=frame.geo(*target) if active else (0.,0.)
        p=Packet(self.radio.seq,now,own.lat,own.lon,own.heading_deg,min(40.,max(0.,own.speed)),
                 track_id=m.number if active else 0,target_lat=lat,target_lon=lon,
                 age_s=max(0.,min(60.,now-sample)),hits=3 if active else 0,
                 sigma_m=m.sigma if active else 150.,ground_m=m.ground if active else None,
                 identity='true_vehicle' if active else 'unknown',capture=True,
                 owner_slot=c.slot(m.owner) if active else 0,partner_slot=c.slot(m.partner) if active else 0,
                 stage=c.phase,visible=c.visible,target_vx=velocity[0],target_vy=velocity[1])
        result=encode(p);self.radio.seq=(self.radio.seq+1)%65536;self.radio.last_send=now
        return result

    partner_orbit_radius=360.
    approach_margin=50.

    def orbit_radius(self,own,assignment):
        return 320. if assignment.owner==self.my_uid else self.partner_orbit_radius

    def partner_approaching(self,position,target,radius=None):
        m=self.capture.mission
        radius=self.partner_orbit_radius if radius is None else radius
        return bool(m and self.my_uid==m.partner and self.capture.phase==APPROACH
                    and math.dist(position,target)>radius+self.approach_margin)

    def camera_fov(self,own,formation):
        m=self.capture.mission
        if (formation and m and self.my_uid in (m.owner,m.partner)
                and self.capture.phase!=RELEASE):
            # A stable zoom enlarges an already nominated object's pixels.
            # Continuous range-based zoom would invalidate the equal-FOV
            # image pairs needed for motion/ground-plane verification.
            # Pointing and zoom alone never establish independent identity.
            return 30.
        return super().camera_fov(own,formation)

    def prepare_planner(self,own,target,formation,position):
        m=self.capture.mission
        self.planner.orbit_guidance_enabled=bool(formation and m
            and self.my_uid in (m.owner,m.partner) and self.capture.phase!=RELEASE
            and not self.partner_approaching(position,target))
        if formation and m and self.my_uid==m.partner and self.capture.phase==APPROACH:
            self.planner.cruise_speed=32. if self.partner_approaching(position,target) else 18.
        else:
            self.planner.cruise_speed=(32. if math.dist(position,target)>700 else 18.) if formation else 35.

    def guidance(self,position,velocity,target,motions,obstacles,formation,radius):
        m=self.capture.mission
        approach=formation and self.partner_approaching(position,target,radius)
        legacy=(formation and m and self.my_uid==m.partner and self.capture.phase!=APPROACH
                and math.dist(position,target)>650.)
        if approach or legacy:
            p=self.radio.peers.get(m.owner)
            if p and 0<=self.clock.previous-p.time_s<=1.5:
                owner=self.frame.xy(p.lat,p.lon);distance=max(1.,math.dist(owner,target))
                rendezvous=tuple(target[i]-(owner[i]-target[i])*radius/distance for i in (0,1))
                return guide_heading(position,velocity,rendezvous,motions,obstacles,formation=False)
            if approach:
                # A missing peer pose must not turn the acquisition leg into
                # an early orbit. The public mission point remains the guide;
                # the same primitive planner still enforces peer clearance.
                return guide_heading(position,velocity,target,motions,obstacles,formation=False)
        return super().guidance(position,velocity,target,motions,obstacles,formation,radius)

    def aim_gimbal(self,own,now,pan,tilt,formation=False):
        m=self.capture.mission
        if (m is None and self.pixel_target is not None and self.pixel_hits>=2
                and now<=self.motion_verified_until and 0<=now-self.photo_time<=.8
                and self.pixel_target.confidence>=.9 and self.pixel_target.class_margin>=.8):
            if self.capture_camera_track!=self.pixel_track_id:
                self.capture_camera_track=self.pixel_track_id;self.capture_camera_until=now+1.5
            # A fresh motion-confirmed image needs another stable pose pair
            # before the report/recruitment geometry can be confirmed. This
            # bounded hold prevents the pixel servo from destroying that pair.
            if self.fast_geo_hits<2 and now<self.capture_camera_until:
                return own.gimbal_pan,own.gimbal_tilt
        if formation and m and self.my_uid in (m.owner,m.partner) and self.capture.phase!=RELEASE:
            # The mission point follows the discovering aircraft's local
            # visual fixes or its legal broadcasts. Aim from the CURRENT own
            # position and heading, so body turns and translation are fully
            # compensated even when processing a repeated image. point_gimbal
            # accepts an orientation directly; the search servo's small relative
            # pan steps cannot keep up with a 30 deg/s aircraft turn, especially
            # near nadir where a large pan change is a small world LOS change.
            # The same command acquires a broadcast point immediately; it does
            # not establish identity, visibility, or authorize a target report.
            x,y=self.frame.xy(own.lat,own.lon);target=m.predict(now)
            pan=wrap(math.degrees(math.atan2(target[0]-x,target[1]-y))-own.heading_deg)
            tilt=-math.degrees(math.atan2(max(60.,own.alt-m.ground),max(1.,math.dist((x,y),target))))
            return pan,max(-89.,min(-15.,tilt))
        return super().aim_gimbal(own,now,pan,tilt,formation)

    def decide(self,obs,dt):
        result=super().decide(obs,dt);c=self.capture;m=c.mission
        self.diagnostics.update(strategy='search_verify_acknowledged_pair',capture=dict(
            phase=CAPTURE_PHASES[c.phase],owner=m.owner if m else None,partner=m.partner if m else None,
            mission=m.number if m else None,own_visual=c.visible,acknowledged=c.ack,
            local_joint_s=c.joint_s,max_local_joint_s=c.max_joint_s,paired_samples=c.pair_frames,
            reason=c.reason,attempts=c.attempts,judge_confirmed=False,
            identity_state=self.capture_identity_state,
            identity_last_true_s=self.capture_identity.last_true if self.capture_identity else None,
            identity_decoy_hits=self.capture_identity.decoy_hits if self.capture_identity else 0,
            pair_consistent=c.pair_consistent,pair_residual_m=c.pair_residual,
            owner_reference_sample_s=c.owner_fix.sample if c.owner_fix else None,
            owner_reference_xy=c.owner_fix.target if c.owner_fix else None,
            planner_goal_mode=getattr(self.planner,'last_goal_mode','straight'),
            target_update_authority='owner_only'))
        return result
