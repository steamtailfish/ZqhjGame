"""Instance-local RGB inference. Model loading belongs to the offline launcher.

Callbacks consume bytes in memory, never filenames, Redis, or simulator truth.
The optional two-class model provides visual identity hypotheses; confidence is
not a calibrated probability and reporting requires separate temporal gates.
"""
from dataclasses import dataclass
from io import BytesIO
import math

import numpy as np
from PIL import Image
import torch
from torchvision.ops import nms


@dataclass(frozen=True)
class PixelBox:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    width: int
    height: int
    category: str = 'vehicle_candidate'
    class_margin: float = 0.

    @property
    def center(self):
        return (self.x1+self.x2)/2, (self.y1+self.y2)/2


class PhotoDetector:
    """YOLOv8 raw forward + explicit fixed-square preprocessing.

    model is a private, already loaded/eval/fused Torch module. No Ultralytics
    predictor is invoked online (it can create directories and lazy dependencies).
    """
    def __init__(self, model, *, size=1024, confidence=.25, iou=.45, device='cpu',names=('vehicle_candidate',)):
        if size < 64 or size % 32 or not 0 < confidence < 1 or not 0 < iou < 1:
            raise ValueError('invalid detector configuration')
        self.model = model.to(device).float().eval()
        self.device, self.size = device, size
        self.confidence, self.iou = confidence, iou
        self.names=tuple(names)
        if self.names not in (('vehicle_candidate',),('true_vehicle','decoy_vehicle')):
            raise ValueError('unsupported detector class contract')

    def warmup(self):
        with torch.inference_mode():
            self.model(torch.zeros(1,3,self.size,self.size,device=self.device))
            nms(torch.tensor([[0.,0.,1.,1.]],device=self.device),
                torch.tensor([1.],device=self.device), self.iou)

    def __call__(self, photo):
        if not isinstance(photo, bytes) or not photo or len(photo) > 16_000_000:
            raise ValueError('expected bounded encoded photo bytes')
        with Image.open(BytesIO(photo)) as source:
            width, height = source.size
            if not 1 < width <= 4096 or not 1 < height <= 4096:
                raise ValueError('unsupported image dimensions')
            rgb = np.asarray(source.convert('RGB'))
        # Match Ultralytics LetterBox(center=True, auto=False): OpenCV bilinear.
        # cv2 is loaded in the module below before any Agent callbacks.
        scale = min(self.size/width,self.size/height)
        rw,rh = round(width*scale),round(height*scale)
        left,top = round((self.size-rw)/2-.1),round((self.size-rh)/2-.1)
        resized = cv2.resize(rgb,(rw,rh),interpolation=cv2.INTER_LINEAR)
        padded = np.full((self.size,self.size,3),114,dtype=np.uint8)
        padded[top:top+rh,left:left+rw] = resized
        tensor = torch.from_numpy(np.ascontiguousarray(padded.transpose(2,0,1))).to(self.device).float()[None]/255.
        with torch.inference_mode():
            raw = self.model(tensor)
            raw = raw[0] if isinstance(raw,(tuple,list)) else raw
            if raw.ndim != 3 or raw.shape[0] != 1 or raw.shape[1] != 4+len(self.names):
                raise ValueError('YOLOv8 output disagrees with configured class contract')
            proposals = raw[0].T
            proposals = proposals[torch.isfinite(proposals).all(dim=1) & (proposals[:,4:].max(dim=1).values >= self.confidence)]
            if not len(proposals): return []
            scores,classes = proposals[:,4:].max(dim=1)
            margins=scores-proposals[:,4:].min(dim=1).values if len(self.names)>1 else scores*0
            boxes = torch.cat((proposals[:,:2]-proposals[:,2:4]/2,
                               proposals[:,:2]+proposals[:,2:4]/2),dim=1)
            keep = nms(boxes,scores,self.iou)[:32]
            classes,margins=classes[keep].cpu().tolist(),margins[keep].cpu().tolist()
            boxes,scores = boxes[keep].cpu().tolist(),scores[keep].cpu().tolist()
        result = []
        for (x1,y1,x2,y2),score,label,margin in zip(boxes,scores,classes,margins):
            # xyxy are continuous box edges (0..W/H), not integer pixel centers.
            x1,x2 = [max(0.,min(width,(x-left)/scale)) for x in (x1,x2)]
            y1,y2 = [max(0.,min(height,(y-top)/scale)) for y in (y1,y2)]
            if x2 > x1 and y2 > y1:
                result.append(PixelBox(x1,y1,x2,y2,float(score),width,height,self.names[label],float(margin)))
        return result


def center_gimbal(box, pan, tilt, *, gain=6., max_step=3.):
    """Bounded image-space feedback; gain is tuned in deg/normalized pixel error.

    This is NOT a pixel-to-world projection or calibrated angular measurement.
    It needs only signs of image axes. Do not infer geographic coordinates here.
    """
    if not all(math.isfinite(x) for x in (pan,tilt,gain,max_step)):
        raise ValueError('nonfinite servo state')
    u,v = box.center
    ex,ey = (u-(box.width-1)/2)/(box.width/2), (v-(box.height-1)/2)/(box.height/2)
    clamp = lambda x: max(-max_step,min(max_step,x))
    return ((pan+clamp(gain*ex)+180)%360-180,
            max(-89.,min(-15.,tilt-clamp(gain*ey))))


import cv2  # Eager import: no lazy module or filesystem work in __call__.
