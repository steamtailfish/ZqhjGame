"""Build one SDK Agent module plus local model assets and provenance."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT),str(PROJECT/'src'),str(PROJECT.parent)]
from vision_support import output_dir,write,sha


def copy_report(source,destination):
    """Keep repository links usable from inside a standalone package."""
    def relative_link(match):
        target=match.group(1)
        if target.startswith(('#','/')) or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target):
            return match.group(0)
        path,separator,anchor=target.partition('#')
        relative=Path(os.path.relpath((source.parent/path).resolve(),destination.parent)).as_posix()
        return ']('+relative+(separator+anchor if separator else '')+')'
    content=re.sub(r'\]\(([^\s)]+)\)',relative_link,source.read_text(encoding='utf-8'))
    destination.write_text(content,encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--controller',type=Path,default=PROJECT/'artifacts/submission/score-v22/agent.py')
    p.add_argument('--weights',type=Path,default=PROJECT/'artifacts/vision/weights/base_vehicle.pt')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--geometry',choices=['off','estimated'],default='off')
    p.add_argument('--async-vision',action='store_true')
    p.add_argument('--team-search',action='store_true',help='analytic formation sweep, independent of YOPO score head')
    p.add_argument('--distributed-search',action='store_true',help='broad search with visual rendezvous and four-sample reporting')
    p.add_argument('--cooperative-capture',action='store_true',help='visual hold, ETA recruitment and acknowledged two-camera tracking')
    p.add_argument('--patch-appearance',action='store_true',help='weights are a VehicleAppearance state dict, using own-photo contour proposals')
    p.add_argument('--reports-default-on',action='store_true',help='enable gated reports when the competition directly constructs EntryAgent')
    args=p.parse_args()
    if args.cooperative_capture:
        if not args.patch_appearance or args.geometry!='estimated':
            p.error('cooperative capture requires --patch-appearance --geometry estimated')
        args.distributed_search=True
    if args.reports_default_on and args.geometry!='estimated':p.error('default reports require estimated geometry')
    out=output_dir(args.output)
    if args.distributed_search:args.team_search=True
    names=('zqhj_state','zqhj_comm','zqhj_cooperation','zqhj_planner','zqhj_features','zqhj_inference',
           'zqhj_entry','zqhj_localization','zqhj_search','zqhj_visual_geometry','zqhj_vision','zqhj_patch_vision','zqhj_photo_entry','zqhj_async','zqhj_team','zqhj_score_search','zqhj_capture')
    chunks=['# Generated self-contained Agent source; vision.pt is a separate local asset.\n']
    sources={}
    for name in names:
        path=PROJECT/'src'/(name+'.py');source=path.read_text(encoding='utf-8')
        sources[name]=sha(path);remove=set()
        for node in ast.parse(source).body:
            if isinstance(node,ast.ImportFrom) and node.module in names:
                remove.update(range(node.lineno,node.end_lineno+1))
        chunks.append('\n# '+name+'\n'+''.join(s for i,s in enumerate(source.splitlines(keepends=True),1) if i not in remove))
    control=args.controller.read_text(encoding='utf-8')
    tree=ast.parse(control)
    weight_function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_policy_weights')
    chunks.append('\n'+ast.get_source_segment(control,weight_function)+'\n')
    weight_sha=sha(args.weights)
    tail='''
import os
from pathlib import Path
import hashlib

class EntryAgent(CaptureSearchAgent if COOPERATIVE_CAPTURE else ScoreSearchAgent if DISTRIBUTED_SEARCH else TeamPhotoEntryAgent if TEAM_SEARCH else AsyncPhotoEntryAgent if ASYNC_VISION else PhotoEntryAgent):
    def __init__(self,my_uid):
        super().__init__(my_uid)
        # Static model asset initialization only; callbacks never load files.
        folder=Path(__file__).resolve().parent
        path=folder/'vision.pt'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=VISION_SHA256:
            raise ValueError('vision asset hash mismatch')
        if PATCH_APPEARANCE:
            torch.set_num_threads(4);cv2.setNumThreads(1)
            model=VehicleAppearance()
            model.load_state_dict(torch.load(path,map_location='cpu',weights_only=True))
            self.detector=PatchPhotoDetector(model,confidence=.55)
            self.detector.warmup();self.enable_geometry=GEOMETRY_ESTIMATED;self.enable_reports=REPORTS_DEFAULT
            return
        runtime=folder/'.runtime';runtime.mkdir(exist_ok=True)
        (runtime/'ultralytics').mkdir(exist_ok=True)
        (runtime/'matplotlib').mkdir(exist_ok=True)
        os.environ['YOLO_CONFIG_DIR']=str(runtime/'ultralytics')
        os.environ['MPLCONFIGDIR']=str(runtime/'matplotlib')
        os.environ['YOLO_AUTOINSTALL']='false';os.environ['YOLO_OFFLINE']='true'
        from ultralytics import YOLO,settings
        settings.update({'sync':False,'runs_dir':str(runtime/'runs'),'datasets_dir':str(runtime/'datasets'),'weights_dir':str(folder)})
        model=YOLO(str(path));classes=list(model.names.values())
        if classes not in (['TargetVehicle'],['vehicle_candidate'],['true_vehicle','decoy_vehicle']):
            raise ValueError('incompatible vision classes')
        if REPORTS_DEFAULT and len(classes)!=2:raise ValueError('default reports require an identity model')
        torch.set_num_threads(4)
        cv2.setNumThreads(1)
        self.detector=PhotoDetector(model.model.fuse(verbose=False),confidence=.45 if TEAM_SEARCH else .25,names=('vehicle_candidate',) if len(classes)==1 else tuple(classes))
        self.detector.warmup()
        self.enable_geometry=GEOMETRY_ESTIMATED
        self.enable_reports=REPORTS_DEFAULT

    def create_planner(self):
        if TEAM_SEARCH:return PrimitivePlanner()
        return LearnedPlanner(EmbeddedPolicy(FEATURE_VERSION,_policy_weights()),PrimitivePlanner())
'''
    chunks.append(f'\nVISION_SHA256={weight_sha!r}\nGEOMETRY_ESTIMATED={args.geometry=="estimated"!r}\nASYNC_VISION={args.async_vision or args.team_search!r}\nTEAM_SEARCH={args.team_search!r}\nDISTRIBUTED_SEARCH={args.distributed_search!r}\n'+tail)
    chunks.insert(-1,f'\nCOOPERATIVE_CAPTURE={args.cooperative_capture!r}\n')
    chunks.append(f'\nPATCH_APPEARANCE={args.patch_appearance!r}\nREPORTS_DEFAULT={args.reports_default_on!r}\n')
    code='\n'.join(chunks);ast.parse(code)
    (out/'agent.py').write_text(code,encoding='utf-8')
    shutil.copy2(args.weights,out/'vision.pt')
    shutil.copy2(PROJECT/'requirements-vision.txt',out/'requirements.txt')
    report=PROJECT/('docs/COOPERATIVE_CAPTURE.md' if args.cooperative_capture else 'docs/TECHNICAL_REPORT.md')
    if report.is_file():copy_report(report,out/'technical_report.md')
    write(out/'manifest.json',dict(agent_sha256=sha(out/'agent.py'),vision_sha256=weight_sha,
        controller_sha256=sha(args.controller),sources=sources,geometry=args.geometry,async_vision=args.async_vision or args.team_search,
        strategy='search_verify_acknowledged_pair' if args.cooperative_capture else 'distributed_search_then_rendezvous' if args.distributed_search else 'analytic_cooperative_sweep' if args.team_search else 'learned_strip',reports_enabled=args.reports_default_on,
        cooperative_capture=args.cooperative_capture,
        image_size=64 if args.patch_appearance else 1024,confidence=.55 if args.patch_appearance else .45 if args.team_search else .25,
        detector_kind='contour_local_appearance' if args.patch_appearance else 'yolov8',
        identity_confidence=.65 if args.distributed_search else .9,
        identity_margin=.35 if args.distributed_search else .6,
        independent_reports=args.distributed_search,
        require_report_motion=args.distributed_search,
        require_candidate_motion=args.distributed_search,
        fast_pixel_reports=args.distributed_search,
        report_from_geo_bank=not args.distributed_search,
        fast_report_identity_hits=3 if args.distributed_search else None,
        fast_report_uncertainty_limit=110. if args.distributed_search else None,
        technical_report_sha256=sha(out/'technical_report.md') if report.is_file() else None,
        technical_report_source_sha256=sha(report) if report.is_file() else None,
        scope='loadable visual-control package; not evidence of recognition accuracy or K=2 success'))
    print(out/'agent.py')


if __name__=='__main__':main()
