"""Bounded public-observation probe. No filesystem, Redis or peer-object access."""
from dataclasses import asdict
import hashlib
import time

from competition.sdk.scenarios.coop_decoy.agent import CoopAgent
from competition.sdk.core.observation import SKIP_DETECTION
from competition.sdk.core.commands import broadcast, send_to, fly_to, point_gimbal, set_gimbal_fov, set_speed


class PerceptionControlProbe(CoopAgent):
    def reset(self):
        self.rows = []
        self.photos = {}
        self.seen = set()
        self.peers = set()
        self.phase = None
        self.seq = 0
        self.dt_sum = 0.0
        self.wall_start = None
        self.last_wall_send = -10.0
        self.last_sim_send = -10.0
        self.last_photo_second = -1
        self.initial = None

    def sensor(self, obs, dt):
        # Explicitly disable synthetic detections; this probe does no recognition.
        return SKIP_DETECTION

    def decide(self, obs, dt):
        wall = time.perf_counter()
        if self.wall_start is None:
            self.wall_start = wall
            self.initial = (obs.self.lat, obs.self.lon)
        wall -= self.wall_start
        sim = obs.briefing.score_view.sim_time if obs.briefing.score_view else 0.0
        self.dt_sum += dt
        cmds = []
        new_peer = self_count = duplicate = 0
        for msg in obs.comm_inbox:
            if msg.sender_uid == self.my_uid:
                self_count += 1
                continue
            key = (msg.sender_uid, msg.payload)
            if key in self.seen:
                duplicate += 1
                continue
            self.seen.add(key)
            self.peers.add(msg.sender_uid)
            new_peer += 1

        # Per-UID camera response windows. This is a static probe role, no target IDs.
        role = sum(self.my_uid.encode('utf-8')) % 3
        phase = int(sim // 5)
        if phase != self.phase:
            self.phase = phase
            if phase == 0:
                cmds += [point_gimbal(0, -60), set_gimbal_fov(50)]
            if phase == 1 + role * 2:
                cmds += [point_gimbal(45, -60)]
            if phase == 2 + role * 2:
                cmds += [set_gimbal_fov(15)]
            if phase == 7:
                cmds += [point_gimbal(0, -60), set_gimbal_fov(50),
                         fly_to(self.initial[0] + 250 / 111320, self.initial[1],
                                speed=20, loiter_radius=200)]
            if phase == 9:
                cmds += [set_speed(30)]
            if phase == 10:
                cmds += [set_speed(20)]

        # Contrasting clocks for communication ONLY; all payloads are short ASCII.
        if 3 <= sim < 24 and wall - self.last_wall_send >= .30:
            self.seq += 1
            cmds.append(broadcast(f'B,{self.seq}'))
            self.last_wall_send = wall
        elif 26 <= sim < 34 and sim - self.last_sim_send >= .30:
            self.seq += 1
            cmds.append(broadcast(f'S,{self.seq}'))
            self.last_sim_send = sim
        elif 36 <= sim < 42 and sim - self.last_sim_send >= .5 and self.peers:
            self.seq += 1
            cmds.append(send_to(sorted(self.peers)[0], f'D,{self.seq}'))
            self.last_sim_send = sim

        photo = obs.self.photo
        digest = hashlib.sha256(photo).hexdigest() if photo else None
        # Bounded in-memory evidence; only public bytes. Export is AFTER official run.
        second = int(sim)
        if photo and second != self.last_photo_second and len(self.photos) < 61:
            self.photos.setdefault(digest, photo)
            self.last_photo_second = second
        own = {k: getattr(obs.self, k) for k in
               ('uid','lat','lon','alt','heading_deg','speed','gimbal_pan',
                'gimbal_tilt','gimbal_fov_deg','status','jammed')}
        if len(self.rows) < 20000:
            self.rows.append(dict(wall_s=wall, score_sim_s=sim, dt=dt, dt_sum=self.dt_sum,
                role=role, phase=phase, own=own, comm_stats=asdict(obs.self.comm_stats),
                inbox=[asdict(m) for m in obs.comm_inbox], new_peer_messages=new_peer,
                self_messages_ignored=self_count, duplicates_ignored=duplicate,
                commands=[asdict(c) for c in cmds], photo_sha256=digest,
                photo_bytes=len(photo) if photo else 0))
        return cmds
