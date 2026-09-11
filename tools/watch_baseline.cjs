// Human-only spectator using the official bridge/frontend. No lifecycle controller.
const path = require('node:path');
const fs = require('node:fs');
const {spawn} = require('node:child_process');
const root = path.resolve(process.argv[2] || path.join(__dirname, '../..'));
const redisPort = Number(process.argv[3] || 6391);
const batchDir = path.resolve(process.argv[4]);
process.env.NODE_PATH = path.join(root, 'lib/node_modules');
require('node:module').Module._initPaths();
const {RedisWebSocketBridge} = require(path.join(root, 'visualization/dist-bridge/bridge/server.js'));
class SpectatorBridge extends RedisWebSocketBridge {
  async handleClientMessage(ws, raw) {
    let message;
    try { message = JSON.parse(raw); } catch { return; }
    // Viewing is allowed; browser commands cannot alter a scored batch round.
    if (!['subscribe', 'unsubscribe', 'ping'].includes(message.type)) return;
    return super.handleClientMessage(ws, raw);
  }
}
const bridge = new SpectatorBridge({wsPort:8080, camHttpPort:8081, camWsPort:8082,
  redisHost:'127.0.0.1', redisPort});
let frontend;
let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  if (frontend) frontend.kill();
  await bridge.stop();
  process.exit(0);
}
bridge.start().then(() => {
  const args = [path.join(root, 'static-server.js'), path.join(root, 'frontend'), '3000'];
  frontend = spawn(path.join(root, 'bin/node.exe'), args, {cwd:root, windowsHide:true, stdio:'inherit',
    env:{...process.env, WS_PORT:'8080', CAM_HTTP_PORT:'8081', CAM_WS_PORT:'8082'}});
  fs.writeFileSync(path.join(batchDir, 'viewer-session.json'), JSON.stringify({
    started:new Date().toISOString(), argv:process.argv, cwd:root, pid:process.pid,
    frontendPid:frontend.pid, frontendArgv:args, redisPort, url:'http://127.0.0.1:3000',
    scope:'Human-only spectator; no simManager/renderManager; browser publish requests blocked. No Agent changes.'
  }, null, 2));
  console.log('SPECTATOR_READY http://127.0.0.1:3000');
  setInterval(() => {
    try {
      const batch = JSON.parse(fs.readFileSync(path.join(batchDir, 'batch.json'), 'utf8'));
      if (batch.status !== 'running') stop();
    } catch {}
  }, 10000);
}).catch(e => {console.error(e); process.exit(1)});
process.on('SIGTERM', stop);
