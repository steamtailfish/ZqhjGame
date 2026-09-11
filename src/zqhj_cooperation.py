"""Candidate rendezvous, not target identification or a replica of the judge."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Assignment:
    role: str
    owner: str | None
    track_id: int | None
    target: tuple | None
    members: tuple
    reporter: str | None
    ground_m: float | None = None


class Coordinator:
    def __init__(self, uid):
        self.uid = uid
        self.local_id = None
        self.key = None
        self.since = None
        self.cooldown = {}
        self.recent_targets={}

    def local_track(self, bank, now):
        for t in bank.tracks.values():
            if t.identity=='decoy_vehicle' and t.identity_hits>=3:
                self.recent_targets.pop((self.uid,t.number),None)
        ready = [t for t in bank.tracks.values() if t.ready(now) and not (t.identity=='decoy_vehicle' and t.identity_hits>=3)
                 and now >= self.cooldown.get((self.uid,t.number),-math.inf)]
        old = next((t for t in ready if t.number == self.local_id),None)
        selected = old or min(ready,key=lambda t:(t.first_s,t.number),default=None)
        self.local_id = selected.number if selected else None
        return selected

    def assign(self, local, peers, frame, now):
        candidates = {}
        if local:
            candidates[(self.uid,local.number)] = local.predict(now)
            self.recent_targets[(self.uid,local.number)]=(local.predict(now),local.sample_s,local.ground_m)
        for uid,p in peers.items():
            if p.track_id and p.identity=='decoy_vehicle':
                self.recent_targets.pop((uid,p.track_id),None)
            if p.track_id and p.hits >= 3 and now-p.time_s+p.age_s <= 2. and p.identity!='decoy_vehicle':
                candidates[(uid,p.track_id)] = frame.xy(p.target_lat,p.target_lon)
                self.recent_targets[(uid,p.track_id)]=(candidates[(uid,p.track_id)],p.time_s-p.age_s,p.ground_m)
        self.cooldown = {k:t for k,t in self.cooldown.items() if t > now}
        self.recent_targets={k:v for k,v in self.recent_targets.items() if 0<=now-v[1]<=8. and k not in self.cooldown}
        candidates={k:v[0] for k,v in self.recent_targets.items()}
        candidates = {k:v for k,v in candidates.items() if k not in self.cooldown}
        # Stable deterministic owner ordering resolves simultaneous discoveries.
        key = min(candidates,default=None)
        if key != self.key:
            self.key,self.since = key,now
        if key is not None and now-self.since >= 45.:
            # Bounded observation attempt; expiry is NOT a claim of destruction.
            self.cooldown[key] = now+30.
            self.key = None
            return Assignment('SEARCH',None,None,None,(),None)
        if key is None:
            return Assignment('SEARCH',None,None,None,(),None)
        owner,number = key
        fleet = sorted({self.uid,*peers})
        other = next((uid for uid in fleet if uid != owner),None)
        members = (owner,other) if other else (owner,)
        role = 'OBSERVE' if self.uid in members else 'SEARCH'
        if len(members) < 2:
            role = 'ACQUIRE'
        ground=self.recent_targets[key][2]
        return Assignment(role,owner,number,candidates[key],members,owner,ground)


class Reporter:
    """Explicit positive evidence required. Motion/SDK confidence never authorizes reporting."""
    def __init__(self):
        self.last = -math.inf

    def position(self, assignment, uid, now, *, identified=False, fresh=False, require_observe=True):
        if (assignment.reporter != uid or (require_observe and assignment.role != 'OBSERVE')
                or not identified or not fresh or assignment.target is None or now-self.last < 1.):
            return None
        self.last = now
        return assignment.target
