// Official bridge, with a stdin hook solely for graceful owned-process shutdown.
const path=require('node:path');
const [root]=process.argv.slice(2);
const {RedisWebSocketBridge}=require(path.join(root,'visualization/dist-bridge/bridge/server.js'));
const bridge=new RedisWebSocketBridge({wsPort:8080,camHttpPort:8081,camWsPort:8082,
 redisHost:'127.0.0.1',redisPort:6379,scenariosDir:path.join(root,'competition/scenarios'),
 userAlgorithmsDir:path.join(root,'competition/user_algorithms'),pythonBin:path.join(root,'python/python.exe'),
 stopGrace:5,renderCtlBinary:path.join(root,'build/opensim-render-ctl.exe'),
 renderersDir:path.join(root,'config/renderers'),advertiseRedisHost:'127.0.0.1',
 ueLoadTimeoutMs:120000,ueShutdownGraceMs:15000});
bridge.start().then(()=>console.log('VIEW_BRIDGE_READY')).catch(e=>{console.error(e);process.exit(1)});
process.stdin.on('data',async()=>{await bridge.stop();process.exit(0)});
