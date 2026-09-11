// Offline service orchestration using unchanged official bridge classes.
// Never reads camera frames, sim:state, target coordinates, or sends data to Agents.
const path = require('node:path');
const fs = require('node:fs');
const [root, output, fixtureScene] = process.argv.slice(2);
const Redis = require(path.join(root, 'lib/node_modules/ioredis'));
const bridge = path.join(root, 'visualization/dist-bridge/bridge');
const {RenderScheduler} = require(path.join(bridge, 'render-scheduler.js'));
const {RenderServiceController} = require(path.join(bridge, 'render-service.js'));
const {SimProcessManager} = require(path.join(bridge, 'sim-process-manager.js'));
const {createNodeExecFile} = require(path.join(bridge, 'render-ctl-client.js'));
const redis = new Redis({host:'127.0.0.1', port:6379});
const deps = {
  publish: async (ch,msg) => { console.log('PUBLISH',ch,msg); await redis.publish(ch,msg); },
  subscribe: async (ch,cb) => {
    const sub = new Redis({host:'127.0.0.1',port:6379});
    sub.on('message', (_ch,msg) => {console.log('EVENT',ch,msg); cb(msg);});
    await sub.subscribe(ch);
    return async () => {sub.disconnect();};
  }
};
const scheduler = new RenderScheduler(deps);
const service = new RenderServiceController({...deps,loadTimeoutMs:120000});
const manager = new SimProcessManager({redis:{set:(k,v)=>redis.set(k,v)},
  redisHost:'127.0.0.1',redisPort:6379,renderScheduler:scheduler,renderService:service,
  execFile:createNodeExecFile()});
async function main() {
  await scheduler.attach();
  await service.start();
  const original = service.onStateChange;
  service.onStateChange = (rid,state) => {
    original(rid,state);
    fs.writeFileSync(path.join(output,'renderer-status.json'),JSON.stringify({rid,state,wall:new Date().toISOString()}));
  };
  await manager.startRenderers({renderCtlBinary:path.join(root,'build/opensim-render-ctl.exe'),
    scenarioJsonAbs:fixtureScene || path.join(root,'competition/scenarios/coop_decoy/scenario.json'),
    renderersDir:path.join(root,'config/renderers'),advertiseRedisHost:'127.0.0.1'});
  fs.writeFileSync(path.join(output,'service-ready.json'),JSON.stringify({ready:true}));
  process.stdin.setEncoding('utf8');
  process.stdin.on('data',async () => {
    service.endMission();
    for (const rid of service.listOnline()) {
      try {await service.shutdown(rid);} catch(e) {console.error(e.message);}
    }
    await scheduler.detach(); await service.stop(); redis.disconnect(); process.exit(0);
  });
}
main().catch(e=>{console.error(e);process.exit(1);});
