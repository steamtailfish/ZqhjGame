"""YOPO guidance-learning mechanism adapted to planar fixed-wing primitives.

Actor -> bounded primitive offsets -> differentiable rollout -> physical costs
-> network gradients. Score targets are detached; no expert action labels.
This module performs no I/O and makes no claims about a depth-based YOPO replica.
"""
from dataclasses import dataclass
import math

import torch
from torch import nn
from torch.nn import functional as F


@dataclass
class Scene:
    """All coordinates are metric body frame at t=0: x right, y forward.

    Peers [B,2,5]: x,y,vx,vy,age; obstacles [B,4,3]: x,y,radius.
    Masks explicitly distinguish unavailable geometry from zero coordinates.
    Offline callers own data provenance. Competition hidden truth is not an input
    contract: any future online features must come only from public observations.
    """
    speed: torch.Tensor
    goal: torch.Tensor
    target: torch.Tensor
    radius: torch.Tensor
    formation: torch.Tensor
    peers: torch.Tensor
    peer_mask: torch.Tensor
    obstacles: torch.Tensor
    obstacle_mask: torch.Tensor
    boundary: torch.Tensor | None = None
    boundary_mask: torch.Tensor | None = None

    def __post_init__(self):
        if self.boundary is None:
            self.boundary = self.speed.new_zeros((self.speed.shape[0],4,3))
        if self.boundary_mask is None:
            self.boundary_mask = self.speed.new_zeros((self.speed.shape[0],4))

    def validate(self):
        b = self.speed.shape[0]
        shapes = dict(speed=(b,),goal=(b,2),target=(b,2),radius=(b,),formation=(b,),
                      peers=(b,2,5),peer_mask=(b,2),obstacles=(b,4,3),obstacle_mask=(b,4),
                      boundary=(b,4,3),boundary_mask=(b,4))
        for name,shape in shapes.items():
            tensor = getattr(self,name)
            if tuple(tensor.shape) != shape or not torch.isfinite(tensor).all():
                raise ValueError(f'invalid {name}: expected finite {shape}')
            if tensor.device != self.speed.device or tensor.dtype != self.speed.dtype:
                raise ValueError('all scene tensors must share floating dtype and device')
        if not (self.speed.is_floating_point() and ((self.speed >= 15)&(self.speed <= 40)).all()):
            raise ValueError('initial speed must be in [15,40] m/s')
        if not (self.radius > 0).all() or not (self.peers[...,4] >= 0).all():
            raise ValueError('radius must be positive and peer age nonnegative')
        if not (self.obstacles[...,2] >= 0).all():
            raise ValueError('obstacle radius must be nonnegative')
        for mask in (self.peer_mask,self.obstacle_mask,self.boundary_mask,self.formation):
            if not ((mask == 0)|(mask == 1)).all():
                raise ValueError('masks and formation must be binary')

    def features(self):
        """51 public geometric features, ordered exactly as zqhj_features.feature_vector."""
        basic = torch.cat((self.speed[:,None]/40,self.goal/200,self.target/1000,
                           self.radius[:,None]/1000,self.formation[:,None]),dim=-1)
        peers = self.peers/self.speed.new_tensor([1000,1000,40,40,3])
        peers = torch.cat((peers*self.peer_mask[...,None],self.peer_mask[...,None]),dim=-1)
        obstacles = self.obstacles/self.speed.new_tensor([1000,1000,200])
        obstacles = torch.cat((obstacles*self.obstacle_mask[...,None],self.obstacle_mask[...,None]),dim=-1)
        boundary = self.boundary/self.speed.new_tensor([1,1,1000])
        boundary = torch.cat((boundary*self.boundary_mask[...,None],self.boundary_mask[...,None]),dim=-1)
        return torch.cat((basic,peers.flatten(1),obstacles.flatten(1),boundary.flatten(1)),dim=-1)


class GuidancePolicy(nn.Module):
    """Nine anchors, each predicts a turn/acceleration offset and a score (-cost)."""
    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(51,64),nn.Tanh(),nn.Linear(64,64),nn.Tanh())
        self.offset_head = nn.Linear(64,18)
        self.score_head = nn.Linear(64,9)
        anchors = [(math.radians(turn),acc) for turn in (-20,0,20) for acc in (-2,0,2)]
        self.register_buffer('anchors',torch.tensor(anchors,dtype=torch.float32))
        self.register_buffer('offset_scale',torch.tensor([math.radians(10),3.]))
        # Start near every anchor rather than collapsing all candidates to one.
        nn.init.normal_(self.offset_head.weight,std=.001)
        nn.init.zeros_(self.offset_head.bias)

    def forward(self, features):
        h = self.encoder(features)
        offsets = self.offset_head(h).reshape(-1,9,2)
        controls = self.anchors+torch.tanh(offsets)*self.offset_scale
        return controls,self.score_head(h)


def rollout(speed, controls, *, steps=16, dt=.25):
    """Midpoint kinematics, with piecewise differentiable speed saturation.

    controls [B,K,2] contain rad/s and m/s². Returns B,K,N+1,2 positions,
    B,K,N+1 speeds and B,K,N realized accelerations. t=0 is retained for checks.
    """
    if steps <= 0 or dt <= 0:
        raise ValueError('positive rollout horizon required')
    b,k,_ = controls.shape
    v = speed[:,None].expand(b,k)
    heading = torch.zeros_like(v)
    p = torch.zeros_like(controls)
    positions,velocities,accelerations = [p],[v],[]
    turn,acc = controls.unbind(-1)
    for _ in range(steps):
        nv = (v+acc*dt).clamp(15.,40.)
        mid = heading+turn*dt/2
        direction = torch.stack((torch.sin(mid),torch.cos(mid)),dim=-1)
        p = p+((v+nv)/2*dt)[...,None]*direction
        accelerations.append((nv-v)/dt)
        heading,v = heading+turn*dt,nv
        positions.append(p)
        velocities.append(v)
    return torch.stack(positions,dim=2),torch.stack(velocities,dim=2),torch.stack(accelerations,dim=2)


def trajectory_cost(scene, controls, *, steps=16, dt=.25):
    """YOPO-style cost gradients through the rollout, with analytic distance queries.

    Goal and safety correspond to paper eqs. (15)-(18). Turn/acceleration
    smoothness and the observation-ring term adapt the original quadrotor cost.
    This sampled differentiable cost does NOT replace swept collision validation.
    """
    path,speeds,accels = rollout(scene.speed,controls,steps=steps,dt=dt)
    points = path[:,:,1:,:]
    horizon = steps*dt
    times = torch.arange(1,steps+1,device=path.device,dtype=path.dtype)*dt
    smooth = (controls[...,0]/math.radians(30)).square()*horizon
    smooth = smooth+.05*(accels/5).square().sum(-1)*dt
    goal = (points[:,:,-1,:]-scene.goal[:,None,:]).square().sum(-1)/(22*horizon)**2
    ring_dist = torch.linalg.vector_norm(points[:,:,-1,:]-scene.target[:,None,:],dim=-1)
    ring = ((ring_dist-scene.radius[:,None])/scene.radius[:,None]).square()*scene.formation[:,None]

    # Known circles: exact signed distance, with a 50m vehicle/safety margin.
    delta = points[:,:,:,None,:]-scene.obstacles[:,None,None,:,:2]
    distance = torch.linalg.vector_norm(delta,dim=-1)-scene.obstacles[:,None,None,:,2]-50.
    # Mask before exp, so absent padded geometry cannot contribute overflow/gradients.
    distance = torch.where(scene.obstacle_mask[:,None,None,:].bool(),distance,torch.full_like(distance,1e6))
    obstacle_safety = torch.exp((-distance/60).clamp(-50,20))*scene.obstacle_mask[:,None,None,:]

    # Teammates: only communicated positions/velocities, with an age-dependent margin.
    peer_positions = scene.peers[:,None,:,:2]+times[None,:,None,None]*scene.peers[:,None,:,2:4]
    relative = points[:,:,:,None,:]-peer_positions[:,None,:,:,:]
    uncertainty = 2.+40*scene.peers[:,None,:,4]+13*times[None,:,None].square()
    peer_distance = torch.linalg.vector_norm(relative,dim=-1)-220.-uncertainty[:,None,:,:]
    peer_distance = torch.where(scene.peer_mask[:,None,None,:].bool(),peer_distance,torch.full_like(peer_distance,1e6))
    peer_safety = torch.exp((-peer_distance/60).clamp(-50,20))*scene.peer_mask[:,None,None,:]
    boundary_distance = (points[:,:,:,None,:]*scene.boundary[:,None,None,:,:2]).sum(-1)+scene.boundary[:,None,None,:,2]-100.
    boundary_distance = torch.where(scene.boundary_mask[:,None,None,:].bool(),boundary_distance,torch.full_like(boundary_distance,1e6))
    boundary_safety = torch.exp((-boundary_distance/60).clamp(-50,20))*scene.boundary_mask[:,None,None,:]
    safety = (obstacle_safety.sum(-1)+peer_safety.sum(-1)+boundary_safety.sum(-1)).sum(-1)*dt
    total = .08*smooth+3*safety+goal+2*ring
    return total,dict(smoothness=smooth,safety=safety,goal=goal,ring=ring),path,speeds


def guidance_loss(policy, scene, *, max_cost=100.):
    """Trajectory head gets dJ/dtheta; score head fits detached -J.

    All scores train. As in the paper's quality gate, excessively costly
    trajectories do not train the offset head. An all-rejected batch has zero
    trajectory loss (connected zero gradient), rather than a NaN or a fake label.
    """
    controls,scores = policy(scene.features())
    costs,terms,path,speeds = trajectory_cost(scene,controls)
    eligible = costs.detach() < max_cost
    trajectory = torch.where(eligible,costs,torch.zeros_like(costs)).sum()/eligible.sum().clamp_min(1)
    score = F.smooth_l1_loss(scores,-costs.detach())
    return dict(loss=trajectory+.1*score,trajectory_loss=trajectory,score_loss=score,
                eligible=eligible,costs=costs,controls=controls,scores=scores,
                terms=terms,path=path,speeds=speeds)


def synthetic_scene(batch_size, seed, *, dtype=torch.float32):
    """Procedural unit-test geometry, unrelated to any competition map or routes."""
    if batch_size <= 0:
        raise ValueError('batch_size must be positive')
    rng = torch.Generator().manual_seed(seed)
    uniform = lambda *shape: torch.rand(*shape,generator=rng,dtype=dtype)
    speed = 18+12*uniform(batch_size)
    angle = (uniform(batch_size)-.5)*1.4
    goal = 88*torch.stack((torch.sin(angle),torch.cos(angle)),dim=-1)
    peers = torch.zeros(batch_size,2,5,dtype=dtype)
    peers[:,:,0] = (uniform(batch_size,2)*2-1)*1000
    peers[:,:,1] = 700+300*uniform(batch_size,2)
    peers[:,:,2:4] = (uniform(batch_size,2,2)-.5)*30
    peers[:,:,4] = uniform(batch_size,2)
    obstacles = torch.zeros(batch_size,4,3,dtype=dtype)
    obstacles[:,:,0] = (uniform(batch_size,4)-.5)*700
    obstacles[:,:,1] = 160+300*uniform(batch_size,4)
    obstacles[:,:,2] = 10+25*uniform(batch_size,4)
    scene = Scene(speed,goal,torch.zeros(batch_size,2,dtype=dtype),
                  torch.full((batch_size,),450.,dtype=dtype),torch.zeros(batch_size,dtype=dtype),
                  peers,torch.ones(batch_size,2,dtype=dtype),obstacles,torch.ones(batch_size,4,dtype=dtype))
    scene.validate()
    return scene
