"""Offline official-runner adapter for three private photo detectors."""
from dataclasses import asdict, is_dataclass
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

from vision_support import load_detector, sha, write
from capture_recording import CaptureRecorder
from capture_geometry_recording import geometry_snapshot


def run_photo_worker(args):
    from competition.sdk.scenarios.coop_decoy.runner import run
    from zqhj_photo_entry import PhotoEntryAgent
    from zqhj_inference import EmbeddedPolicy,LearnedPlanner
    from zqhj_planner import PrimitivePlanner
    submission=getattr(args,'submission',None)
    controller=(submission or args.controller).resolve()
    spec=importlib.util.spec_from_file_location('zqhj_visual_control',controller)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    base=module.EntryAgent if submission else PhotoEntryAgent
    weights=controller.parent/'vision.pt' if submission else args.weights
    instances=[]
    class RecordedPhotoAgent(base):
        def __init__(self,my_uid):
            super().__init__(my_uid)
            if args.geometry is not None or not submission:
                self.enable_geometry=args.geometry=='estimated'
            self.enable_reports=args.enable_reports
            if not submission:
                self.detector=load_detector(weights,size=args.image_size,confidence=args.confidence,device=args.device)
            if self.enable_reports and (not self.enable_geometry or len(self.detector.names)!=2):
                raise ValueError('reporting requires estimated geometry and a two-class identity model')
            self.rows=[];self.photos={};self.record_time=-1.;self.photo_export_time=-1e9
            self.capture_recorder=CaptureRecorder(my_uid)
            self.geometry_records=[];self.geometry_record_key=None
            self.recording_dropped={}
            instances.append(self)

        def create_planner(self):
            if submission:return module.EntryAgent.create_planner(self)
            return LearnedPlanner(EmbeddedPolicy(module.FEATURE_VERSION,module._policy_weights()),PrimitivePlanner())

        def decide(self,obs,dt):
            commands=super().decide(obs,dt)
            now=getattr(obs.briefing.score_view,'sim_time',None)
            # Separate recording from the sparse observation cadence. All data
            # belongs to this instance and remains in memory until run returns.
            try:
                expiry=getattr(self,'motion_verified_until',None)
                memory=getattr(self,'capture_identity',None)
                recorded_diagnostics=dict(self.diagnostics,
                    motion_verified_until=expiry if isinstance(expiry,(int,float)) and math.isfinite(expiry) else None,
                    capture_identity_memory=asdict(memory) if is_dataclass(memory) else None)
                self.capture_recorder.record(now,obs.self,recorded_diagnostics,commands,
                                             source_digest=self.photo_digest)
                key=(self.photo_digest,self.photo_time)
                if self.photo_digest and key!=self.geometry_record_key:
                    self.geometry_record_key=key
                    if len(self.geometry_records)<1500:
                        self.geometry_records.append(dict(recorded_at_s=now,
                            **geometry_snapshot(self.geometry,source_time=self.photo_time,
                                source_digest=self.photo_digest,box=self.pixel_target,
                                pixel_hits=self.pixel_hits,enabled=self.enable_geometry,
                                geo_estimate=self.geo_estimate)))
                    else:
                        self.recording_dropped['geometry_capacity']=self.recording_dropped.get('geometry_capacity',0)+1
            except (TypeError,ValueError,AttributeError,OverflowError):
                # A diagnostic failure must never change commands or activate
                # the SDK's default-detector fallback.
                self.recording_dropped['diagnostic_error']=self.recording_dropped.get('diagnostic_error',0)+1
            if now is not None and now-self.record_time >= .5 and len(self.rows) < 1500:
                self.record_time=now
                own=obs.self
                digest=hashlib.sha256(own.photo).hexdigest() if own.photo else None
                # Spread bounded exports across the whole requested mission.
                interval=args.duration/max(1,args.max_photos-1)
                if digest and len(self.photos)<args.max_photos and now-self.photo_export_time>=interval:
                    self.photos[digest]=own.photo;self.photo_export_time=now
                self.rows.append(dict(score_sim_s=now,own={k:getattr(own,k) for k in (
                    'uid','lat','lon','alt','heading_deg','speed','gimbal_pan','gimbal_tilt','gimbal_fov_deg','status')},
                    photo_sha256=digest,capture_sim_s=None,boxes=[asdict(b) for b in self.boxes],
                    inbox=[asdict(m) for m in obs.comm_inbox],comm_stats=asdict(own.comm_stats),
                    public_briefing=dict(params=obs.briefing.params,mission_area=asdict(obs.briefing.mission_area) if obs.briefing.mission_area else None),
                    boxes_photo_sha256=self.photo_digest,diagnostics=dict(self.diagnostics),
                    commands=[dict(verb=c.verb,params=c.params) for c in commands]))
            return commands

    kwargs=dict(duration=args.duration,scenario=str(args.sim_root/'competition/scenarios/coop_decoy/scenario.json'),
        start_sim=True,output_dir=str(args.output/'official'),host='127.0.0.1',port=6379,
        seed=args.seed,mode='eval',photo_mode='on',sim_binary=str(args.sim_root/'opensim-sim.exe'))
    write(args.output/'runner-call.json',dict(function='competition.sdk.scenarios.coop_decoy.runner.run',
          agent='submission EntryAgent' if submission else 'zqhj_photo_entry:PhotoEntryAgent with exported guidance controller',kwargs=kwargs,
          default_detector_suppressed=True,callback_io=False,weights_sha256=sha(weights),
          controller_sha256=sha(controller),submission=str(controller) if submission else None,
          camera_tracker=getattr(module,'CAMERA_TRACKER','none'),
          tracker_assets_sha256={name:sha(controller.parent/name) for name in getattr(module,'TRACKER_ASSETS',{})},
          image_size=(64 if getattr(module,'PATCH_APPEARANCE',False) else 1024) if submission else args.image_size,
          detector_kind='contour_local_appearance' if getattr(module,'PATCH_APPEARANCE',False) else 'yolov8',
          confidence=(.45 if getattr(module,'TEAM_SEARCH',False) else .25) if submission else args.confidence,
          geometry=args.geometry or ('package setting' if submission else 'off'),reports_enabled=args.enable_reports,
          additional_recording='bounded private control events, key source photos and locate inputs; post-run export only',
          sources={str(p.relative_to(Path(__file__).resolve().parents[1])):sha(p)
                   for p in [Path(__file__).resolve(),Path(__file__).with_name('capture_recording.py'),
                       Path(__file__).with_name('capture_geometry_recording.py'),
                       *sorted((Path(__file__).resolve().parents[1]/'src').glob('zqhj_*.py'))]}))
    try:
        run(RecordedPhotoAgent,**kwargs)
    finally:
        for a in instances:
            if hasattr(a,'close_detector'):a.close_detector()
        # Export after run, never accessible by an online Agent.
        for a in instances:
            folder=args.output/'observations'/a.my_uid;folder.mkdir(parents=True,exist_ok=False)
            with (folder/'observations.jsonl').open('w',encoding='utf-8') as f:
                for row in a.rows:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            for digest,photo in a.photos.items():(folder/(digest+'.image')).write_bytes(photo)
            captured=a.capture_recorder.export()
            for name,records in (('control-events.jsonl',captured.pop('control_events')),
                                 ('geometry-inputs.jsonl',a.geometry_records)):
                with (folder/name).open('w',encoding='utf-8') as f:
                    for row in records:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            for digest,photo in captured.pop('photo_bytes').items():
                if digest not in a.photos:(folder/(digest+'.image')).write_bytes(photo)
            captured.update(geometry_records=len(a.geometry_records),geometry_capacity=1500,
                            wrapper_dropped=a.recording_dropped)
            write(folder/'capture-recording.json',captured)
        write(args.output/'recording.json',dict(source='own public RGB and own state; exported after run',
             callback_file_io=False,peer_state_access=False,
             agents=[dict(uid=a.my_uid,photos=len(a.photos),rows=len(a.rows),diagnostics=a.diagnostics,
                          detector=dict(size=a.detector.size,confidence=a.detector.confidence,names=a.detector.names)) for a in instances]))
