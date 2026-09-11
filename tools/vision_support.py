"""Offline setup and provenance helpers, never imported by online controllers."""
import hashlib
import json
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
VISION = PROJECT/'artifacts/vision'


def environment():
    for key,part in [('YOLO_CONFIG_DIR','ultralytics-config'),('MPLCONFIGDIR','matplotlib-config')]:
        folder=VISION/part
        folder.mkdir(parents=True,exist_ok=True)
        os.environ[key]=str(folder)
    os.environ['YOLO_AUTOINSTALL']='false'
    os.environ['YOLO_OFFLINE']='true'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def output_dir(path):
    path=Path(path).resolve()
    if not path.is_relative_to(PROJECT/'artifacts') or path.exists():
        raise ValueError('output must be a NEW directory under ZqhjGame/artifacts')
    path.mkdir(parents=True)
    return path


def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def load_detector(weights, *, size=1024, confidence=.25, device='cpu'):
    environment()
    import torch
    import cv2
    cv2.setNumThreads(1)
    from ultralytics import YOLO, settings
    from zqhj_vision import PhotoDetector
    settings.update({'sync':False,'runs_dir':str(VISION/'runs'),
                     'datasets_dir':str(VISION/'datasets'),'weights_dir':str(VISION/'weights')})
    weights=Path(weights).resolve()
    if not weights.is_file(): raise ValueError('local detector weights missing')
    model=YOLO(str(weights))
    classes=list(model.names.values())
    if classes not in (['TargetVehicle'],['vehicle_candidate'],['true_vehicle','decoy_vehicle']):
        raise ValueError('unsupported model class contract')
    names=('vehicle_candidate',) if len(classes)==1 else tuple(classes)
    torch.set_num_threads(4)
    detector=PhotoDetector(model.model.fuse(verbose=False),size=size,confidence=confidence,device=device,names=names)
    detector.warmup()
    return detector
