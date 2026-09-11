"""Controlled rendering fixture, separate from competition evaluation.

Only offline setup chooses entity types/positions. Capture Agents receive public
observations and never read this scene or its class labels. Original SDK/scenario
and scoring are unchanged. Fixture scores must never be reported as game scores.
"""
import copy
import json
import math
from pathlib import Path

from vision_support import write,sha


def create_fixture(root,out,kind,altitude=0.,moving=False):
    original=root/'competition/scenarios/coop_decoy/scenario.json'
    scene=json.loads(original.read_text(encoding='utf-8-sig'))
    uavs=[copy.deepcopy(e) for e in scene['entities'] if e['type']=='FixedWingUAV']
    typename='TargetVehicle' if kind=='true' else 'DecoyVehicle'
    template=next(e for e in scene['entities'] if e['type']==typename)
    entities=list(uavs);number=10001
    for uav in (uavs if kind!='blank' else []):
        pose=uav['params']
        for north in (60.,120.,180.,240.):
            for east in (-45.,45.):
                e=copy.deepcopy(template);e['id']=str(number);e['name']=f'fixture_{number}';number+=1
                e['params'].update(initial_latitude=pose['initial_latitude']+north/111320,
                                   initial_longitude=pose['initial_longitude']+east/(111320*math.cos(math.radians(pose['initial_latitude']))),
                                   initial_altitude=float(altitude))
                # The engine requires at least one component per entity.
                e['components']={'trajectory':{'type':'TargetTrajectoryComponent','enabled':True,
                                   'params':{'speed':0.,'speed_jitter':0.,'waypoints':[]}}}
                if moving:
                    lat,lon=e['params']['initial_latitude'],e['params']['initial_longitude']
                    angle=(number%8)*math.pi/4
                    points=[]
                    for i in range(13):
                        phase=angle+i*math.pi/3
                        points.append(dict(lat=lat+35*math.cos(phase)/111320,
                            lon=lon+35*math.sin(phase)/(111320*math.cos(math.radians(lat))),alt=float(altitude),t=i*5.))
                    e['params'].update(initial_latitude=points[0]['lat'],initial_longitude=points[0]['lon'])
                    e['components']['trajectory']['params'].update(speed=7.,waypoints=points)
                entities.append(e)
    scene['entities']=entities
    scene['simulation']['auto_start']=False
    scene['_comment']='Controlled RGB training fixture, NOT competition evaluation; all vehicles share an offline selected class.'
    path=out/'fixture-scene.json';write(path,scene)
    write(out/'fixture-manifest.json',dict(kind=kind,source_sha256=sha(original),fixture_sha256=sha(path),
        scope='controlled rendered training images only; no competition score claims',vehicles=len(entities)-len(uavs),altitude=altitude,moving=moving,
        label_source='offline selected entity type; bounding boxes still require visible-image review',
        agent_reads_scene=False))
    return path


def capture_worker(args):
    from competition.sdk.scenarios.coop_decoy.runner import CoopDecoyRunner
    from competition.sdk.core.runner import ScenarioConfig
    from zqhj_geometry_probe import GeometryCaptureProbe
    class FixtureRunner(CoopDecoyRunner):
        def prepare_scenario(self):pass  # Keep OUR generated placements; no official routes.
        def inject_startup(self,client,first):
            # Fixture-only world setup. Scene waypoints alone do not activate
            # the engine trajectory; use the same command envelope as its SDK.
            from competition.sdk.scenarios._astar_navigator import _publish_cmd
            scene=json.loads(Path(args.fixture_scene).read_text(encoding='utf-8'))
            injected=0
            for e in scene['entities']:
                if e['type']=='FixedWingUAV':continue
                params=e['components']['trajectory']['params']
                if not params.get('waypoints') or params.get('speed',0)<=0:continue
                _publish_cmd(client,str(e['id']),'set_speed',{'speed':params['speed']})
                _publish_cmd(client,str(e['id']),'set_trajectory',{'waypoints':params['waypoints']})
                injected+=1
            self.log(f'[FIXTURE] activated {injected} controlled loop trajectories; not competition routes')
    instances=[]
    class Capture(GeometryCaptureProbe):
        def __init__(self,my_uid):
            super().__init__(my_uid);instances.append(self)
    cfg=ScenarioConfig(scenario_name='coop_decoy',scenario_path=str(args.fixture_scene),
        duration_s=args.duration,redis_host='127.0.0.1',redis_port=6379,
        output_dir=str(args.output/'fixture-evaluation-unused'),sim_binary=str(args.sim_root/'opensim-sim.exe'),
        start_sim_flag=True,seed=0,run_mode='eval',photo_mode='on')
    try:FixtureRunner(cfg,Capture).run()
    finally:
        for a in instances:
            folder=args.output/'observations'/a.my_uid;folder.mkdir(parents=True,exist_ok=False)
            with (folder/'observations.jsonl').open('w',encoding='utf-8') as f:
                for row in a.rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            for digest,photo in a.photos.items():(folder/(digest+'.image')).write_bytes(photo)
        write(args.output/'recording.json',dict(scope='controlled training fixture; not official competition',
            agents=[dict(uid=a.my_uid,photos=len(a.photos),rows=len(a.rows)) for a in instances],callback_file_io=False))
