"""Instance-local public observation adaptation and short noisy candidate tracks."""
from dataclasses import dataclass
import math


def finite(*values):
    return all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) for v in values)


def valid_geo(lat, lon):
    return finite(lat, lon) and -85 <= lat <= 85 and -180 <= lon <= 180


def wrap(angle):
    return (angle + 180) % 360 - 180


@dataclass(frozen=True)
class LocalFrame:
    lat: float
    lon: float

    def xy(self, lat, lon):
        return (wrap(lon-self.lon)*111320*math.cos(math.radians(self.lat)),
                (lat-self.lat)*111320)

    def geo(self, x, y):
        return self.lat+y/111320, wrap(self.lon+x/(111320*math.cos(math.radians(self.lat))))


class SimClock:
    def __init__(self):
        self.previous = None

    def step(self, briefing):
        value = getattr(briefing.score_view, 'sim_time', None)
        if not finite(value) or value < 0:
            return None, 'missing'
        state = ('first' if self.previous is None else 'rewind' if value < self.previous
                 else 'duplicate' if value == self.previous else 'advance')
        self.previous = value
        return value, state


def detections(own):
    """No target identity or real/decoy inference from type, confidence or motion."""
    result, seen = [], set()
    for d in own.detections or (own.detection,):
        if (not d.detected or not finite(d.confidence) or not 0 < d.confidence <= 1
                or not valid_geo(d.target_lat, d.target_lon)):
            continue
        key = (d.target_lat, d.target_lon)
        if key not in seen:
            result.append(d)
            seen.add(key)
    return result


@dataclass
class Track:
    number: int
    x: float
    y: float
    vx: float
    vy: float
    sample_s: float
    first_s: float
    hits: int = 1
    sigma_m: float = 100.
    source: str = 'public_sdk_detection_unverified'
    identity: str = 'unknown'
    identity_hits: int = 0
    ground_m: float | None = None

    def predict(self, now):
        dt = max(0., min(2., now-self.sample_s))
        return self.x+self.vx*dt, self.y+self.vy*dt

    def ready(self, now):
        return self.hits >= 3 and self.sample_s-self.first_s >= .5 and 0 <= now-self.sample_s <= 2.


class TrackBank:
    """Gated one-to-one alpha-beta association; sigma is a heuristic, not covariance."""
    def __init__(self):
        self.tracks = {}
        self.next_id = 1

    def update(self, observations, frame, now):
        self.tracks = {k:t for k,t in self.tracks.items() if 0 <= now-t.sample_s <= 3.}
        points = [frame.xy(d.target_lat, d.target_lon) for d in observations]
        edges = sorted((math.dist(t.predict(now), p), key, i)
                       for key,t in self.tracks.items() for i,p in enumerate(points))
        used_tracks, used_points = set(), set()
        for distance, key, i in edges:
            t = self.tracks[key]
            if distance > 250 or key in used_tracks or i in used_points:
                continue
            used_tracks.add(key)
            used_points.add(i)
            dt = now-t.sample_s
            if dt <= 0:
                continue
            px, py = t.predict(now)
            ex, ey = points[i][0]-px, points[i][1]-py
            t.x, t.y = px+.25*ex, py+.25*ey
            # Short noisy intervals must not produce arbitrary target speeds.
            vx, vy = t.vx+.015*ex/max(.5, dt), t.vy+.015*ey/max(.5, dt)
            scale = min(1., 25/max(1e-9, math.hypot(vx, vy)))
            t.vx, t.vy = vx*scale, vy*scale
            t.sigma_m = max(40., min(200., .9*t.sigma_m+.1*distance))
            t.sigma_m = max(t.sigma_m,min(200.,getattr(observations[i],'uncertainty_m',40.)))
            t.source = getattr(observations[i],'source',t.source)
            identity=getattr(observations[i],'identity','unknown')
            t.identity_hits=t.identity_hits+1 if identity==t.identity and identity!='unknown' else int(identity!='unknown')
            t.identity=identity
            t.ground_m=getattr(observations[i],'ground_m',t.ground_m)
            t.sample_s, t.hits = now, t.hits+1
        for i, (x,y) in enumerate(points):
            if i not in used_points and len(self.tracks) < 32:
                while self.next_id in self.tracks:
                    self.next_id = self.next_id % 65535 + 1
                self.tracks[self.next_id] = Track(self.next_id,x,y,0.,0.,now,now)
                self.tracks[self.next_id].sigma_m=max(40.,min(200.,getattr(observations[i],'uncertainty_m',100.)))
                self.tracks[self.next_id].source=getattr(observations[i],'source','public_sdk_detection_unverified')
                self.tracks[self.next_id].identity=getattr(observations[i],'identity','unknown')
                self.tracks[self.next_id].identity_hits=int(self.tracks[self.next_id].identity!='unknown')
                self.tracks[self.next_id].ground_m=getattr(observations[i],'ground_m',None)
                self.next_id = self.next_id % 65535 + 1
        return self.tracks


class StatsDelta:
    def __init__(self):
        self.previous = {}

    def update(self, stats):
        result = {}
        for key in ('sent','delivered','received','rejected_bytes','rejected_rate',
                    'rejected_range','rejected_jam'):
            value = max(0, getattr(stats, key, 0))
            old = self.previous.get(key, value)
            result[key] = value-old if value >= old else value
            self.previous[key] = value
        return result
