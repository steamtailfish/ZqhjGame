"""Paper-inspired analytic cooperative observation agent; public SDK inputs only.

EntryAgent uses the SDK's available detections as UNVERIFIED candidates.
VisualEntryAgent fails closed until the existing capture-aligned projector can
be paired with an online detector. Neither class identifies true vehicles yet.
"""
import math

from competition.sdk.core.commands import broadcast, point_gimbal, set_gimbal_fov, set_heading, set_speed
from competition.sdk.scenarios.coop_decoy.agent import CoopAgent

from zqhj_comm import Radio
from zqhj_cooperation import Coordinator, Reporter
from zqhj_features import planning_record
from zqhj_planner import Circle, PeerMotion, PrimitivePlanner, guide_heading
from zqhj_state import LocalFrame, SimClock, StatsDelta, TrackBank, detections, finite, valid_geo, wrap


class EntryAgent(CoopAgent):
    """Untrained guide policy with bounded trajectories and a K=2 rendezvous."""

    def reset(self):
        self.clock = SimClock()
        self.radio = Radio(self.my_uid)
        self.bank = TrackBank()
        self.coordinator = Coordinator(self.my_uid)
        self.reporter = Reporter()
        self.planner = self.create_planner()
        self.stats = StatsDelta()
        self.frame = None
        self.last_control = -math.inf
        self.search_index = sum(self.my_uid.encode('utf-8')) % 4
        self.decision_count = 0
        self.diagnostics = {'state':'RESET','identification':'unverified'}

    def create_planner(self):
        return PrimitivePlanner()

    def on_planning_input(self, record, now):
        """Offline recording subclasses may retain this instance's public data in memory."""
        return None

    def perception_candidates(self, own):
        return detections(own)

    def aim_gimbal(self, own, now, pan, tilt, formation=False):
        return pan,tilt

    def navigation_commands(self,own,plan,frame):
        return [set_heading(plan.heading),set_speed(plan.speed)]

    def prepare_planner(self,own,target,formation,position):pass

    def camera_fov(self,own,formation):return 50.

    def coordinate(self,own,local,peers,frame,now):
        return self.coordinator.assign(local,peers,frame,now)

    def communication_payload(self,own,local,frame,now):
        return self.radio.send(own,local,frame,now)

    def orbit_radius(self,own,assignment):return 450.

    def guidance(self,position,velocity,target,motions,obstacles,formation,radius):
        return guide_heading(position,velocity,target,motions,obstacles,radius=radius,formation=formation)

    def decide(self, obs, dt):
        self.decision_count += 1
        now,state = self.clock.step(obs.briefing)
        if state == 'rewind':
            self.reset()
            self.clock.previous = now
            self.diagnostics['state'] = 'TIME_REWIND'
            return []
        if state in ('missing','duplicate'):
            return []
        own = obs.self
        if (own.uid != self.my_uid or own.status == 'destroyed' or not valid_geo(own.lat,own.lon)
                or not finite(own.alt,own.heading_deg,own.speed) or own.alt <= 0 or not 0 <= own.speed <= 41):
            self.diagnostics['state'] = 'INVALID_SELF'
            return []
        area = obs.briefing.mission_area
        if self.frame is None:
            if area and valid_geo(area.lat_min,area.lon_min) and valid_geo(area.lat_max,area.lon_max):
                self.frame = LocalFrame((area.lat_min+area.lat_max)/2,(area.lon_min+area.lon_max)/2)
            else:
                self.frame = LocalFrame(own.lat,own.lon)
        frame = self.frame
        bounds = None
        if area and valid_geo(area.lat_min,area.lon_min) and valid_geo(area.lat_max,area.lon_max):
            xmin,ymin = frame.xy(area.lat_min,area.lon_min)
            xmax,ymax = frame.xy(area.lat_max,area.lon_max)
            if xmin < xmax and ymin < ymax:
                bounds = xmin,xmax,ymin,ymax
        peers = self.radio.receive(obs.comm_inbox,now)
        self.bank.update(self.perception_candidates(own),frame,now)
        local = self.coordinator.local_track(self.bank,now)
        assignment = self.coordinate(own,local,peers,frame,now)
        self.assignment=assignment
        delta = self.stats.update(own.comm_stats)
        commands = []
        payload = self.communication_payload(own,local,frame,now)
        if payload is not None:
            commands.append(broadcast(payload))
        if now-self.last_control < .5-1e-9:
            return commands
        self.last_control = now
        position = frame.xy(own.lat,own.lon)
        angle = math.radians(own.heading_deg)
        velocity = own.speed*math.sin(angle),own.speed*math.cos(angle)
        motions = []
        for p in peers.values():
            x,y = frame.xy(p.lat,p.lon)
            h,age = math.radians(p.heading),now-p.time_s
            vx,vy = p.speed*math.sin(h),p.speed*math.cos(h)
            motions.append(PeerMotion(x+vx*age,y+vy*age,vx,vy,age))
        obstacles = []
        for zone in obs.briefing.known_threats:
            if zone.kind != 'no_fly' or not zone.alt_min <= own.alt <= zone.alt_max or not zone.polygon:
                continue
            if not all(valid_geo(lat,lon) for lat,lon in zone.polygon):
                continue
            points = [frame.xy(lat,lon) for lat,lon in zone.polygon]
            center = tuple(sum(p[i] for p in points)/len(points) for i in (0,1))
            obstacles.append(Circle(*center,max(math.dist(center,p) for p in points)))
        formation = assignment.role in ('OBSERVE','ACQUIRE') and assignment.target is not None
        target = assignment.target if formation else self.search_goal(position,bounds)
        self.prepare_planner(own,target,formation,position)
        radius = self.orbit_radius(own,assignment)
        desired = self.guidance(position,velocity,target,motions,obstacles,formation,radius)
        self.on_planning_input(planning_record(position,own.heading_deg,own.speed,desired,motions,bounds,
                                              obstacles,target if formation else None),now)
        plan = self.planner.plan(position,own.heading_deg,own.speed,desired,motions,bounds,
                                 obstacles,target if formation else None,radius=radius)
        commands.extend(self.navigation_commands(own,plan,frame))
        if formation:
            dx,dy = target[0]-position[0],target[1]-position[1]
            pan = wrap(math.degrees(math.atan2(dx,dy))-own.heading_deg)
            # Conditional aiming model only: heading-relative pan and ground datum 0.
            # This is NOT used to generate visual coordinates or claim calibration.
            tilt = -math.degrees(math.atan2(own.alt,max(1.,math.hypot(dx,dy))))
        else:
            pan,tilt = 45*math.sin(now/6),-65.
        pan,tilt = self.aim_gimbal(own,now,pan,tilt,formation=formation)
        commands.extend((point_gimbal(pan,tilt),set_gimbal_fov(self.camera_fov(own,formation))))
        self.diagnostics = dict(state=assignment.role,owner=assignment.owner,
            candidate=assignment.track_id,members=assignment.members,tracks=len(self.bank.tracks),
            public_peer_count=len(peers),plan_feasible=plan.feasible,planner_reason=plan.reason,
            clearance_m=plan.clearance_m if math.isfinite(plan.clearance_m) else None,
            costs=plan.terms,comm_delta=delta,identification='unverified',reports_enabled=False,
            planner_source=getattr(self.planner,'last_source','analytic'),
            neural_selected=getattr(self.planner,'selected_count',0),
            neural_fallback=getattr(self.planner,'fallback_count',0),
            perception='sdk_candidate_unverified',gimbal_model='heading_relative_pan_ground_datum_0_unverified')
        return commands

    def search_goal(self, position, bounds):
        if bounds:
            xmin,xmax,ymin,ymax = bounds
            mx,my = min(400.,(xmax-xmin)*.25),min(400.,(ymax-ymin)*.25)
            points = ((xmin+mx,ymin+my),(xmin+mx,ymax-my),
                      (xmax-mx,ymax-my),(xmax-mx,ymin+my))
        else:
            points = ((-400.,-400.),(-400.,400.),(400.,400.),(400.,-400.))
        if math.dist(position,points[self.search_index]) < 150:
            self.search_index = (self.search_index+1) % 4
        return points[self.search_index]


class VisualEntryAgent(EntryAgent):
    """Fail closed: do not silently fall back to the SDK's single-camera detector."""
    def sensor(self, obs, dt):
        return []
