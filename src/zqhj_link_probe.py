"""Public-inbox diagnostic; no detector, target truth or cross-Agent access."""
from dataclasses import asdict
from competition.sdk.scenarios.coop_decoy.agent import CoopAgent
from competition.sdk.core.commands import broadcast,fly_to,point_gimbal,set_gimbal_fov
from zqhj_comm import Packet,encode


class LinkProbe(CoopAgent):
    def reset(self):
        self.rows=[];self.photos={};self.first=None;self.last_send=-1.;self.sequence=0

    def sensor(self,obs,dt):return []

    def decide(self,obs,dt):
        now=getattr(obs.briefing.score_view,'sim_time',None)
        if now is None:return []
        own=obs.self;commands=[]
        if self.first is None:
            self.first=(own.lat+.005,own.lon)
            commands=[fly_to(*self.first,speed=15.,loiter_radius=0.),point_gimbal(0.,-80.),set_gimbal_fov(50.)]
        if now-self.last_send>=.5:
            self.last_send=now
            payload=(encode(Packet(self.sequence,now,own.lat,own.lon,own.heading_deg,min(40.,max(0.,own.speed))))
                     if now<20 or now>=40 else f'L:{self.sequence}:{now:.2f}')
            commands.append(broadcast(payload));self.sequence+=1
            if now>=40:commands.extend([fly_to(*self.first,speed=15.,loiter_radius=0.),point_gimbal(0.,-80.),set_gimbal_fov(50.)])
        if len(self.rows)<1500:
            self.rows.append(dict(score_sim_s=now,own={k:getattr(own,k) for k in ('uid','lat','lon','heading_deg','speed')},
                comm_stats=asdict(own.comm_stats),inbox=[asdict(m) for m in obs.comm_inbox],
                commands=[asdict(c) for c in commands]))
        return commands
