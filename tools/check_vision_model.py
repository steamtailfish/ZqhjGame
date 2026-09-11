"""Compare the memory-only adapter to the upstream predictor on real images."""
from pathlib import Path
import argparse
import sys
import time
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT/'src')]
from vision_support import VISION,load_detector,write,sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights',type=Path,default=VISION/'weights/base_vehicle.pt')
    parser.add_argument('--output',type=Path,default=VISION/'model-check.json')
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(PROJECT/'artifacts'):
        raise ValueError('output must be a project artifact')
    from PIL import Image
    import numpy as np
    weights=args.weights
    detector=load_detector(weights,confidence=.001)
    from ultralytics import YOLO
    upstream=YOLO(str(weights))
    paths=list((PROJECT/'docs/manual/media').glob('image*'))
    import json
    scan=VISION/'scans/public-450-native1024/candidates.jsonl'
    if scan.exists():
        paths += [Path(r['image']) for r in map(json.loads,scan.read_text().splitlines()) if r['boxes']]
    for episode in ('20260907-204636','20260907-213142'):
        for uid in ('20001','20002','20003'):
            paths.append(sorted((PROJECT/'artifacts/probes'/episode/'observations'/uid).glob('*.image'))[10])
    for episode,digest in [('true-v2','62c13d88321f8e68637990aca8d0ec440b10194091b18397110322f876452299'),
                           ('decoy-v1','eb5d892723ccb860dd83235e6eef8b37a1ce559088f3edbe85550abf5518f881')]:
        path=VISION/'fixtures'/episode/'observations/20002'/(digest+'.image')
        if path.is_file():paths.append(path)
    rows=[]
    for path in paths:
        photo=path.read_bytes()
        with patch('builtins.open',side_effect=AssertionError('no callback file IO')):
            boxes=detector(photo)
        with Image.open(path) as im:
            ref=upstream.predict(im.convert('RGB'),imgsz=1024,rect=False,conf=.001,iou=.45,
                                 max_det=32,agnostic_nms=True,save=False,verbose=False,device='cpu')[0]
        actual=np.array([[b.x1,b.y1,b.x2,b.y2,b.confidence] for b in boxes]).reshape(-1,5)
        reference=ref.boxes.data.cpu().numpy()
        # Our online contract removes zero-area boxes after clipping to the
        # image; upstream retains such proposals from the letterbox padding.
        reference=reference[(reference[:,2]>reference[:,0]) & (reference[:,3]>reference[:,1])]
        expected=reference[:,:5]
        assert actual.shape==expected.shape,(path,actual.shape,expected.shape)
        error=float(np.max(np.abs(actual-expected))) if len(actual) else 0.
        assert error < .002,(path,error)
        assert [detector.names.index(b.category) for b in boxes]==reference[:,5].astype(int).tolist()
        rows.append(dict(image=str(path),proposals_at_001=len(boxes),boxes_at_025=sum(b.confidence>=.25 for b in boxes),
                         max_confidence=max((b.confidence for b in boxes),default=0),max_parity_error=error))
    output.parent.mkdir(parents=True,exist_ok=True)
    write(output,dict(status='passed',input_images=rows,image_size=1024,
          weights_sha256=sha(weights),
          callback_open_forbidden=True,class_agnostic_nms=True,class_labels_match=True,
          scope='upstream numerical parity, not detection accuracy'))
    print(output)


if __name__=='__main__':main()
