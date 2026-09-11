"""Shared, stdlib-only training/inference feature contract from public geometry."""
import math

FEATURE_VERSION = 'coop-decoy-guidance-v3-51'
FEATURE_DIM = 51


def body_vector(x, y, heading_deg):
    h = math.radians(heading_deg)
    return math.cos(h)*x-math.sin(h)*y, math.sin(h)*x+math.cos(h)*y


def planning_record(position, heading, speed, desired_heading, peers=(), bounds=None,
                    obstacles=(), target=None, radius=450.):
    """Same record is used for inference and offline public-observation collection.

    Boundary rows (nx,ny,b) mean nx*x+ny*y+b >= 0 in the initial body frame.
    Geometry omitted by the network's fixed capacity is still checked by the shield.
    """
    def point(x,y):
        return body_vector(x-position[0],y-position[1],heading)
    goal = body_vector(88*math.sin(math.radians(desired_heading)),
                       88*math.cos(math.radians(desired_heading)),heading)
    peer_rows = [(*point(p.x,p.y),*body_vector(p.vx,p.vy,heading),p.age_s)
                 for p in sorted(peers,key=lambda p:math.dist(position,(p.x,p.y)))[:2]]
    circles = [(*point(o.x,o.y),o.radius)
               for o in sorted(obstacles,key=lambda o:math.dist(position,(o.x,o.y))-o.radius)[:4]]
    boundary = []
    if bounds is not None:
        xmin,xmax,ymin,ymax = bounds
        boundary = [(*body_vector(1,0,heading),position[0]-xmin),
                    (*body_vector(-1,0,heading),xmax-position[0]),
                    (*body_vector(0,1,heading),position[1]-ymin),
                    (*body_vector(0,-1,heading),ymax-position[1])]
    record = dict(speed=max(15.,min(40.,speed)),goal=goal,target=point(*target) if target else (0.,0.),
                  radius=radius,formation=float(target is not None),
                  peers=peer_rows+[(0.,)*5]*(2-len(peer_rows)),peer_mask=[1.]*len(peer_rows)+[0.]*(2-len(peer_rows)),
                  obstacles=circles+[(0.,)*3]*(4-len(circles)),obstacle_mask=[1.]*len(circles)+[0.]*(4-len(circles)),
                  boundary=boundary+[(0.,)*3]*(4-len(boundary)),boundary_mask=[1.]*len(boundary)+[0.]*(4-len(boundary)))
    feature_vector(record)  # Fail early, before recording or inference.
    return record


def feature_vector(r):
    def checked_row(row,n):
        if len(row) != n or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in row):
            raise ValueError('invalid feature row')
        return row
    basic = [r['speed']/40,*[v/200 for v in checked_row(r['goal'],2)],
             *[v/1000 for v in checked_row(r['target'],2)],r['radius']/1000,r['formation']]
    if not 15 <= r['speed'] <= 40 or r['radius'] <= 0 or r['formation'] not in (0,1):
        raise ValueError('invalid speed/radius/formation')
    features = basic
    for key,mask_key,scales,count in [('peers','peer_mask',(1000,1000,40,40,3),2),
                                     ('obstacles','obstacle_mask',(1000,1000,200),4),
                                     ('boundary','boundary_mask',(1,1,1000),4)]:
        rows,masks = r[key],r[mask_key]
        if len(rows) != count or len(masks) != count:
            raise ValueError('invalid geometry capacity')
        for row,mask in zip(rows,masks):
            checked_row(row,len(scales))
            if mask not in (0,1):
                raise ValueError('invalid geometry mask')
            if key == 'peers' and row[4] < 0:
                raise ValueError('negative peer age')
            if key == 'obstacles' and row[2] < 0:
                raise ValueError('negative obstacle radius')
            if key == 'boundary' and mask and abs(math.hypot(row[0],row[1])-1.) > 1e-4:
                raise ValueError('boundary normal must be unit length')
            features.extend(v/s*mask for v,s in zip(row,scales))
            features.append(mask)
    checked_row(features,FEATURE_DIM)
    return features
