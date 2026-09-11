"""Score-oriented cooperative sweep, using own state and broadcast telemetry."""
import math
from statistics import median
from zqhj_async import AsyncPhotoEntryAgent
from zqhj_state import wrap


class TeamPhotoEntryAgent(AsyncPhotoEntryAgent):
    def reset(self):
        super().reset()
        self.team_roster=None;self.sweep_points=[];self.sweep_index=0
        self.search_focus=None;self.search_ground=None;self.follow_slot=None
        self.follow_velocity=None;self.current_own=None
        if hasattr(getattr(self,'detector',None),'confidence'):self.detector.confidence=.45

    def eligible_boxes(self,boxes):
        return [b for b in boxes if b.category!='decoy_vehicle' and b.confidence>=.55]

    def decide(self,obs,dt):
        self.current_own=obs.self
        now=getattr(obs.briefing.score_view,'sim_time',None)
        if now is not None:
            heights=[f[1] for f in self.geometry.fits if 0<=now-f[0]<=4.]
            self.radio.ground_m=median(heights) if len(heights)>=3 else None
        commands=super().decide(obs,dt)
        self.diagnostics.update(strategy='cooperative_sweep',sweep_index=self.sweep_index,
            team_roster=self.team_roster,cruise_speed=self.planner.cruise_speed)
        return commands

    def search_goal(self,position,bounds):
        peers=self.radio.peers;roster=tuple(sorted({self.my_uid,*peers}))
        if self.team_roster is None and len(roster)==3:self.team_roster=roster
        self.follow_slot=None;self.follow_velocity=None
        own=self.current_own;h=math.radians(own.heading_deg)
        if self.team_roster is None:
            self.search_focus=None
            return position[0]+800*math.sin(h),position[1]+800*math.cos(h)
        leader=self.team_roster[0]
        if self.my_uid!=leader and leader in peers:
            p=peers[leader];h=math.radians(p.heading);fx,fy=math.sin(h),math.cos(h)
            x,y=self.frame.xy(p.lat,p.lon);age=max(0.,self.clock.previous-p.time_s)
            x,y=x+p.speed*fx*age,y+p.speed*fy*age
            side=1. if self.team_roster.index(self.my_uid)==1 else -1.
            self.follow_slot=(x-150*fx+side*350*fy,y-150*fy-side*350*fx)
            self.follow_velocity=(p.speed,fx,fy)
            self.search_focus=(x+250*fx,y+250*fy);self.search_ground=p.ground_m
            return self.follow_slot[0]+500*fx,self.follow_slot[1]+500*fy
        self.search_focus=(position[0]+250*math.sin(h),position[1]+250*math.cos(h))
        self.search_ground=getattr(self.radio,'ground_m',None)
        if not bounds:return position[0]+1000*math.sin(h),position[1]+1000*math.cos(h)
        if not self.sweep_points:
            xmin,xmax,ymin,ymax=bounds;cx,cy=(xmin+xmax)/2,(ymin+ymax)/2
            sx,sy=min(1200.,(xmax-xmin)/2-500),min(1200.,(ymax-ymin)/2-500)
            lanes=[0.]
            for i in range(1,max(1,int(sx/280))+1):lanes.extend((280.*i,-280.*i))
            self.sweep_points=[(cx,cy)]
            for i,x in enumerate(lanes):
                direction=1 if i%2==0 else -1
                self.sweep_points.extend([(cx+x,cy+direction*sy),(cx+x,cy-direction*sy)])
        if math.dist(position,self.sweep_points[self.sweep_index])<130.:
            self.sweep_index=(self.sweep_index+1)%len(self.sweep_points)
        return self.sweep_points[self.sweep_index]

    def prepare_planner(self,own,target,formation,position):
        if formation:
            distance=math.dist(position,target)
            self.planner.cruise_speed=32. if distance>750 else 22.
        elif self.follow_slot is not None:
            speed,fx,fy=self.follow_velocity
            along=(self.follow_slot[0]-position[0])*fx+(self.follow_slot[1]-position[1])*fy
            self.planner.cruise_speed=max(15.,min(35.,speed+.05*along))
        else:self.planner.cruise_speed=20.

    def camera_fov(self,own,formation):return 35.

    def aim_gimbal(self,own,now,pan,tilt,formation=False):
        assignment=getattr(self,'assignment',None)
        if formation and assignment and assignment.target is not None:
            matches=(self.geo_estimate is not None and math.dist(self.frame.xy(self.geo_estimate.latitude,
                      self.geo_estimate.longitude),assignment.target)<=80.)
            if assignment.owner==self.my_uid or matches:
                return super().aim_gimbal(own,now,pan,tilt,formation=True)
            ground=assignment.ground_m if assignment.ground_m is not None else (getattr(self.radio,'ground_m',None) or 0.)
            distance=math.dist(self.frame.xy(own.lat,own.lon),assignment.target)
            return pan,-math.degrees(math.atan2(max(60.,own.alt-ground),max(1.,distance)))
        if self.search_focus is not None:
            if self.team_roster and self.my_uid==self.team_roster[0] and self.pixel_hits>=2:
                return super().aim_gimbal(own,now,pan,tilt)
            x,y=self.frame.xy(own.lat,own.lon);dx,dy=self.search_focus[0]-x,self.search_focus[1]-y
            ground=self.search_ground if self.search_ground is not None else (getattr(self.radio,'ground_m',None) or 0.)
            return wrap(math.degrees(math.atan2(dx,dy))-own.heading_deg),-math.degrees(math.atan2(max(60.,own.alt-ground),max(1.,math.hypot(dx,dy))))
        return 0.,-80.
