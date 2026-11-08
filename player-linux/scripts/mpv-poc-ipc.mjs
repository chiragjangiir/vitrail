// mpv-poc-ipc.mjs - SPIKE Phase 0 (jetable) : valide le pilotage mpv via IPC JSON.
// Cf. docs/SPIKE_mpv_hwdecode_linux.md. Appele par mpv-poc.sh.
//
// Exerce exactement ce que MpvSurface devra faire en prod :
//   loadfile, file-loaded, hwdec-current (=vaapi ?), dimensions, time-pos,
//   speed (nudge LAN), seek absolu (resync LAN), end-file (fin d'item).
//
// Protocole mpv : commandes JSON par ligne sur un socket UNIX
//   ->  { "command": [...], "request_id": N }
//   <-  { "error": "success", "data": ..., "request_id": N }   (reponses)
//   <-  { "event": "file-loaded" | "end-file" | ... }          (evenements)
//
// Usage : node mpv-poc-ipc.mjs <socket> <fichier|url>
// Laisse mpv EN LECTURE en sortant (le shell enchaine sur le test z-order).

import net from 'node:net';

const [, , SOCK, SRC] = process.argv;
if (!SOCK || !SRC) { console.error('usage: node mpv-poc-ipc.mjs <socket> <src>'); process.exit(2); }

const sock = net.connect(SOCK);
let buf = '';
let reqId = 0;
const pending = new Map();         // request_id -> {resolve, reject}
const eventWaiters = [];           // {name, resolve}

sock.on('data', (chunk) => {
  buf += chunk.toString('utf8');
  let nl;
  while ((nl = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    if (msg.request_id !== undefined && pending.has(msg.request_id)) {
      const { resolve, reject } = pending.get(msg.request_id);
      pending.delete(msg.request_id);
      msg.error === 'success' ? resolve(msg.data) : reject(new Error(msg.error));
    } else if (msg.event) {
      for (let i = eventWaiters.length - 1; i >= 0; i--) {
        if (eventWaiters[i].name === msg.event) { eventWaiters.splice(i, 1)[0].resolve(msg); }
      }
    }
  }
});
sock.on('error', (e) => { console.error('[ipc] socket error:', e.message); process.exit(1); });

function cmd(...command) {
  const request_id = ++reqId;
  return new Promise((resolve, reject) => {
    pending.set(request_id, { resolve, reject });
    sock.write(JSON.stringify({ command, request_id }) + '\n');
    setTimeout(() => { if (pending.delete(request_id)) reject(new Error(`timeout: ${command[0]} ${command[1] ?? ''}`)); }, 4000);
  });
}
const get = (prop) => cmd('get_property', prop);
const set = (prop, val) => cmd('set_property', prop, val);
function waitEvent(name, ms = 8000) {
  return new Promise((resolve, reject) => {
    const w = { name, resolve };
    eventWaiters.push(w);
    setTimeout(() => { const i = eventWaiters.indexOf(w); if (i >= 0) { eventWaiters.splice(i, 1); reject(new Error(`timeout event ${name}`)); } }, ms);
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ok = true;
const pass = (m) => console.log('  [PASS]', m);
const fail = (m) => { ok = false; console.log('  [FAIL]', m); };

await new Promise((r) => sock.once('connect', r));
console.log('[ipc] connecte a', SOCK);

try {
  // 1. Charger + attendre file-loaded
  const loaded = waitEvent('file-loaded');
  await cmd('loadfile', SRC, 'replace');
  await loaded;
  pass('loadfile -> file-loaded recu');

  // 2. Decode HW reel ?
  const hwdec = await get('hwdec-current').catch(() => 'n/a');
  (typeof hwdec === 'string' && hwdec.includes('vaapi'))
    ? pass(`hwdec-current = ${hwdec} (DECODE HW VAAPI)`)
    : fail(`hwdec-current = ${hwdec} (attendu vaapi* ; verifier vainfo / --hwdec)`);

  // 3. Dimensions + codec (pour l'overlay : resolution jouee)
  const [w, h, codec] = await Promise.all([
    get('dwidth').catch(() => '?'), get('dheight').catch(() => '?'), get('video-codec').catch(() => '?'),
  ]);
  pass(`video ${w}x${h} codec=${codec}`);

  // 4. time-pos progresse (lecture en cours)
  const t1 = await get('time-pos').catch(() => null);
  await sleep(800);
  const t2 = await get('time-pos').catch(() => null);
  (t1 != null && t2 != null && t2 > t1) ? pass(`time-pos progresse ${t1.toFixed(2)} -> ${t2.toFixed(2)}`)
                                        : fail(`time-pos ne progresse pas (${t1} -> ${t2})`);

  // 5. Nudge LAN : speed 1.05 puis retour 1.0
  await set('speed', 1.05); await sleep(500);
  const sp = await get('speed').catch(() => null);
  (sp && Math.abs(sp - 1.05) < 0.001) ? pass('speed=1.05 applique (nudge LAN OK)') : fail(`speed lu=${sp}`);
  await set('speed', 1.0);

  // 6. Resync dur : seek absolu a 3s
  const target = 3.0;
  await cmd('seek', target, 'absolute', 'exact');
  await sleep(400);
  const ts = await get('time-pos').catch(() => null);
  (ts != null && Math.abs(ts - target) < 1.0) ? pass(`seek absolu 3s -> time-pos=${ts.toFixed(2)} (resync LAN OK)`)
                                              : fail(`seek imprecis : time-pos=${ts}`);

  console.log(ok ? '[ipc] >>> TOUS LES TESTS IPC PASSENT' : '[ipc] >>> DES TESTS IPC ONT ECHOUE (voir [FAIL])');
} catch (e) {
  console.error('[ipc] erreur:', e.message);
  ok = false;
}

// IMPORTANT : on se deconnecte SANS arreter la lecture (le shell enchaine le test z-order).
sock.end();
process.exit(ok ? 0 : 1);
