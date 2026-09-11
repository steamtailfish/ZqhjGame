"""Offline analysis of public observations exported AFTER the real runner returns."""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import statistics
import sys
from PIL import Image, ImageDraw, ImageStat

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    args=parser.parse_args()
    root=args.run.resolve()
    summary={'input':str(root),'decoder_python':sys.executable,'agents':{},
      'limits':['No capture timestamps: hashes prove byte changes, not frame age or end-to-end latency.',
                'Public per-UID cache plus controlled response supports ownership; no embedded UID in image bytes.',
                'This probe disables recognition and cannot certify true/decoy classification.']}
    sheets=[]
    clock_analysis={}
    control_events={}
    for folder in sorted((root/'observations').iterdir()):
        rows=[json.loads(s) for s in (folder/'observations.jsonl').read_text(encoding='utf-8').splitlines()]
        if not rows:continue
        decoded={}; errors=[]
        for path in folder.glob('*.image'):
            try:
                with Image.open(path) as im:
                    im.load()
                    decoded[path.stem]=dict(format=im.format,size=im.size,mode=im.mode,
                        channel_stddev=ImageStat.Stat(im.convert('RGB')).stddev)
            except Exception as e:errors.append(dict(file=path.name,error=repr(e)))
        phases=[]
        for p in sorted(set(r['phase'] for r in rows)):
            seq=[r for r in rows if r['phase']==p]
            first,last=seq[0],seq[-1]
            phases.append(dict(phase=p,sim_range=[first['score_sim_s'],last['score_sim_s']],
                wall_range=[first['wall_s'],last['wall_s']],first_own=first['own'],last_own=last['own'],
                commands=[dict(sim_s=r['score_sim_s'],commands=r['commands']) for r in seq if
                    any(not c['verb'].startswith('comm.') for c in r['commands'])]))
        intervals={}
        for name,low,high in [('wall_paced',4,23),('sim_paced',27,33),('directed',37,41)]:
            seq=[r for r in rows if low<=r['score_sim_s']<high]
            if len(seq)>1:
                a,b=seq[0],seq[-1]
                intervals[name]=dict(sim_s=b['score_sim_s']-a['score_sim_s'],wall_s=b['wall_s']-a['wall_s'],
                    attempts=sum(c['verb'].startswith('comm.') for r in seq for c in r['commands']),
                    stats_delta={k:b['comm_stats'][k]-a['comm_stats'][k] for k in a['comm_stats']})
        ds=[b['score_sim_s']-a['score_sim_s'] for a,b in zip(rows,rows[1:])]
        dw=[b['wall_s']-a['wall_s'] for a,b in zip(rows,rows[1:])]
        received={(m['sender_uid'],m['payload'],m['recv_time']) for r in rows for m in r['inbox']}
        rx={(uid,payload) for uid,payload,_ in received}
        attempts=[(r,c['params']['payload']) for r in rows for c in r['commands']
                  if c['verb']=='comm.broadcast' and c['params']['payload'].startswith('B,')]
        models={}
        for clock in ('score_sim_s','wall_s','dt_sum'):
            q=deque(); mismatches=accepted=0
            for r,payload in attempts:
                t=r[clock]
                while q and t-q[0]>=1:q.popleft()
                ok=len(q)<4
                if ok:q.append(t);accepted+=1
                mismatches+=ok!=((folder.name,payload) in rx)
            models[clock]=dict(model_accepted=accepted,model_mismatches=mismatches)
        clock_analysis[folder.name]=dict(B_attempts=len(attempts),
            B_observed_self_received=sum((folder.name,payload) in rx for r,payload in attempts),
            clock_models=models,D_attempts=sum(c['verb']=='comm.send' for r in rows for c in r['commands']),
            D_received=sum(payload.startswith('D,') for uid,payload in rx),
            note='Approximate offline window models use command issue time, not hidden engine execution time; no exact limit reconstruction.')
        control_events[folder.name]=[dict(command_sim_s=r['score_sim_s'],command=c,before=r['own'],
            next=rows[min(i+1,len(rows)-1)]['own'],next_sim_s=rows[min(i+1,len(rows)-1)]['score_sim_s'])
            for i,r in enumerate(rows) for c in r['commands'] if not c['verb'].startswith('comm.')]
        item=dict(callbacks=len(rows),nominal_dt_values=sorted(set(r['dt'] for r in rows)),
            dt_sum=rows[-1]['dt_sum'],score_sim_s=rows[-1]['score_sim_s'],wall_s=rows[-1]['wall_s'],
            median_sim_delta=statistics.median(ds),median_wall_delta=statistics.median(dw),
            duplicate_sim_ticks=sum(d==0 for d in ds),photo_present_ticks=sum(bool(r['photo_bytes']) for r in rows),
            photo_unique_hashes=len(set(r['photo_sha256'] for r in rows if r['photo_sha256'])),
            photo_hash_changes=sum(a['photo_sha256']!=b['photo_sha256'] for a,b in zip(rows,rows[1:])),
            saved_decoded_images=len(decoded),decode_errors=errors,decoded=decoded,
            phases=phases,comm_intervals=intervals,final_comm_stats=rows[-1]['comm_stats'],
            unique_received=len(received),unique_received_self=sum(x[0]==folder.name for x in received),
            unique_received_peer=sum(x[0]!=folder.name for x in received),
            app_processed_peer_messages=sum(r['new_peer_messages'] for r in rows),
            duplicates_ignored=sum(r['duplicates_ignored'] for r in rows),
            self_messages_ignored=sum(r['self_messages_ignored'] for r in rows),
            first_own=rows[0]['own'],last_own=rows[-1]['own'])
        summary['agents'][folder.name]=item
        canvas=Image.new('RGB',(960,810),'#eeeeee');draw=ImageDraw.Draw(canvas)
        role=rows[0]['role']
        times=[3, 5*(1+role*2)+3, 5*(2+role*2)+3,33,38,53]
        for idx,t in enumerate(times):
            candidates=[r for r in rows if r['photo_sha256'] in decoded]
            if not candidates:continue
            r=min(candidates,key=lambda r:abs(r['score_sim_s']-t))
            with Image.open(folder/(r['photo_sha256']+'.image')) as im:
                im=im.convert('RGB');im.thumbnail((470,225))
                x=(idx%2)*480;y=(idx//2)*270
                canvas.paste(im,(x,y+40))
                draw.text((x+4,y+4),f"UID {folder.name} sim {r['score_sim_s']:.2f}s pan {r['own']['gimbal_pan']:.1f}\nFOV {r['own']['gimbal_fov_deg']:.1f} tilt {r['own']['gimbal_tilt']:.1f}",fill='black')
        sheet=root/f'public-photo-{folder.name}.jpg';canvas.save(sheet,quality=90);sheets.append(str(sheet))
    summary['contact_sheets']=sheets
    (root/'clock-comm-analysis.json').write_text(json.dumps(clock_analysis,indent=2),encoding='utf-8')
    (root/'control-events.json').write_text(json.dumps(control_events,indent=2),encoding='utf-8')
    (root/'analysis.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    brief={uid:{k:v for k,v in item.items() if k not in ('decoded','phases')} for uid,item in summary['agents'].items()}
    print(json.dumps(brief,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
