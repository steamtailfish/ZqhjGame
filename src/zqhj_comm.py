"""Versioned 41-byte ASCII broadcast status. No socket, files or shared state."""
import base64
from dataclasses import dataclass
import math
import struct

from zqhj_state import valid_geo

# version, sequence, episode deciseconds, own geo, heading, speed,
# local track number, candidate geo, observation age, hits, uncertainty.
WIRE = struct.Struct('!BHIiiHBHiiHBB')
WIRE_V2 = struct.Struct('!BHIiiHBHiiHBBhB')


@dataclass(frozen=True)
class Packet:
    seq: int
    time_s: float
    lat: float
    lon: float
    heading: float
    speed: float
    track_id: int = 0
    target_lat: float = 0.
    target_lon: float = 0.
    age_s: float = 0.
    hits: int = 0
    sigma_m: float = 100.
    ground_m: float | None = None
    identity: str = 'unknown'


def encode(p):
    if not (valid_geo(p.lat,p.lon) and valid_geo(p.target_lat,p.target_lon)
            and 0 <= p.time_s <= 429496729.5 and 0 <= p.age_s <= 6553.5
            and math.isfinite(p.heading) and 0 <= p.speed <= 40
            and 0 <= p.sigma_m <= 255):
        raise ValueError('invalid packet values')
    extended=p.ground_m is not None or p.identity!='unknown'
    if p.identity not in ('unknown','true_vehicle','decoy_vehicle'):
        raise ValueError('invalid identity')
    if p.ground_m is not None and (not math.isfinite(p.ground_m) or not -1000<=p.ground_m<=2000):
        raise ValueError('invalid ground estimate')
    values=(2 if extended else 1,p.seq % 65536,int(p.time_s*10),round(p.lat*1e6),round(p.lon*1e6),
                    round(p.heading % 360*100) % 36000,round(p.speed),p.track_id,
                    round(p.target_lat*1e6),round(p.target_lon*1e6),
                    math.ceil(p.age_s*10),min(255,p.hits),math.ceil(p.sigma_m))
    raw=(WIRE_V2.pack(*values,round(p.ground_m) if p.ground_m is not None else -32768,
                     ('unknown','true_vehicle','decoy_vehicle').index(p.identity)) if extended else WIRE.pack(*values))
    payload = 'Z'+base64.b85encode(raw).decode('ascii')
    if len(payload.encode('utf-8')) > 50:
        raise ValueError('payload exceeds SDK limit')
    return payload


def decode(payload):
    try:
        if not isinstance(payload,str) or not payload.startswith('Z') or len(payload) not in (41,45):
            return None
        raw = base64.b85decode(payload[1:].encode('ascii'))
        values=(WIRE if len(payload)==41 else WIRE_V2).unpack(raw)
        version,seq,t,lat,lon,h,v,key,a,b,age,hits,sigma = values[:13]
        ground,identity=None,'unknown'
        if len(payload)==45:
            z,label=values[13:]
            if version!=2 or label>2 or (z!=-32768 and not -1000<=z<=2000):return None
            ground=None if z==-32768 else float(z)
            identity=('unknown','true_vehicle','decoy_vehicle')[label]
        elif version!=1:return None
        p = Packet(seq,t/10,lat/1e6,lon/1e6,h/100,v,key,a/1e6,b/1e6,age/10,hits,sigma,ground,identity)
        if h >= 36000 or v > 40 or not valid_geo(p.lat,p.lon):
            return None
        if not valid_geo(p.target_lat,p.target_lon):
            return None
        return p
    except (ValueError, UnicodeError, struct.error, OverflowError):
        return None


class Radio:
    def __init__(self, uid):
        self.uid = uid
        self.peers = {}
        self.latest = {}
        self.seq = 0
        self.last_send = -math.inf

    def receive(self, inbox, now):
        self.peers = {uid:p for uid,p in self.peers.items() if 0 <= now-p.time_s <= 3.}
        self.latest = {uid:key for uid,key in self.latest.items() if now-key[0] <= 10.}
        for message in inbox:
            if message.sender_uid == self.uid:
                continue
            p = decode(message.payload)
            if p is None or not 0 <= now-p.time_s <= 3.:
                continue
            old = self.latest.get(message.sender_uid)
            if old is not None:
                if p.time_s < old[0] or (p.time_s == old[0] and
                        not 0 < (p.seq-old[1]) % 65536 < 32768):
                    continue
            if len(self.peers) >= 16 and message.sender_uid not in self.peers:
                continue
            self.latest[message.sender_uid] = (p.time_s,p.seq)
            self.peers[message.sender_uid] = p
        return self.peers

    def send(self, own, track, frame, now):
        if now-self.last_send < .5-1e-9:
            return None
        lat,lon = frame.geo(track.x,track.y) if track else (0.,0.)
        p = Packet(self.seq,now,own.lat,own.lon,own.heading_deg,min(40.,max(0.,own.speed)),
                   track.number if track else 0,lat,lon,now-track.sample_s if track else 0.,
                   track.hits if track else 0,track.sigma_m if track else 100.,
                   track.ground_m if track else getattr(self,'ground_m',None),
                   track.identity if track and track.identity_hits>=3 else 'unknown')
        payload = encode(p)
        self.seq = (self.seq+1) % 65536
        self.last_send = now
        return payload
