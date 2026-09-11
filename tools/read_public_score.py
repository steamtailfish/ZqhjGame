"""External read-only display of the same score fields exposed in ScoreView.

Never imports or feeds an Agent. No world-state, target IDs or positions emitted.
Final evaluation JSON is still required for the delivered result.
"""
import argparse,json,time
from pathlib import Path
import redis
p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
client=redis.Redis(host='127.0.0.1',port=6379,socket_connect_timeout=2,socket_timeout=2)
pub=client.pubsub(ignore_subscribe_messages=True);pub.subscribe('sim:score');deadline=time.monotonic()+10
try:
    while time.monotonic()<deadline:
        message=pub.get_message(timeout=1)
        if not message:continue
        raw=json.loads(message['data'])
        snapshot={k:raw.get(k) for k in ('total_score','dimension_scores','passed','n_destroyed','n_targets','sim_time')}
        snapshot['scope']='live public ScoreView fields; not final evaluation'
        print(json.dumps(snapshot,ensure_ascii=False))
        if a.output:
            a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        break
    else:raise TimeoutError('no live public score within 10 seconds')
finally:pub.close();client.close()
