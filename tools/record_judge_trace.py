"""Read-only external debug observer. NEVER imported by any Agent.

Records engine judging inputs in a separate process for post-run diagnosis.
No commands, model updates, or communication with player instances.
"""
import argparse,json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import redis
from competition.sdk.core.world_state import parse_world_state
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--max-wall',type=float,default=1200)
p.add_argument('--run',type=Path,help='Stop when this local run/run.json reaches a terminal status')
a=p.parse_args()
if a.output.exists():raise ValueError('new output required')
client=redis.Redis(host='127.0.0.1',port=6379,decode_responses=True,socket_connect_timeout=3)
pub=client.pubsub(ignore_subscribe_messages=True);pub.subscribe('sim:state')
rows=[];last=-float('inf');started=time.monotonic();last_message=started;reason='timeout';last_check=0.
try:
    while time.monotonic()-started<a.max_wall:
        if a.run and time.monotonic()-last_check>=2.:
            last_check=time.monotonic()
            try:run=json.loads((a.run/'run.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):run={}
            if run.get('status') in ('completed','failed'):
                reason='local run reached '+run['status'];break
        msg=pub.get_message(timeout=.5)
        if not msg:
            if time.monotonic()-last_message>(15 if rows else 120):reason='state stream stopped';break
            continue
        if msg['type']!='message':continue
        last_message=time.monotonic();state=parse_world_state(json.loads(msg['data']))
        if state.sim_time-last<.2:continue
        last=state.sim_time
        rows.append(dict(engine_sim_time=state.sim_time,entities=[dict(uid=e.uid,kind=e.kind,lat=e.lat,lon=e.lon,alt=e.alt,
             heading=e.heading,speed=e.speed,status=e.status,gimbal=e.raw.get('gimbal_tracking')) for e in state.entities.values()]))
        if len(rows)>=4000:reason='bounded record limit';break
except (redis.ConnectionError,redis.TimeoutError) as exc:reason=type(exc).__name__
finally:
    pub.close();client.close()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(dict(scope='partial external judge-input trace; post-run diagnosis only; unavailable to frozen Agents',
        exit_reason=reason,rows=rows),ensure_ascii=False),encoding='utf-8')
print(a.output,len(rows))
