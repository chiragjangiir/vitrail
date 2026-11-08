'use strict';

/**
 * mpv_controller.js — Rendu vidéo HW VAAPI via mpv (Intel/Linux), alternatif au <video>
 * Chromium qui reste software sur Intel/Linux (cf. docs/SPIKE_mpv_hwdecode_linux.md).
 *
 * Architecture (Option A du spike) : mpv tourne comme fenêtre X11 plein écran SŒUR du
 * kiosk Electron, pilotée en IPC JSON (socket UNIX). mpv ne rend QUE la vidéo plein
 * écran ; images/web/PDF/templates/overlay restent rendus par Chromium. Le z-order
 * (mpv au-dessus pendant une vidéo, kiosk au-dessus sinon) est piloté par `wmctrl -a`
 * — LEÇON PoC : la propriété mpv `ontop` ne restacke PAS une fenêtre déjà mappée.
 *
 * Activé par player via display_config.video_renderer='mpv' (le renderer décide, ce
 * module exécute). Spawn paresseux (au 1er load), tué quand on quitte le mode mpv ou
 * à la fermeture de l'app.
 */

const { spawn, execFile } = require('child_process');
const net = require('net');
const fs  = require('fs');
const EventEmitter = require('events');

const SOCK      = '/tmp/signflow-mpv.sock';
const MPV_TITLE = 'SIGNFLOW-MPV';          // titre fenêtre → cible wmctrl pour le raise
const KIOSK_TITLE = 'SignFlow Player';     // titre de la fenêtre Electron (BrowserWindow)

class MpvController extends EventEmitter {
  constructor(logfn) {
    super();
    this.log = logfn || (() => {});
    this.proc = null;
    this.sock = null;
    this._buf = '';
    this._reqId = 0;
    this._pending = new Map();
    this._starting = null;   // promesse d'ensureRunning en cours (anti-double-spawn)
  }

  isRunning() { return !!this.proc && !!this.sock && !this.sock.destroyed; }

  ensureRunning() {
    if (this.isRunning()) return Promise.resolve();
    if (this._starting) return this._starting;
    this._starting = this._spawn().finally(() => { this._starting = null; });
    return this._starting;
  }

  async _spawn() {
    if (this.proc) this.quit();        // process orphelin sans socket → repartir propre
    // Filet : tuer un mpv orphelin d'un process player précédent (un restart via app.exit()
    // peut shunter le cleanup). Titre unique → ne touche que NOTRE mpv.
    try { require('child_process').execFileSync('pkill', ['-f', MPV_TITLE], { stdio: 'ignore' }); } catch {}
    try { fs.unlinkSync(SOCK); } catch {}
    const env = { ...process.env, DISPLAY: process.env.DISPLAY || ':0' };
    const args = [
      '--idle=yes', '--force-window=yes', '--fullscreen=yes', '--no-border',
      `--title=${MPV_TITLE}`,
      '--hwdec=vaapi', '--vo=gpu', '--gpu-context=x11egl',
      '--no-osc', '--no-input-default-bindings', '--really-quiet',
      '--keep-open=no',                // fin de fichier → idle (pas de pause sur dernière frame)
      `--input-ipc-server=${SOCK}`,
    ];
    this.log(`[mpv] spawn (hwdec=vaapi, vo=gpu, ipc=${SOCK})`);
    this.proc = spawn('mpv', args, { env, stdio: 'ignore' });
    this.proc.on('exit', (code) => { this.log(`[mpv] exited code=${code}`); this.proc = null; this._teardownSocket(); });
    this.proc.on('error', (e) => { this.log(`[mpv] spawn error: ${e.message}`); this.proc = null; });
    await this._connect();
    // observe_property time-pos : mpv PUSH la position (events property-change, gérés dans _wire)
    // → remplace le poll get_property fragile. Persiste à travers les loadfile (l'observation porte
    // sur le coeur mpv, pas sur le fichier courant) → un seul enregistrement après connexion.
    this._cmd('observe_property', 1, 'time-pos').catch(() => {});
  }

  async _connect() {
    for (let i = 0; i < 100 && !fs.existsSync(SOCK); i++) await new Promise((r) => setTimeout(r, 50));
    await new Promise((resolve, reject) => {
      const s = net.connect(SOCK);
      const to = setTimeout(() => { s.destroy(); reject(new Error('mpv IPC connect timeout')); }, 4000);
      s.once('connect', () => { clearTimeout(to); this.sock = s; this._wire(s); this.log('[mpv] IPC connecté'); resolve(); });
      s.once('error', (e) => { clearTimeout(to); reject(e); });
    });
  }

  _wire(s) {
    s.on('data', (chunk) => {
      this._buf += chunk.toString('utf8');
      let nl;
      while ((nl = this._buf.indexOf('\n')) >= 0) {
        const line = this._buf.slice(0, nl).trim();
        this._buf = this._buf.slice(nl + 1);
        if (!line) continue;
        let msg; try { msg = JSON.parse(line); } catch { continue; }
        if (msg.request_id !== undefined && this._pending.has(msg.request_id)) {
          const { resolve, reject } = this._pending.get(msg.request_id);
          this._pending.delete(msg.request_id);
          msg.error === 'success' ? resolve(msg.data) : reject(new Error(msg.error || 'mpv error'));
        } else if (msg.event) {
          // observe_property time-pos : position poussée par mpv (number ; null à l'EOF/idle, ignoré)
          // → event 'timepos' consommé par le renderer pour le report/nudge LAN.
          if (msg.event === 'property-change' && msg.name === 'time-pos' && typeof msg.data === 'number') {
            this.emit('timepos', { timePos: msg.data });
          }
          this.emit('mpv-event', msg.event, msg);
          if (msg.event === 'end-file') this.emit('ended', msg);
        }
      }
    });
    s.on('close', () => this._teardownSocket());
    s.on('error', () => this._teardownSocket());
  }

  _teardownSocket() {
    if (this.sock) { try { this.sock.destroy(); } catch {} this.sock = null; }
    this._buf = '';
    for (const { reject } of this._pending.values()) reject(new Error('mpv socket closed'));
    this._pending.clear();
  }

  _cmd(...command) {
    return new Promise((resolve, reject) => {
      if (!this.sock || this.sock.destroyed) { reject(new Error('mpv not connected')); return; }
      const request_id = ++this._reqId;
      this._pending.set(request_id, { resolve, reject });
      try { this.sock.write(JSON.stringify({ command, request_id }) + '\n'); }
      catch (e) { this._pending.delete(request_id); reject(e); return; }
      setTimeout(() => { if (this._pending.delete(request_id)) reject(new Error(`mpv timeout: ${command[0]}`)); }, 4000);
    });
  }

  _waitEvent(name, ms) {
    return new Promise((resolve, reject) => {
      const onEv = (ev, msg) => { if (ev === name) { this.off('mpv-event', onEv); clearTimeout(t); resolve(msg); } };
      const t = setTimeout(() => { this.off('mpv-event', onEv); reject(new Error(`mpv timeout event ${name}`)); }, ms);
      this.on('mpv-event', onEv);
    });
  }

  getProp(name)      { return this._cmd('get_property', name); }
  setProp(name, val) { return this._cmd('set_property', name, val); }

  /**
   * Charge et joue un média. `src` = chemin disque local (cache offline-first) OU URL
   * http (MinIO, repli streaming) — la résolution signflow://→disque est faite par main.js.
   * Résout APRÈS l'event file-loaded → le renderer aligne son timer d'avance sur le vrai
   * démarrage de lecture. Throw si le chargement échoue / time out (→ skip côté renderer).
   */
  async load(src, { seekMs = 0, muted = false, subtitles = [] } = {}) {
    await this.ensureRunning();
    await this.setProp('mute', !!muted).catch(() => {});
    await this.setProp('speed', 1.0).catch(() => {});   // reset (la vitesse mpv persiste entre fichiers)
    const loaded = this._waitEvent('file-loaded', 8000);
    await this._cmd('loadfile', src, 'replace');
    await loaded;
    if (seekMs > 0) await this.seek(seekMs).catch(() => {});
    for (const sub of (subtitles || [])) {
      if (sub && sub.url) await this._cmd('sub-add', sub.url, 'auto', sub.label || sub.lang || '', sub.lang || '').catch(() => {});
    }
    // Dimensions + durée pour l'overlay (résolution jouée) et la sync LAN.
    Promise.all([this.getProp('duration'), this.getProp('dwidth'), this.getProp('dheight')])
      .then(([duration, width, height]) => this.emit('videoinfo', { duration, width, height }))
      .catch(() => {});
    // Le suivi de time-pos est assuré par observe_property (enregistré dans _spawn) : mpv PUSH
    // les changements (events property-change, gérés dans _wire). Remplace l'ancien poll
    // get_property toutes les 120ms qui se BLOQUAIT en silence (request/response IPC qui se
    // coince → _mpvTimePos figé → le LEADER diffusait une position MORTE → désync de tout le mur).
  }

  // Message OSD natif mpv (par-dessus la vidéo) — utilisé pour l'indicateur "Reconnecting"
  // que la barre de statut Chromium ne peut pas montrer (masquée derrière la fenêtre mpv).
  osd(text, durMs = 3600000) { return this._cmd('show-text', String(text || ''), durMs).catch(() => {}); }

  // Capture la sortie mpv courante (frame vidéo décodée) dans un fichier PNG. La vidéo mpv
  // rend dans une fenêtre X11 SŒUR, hors de la capture Chromium (capturePage) → sans ça la
  // vignette CMS serait noire en mode mpv. Flag 'window' = exactement ce qui est à l'écran
  // (vidéo + sous-titres + OSD éventuel). Throw si mpv pas prêt / pas de vidéo chargée.
  async screenshot(path) {
    if (!this.isRunning()) throw new Error('mpv not running');
    await this._cmd('screenshot-to-file', path, 'window');
    return path;
  }

  stop()      { return this._cmd('stop').catch(() => {}); }
  setMute(b)  { return this.setProp('mute', !!b).catch(() => {}); }

  // Compensation de bezel (video wall) — étage RENDU mpv (video-zoom + video-align), donc
  // COMPATIBLE hwdec VAAPI (un filtre crop VF forcerait un download GPU→CPU et casserait
  // l'accélération). C'est le geste validé HW au bureau, productisé. Deux modes serveur :
  //   - 'overscan' (B, défaut) : sur-balayage symétrique par axe (chaque écran = sa tuile pleine).
  //   - 'crop' (A, source unique tuilée) : n'afficher que le sous-rect {x,y,w,h} de la source.
  // tf null = reset plein cadre. Persiste entre fichiers (props de rendu globales).
  async setWall(tf) {
    if (!tf) return this._resetWall();

    if (tf.mode === 'crop') {
      // mpv video-zoom est UNIFORME (un seul facteur). Un crop exact à largeur ≠ hauteur (grille
      // non carrée, ex. paire panoramique 2×1) demanderait un zoom non uniforme → IMPOSSIBLE sans
      // filtre VF (qui casserait hwdec VAAPI). On ne traite donc que les grilles CARRÉES (w≈h,
      // ⟺ cols==rows) ; sinon repli plein cadre + avertissement (préférer le mode B overscan sur
      // mpv, ou un renderer CSS/ExoPlayer qui gèrent le crop non uniforme nativement).
      const w = Number(tf.w) || 1, h = Number(tf.h) || 1;
      const x = Number(tf.x) || 0, y = Number(tf.y) || 0;
      if (Math.abs(w - h) > 0.02) {
        this.log(`[wall] crop non carré (w=${w.toFixed(3)} h=${h.toFixed(3)}) → non supporté en mpv uniforme, plein cadre (utiliser mode B overscan)`);
        return this._resetWall();
      }
      // keepaspect=no : la source (authoring = résolution du mur) remplit le cadre, puis zoom
      // uniforme 1/w + align continu pour amener le sous-rect [x..x+w]×[y..y+h] plein écran.
      // align ∈ [-1,1] : a = 2·x/(1-w) − 1 (idem y). Restauré à 'yes' au reset/overscan.
      await this.setProp('keepaspect', 'no').catch(() => {});
      const clamp = (v) => Math.max(-1, Math.min(1, v));
      const zoom = Math.log2(1 / Math.max(w, 1e-4));
      const alignX = w < 1 ? clamp(2 * x / (1 - w) - 1) : 0;
      const alignY = h < 1 ? clamp(2 * y / (1 - h) - 1) : 0;
      await this.setProp('video-zoom', zoom).catch(() => {});
      await this.setProp('video-align-x', alignX).catch(() => {});
      await this.setProp('video-align-y', alignY).catch(() => {});
      return;
    }

    if (tf.mode !== 'overscan') return this._resetWall();

    // Mode B overscan. video-zoom UNIFORME → on prend le max des deux axes (murs homogènes =
    // bezels symétriques → scale_x ≈ scale_y). keepaspect par défaut (yes).
    await this.setProp('keepaspect', 'yes').catch(() => {});
    const zoom = Math.log2(Math.max(Number(tf.scale_x) || 1, Number(tf.scale_y) || 1));
    await this.setProp('video-zoom', zoom).catch(() => {});
    await this.setProp('video-align-x', Number(tf.align_x) || 0).catch(() => {});
    await this.setProp('video-align-y', Number(tf.align_y) || 0).catch(() => {});
  }

  // Plein cadre : annule zoom/align et restaure keepaspect (le crop le passe à 'no').
  async _resetWall() {
    await this.setProp('keepaspect', 'yes').catch(() => {});
    await this.setProp('video-zoom', 0).catch(() => {});
    await this.setProp('video-align-x', 0).catch(() => {});
    await this.setProp('video-align-y', 0).catch(() => {});
  }
  seek(ms)    { return this._cmd('seek', (ms / 1000).toFixed(3), 'absolute', 'exact'); }

  // Z-order : raise explicite via wmctrl (cf. PoC — la prop ontop ne suffit pas).
  raise()        { this._wmctrl(MPV_TITLE); }
  lowerToKiosk() { this._wmctrl(KIOSK_TITLE); }
  _wmctrl(title) {
    const env = { ...process.env, DISPLAY: process.env.DISPLAY || ':0' };
    execFile('wmctrl', ['-a', title], { env }, (e) => { if (e) this.log(`[mpv] wmctrl -a "${title}": ${e.message}`); });
  }

  quit() {
    this._teardownSocket();
    if (this.proc) { try { this.proc.kill('SIGTERM'); } catch {} this.proc = null; }
    try { fs.unlinkSync(SOCK); } catch {}
  }
}

module.exports = { MpvController, MPV_TITLE, KIOSK_TITLE };
