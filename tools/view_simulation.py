"""Start one official baseline with browser visualization; only own processes managed."""
import argparse
from datetime import datetime
import json,os,socket,subprocess,sys,time,urllib.request
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim-root',type=Path,default=PROJECT.parent)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); root=args.sim_root.resolve();out=args.output.resolve()
    if not out.is_relative_to(PROJECT):parser.error('output must be in project')
    out.mkdir(parents=True,exist_ok=True)
    meta={'cwd':str(root),'argv':[sys.executable,*sys.argv],'started':datetime.now().isoformat(),
      'url':'http://127.0.0.1:3000','commands':[],
      'official_runtime_output':str(root/'competition/scenarios/coop_decoy/output')}
    def save(): (out/'session.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    env=dict(os.environ,NODE_PATH=str(root/'lib/node_modules'),PYTHON_BIN=str(root/'python/python.exe'),
      PYTHONPATH=str(root),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',
      OPENSIM_SIM_BIN=str(root/'opensim-sim.exe'),WS_PORT='8080',CAM_HTTP_PORT='8081',CAM_WS_PORT='8082')
    owned=[];logs=[];bridge=None
    def spawn(label,argv,cwd,stdin=None):
        log=(out/(label+'.log')).open('wb');logs.append(log)
        p=subprocess.Popen(argv,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=stdin,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        owned.append((label,p));meta['commands'].append({'label':label,'argv':argv,'cwd':str(cwd),'pid':p.pid});save()
        return p
    def api(endpoint,body=None):
        req=urllib.request.Request('http://127.0.0.1:8081/api/'+endpoint,
          data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    try:
        for port in (6379,8080,8081,8082,3000):
            with socket.socket() as s:s.bind(('127.0.0.1',port))
        config=json.loads((root/'ue-renderer/Windows/testwl/Content/Config/capture_config.json').read_text(encoding='utf-8-sig'))
        if config['redis']!={'host':'127.0.0.1','port':6379}:raise RuntimeError('UE config differs; no rewrite allowed')
        redisdir=out/'redis';redisdir.mkdir(exist_ok=True)
        spawn('redis',[str(root/'bin/redis-server.exe'),'--bind','127.0.0.1','--protected-mode','yes',
          '--port','6379','--save','','--appendonly','no','--dir',str(redisdir),'--logfile',str(redisdir/'redis.log')],root)
        import redis
        r=redis.Redis(socket_timeout=.5)
        for _ in range(30):
            try:
                if r.ping():break
            except redis.RedisError:time.sleep(.2)
        else:raise RuntimeError('Redis not ready')
        r.close()
        bridge=spawn('bridge',[str(root/'bin/node.exe'),str(PROJECT/'tools/view_bridge.cjs'),str(root)],root,subprocess.PIPE)
        for _ in range(60):
            try:api('sim/status');break
            except Exception:time.sleep(.25)
        else:raise RuntimeError('bridge not ready')
        spawn('frontend',[str(root/'bin/node.exe'),str(root/'static-server.js'),str(root/'frontend'),'3000'],root)
        cfg=json.loads((root/'config/renderers/ue_testwl.json').read_text(encoding='utf-8-sig'))['executable']
        uecwd=root/cfg['workdir']
        spawn('ue',[str(uecwd/'testwl/Binaries/Win64/testwl-Win64-Shipping.exe'),
          '/Env_MultiBS_Data/Maps/Map_MultiBS.Map_MultiBS',*cfg['args']],uecwd)
        meta['start_response']=api('sim/start',{'scenario':'coop_decoy','mode':'train','photoMode':'on','routeSeed':42})
        meta['status']='started';save();print(meta['url'],flush=True)
        seen_running=False
        while not (out/'STOP').exists():
            state=api('sim/status');meta['official_status']=state;save()
            if state['status'] in ('running','paused'):seen_running=True
            if state['status']=='error':raise RuntimeError(str(state))
            if seen_running and state['status'] in ('idle','finished','completed'):break
            time.sleep(2)
        meta['status']='stopping';save()
    except Exception as exc:meta.update(status='failed',error=repr(exc));save();raise
    finally:
        if bridge and bridge.poll() is None:
            try:api('sim/stop',{})
            except Exception:pass
            try:bridge.stdin.write(b'stop\n');bridge.stdin.flush();bridge.wait(timeout=35)
            except Exception:pass
        for label,p in reversed(owned):
            if label=='ue' and p.poll() is None:
                try:p.wait(timeout=15)
                except subprocess.TimeoutExpired:pass
            if p.poll() is None:
                result=subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,text=True)
                meta.setdefault('cleanup',[]).append({'label':label,'pid':p.pid,'output':result.stdout+result.stderr})
            meta.setdefault('exit_codes',{})[label]=p.poll()
        for log in logs:log.close()
        meta['ended']=datetime.now().isoformat();save()

if __name__=='__main__':main()
