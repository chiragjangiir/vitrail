'use strict';

/**
 * local_control_server.js — Store Control Panel LAN (§19.3).
 *
 * Mini-serveur HTTP embarqué dans le player, accessible uniquement sur le LAN.
 * L'opérateur magasin scanne un QR code (généré par le CMS) → ouvre cette SPA
 * sur son téléphone → pilote l'audio in-store (paniers, ratio, volume, annonce).
 *
 * Sécurité :
 *   - LAN-only : seules les IP privées/loopback sont acceptées (sinon 403).
 *   - Token QR (du profil serveur) → session HMAC locale 4h.
 *   - Rate limit 10 req/min/IP.
 *
 * Le serveur n'est démarré que si display_config.local_control_enabled (cf. main.js).
 * Les actions sont appliquées localement (callback onAction) ET transmises au
 * backend pour persistance + audit (source=local_control).
 */

const http   = require('http');
const crypto  = require('crypto');

const SESSION_TTL_MS = 4 * 60 * 60 * 1000;  // 4h (§19.3)
const RATE_LIMIT     = 10;                   // requêtes
const RATE_WINDOW_MS = 60 * 1000;            // par minute

function isPrivateAddr(addr) {
  if (!addr) return false;
  // Normalise les IPv4-mapped IPv6 (::ffff:192.168.1.10)
  const ip = addr.replace(/^::ffff:/, '');
  if (ip === '127.0.0.1' || ip === '::1' || ip === 'localhost') return true;
  if (ip.startsWith('10.')) return true;
  if (ip.startsWith('192.168.')) return true;
  if (ip.startsWith('169.254.')) return true;   // link-local
  if (ip.startsWith('fe80:'))    return true;
  const m = ip.match(/^172\.(\d+)\./);
  if (m) { const o = parseInt(m[1], 10); if (o >= 16 && o <= 31) return true; }
  return false;
}

function b64url(buf) {
  return Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

class LocalControlServer {
  /**
   * @param {object} opts
   * @param {number}   opts.port
   * @param {function} opts.getPlayerName  () => string
   * @param {function} opts.getProfile     () => profile|null  (token, role, allowed_basket_ids, can_*)
   * @param {function} opts.getStatus      () => status        (running, volume, now_playing, baskets[])
   * @param {function} opts.onAction       (action) => void    (applique local + forward backend)
   */
  constructor(opts) {
    this.port          = opts.port || 8765;
    this.getPlayerName = opts.getPlayerName || (() => 'Vitrail Player');
    this.getProfile    = opts.getProfile    || (() => null);
    this.getStatus     = opts.getStatus     || (() => ({}));
    this.getVodMedia   = opts.getVodMedia   || (() => []);   // VOD à la demande (Feature B Phase 3)
    this.getVodPeers   = opts.getVodPeers   || (() => []);   // pairs ciblables (trigger multi-cible LAN)
    // Configs VOD PILOTABLES (toutes celles du site, chacune avec SA cible) — cf. _build_vod_configs.
    this.getVodConfigs = opts.getVodConfigs || (() => []);
    this.getSelfId     = opts.getSelfId     || (() => null); // id_player de CE player
    this.onAction      = opts.onAction      || (() => {});
    this.server        = null;
    this._secret       = crypto.randomBytes(32);  // secret de session, régénéré à chaque boot
    this._rate         = new Map();                // ip -> [timestamps]
  }

  start() {
    if (this.server) return;
    this.server = http.createServer((req, res) => this._handle(req, res));
    this.server.on('error', (err) => console.error('[LocalControl] Server error:', err.message));
    this.server.listen(this.port, '0.0.0.0', () => {
      console.log(`[LocalControl] Listening on :${this.port}`);
    });
  }

  stop() {
    if (this.server) {
      try { this.server.close(); } catch {}
      this.server = null;
      console.log('[LocalControl] Stopped');
    }
  }

  // ── Session HMAC ─────────────────────────────────────────────────────────────

  _issueSession() {
    const payload = b64url(JSON.stringify({ exp: Date.now() + SESSION_TTL_MS }));
    const sig = b64url(crypto.createHmac('sha256', this._secret).update(payload).digest());
    return `${payload}.${sig}`;
  }

  _verifySession(token) {
    if (!token || typeof token !== 'string') return false;
    const [payload, sig] = token.split('.');
    if (!payload || !sig) return false;
    const expected = b64url(crypto.createHmac('sha256', this._secret).update(payload).digest());
    if (sig.length !== expected.length) return false;
    if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return false;
    try {
      const data = JSON.parse(Buffer.from(payload.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString());
      return data.exp && data.exp > Date.now();
    } catch { return false; }
  }

  // ── Rate limit ───────────────────────────────────────────────────────────────

  _rateOk(ip) {
    const now = Date.now();
    const hits = (this._rate.get(ip) || []).filter((t) => now - t < RATE_WINDOW_MS);
    hits.push(now);
    this._rate.set(ip, hits);
    return hits.length <= RATE_LIMIT;
  }

  // ── Helpers HTTP ─────────────────────────────────────────────────────────────

  _json(res, code, obj) {
    res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify(obj));
  }

  _readBody(req) {
    return new Promise((resolve) => {
      let body = '';
      req.on('data', (c) => { body += c; if (body.length > 1e5) req.destroy(); });
      req.on('end', () => { try { resolve(body ? JSON.parse(body) : {}); } catch { resolve({}); } });
      req.on('error', () => resolve({}));
    });
  }

  _auth(req) {
    const h = req.headers['authorization'] || '';
    const m = h.match(/^Bearer\s+(.+)$/);
    return m && this._verifySession(m[1]);
  }

  _basketAllowed(profile, id) {
    const allow = profile.allowed_basket_ids;
    return !Array.isArray(allow) || allow.includes(id);
  }

  // ── Routeur ──────────────────────────────────────────────────────────────────

  async _handle(req, res) {
    const ip = req.socket.remoteAddress;
    if (!isPrivateAddr(ip)) { res.writeHead(403); res.end('Forbidden (LAN only)'); return; }
    // NB : le rate-limit ne s'applique QU'À l'auth (anti-bruteforce du token QR).
    // Les routes authentifiées (status/baskets pollés toutes les 5s) ne sont pas limitées.

    const url    = new URL(req.url, `http://localhost:${this.port}`);
    const path   = url.pathname.replace(/\/$/, '') || '/control';
    const method = req.method;

    // SPA (shell, sans auth)
    if (method === 'GET' && (path === '/control' || path === '/')) {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
      res.end(this._spaHtml());
      return;
    }

    const profile = this.getProfile();
    if (!profile) { this._json(res, 503, { error: 'control_unavailable' }); return; }

    // Auth : échange token QR → session (seule route rate-limitée — anti-bruteforce)
    if (method === 'POST' && path === '/control/auth') {
      if (!this._rateOk(ip)) { this._json(res, 429, { error: 'rate_limited' }); return; }
      const body = await this._readBody(req);
      const ok = body.token && typeof body.token === 'string'
        && profile.token && body.token.length === profile.token.length
        && crypto.timingSafeEqual(Buffer.from(body.token), Buffer.from(profile.token));
      if (!ok) { this._json(res, 401, { error: 'invalid_token' }); return; }
      this._json(res, 200, {
        session: this._issueSession(),
        player_name: this.getPlayerName(),
        permissions: {
          role: profile.role,
          can_edit_ratio: !!profile.can_edit_ratio,
          can_set_volume: !!profile.can_set_volume,
          can_trigger_event: !!profile.can_trigger_event,
        },
      });
      return;
    }

    // Routes protégées par session
    if (!this._auth(req)) { this._json(res, 401, { error: 'unauthorized' }); return; }

    if (method === 'GET' && path === '/control/status') {
      const st = this.getStatus() || {};
      this._json(res, 200, {
        running: !!st.running,
        volume: st.volume ?? 100,
        music_volume: st.music_volume ?? 100,        // volume famille music (si families_present)
        ambiance_volume: st.ambiance_volume ?? 100,  // volume famille ambiance (si families_present)
        families_present: !!st.families_present,     // music ET ambiance actives → curseurs par famille
        now_playing: st.now_playing || null,
        now_playing_ambiance: st.now_playing_ambiance || null,  // couche ambiance parallèle
        has_emergency: !!st.has_emergency,        // compat ancien bouton générique
        emergency_playing: !!st.emergency_playing,
        triggers: st.triggers || [],              // boutons nommés (emergency/message)
        triggered_id: st.triggered_id ?? null,    // emergency en cours (toggle)
        basket_output: st.basket_output || 'auto',
        content_sound: st.content_sound || 'on',
      });
      return;
    }

    if (method === 'GET' && path === '/control/baskets') {
      const st = this.getStatus() || {};
      const baskets = (st.baskets || []).filter((b) => this._basketAllowed(profile, b.id_basket));
      this._json(res, 200, { baskets });
      return;
    }

    // /control/baskets/{id}/toggle  &  /control/baskets/{id}/ratio
    let m = path.match(/^\/control\/baskets\/(\d+)\/(toggle|ratio)$/);
    if (m) {
      const id = parseInt(m[1], 10);
      const kind = m[2];
      if (!this._basketAllowed(profile, id)) { this._json(res, 403, { error: 'basket_forbidden' }); return; }
      const body = await this._readBody(req);
      if (kind === 'toggle' && method === 'POST') {
        this.onAction({ action: 'toggle_basket', id_basket: id, is_active: !!body.is_active });
        this._json(res, 200, { ok: true });
        return;
      }
      if (kind === 'ratio' && method === 'PUT') {
        if (!profile.can_edit_ratio) { this._json(res, 403, { error: 'ratio_forbidden' }); return; }
        const ratio = Math.max(0, Math.min(100, parseInt(body.mix_ratio, 10) || 0));
        this.onAction({ action: 'set_ratio', id_basket: id, mix_ratio: ratio });
        this._json(res, 200, { ok: true, mix_ratio: ratio });
        return;
      }
    }

    // Batch ratios (auto-équilibrage option C)
    if (method === 'PUT' && path === '/control/baskets/ratios') {
      if (!profile.can_edit_ratio) { this._json(res, 403, { error: 'ratio_forbidden' }); return; }
      const body = await this._readBody(req);
      const ratios = (Array.isArray(body.ratios) ? body.ratios : [])
        .filter((r) => this._basketAllowed(profile, r.id_basket))
        .map((r) => ({ id_basket: r.id_basket, mix_ratio: Math.max(0, Math.min(100, parseInt(r.mix_ratio, 10) || 0)) }));
      this.onAction({ action: 'set_ratios', ratios });
      this._json(res, 200, { ok: true, ratios });
      return;
    }

    // Rappel des réglages serveur (efface les overrides opérateur → ratios/états du programme)
    if (method === 'POST' && path === '/control/reset-defaults') {
      if (!profile.can_edit_ratio) { this._json(res, 403, { error: 'ratio_forbidden' }); return; }
      this.onAction({ action: 'reset_overrides' });
      this._json(res, 200, { ok: true });
      return;
    }

    // Sortie audio (paniers) + son des contenus
    if (method === 'POST' && path === '/control/output') {
      if (!profile.can_set_volume) { this._json(res, 403, { error: 'output_forbidden' }); return; }
      const body = await this._readBody(req);
      const out = { action: 'set_output' };
      // Le contrôle local pilote l'audio (paniers) → sortie Jack/USB, jamais HDMI (§XIX).
      if (['auto', 'jack', 'usb'].includes(body.basket_output)) out.basket_output = body.basket_output;
      if (['on', 'muted'].includes(body.content_sound)) out.content_sound = body.content_sound;
      this.onAction(out);
      this._json(res, 200, { ok: true });
      return;
    }

    if (method === 'POST' && path === '/control/volume') {
      if (!profile.can_set_volume) { this._json(res, 403, { error: 'volume_forbidden' }); return; }
      const body = await this._readBody(req);
      const volume = Math.max(0, Math.min(100, parseInt(body.volume, 10) || 0));
      this.onAction({ action: 'set_volume', volume });
      this._json(res, 200, { ok: true, volume });
      return;
    }

    if (method === 'POST' && path === '/control/family-volume') {
      if (!profile.can_set_volume) { this._json(res, 403, { error: 'volume_forbidden' }); return; }
      const body = await this._readBody(req);
      const family = body.family === 'ambiance' ? 'ambiance' : (body.family === 'music' ? 'music' : null);
      if (!family) { this._json(res, 400, { error: 'bad_family' }); return; }
      const volume = Math.max(0, Math.min(100, parseInt(body.volume, 10) || 0));
      this.onAction({ action: 'set_family_volume', family, volume });
      this._json(res, 200, { ok: true, family, volume });
      return;
    }

    if (method === 'POST' && path === '/control/event') {
      if (!profile.can_trigger_event) { this._json(res, 403, { error: 'event_forbidden' }); return; }
      const body = await this._readBody(req);
      this.onAction({ action: 'trigger_event', id_basket: body.id_basket ?? null });
      this._json(res, 200, { ok: true });
      return;
    }

    // VOD à la demande LAN-local (Feature B Phase 3) — gated can_trigger_event (lecture ad-hoc)
    if (method === 'GET' && path === '/control/vod') {
      if (!profile.can_trigger_event) { this._json(res, 403, { error: 'vod_forbidden' }); return; }
      // Configs PILOTABLES (toutes celles du site), chacune avec SES medias et SA cible.
      const configs = (this.getVodConfigs ? (this.getVodConfigs() || []) : []).map((c) => ({
        id_vod: c.id_vod, vod_name: c.vod_name,
        medias: (c.medias || []).map((m) => ({
          id_media: m.id_media, media_name: m.media_name,
          media_type: m.media_type, has_audio: m.has_audio !== false,
        })),
        players: (c.players || []).map((p) => ({ id_player: p.id_player, name: p.name })),
      }));
      // `media`/`peers` conserves : un panneau plus ancien (cache navigateur) continue de marcher.
      const media = (this.getVodMedia() || []).map((m) => ({
        id_media: m.id_media, media_name: m.media_name, media_type: m.media_type,
      }));
      const peers = (this.getVodPeers() || []).map((p) => ({ id_player: p.id_player, name: p.name }));
      this._json(res, 200, { configs, media, peers, self_id: this.getSelfId() });
      return;
    }
    if (method === 'POST' && path === '/control/vod/play') {
      if (!profile.can_trigger_event) { this._json(res, 403, { error: 'vod_forbidden' }); return; }
      const body = await this._readBody(req);
      let mode = body.mode === 'loop' ? 'loop' : (body.mode === 'stop' ? 'stop' : 'once');
      // Son choisi au declenchement, encode DANS le mode : la chaine signee du paquet LAN
      // (vod_play|id_player|id_media|mode|ts|nonce) reste inchangee, donc aucune rupture de
      // compatibilite entre versions pendant un deploiement partiel.
      if (body.with_sound === false && mode !== 'stop') mode = mode + '_muted';
      const id_media = parseInt(body.id_media, 10) || null;
      if (mode !== 'stop' && !id_media) { this._json(res, 400, { error: 'bad_media' }); return; }
      // id_players = sous-ensemble de cibles (vide/absent → tous les pairs, géré côté main.js).
      const id_players = Array.isArray(body.id_players)
        ? body.id_players.map((x) => parseInt(x, 10)).filter((x) => !Number.isNaN(x))
        : null;
      this.onAction({ action: 'play_vod', id_media, mode, id_players });
      this._json(res, 200, { ok: true, mode });
      return;
    }

    this._json(res, 404, { error: 'not_found' });
  }

  // ── SPA (mobile-first, design system Vitrail) ─────────────────────────────────

  _spaHtml() {
    // Anglais uniquement (règle player). Inter, fond #1D2B3A, accent #4875B4,
    // cibles tactiles ≥64px, badges icône+couleur+libellé.
    return `<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Vitrail — Audio Control</title>
<style>
  :root{--bg:#1D2B3A;--card:#243548;--accent:#4875B4;--text:#F8F7F5;--muted:#9fb0c3;--ok:#3FB984;--off:#7c8aa0}
  *{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
  body{margin:0;background:var(--bg);color:var(--text);padding:16px;max-width:560px;margin:0 auto}
  h1{font-size:18px;font-weight:600;margin:4px 0}
  .sub{color:var(--muted);font-size:13px;margin-bottom:16px}
  .card{background:var(--card);border-radius:12px;padding:16px;margin-bottom:14px}
  .row{display:flex;align-items:center;justify-content:space-between;gap:12px}
  .npwrap{flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-align:right}
  .np{display:inline-block;font-weight:600;white-space:nowrap}
  .vol{width:100%;height:44px}
  .baskets{display:flex;flex-direction:column;gap:10px}
  .fam-h{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#9aa;font-weight:700;margin:8px 2px -2px}
  .b{background:var(--card);border-radius:12px;padding:14px;min-height:96px;display:flex;flex-direction:column;justify-content:space-between;border:2px solid transparent;cursor:pointer}
  .b.on{border-color:var(--accent)}
  .b .name{font-weight:600;font-size:14px}
  .badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:3px 8px;border-radius:99px}
  .badge.on{background:rgba(63,185,132,.18);color:var(--ok)}
  .badge.off{background:rgba(124,138,160,.18);color:var(--off)}
  .dot{width:8px;height:8px;border-radius:50%;background:currentColor}
  button{font-family:inherit}
  .btn{width:100%;min-height:64px;border:none;border-radius:12px;background:var(--accent);color:#fff;font-size:16px;font-weight:600;margin-top:6px}
  .btn.alt{background:#243548;color:var(--text);border:1px solid var(--accent)}
  .btn.alt.playing{background:#c0392b;color:#fff;border-color:#c0392b}
  .ratio{display:flex;align-items:center;gap:8px;margin-top:8px}
  .ratio input{flex:1}
  .err{color:#f0a; text-align:center;padding:24px}
  .hidden{display:none}
  .ctl{display:flex;gap:6px}
  .step{min-width:64px;min-height:48px;border-radius:10px;border:1px solid var(--accent);background:transparent;color:var(--text);font-size:20px;font-weight:600}
</style></head><body>
<div id="app"><div class="err">Connecting…</div></div>
<script>
const qs = new URLSearchParams(location.search);
let S = { session:null, perm:{} };
async function api(path, opt){ opt=opt||{}; opt.headers=Object.assign({'Content-Type':'application/json'}, opt.headers||{}, S.session?{Authorization:'Bearer '+S.session}:{}); const r=await fetch(path,opt); if(!r.ok) throw new Error((await r.json().catch(()=>({}))).error||r.status); return r.json(); }
function el(h){ const d=document.createElement('div'); d.innerHTML=h; return d.firstElementChild; }
async function auth(){ const t=qs.get('token'); if(!t){ fail('Missing access token. Scan the QR code again.'); return; } try{ const r=await api('/control/auth',{method:'POST',body:JSON.stringify({token:t})}); S.session=r.session; S.perm=r.permissions||{}; S.name=r.player_name; render(); poll(); }catch(e){ fail('Access denied: '+e.message); } }
function fail(m){ document.getElementById('app').innerHTML='<div class="err">'+m+'</div>'; }
async function poll(){ try{ const st=await api('/control/status'); const bk=(await api('/control/baskets')).baskets; paint(st,bk); }catch(e){} setTimeout(poll,5000); }
// Auto-équilibrage des % (option C) — miroir de frontend/src/lib/audioRatio.ts
function rebalance(items, changedId, newValue){
  const cl=(v,mn,mx)=>Math.max(mn,Math.min(mx,v)); const res={};
  const ch=items.find(i=>i.id===changedId); if(!ch){ items.forEach(i=>res[i.id]=i.ratio); return res; }
  const chVal=cl(Math.round(newValue),ch.min,ch.max); res[ch.id]=chVal;
  let free=items.filter(i=>i.id!==changedId).map(i=>({...i}));
  if(!free.length){ res[ch.id]=cl(100,ch.min,ch.max); return res; }
  let remaining=100-chVal, guard=0;
  while(free.length && guard++<30){
    const ws=free.reduce((s,i)=>s+Math.max(0.001,i.ratio),0); let clamped=false;
    for(const i of [...free]){
      const share=remaining*(Math.max(0.001,i.ratio)/ws);
      if(share<i.min){ res[i.id]=i.min; remaining-=i.min; free=free.filter(x=>x.id!==i.id); clamped=true; }
      else if(share>i.max){ res[i.id]=i.max; remaining-=i.max; free=free.filter(x=>x.id!==i.id); clamped=true; }
    }
    if(!clamped){ const ws2=free.reduce((s,i)=>s+Math.max(0.001,i.ratio),0); let acc=0;
      free.forEach((i,idx)=>{ const v=idx===free.length-1?Math.max(0,Math.round(remaining-acc)):Math.round(remaining*(Math.max(0.001,i.ratio)/ws2)); res[i.id]=v; acc+=v; }); free=[]; }
  }
  items.forEach(i=>{ if(res[i.id]===undefined) res[i.id]=cl(i.ratio,i.min,i.max); });
  return res;
}
function applyNowPlayingScroll(){
  const wrap=document.getElementById('npwrap'), np=document.getElementById('np'); if(!wrap||!np) return;
  if(np.getAnimations) np.getAnimations().forEach(a=>a.cancel());
  const overflow = np.scrollWidth - wrap.clientWidth;
  if(overflow > 4 && np.animate){
    const d = Math.max(4000, overflow*45);
    np.animate(
      [{transform:'translateX(0)'},{transform:'translateX(0)'},{transform:'translateX(-'+overflow+'px)'},{transform:'translateX(-'+overflow+'px)'}],
      {duration:d, iterations:Infinity, direction:'alternate', easing:'linear'}
    );
  }
}
let _volTimer=null;
let _busyUntil=0;   // anti-écrasement : on n'écrase pas un curseur pendant ~2.5s après interaction
function buildBasketCard(b, mix, grid){
  const on=!!b.active;
  const c=el('<div class="b '+(on?'on':'')+'" data-id="'+b.id_basket+'"></div>');
  c.appendChild(el('<div class="name">'+(b.basket_name||'Basket')+'</div>'));
  c.appendChild(el('<span class="badge '+(on?'on':'off')+'"><span class="dot"></span>'+(on?'ACTIVE':'INACTIVE')+'</span>'));
  c.onclick=async()=>{ const ni=!c.classList.contains('on'); c.classList.toggle('on', ni); const bd=c.querySelector('.badge'); if(bd){ bd.className='badge '+(ni?'on':'off'); bd.innerHTML='<span class="dot"></span>'+(ni?'ACTIVE':'INACTIVE'); } try{ await api('/control/baskets/'+b.id_basket+'/toggle',{method:'POST',body:JSON.stringify({is_active:ni})}); }catch(e){} };
  if(S.perm.can_edit_ratio){
    // mix = paniers de LA MÊME famille (music ou ambiance) → rééquilibrage par famille.
    // Panier unique dans sa famille → 100% verrouillé (curseur désactivé).
    const solo = (mix||[]).length===1;
    const val = solo ? 100 : (b.mix_ratio||0);
    const rr=el('<div class="ratio"></div>');
    const ri=el('<input type="range" min="'+(b.min_ratio||0)+'" max="'+(b.max_ratio??100)+'" value="'+val+'"'+(solo?' disabled':'')+'>');
    const rv=el('<span class="rv">'+val+'%</span>');
    if(!solo){
      ri.oninput=()=>{ _busyUntil=Date.now()+2500; rv.textContent=ri.value+'%'; };
      ri.onchange=async()=>{
        _busyUntil=Date.now()+2500;
        // état courant lu depuis les curseurs de LA FAMILLE (compose les éditions successives)
        const items=mix.map(x=>{ const e2=grid.querySelector('[data-id="'+x.id_basket+'"] input[type=range]'); return {id:x.id_basket, ratio:e2?parseInt(e2.value,10):(x.mix_ratio||0), min:x.min_ratio||0, max:x.max_ratio??100}; });
        const r=rebalance(items, b.id_basket, parseInt(ri.value,10));
        Object.keys(r).forEach(k=>{ const e2=grid.querySelector('[data-id="'+k+'"] input[type=range]'); if(e2){ e2.value=r[k]; const rvk=e2.parentElement.querySelector('.rv'); if(rvk) rvk.textContent=r[k]+'%'; } });
        const ratios=Object.keys(r).map(k=>({id_basket:+k,mix_ratio:r[k]}));
        try{ await api('/control/baskets/ratios',{method:'PUT',body:JSON.stringify({ratios})}); }catch(e){}
      };
      ri.onclick=(e)=>e.stopPropagation();
    }
    rr.appendChild(ri); rr.appendChild(rv); c.appendChild(rr);
  }
  return c;
}
function paint(st,baskets){
  const np = st.now_playing ? (st.now_playing.name||'—') : '—';
  const npEl = document.getElementById('np');
  if(npEl.textContent !== np){ npEl.textContent = np; applyNowPlayingScroll(); }
  // 2e ligne : couche ambiance (affichée seulement si une ambiance joue en parallèle)
  const npa = st.now_playing_ambiance ? (st.now_playing_ambiance.name||'—') : null;
  const npaRow = document.getElementById('nparow'), npaEl = document.getElementById('npa');
  if(npaRow && npaEl){ if(npa){ npaRow.style.display=''; if(npaEl.textContent!==npa) npaEl.textContent=npa; } else { npaRow.style.display='none'; } }
  const tg=document.getElementById('triggers');
  if(tg){
    tg.innerHTML='';
    (st.triggers||[]).forEach(tr=>{
      const playing = tr.basket_type==='emergency' && st.triggered_id===tr.id_basket;
      const b=el('<button class="btn alt'+(playing?' playing':'')+'"></button>');
      b.textContent = playing ? ('■ Stop '+tr.basket_name) : ((tr.basket_type==='emergency'?'📢 ':'▶ ')+tr.basket_name);
      b.onclick=async()=>{ try{ await api('/control/event',{method:'POST',body:JSON.stringify({id_basket:tr.id_basket})}); poll(); }catch(e){} };
      tg.appendChild(b);
    });
  }
  // Volume — ne pas écraser pendant que l'utilisateur le manipule
  if(Date.now() > _busyUntil){ const v=document.getElementById('vol'); if(v && document.activeElement!==v){ v.value=st.volume; const vv=document.getElementById('volv'); if(vv) vv.textContent=st.volume+'%'; } }
  // Volumes par famille — affichés seulement si les 2 familles jouent
  const fvCard=document.getElementById('famvol');
  if(fvCard){
    fvCard.style.display = st.families_present ? '' : 'none';
    if(st.families_present && Date.now() > _busyUntil){
      [['music', st.music_volume],['ambiance', st.ambiance_volume]].forEach(([fam,val])=>{
        const fr=document.getElementById('fv_'+fam);
        if(fr && document.activeElement!==fr){ fr.value=(val ?? 100); const lv=document.getElementById('fv_'+fam+'v'); if(lv) lv.textContent=(val ?? 100)+'%'; }
      });
    }
  }
  // Sortie audio + mute contenus
  const bo=document.getElementById('bout'); if(bo && document.activeElement!==bo) bo.value=st.basket_output||'auto';
  const cm=document.getElementById('cmute'); if(cm) cm.checked = st.content_sound==='muted';

  // My Baskets = music/ambiance, regroupés par FAMILLE (2 couches simultanées, budgets
  // indépendants). On ne reconstruit la grille QUE si l'ensemble des paniers/familles
  // change (sinon on détruirait les curseurs en cours d'usage).
  const grid=document.getElementById('baskets'); if(!grid) return;
  const mix = baskets.filter(b=>['music','ambiance'].includes(b.basket_type));
  const sig = mix.map(b=>b.basket_type+':'+b.id_basket).join(',');
  if(grid.__sig !== sig){
    grid.__sig = sig; grid.innerHTML='';
    ['music','ambiance'].forEach(fam=>{
      const fb = mix.filter(b=>b.basket_type===fam);
      if(!fb.length) return;
      grid.appendChild(el('<div class="fam-h">'+(fam==='music'?'Music':'Ambiance')+'</div>'));
      fb.forEach(b=>grid.appendChild(buildBasketCard(b, fb, grid)));   // fb = famille → rebalance par famille
    });
  } else {
    // Mise à jour légère en place (badge actif + curseur si pas en interaction/désactivé)
    mix.forEach(b=>{
      const c=grid.querySelector('[data-id="'+b.id_basket+'"]'); if(!c) return;
      const on=!!b.active; c.className='b '+(on?'on':'');
      const bd=c.querySelector('.badge'); if(bd){ bd.className='badge '+(on?'on':'off'); bd.innerHTML='<span class="dot"></span>'+(on?'ACTIVE':'INACTIVE'); }
      if(Date.now() > _busyUntil){ const ri=c.querySelector('input[type=range]'); if(ri && !ri.disabled && document.activeElement!==ri){ ri.value=b.mix_ratio||0; const rv=c.querySelector('.rv'); if(rv) rv.textContent=(b.mix_ratio||0)+'%'; } }
    });
  }
}
function render(){
  document.getElementById('app').innerHTML='';
  const root=document.getElementById('app');
  root.appendChild(el('<h1>♪ Vitrail — Audio Control</h1>'));
  root.appendChild(el('<div class="sub">'+(S.name||'Player')+'</div>'));
  root.appendChild(el('<div class="card"><div class="row"><span>Now playing</span><span class="npwrap" id="npwrap"><span class="np" id="np">—</span></span></div><div class="row" id="nparow" style="display:none"><span>Ambiance</span><span class="npwrap"><span class="np" id="npa">—</span></span></div></div>'));
  if(S.perm.can_set_volume){
    const v=el('<div class="card"></div>');
    v.appendChild(el('<div class="row"><span>Volume</span><span id="volv">—</span></div>'));
    const r=el('<input class="vol" id="vol" type="range" min="0" max="100" value="100">');
    r.oninput=()=>{ _busyUntil=Date.now()+2500; document.getElementById('volv').textContent=r.value+'%'; };
    r.onchange=()=>{ _busyUntil=Date.now()+2500; clearTimeout(_volTimer); _volTimer=setTimeout(()=>api('/control/volume',{method:'POST',body:JSON.stringify({volume:parseInt(r.value,10)})}).catch(()=>{}),150); };
    v.appendChild(r);
    root.appendChild(v);
    // Volumes PAR FAMILLE (Music / Ambiance) — visibles seulement si les 2 familles jouent
    // (sinon le volume général suffit). Pilotés via /control/family-volume.
    const fv=el('<div class="card" id="famvol" style="display:none"></div>');
    [['music','Music'],['ambiance','Ambiance']].forEach(([fam,label])=>{
      fv.appendChild(el('<div class="row"><span>'+label+' volume</span><span id="fv_'+fam+'v">—</span></div>'));
      const fr=el('<input class="vol" id="fv_'+fam+'" type="range" min="0" max="100" value="100">');
      fr.oninput=()=>{ _busyUntil=Date.now()+2500; document.getElementById('fv_'+fam+'v').textContent=fr.value+'%'; };
      fr.onchange=()=>{ _busyUntil=Date.now()+2500; clearTimeout(fr._t); fr._t=setTimeout(()=>api('/control/family-volume',{method:'POST',body:JSON.stringify({family:fam,volume:parseInt(fr.value,10)})}).catch(()=>{}),150); };
      fv.appendChild(fr);
    });
    root.appendChild(fv);
  } else { root.appendChild(el('<div class="card"><div class="row"><span>Volume</span><span id="vol" style="display:none"></span><span id="volv"></span></div></div>')); }
  if(S.perm.can_set_volume){
    const o=el('<div class="card"></div>');
    o.appendChild(el('<div class="row" style="margin-bottom:6px"><span>Audio output</span></div>'));
    const sel=el('<select id="bout" style="width:100%;min-height:44px;border-radius:10px;border:1px solid var(--accent);background:#1b2736;color:var(--text);padding:0 8px;font-size:15px"></select>');
    [['auto','Auto (default)'],['jack','Jack 3.5mm'],['usb','USB']].forEach(([v,t])=>{ const op=document.createElement('option'); op.value=v; op.textContent=t; sel.appendChild(op); });
    sel.onchange=async()=>{ try{ await api('/control/output',{method:'POST',body:JSON.stringify({basket_output:sel.value})}); poll(); }catch(e){} };
    o.appendChild(sel);
    const lab=el('<label style="display:flex;align-items:center;gap:8px;margin-top:10px;font-size:13px"><input type="checkbox" id="cmute"><span>Mute standard content sound</span></label>');
    lab.querySelector('input').onchange=async(ev)=>{ try{ await api('/control/output',{method:'POST',body:JSON.stringify({content_sound:ev.target.checked?'muted':'on'})}); poll(); }catch(e){} };
    o.appendChild(lab);
    root.appendChild(o);
  }
  root.appendChild(el('<div style="font-size:13px;color:var(--muted);margin:8px 4px">MY BASKETS</div>'));
  root.appendChild(el('<div class="baskets" id="baskets"></div>'));
  if(S.perm.can_edit_ratio){
    const rb=el('<button class="btn alt" style="margin-top:10px">↺ Recall server settings</button>');
    rb.onclick=async()=>{ if(!confirm('Recall the server default mix? Your local changes will be cleared.')) return; try{ await api('/control/reset-defaults',{method:'POST'}); _busyUntil=0; setTimeout(poll,300); }catch(e){} };
    root.appendChild(rb);
  }
  if(S.perm.can_trigger_event){
    // Boutons déclencheurs nommés (un par panier emergency/message), peuplés par paint().
    root.appendChild(el('<div id="triggers" style="display:flex;flex-direction:column;gap:8px;margin-top:6px"></div>'));
    // VOD à la demande LAN-local (Feature B Phase 3) : « Play a video » (takeover local).
    root.appendChild(el('<div style="font-size:13px;color:var(--muted);margin:14px 4px 4px">PLAY A VIDEO</div>'));
    root.appendChild(el('<div id="vodbox" style="display:flex;flex-direction:column;gap:8px"></div>'));
    loadVod();
  }
}
var _vodTargets={};   // id_vod -> Set d'id_player coches (cibles de CETTE config)
var _vodSound={};     // id_vod -> bool (son au declenchement)
async function vodPlay(idVod, id, mode){
  var set=_vodTargets[idVod];
  var ids = set ? Array.from(set) : null;
  if(set && !ids.length){ alert('Pick at least one screen.'); return; }
  var withSound = _vodSound[idVod] !== false;
  try{ await api('/control/vod/play',{method:'POST',body:JSON.stringify(
    {id_media:id,mode,id_players:ids,with_sound:withSound})}); }catch(e){}
}
async function loadVod(){
  const box=document.getElementById('vodbox'); if(!box) return;
  let configs=[], selfId=null;
  try{ const r=await api('/control/vod'); configs=r.configs||[]; selfId=r.self_id; }catch(e){}
  box.innerHTML='';
  if(!configs.length){ box.appendChild(el('<div class="sub" style="margin:0">No VOD list available.</div>')); return; }
  configs.forEach(cfg=>{
    const key=cfg.id_vod;
    if(!_vodTargets[key]) _vodTargets[key]=new Set((cfg.players||[]).map(p=>p.id_player));
    if(_vodSound[key]===undefined) _vodSound[key]=true;
    const c=el('<div class="card" style="margin-bottom:0;padding:12px"></div>');
    // En-tete repliable : nom de la config + nombre d'ecrans REELLEMENT vises.
    const head=el('<div style="display:flex;align-items:center;gap:8px;cursor:pointer"></div>');
    const caret=el('<span style="font-size:12px;width:10px">&#9654;</span>');
    head.appendChild(caret);
    head.appendChild(el('<div class="name" style="font-weight:600;font-size:14px;flex:1">'+(cfg.vod_name||('VOD #'+key))+'</div>'));
    const cnt=el('<span class="sub" style="margin:0;font-size:12px"></span>');
    const refreshCount=()=>{ cnt.textContent=_vodTargets[key].size+'/'+(cfg.players||[]).length+' screens'; };
    refreshCount(); head.appendChild(cnt); c.appendChild(head);
    const body=el('<div style="display:none;margin-top:10px"></div>');
    head.onclick=()=>{ const open=body.style.display!=='none';
      body.style.display=open?'none':'block'; caret.innerHTML=open?'&#9654;':'&#9660;'; };
    // Cibles de CETTE config uniquement (le bug corrige : plus la liste du site entier).
    (cfg.players||[]).forEach(p=>{
      const row=el('<label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:14px"></label>');
      const cb=el('<input type="checkbox" style="width:18px;height:18px">'); cb.checked=_vodTargets[key].has(p.id_player);
      cb.onchange=()=>{ if(cb.checked)_vodTargets[key].add(p.id_player); else _vodTargets[key].delete(p.id_player); refreshCount(); };
      row.appendChild(cb);
      row.appendChild(el('<span>'+(p.name||('#'+p.id_player))+(p.id_player===selfId?' (this screen)':'')+'</span>'));
      body.appendChild(row);
    });
    if(!(cfg.players||[]).length) body.appendChild(el('<div class="sub" style="margin:0">No screen targeted.</div>'));
    // Son du declenchement, pour cette config.
    const srow=el('<label style="display:flex;align-items:center;gap:8px;padding:8px 0 4px;font-size:14px"></label>');
    const scb=el('<input type="checkbox" style="width:18px;height:18px">'); scb.checked=_vodSound[key];
    scb.onchange=()=>{ _vodSound[key]=scb.checked; };
    srow.appendChild(scb); srow.appendChild(el('<span>Play with sound</span>'));
    body.appendChild(srow);
    // Medias de CETTE config.
    (cfg.medias||[]).forEach(m=>{
      const mc=el('<div style="border-top:1px solid rgba(255,255,255,.08);padding-top:8px;margin-top:8px"></div>');
      const label=(m.media_name||('#'+m.id_media))+(m.has_audio===false?' (silent)':'');
      mc.appendChild(el('<div style="font-size:13px;margin-bottom:6px">'+label+'</div>'));
      const row=el('<div class="ctl"></div>');
      const once=el('<button class="step" style="flex:1">&#9654; Once</button>');
      once.onclick=()=>vodPlay(key,m.id_media,'once');
      const loop=el('<button class="step" style="flex:1">&#8635; Loop</button>');
      loop.onclick=()=>vodPlay(key,m.id_media,'loop');
      row.appendChild(once); row.appendChild(loop); mc.appendChild(row); body.appendChild(mc);
    });
    if(!(cfg.medias||[]).length) body.appendChild(el('<div class="sub" style="margin:0">No video in this list.</div>'));
    const stop=el('<button class="btn alt" style="margin-top:10px;width:100%">&#9632; Stop video</button>');
    stop.onclick=()=>vodPlay(key,(cfg.medias&&cfg.medias[0]?cfg.medias[0].id_media:0),'stop');
    body.appendChild(stop);
    c.appendChild(body); box.appendChild(c);
  });
}
auth();
</script></body></html>`;
  }
}

module.exports = { LocalControlServer, isPrivateAddr };
