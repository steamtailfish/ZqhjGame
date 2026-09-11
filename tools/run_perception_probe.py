"""One bounded real-engine photo/control probe. Offline orchestration only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def worker(args):
    if args.probe == 'fixture':
        from capture_fixture import capture_worker
        capture_worker(args);return
    if args.probe == 'vision':
        from vision_runner import run_photo_worker
        run_photo_worker(args)
        return
    # The official public runner accepts an Agent class. Registry belongs exclusively
    # to this offline harness; Agents never receive it or another instance reference.
    from competition.sdk.scenarios.coop_decoy.runner import run
    if args.probe == 'comm':
        from zqhj_link_probe import LinkProbe as Probe
    elif args.probe == 'geometry':
        from zqhj_geometry_probe import GeometryCaptureProbe as Probe
    else:
        from zqhj_probe import PerceptionControlProbe as Probe
    instances = []
    class RecordedProbe(Probe):
        def __init__(self, my_uid):
            super().__init__(my_uid)
            instances.append(self)
    kwargs = dict(duration=42 if args.probe == 'geometry' else 60, scenario=str(args.sim_root/'competition/scenarios/coop_decoy/scenario.json'),
        start_sim=True,output_dir=str(args.output/'official'),host='127.0.0.1',port=6379,
        seed=42,mode='train',photo_mode='on',sim_binary=str(args.sim_root/'opensim-sim.exe'))
    write(args.output/'runner-call.json', dict(function='competition.sdk.scenarios.coop_decoy.runner.run',
          agent=Probe.__module__+':'+Probe.__name__+' (offline recording subclass)', kwargs=kwargs))
    try:
        run(RecordedProbe, **kwargs)
    finally:
        # No recording I/O in sensor/decide; all exports follow runner termination.
        for agent in instances:
            folder = args.output/'observations'/agent.my_uid
            folder.mkdir(parents=True,exist_ok=False)
            with (folder/'observations.jsonl').open('w',encoding='utf-8') as stream:
                for row in agent.rows:
                    stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            for digest, data in agent.photos.items():
                (folder/(digest+'.image')).write_bytes(data)
        write(args.output/'recording.json',dict(agent_uids=[a.my_uid for a in instances],
              source='Public obs.self / comm_inbox / briefing only; exported after run',
              callback_file_io=False, peer_state_access=False))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim-root',type=Path,default=PROJECT.parent)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--ue-direct',action='store_true',help='diagnose bundled Shipping executable directly after bootstrap failure')
    parser.add_argument('--probe',choices=['control','geometry','vision','fixture','comm'],default='control')
    parser.add_argument('--fixture-kind',choices=['true','decoy','blank'],default='true')
    parser.add_argument('--fixture-altitude',type=float,default=0.,help='offline fixture objects only, never changes official scenario')
    parser.add_argument('--fixture-moving',action='store_true',help='controlled training-only short loops with varied headings')
    parser.add_argument('--fixture-scene',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--duration',type=float,help='vision only: simulation seconds, <=600')
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--weights',type=Path,default=PROJECT/'artifacts/vision/weights/base_vehicle.pt')
    parser.add_argument('--controller',type=Path,default=PROJECT/'artifacts/submission/competition-guidance-v3.py')
    parser.add_argument('--submission',type=Path,help='exported visual agent.py; uses its bundled weights and detector configuration')
    parser.add_argument('--image-size',type=int,default=1024)
    parser.add_argument('--confidence',type=float,default=.25)
    parser.add_argument('--device',default='cpu')
    parser.add_argument('--geometry',choices=['off','estimated'],help='override experimental plane estimates; default off or exported package setting')
    parser.add_argument('--enable-reports',action='store_true',help='requires two-class model, repeated true-class evidence and bounded location error estimate')
    parser.add_argument('--max-photos',type=int,default=150,help='per-instance in-memory photo export limit')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.probe=='fixture':args.seed=0
    if args.probe not in ('vision','fixture') and (args.duration is not None or args.seed != 42):
        parser.error('duration/seed overrides are only available for the vision run')
    args.duration=args.duration if args.duration is not None else (42 if args.probe=='geometry' else 60)
    if not 0 < args.duration <= 600 or not 0 <= args.max_photos <= 500:
        parser.error('duration must be (0,600]; max-photos must be [0,500]')
    args.sim_root=args.sim_root.resolve()
    default_folder=PROJECT/'artifacts'/('vision/runs' if args.probe=='vision' else 'probes')
    args.output=(args.output or default_folder/datetime.now().strftime('%Y%m%d-%H%M%S')).resolve()
    if not args.output.is_relative_to(PROJECT) or args.output==PROJECT:
        parser.error('output must be inside existing project')
    if args.worker:
        worker(args); return 0
    args.output.mkdir(parents=True,exist_ok=False)
    if args.probe=='fixture':
        from capture_fixture import create_fixture
        args.fixture_scene=create_fixture(args.sim_root,args.output,args.fixture_kind,args.fixture_altitude,args.fixture_moving)
    root,out=args.sim_root,args.output
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',
             PYTHONPATH=os.pathsep.join([str(root),str(PROJECT/'src')]),
             NODE_PATH=str(root/'lib/node_modules'),
             OPENSIM_SIM_STDERR=str(out/'engine.stderr.log'))
    if env.get('OPENSIM_TERRAIN_CSV'):
        parser.error('terrain override forbidden')
    meta=dict(launcher_argv=[sys.executable,*sys.argv],launcher_cwd=str(Path.cwd()),
        cwd=str(root),python=sys.executable,python_version=sys.version,
        environment_overrides={k:env[k] for k in ('PYTHONDONTWRITEBYTECODE','PYTHONUTF8','PYTHONIOENCODING','PYTHONPATH','NODE_PATH','OPENSIM_SIM_STDERR')},
        started_utc=datetime.now(timezone.utc).isoformat(),
        seed=args.seed,duration_sim_s=args.duration,probe=args.probe,
        mode='eval + own RGB sensor' if args.probe=='vision' else ('controlled fixture + SKIP_DETECTION' if args.probe=='fixture' else 'train + custom SKIP_DETECTION'),photo_mode='on',
        commands=[],official_runtime_locations=[str(root/'ue-renderer/Windows/testwl/Saved')])
    owned=[]; logs=[]; started=time.perf_counter(); service=None; exitcode=1
    def spawn(argv,cwd,label,stdin=None):
        log=(out/(label+'.log')).open('wb');logs.append(log)
        startup=subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow=0
        p=subprocess.Popen(argv,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,
            stdin=stdin,creationflags=subprocess.CREATE_NO_WINDOW,startupinfo=startup)
        owned.append((label,p))
        meta['commands'].append(dict(argv=argv,command_line=subprocess.list2cmdline(argv),cwd=str(cwd),pid=p.pid,label=label))
        write(out/'run.json',meta)
        return p
    def wait_file(path,seconds,proc):
        end=time.monotonic()+seconds
        while not path.exists():
            if proc.poll() is not None: raise RuntimeError(f'process exited before {path.name}: {proc.returncode}')
            if time.monotonic()>end: raise TimeoutError(f'timed out waiting for {path.name}')
            time.sleep(.25)
    print('RUN_DIR='+str(out),flush=True)
    try:
        config=json.loads((root/'ue-renderer/Windows/testwl/Content/Config/capture_config.json').read_text(encoding='utf-8-sig'))
        if config.get('redis',{}).get('port')!=6379 or config.get('redis',{}).get('host')!='127.0.0.1':
            raise RuntimeError('official UE Redis config differs; no automatic rewrite')
        with socket.socket() as s:s.bind(('127.0.0.1',6379))
        redisdir=out/'redis';redisdir.mkdir()
        rp=spawn([str(root/'bin/redis-server.exe'),'--bind','127.0.0.1','--port','6379',
            '--protected-mode','yes','--save','','--appendonly','no','--dir',str(redisdir),
            '--logfile',str(redisdir/'redis.log')],root,'redis')
        import redis
        rc=redis.Redis(host='127.0.0.1',port=6379,socket_timeout=.5)
        for _ in range(30):
            try:
                if rp.poll() is not None:raise RuntimeError('owned Redis exited')
                if rc.ping():break
            except redis.RedisError:time.sleep(.2)
        else:raise TimeoutError('owned Redis not ready')
        rc.close()
        render_args=[str(root/'bin/node.exe'),str(PROJECT/'tools/render_probe_service.cjs'),str(root),str(out)]
        if args.probe=='fixture':render_args.append(str(args.fixture_scene))
        service=spawn(render_args,root,'render-service',subprocess.PIPE)
        wait_file(out/'service-ready.json',30,service)
        uecfg=json.loads((root/'config/renderers/ue_testwl.json').read_text(encoding='utf-8-sig'))['executable']
        uecwd=root/uecfg['workdir']
        ue_exe=uecwd/'testwl/Binaries/Win64/testwl-Win64-Shipping.exe' if args.ue_direct else uecwd/uecfg['launcher']
        ue=spawn([str(ue_exe),'/Env_MultiBS_Data/Maps/Map_MultiBS.Map_MultiBS',*uecfg['args']],uecwd,'ue')
        deadline=time.monotonic()+240
        while True:
            status=out/'renderer-status.json'
            if status.exists():
                try:
                    if json.loads(status.read_text())['state']=='rendering':break
                except (json.JSONDecodeError,PermissionError):pass
            if ue.poll() is not None:raise RuntimeError(f'UE exited during startup: {ue.returncode}')
            if time.monotonic()>deadline:raise TimeoutError('UE did not reach rendering in 240 wall seconds')
            time.sleep(.5)
        print('UE_RENDERING; starting official '+str(meta['duration_sim_s'])+'-second runner',flush=True)
        worker_args=[sys.executable,'-B','-u',str(Path(__file__).resolve()),'--worker','--sim-root',str(root),'--output',str(out),'--probe',args.probe]
        if args.probe=='vision':
            worker_args += ['--duration',str(args.duration),'--seed',str(args.seed),
                '--weights',str(args.weights.resolve()),'--controller',str(args.controller.resolve()),
                '--image-size',str(args.image_size),'--confidence',str(args.confidence),
                '--device',args.device,'--max-photos',str(args.max_photos)]
            if args.geometry:worker_args += ['--geometry',args.geometry]
            if args.submission:worker_args += ['--submission',str(args.submission.resolve())]
            if args.enable_reports:worker_args.append('--enable-reports')
        elif args.probe=='fixture':
            worker_args += ['--duration',str(args.duration),'--fixture-scene',str(args.fixture_scene),'--fixture-kind',args.fixture_kind]
        cli=spawn(worker_args,root,'runner')
        cli.wait(timeout=max(360,args.duration*8+120))
        meta['runner_exit_code']=cli.returncode
        evaluation_files=sorted((out/('fixture-evaluation-unused' if args.probe=='fixture' else 'official')).glob('*.evaluation.json'))
        meta['evaluation_files']=[str(p.relative_to(out)) for p in evaluation_files]
        if cli.returncode or not evaluation_files:raise RuntimeError('runner failed or no official evaluation')
        evaluation=json.loads(evaluation_files[-1].read_text(encoding='utf-8'))
        last=max((r['sim_time'] for r in evaluation.get('score_timeline',[])),default=0)
        meta['last_sim_s']=last
        if last<meta['duration_sim_s']-1:raise RuntimeError('official timeline did not complete requested duration')
        exitcode=0;meta['status']='completed'
    except Exception as exc:
        meta.update(status='failed',error=repr(exc));print('ERROR: '+repr(exc),flush=True)
    finally:
        if service and service.poll() is None:
            try:
                service.stdin.write(b'stop\n');service.stdin.flush();service.wait(timeout=30)
            except Exception as exc:meta['service_stop_error']=repr(exc)
        for label,p in reversed(owned):
            if label == 'ue' and p.poll() is None:
                try:p.wait(timeout=15)
                except subprocess.TimeoutExpired:pass
            if p.poll() is None:
                # Exact owned PID tree only. Official Windows launcher uses this too.
                result=subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,text=True)
                meta.setdefault('cleanup',[]).append(dict(label=label,pid=p.pid,exit_code=result.returncode,output=result.stdout+result.stderr))
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:pass
            meta.setdefault('process_exit_codes',{})[label]=p.poll()
        for log in logs:log.close()
        meta.update(exit_code=exitcode,elapsed_wall_s=time.perf_counter()-started,finished_utc=datetime.now(timezone.utc).isoformat())
        write(out/'run.json',meta)
    print(json.dumps(meta,ensure_ascii=False),flush=True)
    return exitcode

if __name__=='__main__':raise SystemExit(main())
