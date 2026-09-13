"""Gou APF guide + YOPO-inspired primitive scoring, adapted to fixed-wing SDK.

This is an analytic receding-horizon baseline, not a trained YOPO/MRA-RLEC model.
All geometry passed here must originate in own observations or legal messages.
"""
from dataclasses import dataclass
import math

from zqhj_state import wrap


@dataclass(frozen=True)
class PeerMotion:
    x: float
    y: float
    vx: float
    vy: float
    age_s: float = 0.


@dataclass(frozen=True)
class Circle:
    x: float
    y: float
    radius: float


@dataclass(frozen=True)
class Plan:
    heading: float
    speed: float
    feasible: bool
    clearance_m: float
    cost: float
    terms: dict
    path: tuple
    reason: str


def segment_distance(a, b, point=(0.,0.)):
    dx,dy = b[0]-a[0],b[1]-a[1]
    den = dx*dx+dy*dy
    u = max(0.,min(1.,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/den)) if den else 0.
    return math.hypot(a[0]+u*dx-point[0],a[1]+u*dy-point[1])


def guide_heading(position, velocity, target, peers=(), obstacles=(), radius=450.,
                  formation=False):
    """Eqs. (7)-(10): radial attraction, repulsion, damping + fixed-wing tangent.

    Gains are engineering defaults in meters, not the paper's vehicle parameters.
    The tangent prevents the guide from asking a fixed-wing aircraft to stop.
    """
    x,y = position
    dx,dy = target[0]-x,target[1]-y
    distance = max(1e-6,math.hypot(dx,dy))
    desired_radius = radius if formation else 0.
    fx,fy = .08*(distance-desired_radius)*dx/distance,.08*(distance-desired_radius)*dy/distance
    if formation:
        fx,fy = fx+22*dy/distance,fy-22*dx/distance
    for peer in peers:
        ex,ey = x-peer.x,y-peer.y
        d = max(1e-6,math.hypot(ex,ey))
        reach = 2*radius if formation else 300.
        gain = .06*max(0.,reach-d)
        fx,fy = fx+gain*ex/d,fy+gain*ey/d
    for obstacle in obstacles:
        ex,ey = x-obstacle.x,y-obstacle.y
        d = max(1e-6,math.hypot(ex,ey))
        gain = .3*max(0.,obstacle.radius+150-d)
        fx,fy = fx+gain*ex/d,fy+gain*ey/d
    fx,fy = fx-.15*velocity[0],fy-.15*velocity[1]
    if math.hypot(fx,fy) < 1e-6:
        fx,fy = velocity if math.hypot(*velocity) > 0 else (0.,1.)
    return math.degrees(math.atan2(fx,fy)) % 360


class PrimitivePlanner:
    horizon_s = 4.
    step_s = .25
    command_s = .5
    cruise_speed = 22.
    orbit_guidance_enabled = False
    last_goal_mode = 'straight'

    def plan(self, position, heading, speed, desired_heading, peers=(), bounds=None,
             obstacles=(), target=None, radius=450.):
        """Evaluate feasible constant-turn/acceleration anchors, execute first step.

        YOPO eqs. (10), (15), (16), (18) inspire smoothness, time-integrated
        exponential clearance and temporary-goal costs. We enumerate these costs
        directly because no trained scorer or calibrated depth/ESDF is available.
        """
        rates = sorted(set((-30.,-15.,-5.,0.,5.,15.,30.,
                            max(-30.,min(30.,wrap(desired_heading-heading)/self.horizon_s)))))
        cruise=max(15.,min(40.,self.cruise_speed))
        goal = (position[0]+cruise*self.horizon_s*math.sin(math.radians(desired_heading)),
                position[1]+cruise*self.horizon_s*math.cos(math.radians(desired_heading)))
        self.last_goal_mode = 'straight'
        if (self.orbit_guidance_enabled and target is not None and radius > 0
                and abs(math.dist(position,target)-radius) <= 60.):
            # Follow the existing counterclockwise ENU orbit over the horizon.
            # A tangent-line endpoint otherwise penalizes the orbit's curvature.
            # SDK heading atan2(E,N) gives this orbit a negative heading rate.
            angle = math.atan2(position[1]-target[1],position[0]-target[0])
            angle += cruise*self.horizon_s/radius
            goal = (target[0]+radius*math.cos(angle),target[1]+radius*math.sin(angle))
            curvature_rate = max(-30.,min(30.,-math.degrees(cruise/radius)))
            rates = sorted(set((*rates,curvature_rate)))
            self.last_goal_mode = 'orbit_arc'
        plans = []
        for rate in rates:
            for desired_speed in sorted({15.,22.,30.,cruise}):
                x,y,h,v = *position,heading,speed
                path = [(0.,x,y)]
                clearance = math.inf
                safety = 0.
                smoothness = 0.
                for k in range(1,round(self.horizon_s/self.step_s)+1):
                    t,dt = k*self.step_s,self.step_s
                    prev = (x,y)
                    nv = max(15.,min(40.,v+max(-5*dt,min(5*dt,desired_speed-v))))
                    mid = math.radians(h+rate*dt/2)
                    x,y = x+(v+nv)/2*math.sin(mid)*dt,y+(v+nv)/2*math.cos(mid)*dt
                    smoothness += ((rate/30)**2+((nv-v)/(5*dt))**2*.05)*dt
                    h,v = h+rate*dt,nv
                    margins = []
                    if bounds is not None:
                        xmin,xmax,ymin,ymax = bounds
                        margins.append(min(prev[0]-xmin,xmax-prev[0],prev[1]-ymin,ymax-prev[1],
                                           x-xmin,xmax-x,y-ymin,ymax-y)-100.)
                    for p in peers:
                        a = (prev[0]-p.x-p.vx*(t-dt),prev[1]-p.y-p.vy*(t-dt))
                        b = (x-p.x-p.vx*t,y-p.y-p.vy*t)
                        # Conservative growth for stale public telemetry and unknown turns.
                        uncertainty = 2.+40*p.age_s+13*t*t
                        margins.append(segment_distance(a,b)-220.-uncertainty)
                    for o in obstacles:
                        margins.append(segment_distance(prev,(x,y),(o.x,o.y))-o.radius-50.)
                    if margins:
                        c = min(margins)-1.  # chord integration margin
                        clearance = min(clearance,c)
                        safety += math.exp(max(-50.,min(30.,-c/60.)))*dt
                    path.append((t,x,y))
                goal_cost = ((x-goal[0])**2+(y-goal[1])**2)/(cruise*self.horizon_s)**2
                ring_cost = ((math.dist((x,y),target)-radius)/radius)**2 if target else 0.
                terms = dict(smoothness=smoothness,safety=safety,goal=goal_cost,ring=ring_cost)
                cost = .08*smoothness+3*safety+goal_cost+2*ring_cost
                first_heading = (heading+rate*self.command_s) % 360
                first_speed = max(15.,min(40.,speed+max(-2.5,min(2.5,desired_speed-speed))))
                feasible = clearance >= 0
                plans.append(Plan(first_heading,first_speed,feasible,clearance,cost,terms,
                                  tuple(path),'feasible' if feasible else 'no_feasible_primitive'))
        valid = [p for p in plans if p.feasible]
        if valid:
            return min(valid,key=lambda p:p.cost)
        # Fixed wing cannot stop. Expose infeasibility and maximize worst clearance.
        return max(plans,key=lambda p:(p.clearance_m,-p.cost))
