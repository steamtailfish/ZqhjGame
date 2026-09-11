"""One bounded private detector worker per aircraft; never shares Agent state."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import math
import time
from zqhj_photo_entry import PhotoEntryAgent


class AsyncPhotoEntryAgent(PhotoEntryAgent):
    def reset(self):
        if getattr(self,'_pending',None) is not None:self._pending.cancel()
        super().reset()
        if not hasattr(self,'_detector_executor'):
            self._detector_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='own-photo-'+self.my_uid)
        self._pending=None;self._pending_obs=None
        self._submitted_time=-math.inf;self._submitted_digest=None;self._async_clock=-math.inf
        self.vision_stats.update(async_dropped=0,async_submitted=0)

    @staticmethod
    def _infer(detector,photo):
        started=time.perf_counter()
        boxes=detector(photo)
        return boxes,time.perf_counter()-started

    def sensor(self,obs,dt):
        now=getattr(obs.briefing.score_view,'sim_time',None)
        if now is None or not math.isfinite(now) or now<0 or obs.self.uid!=self.my_uid:return []
        if now<self._async_clock:self.reset()
        self._async_clock=now
        if self._pending is not None and self._pending.done():
            source=self._pending_obs;receipt=source.briefing.score_view.sim_time
            try:
                boxes,elapsed=self._pending.result()
                if 0<=now-receipt<=1.:
                    detector=self.detector
                    # Parent associates boxes with their original public photo
                    # and receipt pose, never with a later control observation.
                    self.detector=lambda photo:boxes
                    try:super().sensor(source,dt)
                    finally:self.detector=detector
                    self.vision_stats['inference_wall_s']+=elapsed
                    self.vision_stats['max_inference_wall_s']=max(self.vision_stats['max_inference_wall_s'],elapsed)
                else:self.vision_stats['async_dropped']+=1
            except Exception as exc:
                self.vision_stats['failures']+=1;self.vision_state='DETECTOR_ERROR'
                self.last_vision_error=f'{type(exc).__name__}: {exc}'[:240]
                self.boxes=[];self.pixel_target=None;self.pixel_hits=0;self.pending_geo=[];self.geo_estimate=None
            self._pending=None;self._pending_obs=None
        if self._pending is None and obs.self.photo and now-self._submitted_time>=.5:
            digest=hashlib.sha256(obs.self.photo).hexdigest()
            if digest!=self._submitted_digest:
                self._pending_obs=obs
                self._pending=self._detector_executor.submit(self._infer,self.detector,obs.self.photo)
                self._submitted_time=now;self._submitted_digest=digest
                self.vision_stats['async_submitted']+=1
        return []

    def close_detector(self):
        if hasattr(self,'_detector_executor'):
            self._detector_executor.shutdown(wait=True,cancel_futures=True)
