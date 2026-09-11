"""Causal replay of own-photo plane estimates; no target truth or runtime labels."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import cv2

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT/'src')]
from zqhj_visual_geometry import MotionPlane
from zqhj_vision import PixelBox
from vision_support import output_dir,write


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args();out=output_dir(args.output)
    cv2.setNumThreads(1);summary={}
    for folder in sorted((args.run/'observations').iterdir()):
        plane=MotionPlane();rows=[]
        for line in (folder/'observations.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line);now=row.get('score_sim_s')
            if now is None:continue
            own=SimpleNamespace(**row['own']);plane.observe_pose(own,now)
            digest=row.get('photo_sha256');path=folder/(str(digest)+'.image')
            if not path.is_file():continue
            plane.update(path.read_bytes(),own,now,digest)
            # Geometric diagnostic probe at image center, NOT a vehicle detection.
            w,h=plane.size
            box=PixelBox(w/2-1,h/2-1,w/2+1,h/2+1,1.,w,h)
            estimate=plane.locate(box,now,digest)
            rows.append(dict(sim_s=now,state=plane.status,residual_px=plane.last_residual,
                             center_ray_estimate=asdict(estimate) if estimate else None))
        counts={s:sum(r['state']==s for r in rows) for s in {r['state'] for r in rows}}
        summary[folder.name]=dict(frames=len(rows),states=counts,usable_geometry_estimates=sum(r['center_ray_estimate'] is not None for r in rows))
        write(out/(folder.name+'.json'),rows);print(folder.name,summary[folder.name],flush=True)
    write(out/'summary.json',dict(agents=summary,scope='causal own-photo plane model; no vehicle labels; no absolute accuracy claim'))


if __name__=='__main__':main()
