'use strict';

// ── Local Content Store (offline-first / download-then-play, épopée P0) ─────────
// Télécharge les octets des médias (vidéo/image/audio) dans un store local sur disque
// et les sert au renderer via le protocole signflow:// (cf. main.js). Tant qu'un octet
// n'est pas en cache *vérifié*, le renderer continue de streamer l'URL MinIO (repli
// gracieux → P0 ne peut pas régresser).
//
// Clé du store = `cache_key` (le storage_key RÉELLEMENT servi : parent ou rendition),
// pas le checksum du payload — car pour une rendition le payload porte le checksum du
// PARENT (collision/péremption sinon). Nom de fichier = sha1(cache_key) (sûr, stable,
// dédupliqué : deux players qui veulent la même variante partagent le fichier).
// Vérification d'intégrité = sha256 == `cache_checksum` quand il est fourni (parent) ;
// sinon best-effort (atomicité .part→rename, taille via Content-Length).
//
// Look-ahead (prefetch) : le serveur joint au sync une liste `prefetch` du contenu
// programmé sur les prochaines semaines, chaque entrée avec une `priority` (= date de
// diffusion ; plus petit = plus tôt). Le store télécharge à l'avance (file triée par
// priorité) DANS LA LIMITE DU DISQUE, et sous pression évince d'abord le contenu non
// programmé (stale), puis le plus lointain — jamais la playlist courante (épinglée).
// Les downloads de prefetch ne s'effectuent que dans les fenêtres horaires autorisées
// (Phase 2) ; la playlist courante (non-prefetch) télécharge toujours.

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const crypto = require('crypto');
const { URL } = require('url');
const { Transform } = require('stream');

const DL_TIMEOUT_MS = 120000;
const WINDOW_RECHECK_MS = 60000;  // re-tente le prefetch quand une fenêtre peut s'ouvrir
const MIN_MEASURE_BYTES = 1048576;  // mesure de débit : ignorer les fichiers < 1 Mo (bruit)

// "HH:MM" → minutes depuis minuit (null si invalide).
function _hm(str) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(str || '').trim());
  if (!m) return null;
  const h = +m[1], mi = +m[2];
  if (h > 23 || mi > 59) return null;
  return h * 60 + mi;
}

// Throttle de débit (Q3) : retarde le callback _transform → crée une backpressure qui
// ralentit la source via le flow-control de pipe (pacing fiable, sans fighter pipe).
class _Throttle extends Transform {
  constructor(bytesPerSec) { super(); this._bps = bytesPerSec; this._t0 = Date.now(); this._sent = 0; }
  _transform(chunk, _enc, cb) {
    this._sent += chunk.length;
    this.push(chunk);
    const allowedMs = (this._sent / this._bps) * 1000;
    const wait = allowedMs - (Date.now() - this._t0);
    if (wait > 0) return setTimeout(cb, Math.ceil(wait));
    cb();
  }
}
// Éviction (Q2) : on évince le non-épinglé quand le disque dépasse HIGH, jusqu'à LOW.
// Watermarks sur le disque ENTIER (réserve OS/logs incluse), pas juste le store.
const HIGH_WATERMARK = 0.85;
const LOW_WATERMARK = 0.70;
// Frein de stockage (2026-08-06) : plancher ABSOLU d'espace libre.
// Les watermarks ci-dessus sont des RATIOS, et ils ne peuvent RIEN quand tout le cache est
// épinglé (= playlist courante) : l'éviction n'a alors rien à libérer, elle lève `_pressure`
// pour prévenir le serveur… et l'ancien code téléchargeait quand même, jusqu'à saturer la
// partition. Mesuré le 2026-08-06 sur un stick Android de 4 Go : disque à 100 %, 0 octet
// libre, et c'est ANDROID qui casse (SQLITE_FULL, keystore en échec, ENOSPC) — pas seulement
// notre app. L'appareil n'a pu être récupéré qu'en DÉSINSTALLANT Vitrail, donc par un
// déplacement sur site. On préfère désormais renoncer à un média plutôt que rendre la
// machine inutilisable : un écran qui diffuse une partie de sa playlist reste réparable à
// distance, un écran dont l'OS est mort ne l'est plus.
const MIN_FREE_BYTES = 512 * 1024 * 1024;   // 512 Mo laissés à l'OS, jamais consommés
const FREE_GUARD_MS = 2000;                 // re-mesure pendant l'écriture (taille inconnue d'avance)

class ContentStore {
  constructor(baseDir, logger) {
    this.dir = path.join(baseDir, 'content_store');
    this.indexPath = path.join(this.dir, 'index.json');
    this.log = logger || (() => {});
    this.index = {};            // filekey -> { cache_key, mime, size, id_media, last_used, priority }
    this.inflight = new Set();  // filekeys en cours de download
    this.queue = [];            // [{ filekey, cache_key, cache_checksum, mime, url, id_media, priority, isPrefetch }]
    this.active = false;
    this.onReady = null;        // cb({ filekey, cache_key, url })
    this.pinned = new Set();    // filekeys ÉPINGLÉS (= playlist courante) → jamais évincés
    this.prefetchKeys = new Map(); // filekey -> priority (contenu programmé voulu, évinçable par lointain)
    this.downloading = new Set(); // id_media en file/en cours (inventaire UI Q4)
    this._pressure = false;     // true si l'épinglé ne tient pas (alerte serveur)
    this.blocked = new Set();   // id_media non mis en cache faute de place (remonté au serveur)
    this._blockedLogged = false; // n'inonde pas le journal tant que la situation dure
    this.bandwidthKbps = 0;     // QoS (Q3) : plafond download en kbit/s (0 = illimité)
    this.windows = null;        // fenêtres horaires de download (prefetch only), null = toujours
    this.measureBandwidth = false; // mesure passive du débit réel (opt-in display_config)
    this.measuredKbps = 0;      // EWMA du débit mesuré (kbit/s) ; remonté au heartbeat
    this._recheckTimer = null;
    this._activeReq = null;     // requête HTTP du download en cours (pour interruption à chaud)
    this._activeJob = null;     // job en cours (pour le remettre en file si la politique change)
    this._requeueActive = false; // demande de remise en file du download courant (plafond changé)
    this._load();
  }

  // QoS (Q3) + fenêtres (Phase 2 look-ahead) : politique de download. Piloté par display_config.
  setPolicy({ bandwidth_kbps, windows, measure_bandwidth } = {}) {
    const prevBandwidth = this.bandwidthKbps;
    const v = Number(bandwidth_kbps);
    this.bandwidthKbps = Number.isFinite(v) && v > 0 ? v : 0;
    this.measureBandwidth = !!measure_bandwidth;
    // Fenêtres autorisées pour le PREFETCH : [{start:"HH:MM", end:"HH:MM"}]. La playlist
    // courante (non-prefetch) télécharge hors fenêtre aussi. Vide/absent = toujours autorisé.
    if (Array.isArray(windows) && windows.length) {
      const parsed = windows
        .map((w) => ({ s: _hm(w && w.start), e: _hm(w && w.end) }))
        .filter((w) => w.s != null && w.e != null);
      this.windows = parsed.length ? parsed : null;
    } else {
      this.windows = null;
    }
    // Plafond changé EN COURS de download : on interrompt + reprend pour appliquer le nouveau
    // throttle tout de suite (sinon le débit figé au lancement tient jusqu'à la fin → il
    // fallait un reboot ; vu sur fifi 2026-06-08). Le .part est conservé (reprise via Range).
    if (this.bandwidthKbps !== prevBandwidth) this._interruptActiveForPolicy();
    this._pump();  // une fenêtre qui s'ouvre (ou un débit relevé) peut débloquer le prefetch
  }

  // Interrompt le download en cours pour le remettre en file → le nouveau plafond s'applique
  // au prochain pump. No-op s'il n'y a pas de download actif. La reprise est gratuite : le
  // .part déjà écrit est repris via Range, rien n'est re-téléchargé.
  _interruptActiveForPolicy() {
    if (!this.active || !this._activeReq) return;
    this._requeueActive = true;
    this.log('débit: plafond changé en cours de download → interruption + reprise');
    try { this._activeReq.destroy(new Error('throttle-change')); } catch {}
  }

  // True si le prefetch a le droit de télécharger maintenant (selon les fenêtres).
  _downloadAllowed() {
    if (!this.windows) return true;
    const d = new Date();
    const cur = d.getHours() * 60 + d.getMinutes();
    return this.windows.some((w) =>
      w.s <= w.e ? (cur >= w.s && cur <= w.e) : (cur >= w.s || cur <= w.e));  // gère overnight
  }

  // sha1 du cache_key → nom de fichier sûr et stable
  keyFor(cacheKey) {
    return crypto.createHash('sha1').update(String(cacheKey)).digest('hex');
  }

  _fp(filekey) { return path.join(this.dir, filekey); }

  has(filekey) { return !!(filekey && this.index[filekey]); }

  localUrl(filekey) { return `signflow://media/${filekey}`; }

  // MIME d'après l'extension du cache_key servi (objet réel : rendition .mp4, etc.).
  _mimeFromKey(cacheKey) {
    const m = String(cacheKey).toLowerCase().match(/\.([a-z0-9]+)$/);
    if (!m) return null;
    return ({
      mp4: 'video/mp4', m4v: 'video/mp4', webm: 'video/webm', mkv: 'video/x-matroska',
      mov: 'video/quicktime', ogv: 'video/ogg',
      jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif',
      webp: 'image/webp', svg: 'image/svg+xml',
      // Audio (offline-first §XIX) : l'audio ré-encodé est en .ogg ; on couvre les formats courants.
      ogg: 'audio/ogg', opus: 'audio/ogg', mp3: 'audio/mpeg', m4a: 'audio/mp4',
      aac: 'audio/aac', wav: 'audio/wav', flac: 'audio/flac',
      // Documents
      pdf: 'application/pdf',
    })[m[1]] || null;
  }

  // Garde d'intégrité RUNTIME : l'entrée est-elle réellement servable (fichier présent +
  // taille cohérente avec l'index) ? Le `_load` ne purge qu'au démarrage ; ici on couvre
  // une disparition / troncature à chaud (disque qui se remplit, suppression externe,
  // corruption). En cas d'échec on OUBLIE l'entrée → le rewrite gardera l'URL MinIO (repli
  // streaming) et re-mettra le téléchargement en file. Utilisé au rewrite + readiness LAN.
  verify(filekey) {
    const e = this.index[filekey];
    if (!e) return false;
    let size = -1;
    try { size = fs.statSync(this._fp(filekey)).size; } catch { size = -1; }
    if (size < 0 || (e.size != null && size !== e.size)) {
      delete this.index[filekey];
      this._saveIndex();
      this.log(`verify: ${filekey.slice(0, 12)} invalide (taille ${size}/${e.size}) → oublié, repli stream`);
      return false;
    }
    return true;
  }

  // { path, mime } pour le handler de protocole, ou null si absent. Garde existsSync légère
  // (par requête) : si le fichier a disparu en cours de route, on renvoie 404 → le renderer
  // bascule en erreur puis se répare au prochain sync (verify le retire de l'index).
  fileFor(filekey) {
    const e = this.index[filekey];
    if (!e) return null;
    if (!fs.existsSync(this._fp(filekey))) return null;
    e.last_used = Date.now();
    return { path: this._fp(filekey), mime: e.mime || 'application/octet-stream' };
  }

  _load() {
    try {
      fs.mkdirSync(this.dir, { recursive: true });
      this.index = JSON.parse(fs.readFileSync(this.indexPath, 'utf8')) || {};
    } catch { this.index = {}; }
    // Purge les entrées dont le fichier a disparu (cohérence index↔disque).
    let pruned = 0;
    for (const k of Object.keys(this.index)) {
      if (!fs.existsSync(this._fp(k))) { delete this.index[k]; pruned++; }
    }
    if (pruned) this._saveIndex();
    this.log(`store: ${Object.keys(this.index).length} média(s) en cache (${pruned} purgé[s])`);
  }

  _saveIndex() {
    try {
      const tmp = this.indexPath + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify(this.index));
      fs.renameSync(tmp, this.indexPath);
    } catch (e) { this.log(`index save failed: ${e.message}`); }
  }

  _sortQueue() {
    // Plus petite priorité d'abord = diffusion la plus proche téléchargée en premier.
    this.queue.sort((a, b) => (a.priority - b.priority));
  }

  // Met un média en file d'attente (no-op si déjà présent / en vol). priority = date de
  // diffusion (epoch s) ; isPrefetch=true → soumis aux fenêtres horaires. Un même filekey
  // déjà en file conserve la priorité la plus haute (la + petite) et perd isPrefetch si
  // une demande non-prefetch (playlist courante) arrive.
  enqueue({ cache_key, cache_checksum, mime, url, id_media, priority, isPrefetch }) {
    if (!cache_key || !url) return;
    const filekey = this.keyFor(cache_key);
    if (this.has(filekey) || this.inflight.has(filekey)) return;
    const prio = Number.isFinite(Number(priority)) ? Number(priority) : 0;
    const existing = this.queue.find((q) => q.filekey === filekey);
    if (existing) {
      if (prio < existing.priority) existing.priority = prio;
      if (!isPrefetch) existing.isPrefetch = false;
      this._sortQueue();
      return;
    }
    if (id_media != null) this.downloading.add(id_media);  // inventaire UI (Q4)
    this.queue.push({ filekey, cache_key, cache_checksum, mime, url, id_media, priority: prio, isPrefetch: !!isPrefetch });
    this._sortQueue();
    this._pump();
  }

  _pump() {
    if (this.active) return;
    // 1er job exécutable : la playlist courante (non-prefetch) toujours ; le prefetch
    // seulement dans une fenêtre autorisée.
    const idx = this.queue.findIndex((j) => !j.isPrefetch || this._downloadAllowed());
    if (idx < 0) {
      if (this.queue.length) this._scheduleRecheck();  // que du prefetch hors fenêtre → on réessaiera
      return;
    }
    // FREIN : on libère d'abord ce qui est libérable, puis on refuse de DÉMARRER si le
    // plancher n'est pas tenu. Le job reste EN FILE (jamais jeté) : il repartira dès qu'une
    // éviction, une désaffectation de contenu ou un ménage aura rendu de la place.
    this.enforceQuota();
    if (this._freeBytes() < MIN_FREE_BYTES) {
      const j = this.queue[idx];
      if (j && j.id_media != null) this.blocked.add(j.id_media);
      this._pressure = true;
      if (!this._blockedLogged) {
        this.log(`FREIN STOCKAGE: ${(this._freeBytes() / 1048576).toFixed(0)} MB libres < plancher `
          + `${(MIN_FREE_BYTES / 1048576).toFixed(0)} MB — téléchargements suspendus, le contenu déjà en cache continue de diffuser`);
        this._blockedLogged = true;
      }
      this._scheduleRecheck();
      return;
    }
    // La place est revenue : on repart d'un état propre (sinon un média resterait signalé
    // « bloqué » à vie alors qu'il vient d'être téléchargeable).
    if (this.blocked.size) this.blocked.clear();
    this._blockedLogged = false;

    const job = this.queue.splice(idx, 1)[0];
    this.active = true;
    this.inflight.add(job.filekey);
    this._activeJob = job;
    this._requeueActive = false;
    this._download(job)
      .then(() => {
        if (this.onReady) this.onReady({ filekey: job.filekey, cache_key: job.cache_key, url: this.localUrl(job.filekey) });
        this.enforceQuota();  // un nouvel octet peut avoir poussé le disque au-dessus du seuil
      })
      .catch((e) => this.log(`download ${job.filekey.slice(0, 12)} failed: ${e.message}`))
      .finally(() => {
        this.inflight.delete(job.filekey);
        if (job.id_media != null) this.downloading.delete(job.id_media);  // fini (caché) ou échec
        this.active = false;
        this._activeReq = null;
        this._activeJob = null;
        // Plafond de débit changé pendant ce download → on le remet en file pour reprendre
        // sous le nouveau throttle (no-op si entre-temps il a fini : enqueue voit has()=true).
        if (this._requeueActive) {
          this._requeueActive = false;
          this.enqueue({
            cache_key: job.cache_key, cache_checksum: job.cache_checksum, mime: job.mime,
            url: job.url, id_media: job.id_media, priority: job.priority, isPrefetch: job.isPrefetch,
          });
        }
        this._pump();
      });
  }

  _scheduleRecheck() {
    if (this._recheckTimer) return;
    this._recheckTimer = setTimeout(() => { this._recheckTimer = null; this._pump(); }, WINDOW_RECHECK_MS);
  }

  _download(job) {
    return new Promise((resolve, reject) => {
      const fp = this._fp(job.filekey);
      const tmp = fp + '.part';
      let u;
      try { u = new URL(job.url); } catch (e) { return reject(e); }
      const mod = u.protocol === 'https:' ? https : http;

      // Reprise (Q3) : si un .part existe (download interrompu par reboot/coupure/fenêtre),
      // on reprend via Range au lieu de tout retélécharger. Sur 200 (serveur ignore le
      // Range), on repart de zéro.
      let startByte = 0;
      try { startByte = fs.statSync(tmp).size; } catch {}
      const headers = startByte > 0 ? { Range: `bytes=${startByte}-` } : {};

      const _t0 = Date.now();   // mesure passive du débit (opt-in)
      const req = mod.get(job.url, { headers }, (res) => {
        const code = res.statusCode;
        if (code !== 200 && code !== 206) { res.resume(); return reject(new Error(`HTTP ${code}`)); }
        const resuming = (code === 206 && startByte > 0);
        const base = resuming ? startByte : 0;
        const expected = base + parseInt(res.headers['content-length'] || '0', 10);
        const out = fs.createWriteStream(tmp, { flags: resuming ? 'a' : 'w' });

        // Plafond de bande passante (Q3) : pipe via un Throttle qui pace la source par
        // backpressure → préserve la ligne du client. bandwidthKbps=0 → illimité.
        const bytesPerSec = this.bandwidthKbps > 0 ? this.bandwidthKbps * 125 : 0;
        if (bytesPerSec > 0) res.pipe(new _Throttle(bytesPerSec)).pipe(out);
        else res.pipe(out);

        // FREIN EN COURS D'ÉCRITURE. Indispensable : la taille du fichier n'est PAS connue
        // avant de commencer (le serveur ne l'envoie pas au player), donc le contrôle
        // d'avant-démarrage ne suffit pas — un seul média peut à lui seul remplir le disque.
        // On abandonne le .part au lieu de le garder pour reprise : le conserver
        // immobiliserait précisément l'espace qui manque.
        const guard = setInterval(() => {
          if (this._freeBytes() >= MIN_FREE_BYTES) return;
          clearInterval(guard);
          if (job.id_media != null) this.blocked.add(job.id_media);
          this._pressure = true;
          try { req.destroy(); } catch { /* déjà terminée */ }
          try { out.destroy(); } catch { /* déjà fermée */ }
          fs.unlink(tmp, () => {});
          this.log(`FREIN STOCKAGE en cours d'écriture: ${job.filekey.slice(0, 12)} abandonné, `
            + `${(this._freeBytes() / 1048576).toFixed(0)} MB libres — la machine reste utilisable`);
          reject(new Error('insufficient-space'));
        }, FREE_GUARD_MS);
        res.on('close', () => clearInterval(guard));
        out.on('close', () => clearInterval(guard));

        out.on('finish', () => out.close(() => {
          clearInterval(guard);
          let size = 0;
          try { size = fs.statSync(tmp).size; } catch {}
          // Garde anti-troncature = taille annoncée. On NE vérifie PAS le sha (checksum du
          // payload = upload, pas l'objet transcodé/rendition servi). Atomicité .part→rename.
          if (expected && size !== expected) {
            if (size > expected) { fs.unlink(tmp, () => {}); return reject(new Error(`oversized (${size}>${expected})`)); }
            return reject(new Error(`incomplete (${size}/${expected}) — .part gardé pour reprise`));
          }
          try { fs.renameSync(tmp, fp); }
          catch (e) { return reject(e); }
          this.index[job.filekey] = {
            // MIME dérivé de l'extension du cache_key SERVI (la rendition est .mp4 même
            // si le parent est .mkv/.mov) — sinon <video> peut rejeter (error code 4).
            cache_key: job.cache_key, mime: this._mimeFromKey(job.cache_key) || job.mime || 'application/octet-stream',
            size, id_media: job.id_media, last_used: Date.now(), priority: job.priority,
          };
          this._saveIndex();
          // Mesure passive du débit (opt-in) : seulement les downloads COMPLETS, NON bridés
          // (sinon on mesurerait le throttle, pas la ligne) et assez gros pour être fiables.
          if (this.measureBandwidth && !this.bandwidthKbps && !resuming && size >= MIN_MEASURE_BYTES) {
            const sec = (Date.now() - _t0) / 1000;
            if (sec > 0.05) {
              const kbps = (size * 8) / 1000 / sec;
              this.measuredKbps = this.measuredKbps ? 0.6 * this.measuredKbps + 0.4 * kbps : kbps;
            }
          }
          this.log(`stored ${job.filekey.slice(0, 12)} (${(size / 1048576).toFixed(1)} MB${resuming ? ', repris' : ''})`);
          resolve(true);
        }));
        out.on('error', (e) => reject(e));  // .part conservé → reprise au prochain essai
      });
      req.on('error', (e) => reject(e));     // .part conservé → reprise au prochain essai
      req.setTimeout(DL_TIMEOUT_MS, () => req.destroy(new Error('timeout')));
      this._activeReq = req;  // exposée pour interruption à chaud (changement de plafond)
    });
  }

  // Purge tous les octets d'un id_media (kill-switch Q5 → vraie suppression fichier).
  purgeMedia(idMedia) {
    let removed = 0;
    for (const k of Object.keys(this.index)) {
      if (this.index[k].id_media === idMedia) {
        try { fs.unlinkSync(this._fp(k)); } catch {}
        delete this.index[k];
        removed++;
      }
    }
    if (removed) this._saveIndex();
    return removed;
  }

  // ── Éviction (Q2) ────────────────────────────────────────────────────────────
  // Épingle l'ensemble SERVI à ce player (= playlist courante, via cache_key). Le
  // programmé n'est jamais évincé ; le reste (anciennes playlists) devient évinçable.
  setPinned(cacheKeys) {
    this.pinned = new Set((cacheKeys || []).map((ck) => this.keyFor(ck)));
    this.enforceQuota();  // une nouvelle playlist libère l'ancien contenu
  }

  // Look-ahead : enregistre l'ensemble du contenu programmé futur (avec priorité = date de
  // diffusion) et met en file ce qui manque (téléchargé en fond, sous fenêtres). Met aussi à
  // jour la priorité des entrées déjà en cache → ranking d'éviction correct. Le contenu en
  // cache qui n'est NI épinglé NI dans ce set devient « stale » (évincé en premier).
  setPrefetch(list) {
    const arr = Array.isArray(list) ? list : [];
    this.prefetchKeys = new Map();
    for (const it of arr) {
      if (!it || !it.cache_key) continue;
      const fk = this.keyFor(it.cache_key);
      const prio = Number.isFinite(Number(it.priority)) ? Number(it.priority) : 0;
      this.prefetchKeys.set(fk, prio);
      if (this.index[fk]) this.index[fk].priority = prio;  // re-rank une entrée déjà en cache
      this.enqueue({
        cache_key: it.cache_key, cache_checksum: it.cache_checksum,
        mime: it.mime_type, url: it.url, id_media: it.id_media,
        priority: prio, isPrefetch: true,
      });
    }
    this.enforceQuota();
  }

  // Octets réellement libres sur le disque. Infinity si statfs indisponible → AUCUN frein :
  // une mesure qu'on ne sait pas faire ne doit jamais bloquer la diffusion (même règle que
  // `_diskUsedRatio` qui rend 0 pour désactiver l'éviction).
  _freeBytes() {
    try {
      const s = fs.statfsSync(this.dir);
      return s.bavail * s.bsize;
    } catch { return Infinity; }
  }

  // Capacité totale du disque, en octets. null si indisponible (le serveur s'abstiendra
  // alors de tout contrôle d'affectation plutôt que de le faire sur une valeur inventée).
  _diskTotalBytes() {
    try {
      const s = fs.statfsSync(this.dir);
      const t = s.blocks * s.bsize;
      return t > 0 ? t : null;
    } catch { return null; }
  }

  // Fraction du disque ENTIER utilisée (0..1). 0 si statfs indisponible (→ pas d'éviction).
  _diskUsedRatio() {
    try {
      const s = fs.statfsSync(this.dir);
      if (!s || !s.blocks) return 0;
      return 1 - (s.bavail / s.blocks);
    } catch { return 0; }
  }

  // Évince le NON-épinglé tant que le disque dépasse HIGH, jusqu'à repasser sous LOW.
  // Ordre d'éviction : (1) le « stale » (ni épinglé ni programmé) en premier, le plus
  // ancien d'abord ; (2) puis le programmé (prefetch) le plus LOINTAIN d'abord (priorité
  // la + haute = date la + tardive). Le programmé proche et la playlist courante (épinglée)
  // sont les derniers servis. Si l'épinglé seul ne tient pas → pression (alerte serveur).
  enforceQuota() {
    if (this._diskUsedRatio() < HIGH_WATERMARK) { this._pressure = false; return; }
    const evictable = Object.entries(this.index).filter(([k]) => !this.pinned.has(k));
    evictable.sort((a, b) => {
      const wa = this.prefetchKeys.has(a[0]), wb = this.prefetchKeys.has(b[0]);
      if (wa !== wb) return wa ? 1 : -1;                       // stale (non voulu) évincé d'abord
      if (!wa) return (a[1].last_used || 0) - (b[1].last_used || 0);  // stale : LRU (vieux d'abord)
      return this.prefetchKeys.get(b[0]) - this.prefetchKeys.get(a[0]);  // voulu : lointain d'abord
    });
    let freed = 0;
    for (const [k, e] of evictable) {
      if (this._diskUsedRatio() < LOW_WATERMARK) break;
      const cat = this.prefetchKeys.has(k) ? 'far-future' : 'stale';
      try { fs.unlinkSync(this._fp(k)); } catch {}
      delete this.index[k];
      freed += e.size || 0;
      this.log(`evicted ${k.slice(0, 12)} (${((e.size || 0) / 1048576).toFixed(1)} MB, ${cat})`);
    }
    if (freed) this._saveIndex();
    this._pressure = this._diskUsedRatio() >= HIGH_WATERMARK;
    if (this._pressure) {
      this.log(`STORAGE PRESSURE: disque ${(this._diskUsedRatio() * 100).toFixed(0)}% après éviction du non-épinglé — l'ensemble épinglé (playlist assignée) ne tient pas`);
    } else if (freed) {
      this.log(`éviction: ${(freed / 1048576).toFixed(0)} MB libérés, disque ${(this._diskUsedRatio() * 100).toFixed(0)}%`);
    }
  }

  // État de stockage pour le heartbeat (alerte serveur Q4 + inventaire par player).
  getStorageStatus() {
    // id_media distincts réellement en cache (un parent peut avoir plusieurs cache_keys).
    const cachedIds = new Set();
    for (const e of Object.values(this.index)) if (e.id_media != null) cachedIds.add(e.id_media);
    const out = {
      disk_used_ratio: Math.round(this._diskUsedRatio() * 100) / 100,
      storage_pressure: !!this._pressure,
      cached_count: cachedIds.size,
      cached_ids: [...cachedIds],
      downloading_ids: [...this.downloading],
      // Médias auxquels on a RENONCÉ faute de place, et octets libres réels. Sans ces deux
      // champs, le frein serait muet côté serveur : l'écran diffuserait une partie de sa
      // playlist sans que personne ne sache pourquoi.
      blocked_ids: [...this.blocked],
      free_bytes: this._freeBytes() === Infinity ? null : this._freeBytes(),
      // Capacité ABSOLUE (point 4) : le ratio seul ne permet pas au serveur de dire
      // « ces 6 vidéos font 1,85 Go, cet écran n'a que 1,2 Go libres ».
      disk_total_bytes: this._diskTotalBytes(),
    };
    // Débit mesuré (opt-in) → nourrit l'ETA de readiness côté serveur (repli du plafond manuel).
    if (this.measureBandwidth && this.measuredKbps > 0) out.throughput_kbps = Math.round(this.measuredKbps);
    return out;
  }
}

module.exports = { ContentStore };
