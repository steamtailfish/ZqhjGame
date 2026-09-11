"""Capture legal own-photo evidence with stable straight-flight windows; no detector."""
from dataclasses import asdict
import math
import time
from competition.sdk.scenarios.coop_decoy.agent import CoopAgent
from competition.sdk.core.observation import SKIP_DETECTION
from competition.sdk.core.commands import fly_to, point_gimbal, set_gimbal_fov
from zqhj_localization import ObservationClock


class GeometryCaptureProbe(CoopAgent):
    def reset(self):
        self.clock=ObservationClock()
        self.rows=[]; self.photos={}
        self.first=None; self.stage=None; self.last_saved=-1.0

    def sensor(self,obs,dt):return SKIP_DETECTION

    def decide(self,obs,dt):
        public_time=obs.briefing.score_view.sim_time if obs.briefing.score_view else None
        timing=self.clock.update(public_time,obs.self.photo,time.perf_counter())
        commands=[]
        if self.first is None:self.first=(obs.self.lat,obs.self.lon)
        if public_time is not None:
            stage=0 if public_time<18 else 1 if public_time<26 else 2 if public_time<34 else 3
            if stage != self.stage:
                self.stage=stage
                if stage==0:
                    # Destination from this UAV's allowed position only; no target/map data.
                    commands=[fly_to(self.first[0]+1000/111320,self.first[1],speed=15),
                              point_gimbal(0,-90),set_gimbal_fov(50)]
                elif stage==1:commands=[set_gimbal_fov(30)]
                elif stage==2:commands=[point_gimbal(0,-60),set_gimbal_fov(50)]
                else:commands=[point_gimbal(30,-60)]
        if (obs.self.photo and timing['accept_new_sample'] and public_time-self.last_saved>=.45
                and len(self.photos)<110):
            self.photos[timing['photo_sha256']]=obs.self.photo
            self.last_saved=public_time
        own={k:getattr(obs.self,k) for k in ('uid','lat','lon','alt','heading_deg','speed',
             'gimbal_pan','gimbal_tilt','gimbal_fov_deg','status','jammed')}
        if len(self.rows)<5000:
            self.rows.append(dict(score_sim_s=public_time,own=own,time=timing,callback_dt_diagnostic=dt,
                commands=[asdict(c) for c in commands],photo_sha256=timing['photo_sha256'],
                photo_bytes=len(obs.self.photo) if obs.self.photo else 0,
                candidate_source=None,candidate_gap='No verified online pixel detector configured'))
        return commands
