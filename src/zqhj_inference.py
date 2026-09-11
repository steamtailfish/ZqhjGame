"""Dependency-free neural inference plus conservative geometric safety checks.

Weights are embedded in the exported module, never read from files by Agent.
"""
import math

from zqhj_features import FEATURE_VERSION, FEATURE_DIM, feature_vector, planning_record
from zqhj_planner import Plan, segment_distance


def dense(values,weight,bias,activation=False):
    output = [sum(v*w for v,w in zip(values,row))+b for row,b in zip(weight,bias)]
    return [math.tanh(x) for x in output] if activation else output


class EmbeddedPolicy:
    def __init__(self, version, weights):
        if version != FEATURE_VERSION:
            raise ValueError('checkpoint feature contract mismatch')
        shapes = {'encoder.0.weight':(64,FEATURE_DIM),'encoder.0.bias':(64,),
                  'encoder.2.weight':(64,64),'encoder.2.bias':(64,),
                  'offset_head.weight':(18,64),'offset_head.bias':(18,),
                  'score_head.weight':(9,64),'score_head.bias':(9,),
                  'anchors':(9,2),'offset_scale':(2,)}
        def freeze(value,shape):
            if not shape:
                if not isinstance(value,(int,float)) or not math.isfinite(value):
                    raise ValueError('nonfinite model weight')
                return float(value)
            if len(value) != shape[0]:
                raise ValueError('model weight shape mismatch')
            return tuple(freeze(v,shape[1:]) for v in value)
        if set(weights) != set(shapes):
            raise ValueError('model keys mismatch')
        self.weights = {k:freeze(weights[k],shape) for k,shape in shapes.items()}

    def predict(self, record):
        w = self.weights
        h = dense(feature_vector(record),w['encoder.0.weight'],w['encoder.0.bias'],True)
        h = dense(h,w['encoder.2.weight'],w['encoder.2.bias'],True)
        offsets = dense(h,w['offset_head.weight'],w['offset_head.bias'])
        scores = dense(h,w['score_head.weight'],w['score_head.bias'])
        controls = [(max(-math.pi/6,min(math.pi/6,w['anchors'][i][0]+math.tanh(offsets[2*i])*w['offset_scale'][0])),
                     max(-5.,min(5.,w['anchors'][i][1]+math.tanh(offsets[2*i+1])*w['offset_scale'][1]))) for i in range(9)]
        if not all(math.isfinite(v) for pair in controls for v in pair) or not all(math.isfinite(v) for v in scores):
            raise ValueError('nonfinite network output')
        return controls,scores


def check_control(position,heading,speed,control,peers=(),bounds=None,obstacles=()):
    """Same midpoint rollout as training; swept checks use ALL public geometry."""
    turn,acc = control
    if not (math.isfinite(turn) and math.isfinite(acc) and abs(turn) <= math.pi/6+1e-7 and abs(acc) <= 5+1e-7):
        raise ValueError('invalid learned control')
    x,y = position
    h,v = math.radians(heading),speed
    path = [(0.,x,y)]
    worst = math.inf
    for k in range(1,17):
        t,dt = k*.25,.25
        old = x,y
        nv = max(15.,min(40.,v+acc*dt))
        mid = h+turn*dt/2
        x,y = x+(v+nv)/2*math.sin(mid)*dt,y+(v+nv)/2*math.cos(mid)*dt
        h,v = h+turn*dt,nv
        margins = []
        if bounds is not None:
            xmin,xmax,ymin,ymax = bounds
            margins.append(min(old[0]-xmin,xmax-old[0],old[1]-ymin,ymax-old[1],
                               x-xmin,xmax-x,y-ymin,ymax-y)-100.)
        for p in peers:
            a = (old[0]-p.x-p.vx*(t-dt),old[1]-p.y-p.vy*(t-dt))
            b = (x-p.x-p.vx*t,y-p.y-p.vy*t)
            margins.append(segment_distance(a,b)-220.-2.-40*p.age_s-13*t*t)
        for o in obstacles:
            margins.append(segment_distance(old,(x,y),(o.x,o.y))-o.radius-50.)
        if margins:
            worst = min(worst,min(margins)-1.)
        path.append((t,x,y))
    return tuple(path),worst


class LearnedPlanner:
    def __init__(self, policy, fallback):
        self.policy,self.fallback = policy,fallback
        self.last_record = None
        self.last_source = 'uninitialized'
        self.selected_count = 0
        self.fallback_count = 0

    def plan(self, position,heading,speed,desired_heading,peers=(),bounds=None,obstacles=(),target=None,radius=450.):
        args = position,heading,speed,desired_heading,peers,bounds,obstacles,target,radius
        reference = self.fallback.plan(*args)
        reference_quality = (reference.terms.get('goal',math.inf)
                             +2*reference.terms.get('ring',0.)+.08*reference.terms.get('smoothness',0.))
        goal=(position[0]+88*math.sin(math.radians(desired_heading)),
              position[1]+88*math.cos(math.radians(desired_heading)))
        reason = 'no_safe_neural_candidate'
        try:
            record = planning_record(*args)
            self.last_record = record
            controls,scores = self.policy.predict(record)
            for i in sorted(range(len(scores)),key=lambda i:scores[i],reverse=True):
                path,clearance = check_control(position,heading,speed,controls[i],peers,bounds,obstacles)
                if clearance >= 0:
                    turn,acc = controls[i]
                    endpoint=path[-1][1:]
                    quality=(math.dist(endpoint,goal)/88)**2
                    quality+=2*((math.dist(endpoint,target)-radius)/radius)**2 if target else 0.
                    quality+=.08*4*((turn/(math.pi/6))**2+.05*(acc/5)**2)
                    # A score head trained on a small public dataset can rank
                    # safe circles above progress. Keep the learned proposal only
                    # when its actual tracking/smoothness cost matches the guide.
                    if reference.feasible and quality>reference_quality*1.1+.02:
                        reason='neural_guide_quality_rejected'
                        continue
                    self.last_source = 'neural_with_swept_check'
                    self.selected_count += 1
                    return Plan((heading+math.degrees(turn)*.5)%360,max(15.,min(40.,speed+acc*.5)),
                                True,clearance,-scores[i],{'predicted_cost':-scores[i],
                                    'verified_guide_cost':quality,'reference_guide_cost':reference_quality},path,self.last_source)
        except (ValueError,OverflowError,TypeError) as exc:
            reason = 'invalid_neural_input_or_output:'+type(exc).__name__
        self.last_source = reason
        self.fallback_count += 1
        return reference
