"""Propagate visually selected car boxes in controlled public-photo recordings.

Outputs stay pending review until the contact sheets have been inspected.
No simulator positions or object IDs are used to find image boxes.
"""
from pathlib import Path
import json
import sys
import hashlib
import cv2
import numpy as np
from PIL import Image,ImageDraw

PROJECT=Path(__file__).resolve().parents[1]
from vision_support import output_dir,write,sha


def main():
    cv2.setNumThreads(1)
    out=output_dir(PROJECT/'artifacts/vision/datasets/fixture-crops-v1')
    rows=[]
    # Original 1024x768 photos at t=22 s, inspected before selecting these boxes.
    anchors={
        'true-v2':('true_vehicle',[(59,639,75,674),(556,665,576,700)]),
        'decoy-v1':('decoy_vehicle',[(58,638,77,674),(554,664,580,700)]),
        'true-height200':('true_vehicle',[(59,639,75,674),(556,665,576,700)]),
        'decoy-height200':('decoy_vehicle',[(58,638,77,674),(554,664,580,700)]),
    }
    for episode,(category,boxes) in anchors.items():
        folder=PROJECT/'artifacts/vision/fixtures'/episode/'observations/20002'
        records=[r for r in map(json.loads,(folder/'observations.jsonl').read_text().splitlines())
                 if r.get('score_sim_s') is not None and (folder/(str(r.get('photo_sha256'))+'.image')).is_file()]
        unique={r['photo_sha256']:r for r in records};records=list(unique.values())
        anchor=min(records,key=lambda r:abs(r['score_sim_s']-22.))
        anchor_path=folder/(anchor['photo_sha256']+'.image')
        initial=cv2.imdecode(np.frombuffer(anchor_path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        gray=cv2.cvtColor(initial,cv2.COLOR_BGR2GRAY)
        sift=cv2.SIFT_create(nfeatures=1000);ka,da=sift.detectAndCompute(gray,None);bf=cv2.BFMatcher()
        episode_rows=[]
        for index,record in enumerate(records):
            t=record['score_sim_s']
            if not 19.<=t<=25.5:continue
            source=folder/(record['photo_sha256']+'.image')
            raw=cv2.imdecode(np.frombuffer(source.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            target=cv2.cvtColor(raw,cv2.COLOR_BGR2GRAY);kb,db=sift.detectAndCompute(target,None)
            pairs=[a for a,b in bf.knnMatch(da,db,k=2) if a.distance<.7*b.distance]
            if len(pairs)<30:continue
            pa=np.float32([ka[m.queryIdx].pt for m in pairs]);pb=np.float32([kb[m.trainIdx].pt for m in pairs])
            H,mask=cv2.findHomography(pa,pb,cv2.RANSAC,2.)
            if H is None or int(mask.sum())<30:continue
            for n,(x1,y1,x2,y2) in enumerate(boxes):
                template=gray[y1:y2,x1:x2];w,h=x2-x1,y2-y1
                center=cv2.perspectiveTransform(np.float32([[[.5*(x1+x2),.5*(y1+y2)]]]),H)[0,0]
                sx,sy=max(0,int(center[0]-w/2-12)),max(0,int(center[1]-h/2-12))
                search=target[sy:min(target.shape[0],sy+h+24),sx:min(target.shape[1],sx+w+24)]
                if search.shape[0]<h or search.shape[1]<w:continue
                _,score,_,(dx,dy)=cv2.minMaxLoc(cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED))
                if score<.88:continue
                bx,by=sx+dx,sy+dy
                # Keep the object at its original pixel scale, with varied crop offsets.
                left=max(0,min(raw.shape[1]-256,bx-90-(index*13+n*19)%60))
                top=max(0,min(raw.shape[0]-256,by-90-(index*17+n*11)%60))
                crop=raw[top:top+256,left:left+256]
                if bx+w>=left+256 or by+h>=top+256:continue
                name=f'{episode}-{index:03d}-{n}'
                path=out/(name+'.png');cv2.imwrite(str(path),crop)
                row=dict(id=name,episode=episode,uid='20002',image=str(path),sha256=sha(path),
                    source='controlled_render_fixture_public_photo',source_photo=str(source),source_photo_sha256=sha(source),
                    observation_sim_s=t,crop_xyxy=[left,top,left+256,top+256],
                    boxes=[dict(x1=bx-left,y1=by-top,x2=bx+w-left,y2=by+h-top,category=category)],
                    template_ncc=score,anchor_sha256=sha(anchor_path),
                    review_status='pending',reviewer=None,review_evidence=None,
                    label_source='controlled fixture type plus visually selected physical vehicle; no judge state used')
                rows.append(row);episode_rows.append(row)
        canvas=Image.new('RGB',(8*160,((len(episode_rows)+7)//8)*185),'white');draw=ImageDraw.Draw(canvas)
        for i,row in enumerate(episode_rows):
            im=Image.open(row['image']).convert('RGB');d=ImageDraw.Draw(im);b=row['boxes'][0]
            d.rectangle((b['x1'],b['y1'],b['x2'],b['y2']),outline='red',width=1)
            im=im.resize((160,160));x,y=i%8*160,i//8*185;canvas.paste(im,(x,y+25))
            draw.text((x,y),f"{row['observation_sim_s']:.1f}s NCC={row['template_ncc']:.2f}",fill='black')
        canvas.save(out/(episode+'-review.jpg'))
        print(episode,len(episode_rows),flush=True)
    (out/'pending.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    write(out/'provenance.json',dict(scope='controlled rendered crop dataset, pending visual review',records=len(rows),
          labels_are_not_official_benchmark_ground_truth=True))


if __name__=='__main__':main()
