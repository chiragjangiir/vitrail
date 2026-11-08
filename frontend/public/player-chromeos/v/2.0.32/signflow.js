'use strict';

// ── Bridge PWA SignFlow (ChromeOS) ───────────────────────────────────────────
//
// Remplace la coque native Electron (`preload.js` + `main.js`). Expose le MÊME contrat
// `window.signflow` que le preload Electron, mais la source d'événements est un
// WebSocket NAVIGATEUR (`new WebSocket(...)`) au lieu de l'IPC Electron, et la
// persistance se fait en localStorage au lieu de `config.json`.
//
// Le renderer (`player.js` + `audio_player.js`) est réutilisé VERBATIM : il n'expose pas
// `window.signflow.mpv`, donc `_hasMpv` y vaut false → la vidéo passe par le `<video>`
// Chromium (ChromeOS décode en HW nativement, pas de flag à poser).
//
// Limites Phase A (assumées, cf. docs/PLAN_PORTAGE_CHROMEOS.md) :
//  - LAN sync UDP impossible en sandbox PWA → onLanAdjust/onLanSwitch/onLanRelease
//    jamais déclenchés, reportPlaybackPos no-op (players non frame-locked).
//  - Offline cache (Service Worker / Cache API) = Phase B → onStoreUpdate jamais déclenché.
//  - Store Control Panel = Phase C (médié par le backend) → onControlApply jamais déclenché.

(function () {
  const PLAYER_VERSION = (typeof window !== 'undefined' && window.__SF_PLAYER_VERSION__) || '1.0.0-chromeos';
  const LS_BACKEND = 'signflow_backend_url';
  const LS_TOKEN   = 'signflow_player_token';

  // Famille de player web : 'chromeos' (PWA), 'chrome_extension' (extension) ou 'brightsign'
  // (roHtmlWidget Chromium). Posée par la page via window.__SF_PLAYER_OS__ avant ce script.
  // Tout le code spécifique BrightSign ci-dessous est INERTE si SF_OS !== 'brightsign'.
  const SF_OS = (typeof window !== 'undefined' && window.__SF_PLAYER_OS__) || 'chromeos';
  const IS_BS = SF_OS === 'brightsign';

  // Version rapportée au serveur = constante de CE fichier (signflow.js) pour les renderers dont le
  // CODE est servi par prod → la version reflète le code réellement en place, cible de la détection de
  // succès OTA §XXX (le serveur constate la montée de version après un apply).
  //  - BrightSign : signflow.js tiré par RefreshRenderer à chaque apply/boot (bootstrap.html jamais
  //    rafraîchi → __SF_PLAYER_VERSION__ stagnerait → on n'en dépend pas).
  //  - ChromeOS PWA : signflow.js servi par prod, re-tiré à chaque `location.reload()` (SW network-first)
  //    → un OTA = reload = code frais de prod = version à jour.
  //  - Extension Chrome : signflow.js est BUNDLÉ (MV3 interdit le code distant) → la version reflète le
  //    bundle (mise à jour via le Web Store / rechargement de l'extension, pas via un reload). On garde
  //    donc __SF_PLAYER_VERSION__ (posé par ext_bootstrap) comme source pour l'extension.
  // ⚠️ ≤20 car. (cms_players.player_version varchar(20)) + SemVer M.m.p (semver_key backend).
  const BS_PLAYER_VERSION = '2.0.32';  // 2.0.32 = basculer `campaign_placement` (plein ecran <-> zone) ne changeait PAS l'empreinte multi-zones (meme media, meme duree, meme URL, et un spot n'a pas d'id_item) -> le payload etait jete en « same content already playing » et le changement n'atteignait JAMAIS l'ecran ; le marquage campagne entre desormais dans l'empreinte ; 2.0.31 = fin de VOD : `v.onended = hideVodOverlay` passait l'objet Event dans le parametre `replacing` (toujours vrai) -> la programmation ne repartait JAMAIS et onSync avalait tous les syncs en silence : ecran NOIR fige jusqu'au redemarrage manuel (XT1144, 06/08) ; + liberation des zones pendant un takeover sur BS (elles gardaient la route audio EXCLUSIVE `pcmaudio` -> VOD MUETTE en multi-zones) ; + filet anti-gel dans onSync ; 2.0.30 = spots de campagne sur ecran multi-zones (P3.6) : plein ecran ou zone principale, selon le template ;  // 2.0.29 = frein de stockage : plancher absolu d'espace libre (un disque plein cassait l'OS de l'appareil, 2026-08-06) ; 2.0.28 = zip de contenu identique a 2.0.27 (validation du canal d'import, 28/07) ;  // 2.0.27 = cle de synchro LAN pour les programmes GOUVERNES (SS XVIII) : le payload gouverne n'a ni id_playlist ni id_event, le leader n'emettait donc AUCUN sync_play (ecrans gouvernes desynchronises) ; le serveur fournit desormais sync_key ; 2.0.26 = precache video DESACTIVE sur BrightSign (le 2e <video> du double-buffer engageait le 2e decodeur HW du XT4 pour decoder la prochaine video PENDANT la lecture -> gel deterministe de la video en cours sur XT1144 ; fichier deja sur SD -> preload inutile sur BS) ; 2.0.25 = handleWebOta IGNORE les deploiements track=firmware (le renderer ne doit pas les faux-echouer : sa version 2.0.x n'atteint jamais la version BOS 9.1.x ; succes firmware = serveur via bs_bos) ; 2.0.24 = VOD sonore cede le passage aux overlays (jingle/spot/message/alerte) ; 2.0.23 =  // 2.0.23 = relais main->renderer transmettait pas with_sound/has_audio (case son sans effet) ; 2.0.22 =  // 2.0.22 = takeover VOD : son au declenchement (with_sound) + ducking conditionne (has_audio) + PoP §XXIV ; 2.0.21 = VOD LAN rafale multi-cibles (autorun v51 packets[], rétro-compat v50) ; 2.0.20 = takeover VOD libère le plan vidéo (HD/LS = plan HW unique) ; 2.0.19 = VOD LAN :7779 (v50)
  const CHROMEOS_PLAYER_VERSION = '2.0.13';  // 2.0.13 = basculer `campaign_placement` (plein ecran <-> zone) ne changeait PAS l'empreinte multi-zones (meme media, meme duree, meme URL, et un spot n'a pas d'id_item) -> le payload etait jete en « same content already playing » et le changement n'atteignait JAMAIS l'ecran ; le marquage campagne entre desormais dans l'empreinte ; 2.0.12 = fin de VOD : `v.onended = hideVodOverlay` passait l'objet Event dans le parametre `replacing` (toujours vrai) -> la programmation ne repartait JAMAIS et onSync avalait tous les syncs en silence : ecran NOIR fige jusqu'au redemarrage manuel (XT1144, 06/08) ; + liberation des zones pendant un takeover sur BS (elles gardaient la route audio EXCLUSIVE `pcmaudio` -> VOD MUETTE en multi-zones) ; + filet anti-gel dans onSync ; 2.0.11 = spots de campagne sur ecran multi-zones (P3.6) : plein ecran ou zone principale, selon le template ;  // 2.0.10 = frein de stockage : plancher absolu d'espace libre (un disque plein cassait l'OS de l'appareil, 2026-08-06) ; 2.0.9 = zip de contenu identique a 2.0.8 (validation du canal d'import, 28/07) ;  // 2.0.8 = cle de synchro LAN pour les programmes GOUVERNES (SS XVIII) : le payload gouverne n'a ni id_playlist ni id_event, le leader n'emettait donc AUCUN sync_play (ecrans gouvernes desynchronises) ; le serveur fournit desormais sync_key ; 2.0.7 = VOD sonore cede le passage aux overlays (jingle/spot/message/alerte) ; 2.0.6 =  // 2.0.6 = relais main->renderer transmettait pas with_sound/has_audio (case son sans effet) ; 2.0.5 =  // 2.0.5 = takeover VOD : son au declenchement (with_sound) + ducking conditionne (has_audio) + PoP §XXIV ; 2.0.4 = PoP audio §XXIV (paniers : musique/ambiance/overlays)
  const REPORTED_VERSION = IS_BS ? BS_PLAYER_VERSION
    : SF_OS === 'chromeos' ? CHROMEOS_PLAYER_VERSION
    : PLAYER_VERSION;   // chrome_extension → __SF_PLAYER_VERSION__ (bundlé), autres → défaut

  // ── BrightSign : objets JavaScript natifs (require('@brightsign/...')) ─────────────
  // Disponibles UNIQUEMENT si autorun.brs a posé brightsign_js_objects_enabled=true +
  // allowJavaScriptUrls. Tout est best-effort/try-catch : sans ces objets, le player reste
  // un player navigateur standard (streaming-only, reboot=reload). cf. player-brightsign/.
  let _bsInfo = {};
  // Canal de commande loopback : POSTe au roHttpServer de l'autorun (même mécanique prouvée que
  // /queue) → l'autorun exécute la commande en BrightScript NATIF. Remplace les objets Node
  // require('@brightsign/*') (désactivés sur ce firmware → ne marchaient pas). Fire-and-forget.
  function bsCmd(cmd, extra) {
    if (!IS_BS) return false;
    try {
      // POSTe sur /queue (seul endpoint POST fiable du firmware) ; l'autorun discrimine par le corps.
      fetch(`${LOCAL_BASE}/queue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign({ cmd }, extra || {})),
      }).catch(() => {});
      return true;
    } catch (e) { return false; }
  }
  function bsReboot() {
    // Vrai reboot OS via l'autorun (RebootSystem). Le pont @brightsign/* Node est mort sur ce BOS.
    return bsCmd('reboot');
  }
  function bsRefreshInfo() {
    if (!IS_BS) return;
    try {
      const DI = require('@brightsign/deviceinfo');
      const di = new DI();
      const info = { platform: 'brightsign' };
      try { info.bs_model   = di.model; } catch (e) {}
      try { info.bs_serial  = di.serialnumber; } catch (e) {}
      try { info.osversion  = di.osversion; } catch (e) {}
      try { info.bs_family  = di.family; } catch (e) {}
      Object.assign(_bsInfo, info);
      if (typeof di.gettemperature === 'function') {
        di.gettemperature().then((t) => { if (t && t.celsius != null) _bsInfo.temperature_c = t.celsius; }).catch(() => {});
      }
      if (typeof di.getloadstatistics === 'function') {
        di.getloadstatistics('loadavg').then((l) => { _bsInfo.loadavg = l; }).catch(() => {});
        di.getloadstatistics('meminfo').then((m) => { _bsInfo.meminfo = m; }).catch(() => {});
      }
    } catch (e) { /* objets JS BrightSign non activés → reste un player navigateur standard */ }
  }

  // ── Provisioning : URL kiosk (?backend=&token=) > localStorage > écran de setup ──
  // En kiosk managé (Google Admin), aucune saisie clavier n'est possible → on lit le
  // backend + token depuis les query params de l'URL du kiosk. On les persiste pour
  // survivre à un reload, et on nettoie l'URL (ne pas laisser le token visible/loggué).
  function readProvisioning() {
    const qs = new URLSearchParams(location.search);
    let backend = qs.get('backend') || qs.get('backend_url') || '';
    let token   = qs.get('token')   || qs.get('player_token') || '';
    // Appliance x86 Alpine : &agent=<port> = agent local (httpd loopback) qui exécute reboot/poweroff
    // (impossibles depuis le navigateur). Persisté (survit au reload qui purge l'URL). Absent ailleurs.
    const agent = qs.get('agent') || '';
    if (agent) { try { localStorage.setItem('sf_kiosk_agent', agent); } catch {} }
    if (backend) localStorage.setItem(LS_BACKEND, backend.replace(/\/+$/, ''));
    if (token) {
      // Un token de provisioning (sfp_…) ne sert qu'au PREMIER enrôlement. S'il existe
      // déjà un JWT player enregistré en localStorage, on IGNORE le sfp_ de l'URL —
      // sinon chaque ouverture de l'URL kiosk (page de démarrage, reload) ré-enregistre
      // un NOUVEAU player (POST /players/register) = doublons dans l'UI. Un vrai JWT
      // dans l'URL (cas rare) écrase toujours, lui.
      const existing = localStorage.getItem(LS_TOKEN) || '';
      const isProvisioning = token.startsWith('sfp_');
      const haveJwt = existing && !existing.startsWith('sfp_');
      if (!(isProvisioning && haveJwt)) localStorage.setItem(LS_TOKEN, token);
    }
    if (backend || token) {
      // Purge les secrets de l'URL (history) sans recharger la page.
      try { history.replaceState(null, '', location.pathname); } catch {}
    }
    return {
      backend_url:  localStorage.getItem(LS_BACKEND) || '',
      player_token: localStorage.getItem(LS_TOKEN) || '',
    };
  }

  let config = readProvisioning();

  // ── Agent local de commandes natives (appliance x86 Alpine, installeur greenfield) ──
  // Le player PWA ne peut pas rebooter l'OS depuis le navigateur. L'install x86 pose un petit httpd
  // loopback (127.0.0.1:8890, cf. sf-install.sh) qui exécute reboot/poweroff en natif ; le renderer
  // y POSTe. INERTE partout ailleurs (ChromeOS managé, extension, BrightSign) : sans &agent=, pas d'appel.
  const KIOSK_AGENT_PORT = (function () { try { return localStorage.getItem('sf_kiosk_agent') || ''; } catch { return ''; } })();
  function kioskCmd(action) {
    if (!KIOSK_AGENT_PORT) return false;
    try {
      fetch(`http://127.0.0.1:${KIOSK_AGENT_PORT}/cgi-bin/${action}`, { mode: 'no-cors', cache: 'no-store' });
      return true;   // fire-and-forget (l'OS reboote → la réponse importe peu)
    } catch (e) { return false; }
  }

  // ── Bus d'événements (mime le `ipcRenderer.on` du preload) ────────────────────
  const handlers = {};
  function on(ev, cb) { (handlers[ev] || (handlers[ev] = [])).push(cb); }
  function emit(ev, payload) { (handlers[ev] || []).forEach((cb) => { try { cb(payload); } catch (e) { console.error(`[bridge] ${ev}:`, e); } }); }

  // ── Offline content store (Phase B §3.9) — Cache API + IndexedDB meta ─────────
  //
  // Download-then-play (miroir du content_store.js Electron) : à chaque player:sync, les
  // médias déjà en cache voient leur url réécrite vers un chemin synthétique same-origin
  // `…/__sf_media__/<cache_key>` (servi par le Service Worker, Range OK) ; les manquants
  // sont téléchargés en fond (CORS MinIO) puis signalés via store-update → player.js patche
  // en place. Repli gracieux : tant que non caché (ou si le fetch CORS échoue), l'url MinIO
  // d'origine est conservée → streaming online inchangé. Clé = cache_key (objet immuable,
  // stable au re-signage d'URL). Éviction LRU par budget (les clés du sync courant = pinned).
  const MEDIA_CACHE = 'signflow-media-v1';   // DOIT rester aligné avec sw.js
  const SCOPE = location.pathname.replace(/[^/]*$/, '');   // ex. /player-chromeos/
  const STORE_BUDGET_BYTES = 8 * 1024 * 1024 * 1024;       // 8 Go (cap soft ; le quota navigateur prime)

  let _swActive = false;             // le SW contrôle la page → les urls locales sont servies
  const _cachedKeys = new Set();     // cache_key présents en cache (chargé au boot + maj live)
  const _keyToMedia = new Map();     // cache_key → id_media (inventaire/sync-readiness serveur)
  let _diskRatio = null;             // occupation du stockage navigateur (navigator.storage.estimate)
  // Pression de stockage RÉELLE (2026-08-06). Ce drapeau valait `false` EN DUR, avec le
  // commentaire « l'éviction LRU par budget gère la pression silencieusement » : c'était vrai
  // pour l'éviction, faux pour l'alerte. Conséquence mesurée : ces surfaces ne pouvaient
  // STRUCTURELLEMENT jamais signaler de pression, donc une alerte serveur branchée dessus
  // serait restée muette à vie sur ChromeOS, l'extension et les BrightSign — une garde inerte,
  // pire que pas de garde puisqu'on se croit couvert.
  let _storagePressure = false;
  const _blockedMedia = new Set();   // id_media renoncés faute de place (remontés au serveur)
  let _diskQuotaBytes = null;        // capacité absolue (point 4 : contrôle à l'affectation)
  let _diskUsageBytes = null;
  let _pinnedKeys = new Set();       // cache_key du sync courant (jamais évincés)
  const _queued = new Set();         // cache_key en file/cours de DL (dédup)
  const _dlQueue = [];
  let _draining = false;
  // Barrière download-then-play (§3.9) : ne pas basculer sur un nouveau contenu tant qu'il n'est
  // pas ENTIÈREMENT caché — sinon on jouerait du média partiel (erreurs/crash observés sur ChromeOS).
  let _pendingHold = null;           // sync retenu en attente de cache complet (null = rien retenu)
  let _allowStreaming = false;       // display_config.allow_streaming : OFF = download-then-play strict (défaut)
  let _bandwidthKbps = 0;            // display_config.download_bandwidth_kbps : plafond de débit DL (0 = illimité)
  let _measureBandwidth = false;     // display_config.measure_bandwidth : mesure passive du débit DL (opt-in)

  // ── LAN sync (BrightSign, Phase 2 slave-only) ────────────────────────────────
  // Le renderer web (roHtmlWidget) n'a PAS d'UDP -> l'autorun BrightScript recoit le broadcast du
  // groupe sur :7778 et EXPOSE le dernier sync_play BRUT du leader (NUC) en /lan.json. Ici on le POLL
  // et on alimente les callbacks LAN DEJA presents dans player.js (onLanSwitch/onLanAdjust). Slave-only :
  // le BrightSign ne devient jamais leader (pas de broadcast). Gate = display_config.lan_sync_enabled
  // (toggle serveur = kill-switch). Repli auto sur le sync serveur si le leader se tait (fraicheur).
  let _bsLanEnabled = false;         // display_config.lan_sync_enabled (ce player est dans un groupe LAN)
  let _bsLanGroup   = '';            // display_config.lan_sync_group (filtre : on ne suit que ce groupe)
  let _bsLanMaster  = false;         // display_config.lan_sync_master (Phase 2b : ce player DIFFUSE le sync_play)
  let _bsLanTimer   = null;          // poller /lan.json (demarre au 1er sync, idempotent)
  let _bsLanLastSwitchAt = 0;        // dedup : ne re-planifie pas la meme bascule chaque tick
  const BS_LAN_FRESH_MS = 8000;      // au-dela, sync_play du leader perime (leader mort/reseau) -> repli serveur
  let _measuredKbps = 0;             // EWMA du débit DL mesuré (kbit/s) → throughput_kbps au heartbeat (sync-readiness ETA serveur)
  let _deliveredKeys = new Set();    // cache_key du contenu ACTUELLEMENT joué (protégé de l'éviction)

  function localMediaUrl(key) { return `${SCOPE}__sf_media__/${encodeURIComponent(key)}`; }

  // ── BrightSign : cache local NATIF via le serveur HTTP loopback de l'autorun ──────────────
  // Le SW ne rend PAS la vidéo sur roHtmlWidget (écran noir, prouvé). À la place, l'autorun.brs
  // fait tourner un roHttpServer (LOCAL_BASE) qui sert les médias téléchargés sur la SD. Le
  // renderer POSTe la liste {cache_key,url} à /queue (BrightScript télécharge via roUrlTransfer),
  // poll /cached.json pour savoir lesquels sont dispos, et réécrit les urls vers
  // LOCAL_BASE/media/<cache_key> (source HTTP locale, que le <video> lit — contrairement au SW).
  // Repli URL MinIO tant que non téléchargé. cf. player-brightsign/NATIVE_CACHE_PLAN.md.
  const LOCAL_BASE = (typeof window !== 'undefined' && window.__SF_LOCAL_CACHE_BASE__) || 'http://127.0.0.1:8888';
  const _bsLocalKeys = new Set();    // cache_keys dispos en local (rafraîchi par /cached.json)
  const _bsQueued = new Map();       // cache_key → url, accumulés pour le prochain POST /queue
  let _bsQueueTimer = null;
  let _bsPrefetchKeys = new Set();   // P2.7 : cache_keys de la liste prefetch courante (protégées de l'éviction)
  let _bsPrefetchTimer = null;
  let _bsPrefetchBody = null;        // { prefetch:[{cache_key,url}], windows:[{start,end}] } à POSTer
  function bsLocalUrl(key) { return `${LOCAL_BASE}/media/${key}`; }   // key = path (ex 1/x.mp4) — OK en URL
  function bsQueue(key, url) {
    if (!IS_BS || !key || !url) return;
    if (_bsLocalKeys.has(key) || _bsQueued.has(key)) return;   // déjà local ou déjà en file
    _bsQueued.set(key, url);
    if (!_bsQueueTimer) _bsQueueTimer = setTimeout(bsFlushQueue, 500);   // debounce : 1 POST / salve de sync
  }
  async function bsFlushQueue() {
    _bsQueueTimer = null;
    if (!_bsQueued.size) return;
    const items = [..._bsQueued.entries()].map(([cache_key, url]) => ({ cache_key, url }));
    _bsQueued.clear();
    try {
      await fetch(`${LOCAL_BASE}/queue`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      });
    } catch (e) { console.warn('[bs-cache] POST /queue échec:', e.message); }
  }
  // Prefetch look-ahead (P2.7) : le backend envoie une liste `prefetch` (contenu FUTUR programmé, trié
  // par date de diffusion). On la POSTe à l'autorun comme file BASSE priorité (drainée après les items
  // courants) + les fenêtres horaires (P2.8 `download_windows`). Les clés prefetch sont mémorisées
  // (_bsPrefetchKeys) pour être ajoutées au keep-set → sinon le contenu préchargé serait évincé
  // immédiatement (il n'est pas dans _pinnedKeys). Debounce pour 1 POST par salve de sync.
  function bsPrefetch(list, windows) {
    if (!IS_BS) return;
    _bsPrefetchKeys = new Set();
    const items = [];
    for (const e of (list || [])) {
      if (!e || !e.cache_key || !e.url) continue;
      _bsPrefetchKeys.add(e.cache_key);              // protège de l'éviction même si déjà téléchargé
      if (_bsLocalKeys.has(e.cache_key)) continue;   // déjà sur SD → rien à télécharger
      items.push({ cache_key: e.cache_key, url: e.url, priority: Number(e.priority) || 0 });
    }
    items.sort((a, b) => a.priority - b.priority);   // date de diffusion la plus proche d'abord
    _bsPrefetchBody = {
      prefetch: items.map(({ cache_key, url }) => ({ cache_key, url })),
      windows: Array.isArray(windows) ? windows : [],
    };
    if (!_bsPrefetchTimer) _bsPrefetchTimer = setTimeout(bsFlushPrefetch, 900);
  }
  async function bsFlushPrefetch() {
    _bsPrefetchTimer = null;
    if (!_bsPrefetchBody) return;
    const body = _bsPrefetchBody;
    _bsPrefetchBody = null;
    try {
      await fetch(`${LOCAL_BASE}/queue`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (e) { console.warn('[bs-cache] POST prefetch échec:', e.message); }
  }
  // Éviction du cache SD (Tier 1.1) : après chaque sync on POSTe l'ensemble des cache_keys ENCORE
  // nécessaires (pinned du sync courant + contenu en cours de lecture protégé) à l'autorun, qui
  // supprime les sfc_* absents de cette liste. Sans ça les médias déréférencés s'accumulent sur la
  // SD indéfiniment (les autres players ont une éviction LRU, désactivée en IS_BS). Debounce pour
  // ne lancer qu'un POST par salve de sync ; jamais de keep VIDE (l'autorun n'évince pas alors →
  // garde-fou anti-purge-totale pendant un idle/transition).
  let _bsKeepTimer = null;
  function bsSendKeep() {
    if (!IS_BS) return;
    if (!_bsKeepTimer) _bsKeepTimer = setTimeout(bsFlushKeep, 1500);
  }
  async function bsFlushKeep() {
    _bsKeepTimer = null;
    const keep = new Set(_pinnedKeys);
    for (const k of _deliveredKeys) keep.add(k);   // protège le contenu joué pendant une transition
    for (const k of _bsPrefetchKeys) keep.add(k);  // P2.7 : protège le contenu PRÉCHARGÉ de l'éviction
    if (keep.size === 0) return;                    // sync vide → ne pas demander de purge totale
    try {
      await fetch(`${LOCAL_BASE}/queue`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keep: [...keep] }),
      });
    } catch (e) { console.warn('[bs-cache] POST /keep échec:', e.message); }
  }
  // Kill-switch (Tier 1.3) : purge ciblée des sfc_* d'un média retiré (commande player:purge_media).
  function bsPurge(keys) {
    if (!IS_BS || !keys || !keys.length) return;
    fetch(`${LOCAL_BASE}/queue`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ purge: keys }),
    }).catch((e) => console.warn('[bs-cache] POST /purge échec:', e.message));
  }
  async function bsPollCached() {
    try {
      const r = await fetch(`${LOCAL_BASE}/cached.json`, { cache: 'no-store' });
      if (!r.ok) return;
      const data = await r.json();
      const keys = Array.isArray(data) ? data : (data.keys || data.cached || []);
      const before = _bsLocalKeys.size;
      _bsLocalKeys.clear();
      for (const k of keys) _bsLocalKeys.add(k);
      // De nouveaux médias sont devenus dispos en local → libère un éventuel hold download-then-play.
      if (_bsLocalKeys.size !== before) maybeReleaseHold();
    } catch (e) { /* serveur local pas prêt → repli MinIO (streaming) */ }
  }
  // LAN sync (Phase 2, BrightSign slave-only) : poll du sync_play du leader expose par l'autorun.
  async function bsPollLanSync() {
    if (!IS_BS || !_bsLanEnabled) return;
    try {
      const r = await fetch(`${LOCAL_BASE}/lan.json`, { cache: 'no-store' });
      if (!r.ok) return;
      const m = await r.json();
      // L'autorun n'ecrit que le sync_play BRUT du leader ; sinon placeholder {probe:"waiting"} -> ignore.
      if (!m || m.type !== 'sync_play') return;
      if (_bsLanGroup && m.group !== _bsLanGroup) return;          // autre groupe LAN -> ignore
      const sentAt = Number(m.sent_at) || 0;
      const age = Date.now() - sentAt;                             // horloges NTP alignees (~5ms mesure HW)
      if (!sentAt || age < -2000 || age > BS_LAN_FRESH_MS) return; // perime / horloge aberrante -> repli serveur
      // Bascule d'item = switch_at ABSOLU (latence-immune : le pont HTTP ne compte pas). player.js
      // (onLanSwitch) recale son timer d'avance sur cet instant. Dedup sur la valeur de switch_at.
      if (typeof m.switch_at === 'number' && m.switch_at !== _bsLanLastSwitchAt) {
        _bsLanLastSwitchAt = m.switch_at;
        emit('lan-switch', { start_index: m.start_index, switch_at: m.switch_at, next_index: m.next_index });
      }
      // Offset fin : extrapole la position LIVE du leader (position a sent_at + age ecoule) -> cible la
      // position courante du NUC malgre l'age du dernier broadcast (~2s). player.js (onLanAdjust) compare
      // a SA propre position video et nudge/seek (dead-zone/cooldown/wrap geres la-bas).
      const liveOffset = (Number(m.start_offset_ms) || 0) + Math.max(0, age);
      emit('lan-adjust', { id_playlist: m.id_playlist, start_index: m.start_index, start_offset_ms: liveOffset });
    } catch (e) { /* serveur local pas pret -> repli sync serveur */ }
  }
  function startBsLanSync() {
    if (!IS_BS || _bsLanTimer) return;   // idempotent : demarre une fois, lit _bsLanEnabled a chaque tick
    _bsLanTimer = setInterval(bsPollLanSync, 1000);
  }
  // Infos device natives (modèle/famille/BOS/IP/MAC) servies par l'autorun en /device.json
  // (le JS @brightsign/* est désactivé → BrightScript natif). model/family/bos → capabilities
  // (via _bsInfo) ; ip/mac → heartbeat top-level (le serveur lit ip_address/mac_address) → le
  // drawer affiche la VRAIE IP LAN (et non la gateway) + le modèle (→ capacité 4K).
  let _bsDevice = {};
  async function bsFetchDevice() {
    if (!IS_BS) return;
    try {
      const r = await fetch(`${LOCAL_BASE}/device.json`, { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      if (d.model)  _bsInfo.bs_model  = d.model;
      if (d.family) _bsInfo.bs_family = d.family;
      if (d.bos)    _bsInfo.bs_bos    = d.bos;
      if (d.serial) _bsInfo.bs_serial = d.serial;   // P1.3 : série natif (drawer device enrichi)
      if (d.autorun_ver) _bsInfo.bs_autorun_ver = d.autorun_ver;   // P1.2 : version autorun (auto-update observable)
      if (typeof d.disk_ratio === 'number') _diskRatio = Math.round(d.disk_ratio * 100) / 100;   // P2.1 : occupation SD (autorun roStorageInfo)
      if (d.ip)     _bsDevice.ip  = d.ip;
      if (d.mac)    _bsDevice.mac = d.mac;
      // Modes vidéo natifs : video_mode = sortie COURANTE (→ rendition servie), best_mode = max
      // écran EDID (informatif). Format BrightSign "3840x2160x60p" (cf. getDisplayInfo/bsModeToWxH).
      if (d.video_mode) { _bsDevice.video_mode = d.video_mode; _bsInfo.bs_video_mode = d.video_mode; }
      if (d.best_mode)  { _bsDevice.best_mode  = d.best_mode;  _bsInfo.bs_best_mode  = d.best_mode; }
      // Sortie audio courante (sidecar, exposée par l'autorun v16) → bsApplyAudioOutput compare à l'état
      // RÉEL pour son anti-boucle. SANS cette copie, _bsDevice.audio_out reste undefined → le garde
      // `if (!cur) return` bloquait TOUT changement de sortie depuis le drawer.
      if (d.audio_out) _bsDevice.audio_out = d.audio_out;
      // Rotation écran courante (sidecar, exposée par l'autorun v35) → bsApplyRotation compare à l'état
      // RÉEL (anti-boucle). MÊME piège que audio_out : sans cette copie, _bsDevice.rotation reste undefined
      // → le garde `if (!cur) return` bloquait TOUT changement de rotation (symptôme : toujours paysage).
      if (d.rotation) _bsDevice.rotation = d.rotation;
    } catch (e) { /* serveur local pas prêt */ }
  }
  // v49/2.0.18 : charge CPU + RAM réelles depuis /mem.json (écrit toutes les 60 s par le MemCheck
  // de l'autorun via le LDWS — meminfo + loadavg). ≠ /device.json qui est un snapshot de boot.
  // ram = % UTILISÉ (1 - avail_ratio) ; cpu = load1/ncpu en % (cap 100 côté autorun). Champs absents
  // (vieil autorun, LDWS off) → on n'envoie simplement rien (le CMS garde NULL, comme avant).
  let _bsStats = {};
  async function bsFetchStats() {
    if (!IS_BS) return;
    try {
      const r = await fetch(`${LOCAL_BASE}/mem.json`, { cache: 'no-store' });
      if (!r.ok) return;
      const s = await r.json();
      if (s && s.measured === true && typeof s.avail_ratio === 'number' && s.avail_ratio >= 0) {
        _bsStats.ram = Math.round((1 - s.avail_ratio) * 100);
      }
      if (s && typeof s.cpu_ratio === 'number' && s.cpu_ratio >= 0) {
        _bsStats.cpu = Math.round(s.cpu_ratio * 100);
      }
    } catch (e) { /* serveur local pas prêt */ }
  }
  // Toggle 4K par-player (P2.4/P3.1) : display_config.bs_video_mode ∈ {"best","fhd","WxHxR",absent}.
  // On résout la cible (best → best_mode EDID = 4K/8K selon le panneau ; fhd → 1080) et on demande à
  // l'autorun de changer le mode SEULEMENT si elle diffère de la sortie courante (_bsDevice.video_mode)
  // → pas de boucle de reboot. L'autorun écrit le sidecar + reboote (SetMode au prochain boot, le
  // mot-clé "best"/"fhd" y est re-résolu). Garde : on attend que /device.json soit lu (video_mode +
  // best_mode connus) et on dé-doublonne la demande (_bsVideoModeReq). Absent/null = pas d'avis.
  let _bsVideoModeReq = null;
  function bsApplyVideoMode(desired) {
    if (!IS_BS) return;
    const cur = _bsDevice.video_mode || '';
    const best = _bsDevice.best_mode || '';
    if (!cur) return;                                  // /device.json pas encore lu → on réessaiera au prochain sync
    let target = '';
    if (desired === 'best') target = best;
    else if (desired === 'fhd') target = '1920x1080x60p';
    else if (typeof desired === 'string' && /^\d+x\d+x\d+/.test(desired)) target = desired;
    else { _bsVideoModeReq = null; return; }           // absent/null → pas d'avis, on ne touche à rien
    if (!target || target === cur) { _bsVideoModeReq = null; return; }   // déjà au bon mode (anti-boucle)
    if (_bsVideoModeReq === desired) return;            // changement déjà demandé → pas de spam de reboot
    _bsVideoModeReq = desired;
    console.log('[BS] bs_video_mode', desired, '→', target, '(courant', cur + ') → set_video_mode + reboot');
    bsCmd('set_video_mode', { mode: desired });        // l'autorun résout "best"/"fhd" et reboote
  }
  // ── BrightSign : sortie audio (point AV 2/3) ─────────────────────────────────────────
  // EXCLUSIVITÉ = attribut pcmaudio par <video> (player.js, posé à la CRÉATION). CHANGEMENT de sortie =
  // reboot : sur le XT4 (XT1144), le sous-système audio n'initialise proprement qu'UNE sortie par chargement
  // de page → re-router à chaud vers une sortie « fraîche » reste muet ; seul un reboot ré-init la sortie
  // choisie (validé HW ; le HD4 tolérait le switch à chaud, mais on unifie sur le comportement fiable). On
  // émet donc cmd audio_output (sidecar sf_audioout.txt + reboot autorun) sur changement RÉEL. audio_volume/
  // audio_mute = no-op (mute via content_sound côté player.js). ⚠️ roAudioOutput TOUJOURS banni (casse
  // l'audio HTML5 widget). Anti-spam : on n'émet QUE sur changement (sinon reboot en boucle).
  let _bsAudioOutReq = null;
  function bsApplyAudioOutput(out) {
    if (!IS_BS) return;
    if (out == null || out === '') { _bsAudioOutReq = null; return; }   // pas d'avis → on ne touche à rien
    if (!/^(hdmi|analog|spdif|usb|none)$/.test(out)) return;
    // 🔑 ANTI-BOUCLE : compare à la sortie RÉELLE du device (device.json audio_out = sidecar courant), pas
    // au seul flag mémoire (réinitialisé à chaque reboot) ; sinon le renderer ré-émettait audio_output à
    // chaque boot → reboot en boucle infinie.
    const cur = _bsDevice.audio_out || '';
    if (!cur) return;                                                   // device.json pas encore lu → on réessaiera au prochain sync
    if (out === cur) { _bsAudioOutReq = null; return; }                 // déjà à cette sortie → rien à faire
    if (_bsAudioOutReq === out) return;                                 // changement déjà demandé → pas de spam
    _bsAudioOutReq = out;
    console.log('[BS][Audio] sortie', cur, '→', out, '(reboot)');
    bsCmd('audio_output', { output: out });
  }
  // ⚠️ Volume/mute NE passent PLUS par roAudioOutput (autorun) : incompatible avec l'audio HTML5 du
  // roHtmlWidget → cassait le son de façon non récupérable (prouvé HW HD1024). Le MUTE du contenu se fait
  // via `content_sound` (player.js mute le <video> HTML5, mécanisme éprouvé) → l'UI BrightSign écrit
  // `content_sound`, pas `audio_mute`. Le volume HTML5 reste à câbler (video.volume) → ces 2 fns = no-op.
  function bsApplyAudioVolume() { /* no-op : volume HTML5 à venir (plus de roAudioOutput) */ }
  function bsApplyAudioMute() { /* no-op : mute = content_sound côté player.js (plus de roAudioOutput) */ }
  // Correctif A : persiste le JWT roté sur la SD (via l'autorun → sf_token.txt) pour qu'il SURVIVE au
  // wipe du profil Chromium (localStorage effacé à chaque saut de firmware) → plus de boucle register
  // 409. On ne POSTe que les JWT (pas un provisioning sfp_) et seulement au changement (dédup → pas de
  // spam ni d'usure flash). L'autorun ne réécrit que si différent (double garde). Fire-and-forget.
  let _bsLastPersistedToken = null;
  function bsPersistToken(tok) {
    if (!IS_BS || !tok || tok.startsWith('sfp_') || tok === _bsLastPersistedToken) return;
    _bsLastPersistedToken = tok;
    bsCmd('persist_token', { token: tok });
  }

  // ── BrightSign : contrôle écran physique RS232 (Tier AV / parité player-linux) ────────
  // TOUTE la logique de protocole (Samsung MDC / LG RS232C / generic) vit ICI en JS, alignée sur
  // player-linux/src/display_control.js (mêmes trames/checksums) → produit une TRAME HEX. L'autorun.brs
  // ne fait qu'« ouvrir le port série et écrire ces octets » (bridge minimal, HORS chemin de boot →
  // compile sûre, pas de risque de brick ; au pire une commande échoue à l'invocation). Le display_config
  // arrive dans player:sync. Sur BrightSign, serial_port = INDEX numérique (0 = port intégré), pas
  // '/dev/ttyUSBx'. Fire-and-forget (pas de retour série lu en v1, comme reboot/firmware_update).
  let _bsDisplayCfg = {};
  // Boot OFFLINE : recharge le dernier display_config persisté (le pilote auto-power offline
  // ci-dessous doit connaître offline_power/type d'écran AVANT le premier sync serveur).
  try { _bsDisplayCfg = JSON.parse(localStorage.getItem('signflow_dcfg') || '{}') || {}; } catch { _bsDisplayCfg = {}; }

  // ── Pilote auto-power OFFLINE (BrightSign uniquement — un PWA ne pilote pas l'écran) ──
  // Fenêtres d'allumage pré-calculées par le serveur (display_config.offline_power, persisté
  // localStorage) : si la WS est down depuis > grace, le player pilote SEUL son écran (CEC /
  // RS232 / repli SetPowerSaveMode via l'autorun). Online, le serveur reste la source de
  // vérité (worker apply_site_power + re-assertion à la reconnexion). Même logique que les
  // players Electron (main.js) : tick minute, edge-triggered + baseline, projection hebdo.
  let _wsDownSince = Date.now();          // boot = « down » jusqu'au 1er onopen
  let _offlineAppliedPower = null;
  const OFFLINE_POWER_GRACE_MS = 3 * 60 * 1000;   // > backoff reconnect max

  // NTP du site (migr 0071) : le sync merge dc.ntp_server pour les players sans config
  // propre → l'autorun v42 pose le time server BOS (roNetworkConfiguration.SetTimeServer).
  // Idempotent (le sync repasse ~30 s) ; valeur vide = on ne touche pas au défaut BOS.
  let _bsAppliedNtp = null;
  function bsApplyNtp(server) {
    if (!IS_BS) return;
    const s = server || '';
    if (s === _bsAppliedNtp) return;
    _bsAppliedNtp = s;
    if (!s) return;
    // Le BOS exige une URL a SCHEMA (defaut: http://time.brightsignnetwork.com) —
    // une IP/host nu est REFUSE par SetTimeServer (constate HW). ntp:// par defaut.
    const url = /^[a-z]+:\/\//i.test(s) ? s : 'ntp://' + s;
    bsCmd('set_time_server', { server: url });
    console.log(`[BS][NTP] time server -> ${url}`);
  }

  // v46 : config du contrôle LOCAL (/control) poussée à l'autorun — la page locale est gérée
  // par HandleHdmiInput (autorun) qui ne lit pas display_config. local_control=false coupe la
  // page ; local_control_pin la protège (validé DANS l'autorun, RAM only : le PIN n'est jamais
  // écrit dans un fichier servi en HTTP). Change-guard = pas de POST à chaque sync.
  let _bsAppliedHdmiLocal = null;
  function bsApplyHdmiLocalCfg(dc, playerName) {
    if (!IS_BS) return;
    const enabled = (dc || {}).local_control !== false;
    const pin = String((dc || {}).local_control_pin || '');
    // v48 : nom du player affiché sur /control (via /controlst.json — pas un secret).
    // Vient du sync (player_name) ; persisté pour le boot offline comme signflow_dcfg.
    const name = String(playerName || '');
    const sig = `${enabled}|${pin}|${name}`;
    if (sig === _bsAppliedHdmiLocal) return;
    _bsAppliedHdmiLocal = sig;
    bsCmd('hdmi_local_cfg', { enabled, pin, name });
    console.log(`[BS][HDMI] local control ${enabled ? 'enabled' : 'DISABLED'}${pin ? ' (PIN set)' : ''}`);
  }

  function bsApplyPower(on, source) {
    const dcfg = _bsDisplayCfg || {};
    if (dcfg.type === 'cec') bsCmd('cec_power', { on });
    else if (dcfg.type === 'rs232' || dcfg.type === 'ip') bsDisplayCommand({ display_cmd: on ? 'power_on' : 'power_off' });
    else bsCmd('video_output', { on });
    // Auto-OFF du switch HDMI (VOD/override) : écran coupé (pilote offline = fermeture du site)
    // → fin du takeover, la playlist reprend au wall-clock. No-op si aucun switch actif
    // (garde d'idempotence dans _bsStopHdmiInput, player.js).
    if (!on) emit('hdmi_input', { mode: 'stop' });
    // Rallumage : ré-armer un éventuel plan HDMI monté écran éteint (mort-né, bug HW
    // 2026-07-08). Conditionnel côté player.js (plan sain = no-op, pas de clignotement).
    else emit('hdmi_input', { mode: 'rearm' });
    console.log(`[BS][Power] ${source} ${on ? 'power_on' : 'power_off'}`);
  }

  function offlineDesiredPower(op, now) {
    if (!op || op.mode === 'manual') return null;
    if (op.mode === 'always_on') return true;
    const iv = Array.isArray(op.intervals) ? op.intervals : [];
    if (iv.length === 0) return false;
    let t = now.getTime();
    const lastEnd = new Date(iv[iv.length - 1][1]).getTime();
    if (Number.isFinite(lastEnd) && t > lastEnd) {
      const WEEK_MS = 7 * 24 * 3600 * 1000;
      t -= Math.ceil((t - lastEnd) / WEEK_MS) * WEEK_MS;   // offline > 14 j : motif hebdo
    }
    for (const pair of iv) {
      const a = new Date(pair[0]).getTime();
      const b = new Date(pair[1]).getTime();
      if (Number.isFinite(a) && Number.isFinite(b) && a <= t && t < b) return true;
    }
    return false;
  }

  function offlinePowerTick() {
    try {
      const op = (_bsDisplayCfg || {}).offline_power;
      const wsUp = ws && ws.readyState === WebSocket.OPEN;
      if (!wsUp && op && _wsDownSince && (Date.now() - _wsDownSince) >= OFFLINE_POWER_GRACE_MS) {
        const desired = offlineDesiredPower(op, new Date());
        if (desired !== null && desired !== _offlineAppliedPower) {
          const downMin = Math.round((Date.now() - _wsDownSince) / 60000);
          console.log(`[BS][Power] Offline pilot: ${desired ? 'power_on' : 'power_off'} (no server for ${downMin} min)`);
          bsApplyPower(desired, 'offline');
          _offlineAppliedPower = desired;
        }
      }
    } catch (e) { console.error('[BS][Power] offline tick:', e.message); }
  }
  if (IS_BS) setInterval(offlinePowerTick, 60 * 1000);

  function _bsHex(bytes) {
    let h = '';
    for (let i = 0; i < bytes.length; i++) h += (bytes[i] & 0xFF).toString(16).padStart(2, '0');
    return h;
  }
  function _bsAsciiHex(s) {
    let h = '';
    for (let i = 0; i < s.length; i++) h += (s.charCodeAt(i) & 0xFF).toString(16).padStart(2, '0');
    return h;
  }
  function _bsLevel(p) {
    const n = (p && typeof p.level === 'number') ? p.level : 50;
    return Math.max(0, Math.min(100, Math.round(n)));
  }
  function _bsSamsungFrame(cmd, id, data) {
    const f = [0xAA, cmd, id, data.length].concat(data);
    let sum = 0;                                   // checksum = somme des octets après 0xAA, mod 256
    for (let i = 1; i < f.length; i++) sum = (sum + f[i]) & 0xFF;
    f.push(sum);
    return _bsHex(f);
  }
  function _bsLgFrame(c1, c2, setId, data) {
    return _bsAsciiHex(`${c1}${c2} ${String.fromCharCode(setId)} ${data}\r`);
  }
  const _BS_SAMSUNG_INPUT = { pc: 0x14, av: 0x18, hdmi1: 0x21, hdmi2: 0x23, hdmi3: 0x31, dp: 0x25, dvi: 0x18 };
  const _BS_DISPLAY_PROTO = {
    samsung_mdc: {
      power_on:       (id)    => _bsSamsungFrame(0x11, id, [0x01]),
      power_off:      (id)    => _bsSamsungFrame(0x11, id, [0x00]),
      get_status:     (id)    => _bsSamsungFrame(0x00, id, [0x11]),
      set_brightness: (id, p) => _bsSamsungFrame(0x25, id, [_bsLevel(p)]),
      set_contrast:   (id, p) => _bsSamsungFrame(0x24, id, [_bsLevel(p)]),
      set_volume:     (id, p) => _bsSamsungFrame(0x12, id, [_bsLevel(p)]),
      mute_on:        (id)    => _bsSamsungFrame(0x13, id, [0x01]),
      mute_off:       (id)    => _bsSamsungFrame(0x13, id, [0x00]),
      set_input:      (id, p) => {
        const code = _BS_SAMSUNG_INPUT[(p && p.source) || 'hdmi1'];
        return _bsSamsungFrame(0x14, id, [code != null ? code : 0x21]);
      },
    },
    lg_rs232c: {
      power_on:       (id)    => _bsLgFrame('k', 'a', id, '01'),
      power_off:      (id)    => _bsLgFrame('k', 'a', id, '00'),
      get_status:     (id)    => _bsLgFrame('k', 'a', id, 'ff'),
      set_brightness: (id, p) => _bsLgFrame('k', 'h', id, _bsLevel(p).toString(16).padStart(2, '0')),
      set_input:      (id, p) => {
        const codes = { av: '20', hdmi1: '90', hdmi2: '91', dp: 'c0' };
        return _bsLgFrame('x', 'b', id, codes[(p && p.source) || 'hdmi1'] || '90');
      },
    },
    generic: {                                     // params.hex = octets bruts en hexadécimal
      power_on:       (id, p) => (p && p.hex) || '',
      power_off:      (id, p) => (p && p.hex) || '',
      get_status:     (id, p) => (p && p.hex) || '',
      set_brightness: (id, p) => (p && p.hex) || '',
      set_input:      (id, p) => (p && p.hex) || '',
    },
  };
  function bsBuildDisplayHex(model, cmd, address, params) {
    const proto = _BS_DISPLAY_PROTO[model] || _BS_DISPLAY_PROTO.generic;
    const fn = proto[cmd];
    if (!fn) throw new Error(`commande inconnue '${cmd}' pour '${model}'`);
    return String(fn(address || 1, params || {}) || '').replace(/[^0-9a-fA-F]/g, '');
  }
  function bsDisplayCommand(params) {
    if (!IS_BS) return;
    const p = params || {};
    const cmd = p.display_cmd;
    if (!cmd) return;
    if (cmd === 'run_startup_sequence') return;    // séquence de démarrage écran : pas en v1 BrightSign
    const cfg = _bsDisplayCfg || {};
    const model = cfg.model || 'samsung_mdc';
    const address = Number(cfg.address) || 1;
    const cmdParams = Object.assign({}, p); delete cmdParams.display_cmd;
    let hex;
    try { hex = bsBuildDisplayHex(model, cmd, address, cmdParams); }
    catch (e) { console.warn('[BS][Display] build échec:', e.message); return; }
    if (!hex) { console.warn('[BS][Display] trame vide pour', cmd, '(check params.hex en generic)'); return; }
    const baud = Number(cfg.baud_rate) || 9600;
    const portN = Number(cfg.serial_port);         // BrightSign = index numérique ; NaN → 0 (port intégré)
    // On envoie un TABLEAU D'ENTIERS (pas du hex) : l'autorun les pousse direct dans un roByteArray, SANS
    // parsing hex côté BrightScript (Val(s,16)/Mid non fiables sur ce firmware → crashaient). hex = juste
    // pour la sonde /rs232.json (lisibilité). bytes = la source de vérité pour l'envoi série.
    const bytes = [];
    for (let i = 0; i + 1 < hex.length + 1; i += 2) bytes.push(parseInt(hex.substr(i, 2), 16));
    console.log('[BS][Display]', cmd, model, '→', hex, '@', baud, 'baud');
    bsCmd('display_command', { hex, bytes, baud, port: Number.isFinite(portN) ? portN : 0 });
  }
  function startBsLocalCache() {
    if (!IS_BS) return;
    bsFetchDevice();                     // modèle/IP/MAC natifs (1ʳᵉ lecture)
    bsPollCached();
    setInterval(bsPollCached, 15000);
    setInterval(bsFetchDevice, 60000);   // l'IP DHCP peut changer → rafraîchir
    setInterval(bsPollHdmiCmd, 2000);    // v44 : commandes de la page locale /control (switch HDMI)
    setInterval(bsPollVodCmd, 2000);     // 2.0.19 : broadcasts VOD LAN :7779 relayés par l'autorun v50
    let bootName = '';
    try { bootName = localStorage.getItem('signflow_pname') || ''; } catch { /* quota */ }
    bsApplyHdmiLocalCfg(_bsDisplayCfg, bootName);  // v46 : gate /control dès le boot (config persistée localStorage)
  }

  // v44 : commandes LOCALES — la page /control (servie par l'autorun :8888, magasin) POSTe
  // {cmd:'hdmi_input'} → l'autorun écrit sf_hdmicmd.json {mode,seq} → on exécute au CHANGEMENT
  // de seq via le même chemin que la commande WS (emit hdmi_input → player.js). 1re lecture =
  // adoption du seq courant SANS exécuter (ne pas rejouer une commande d'avant le reload).
  // Endpoint absent (autorun < v44 ou modèle sans entrée HDMI) → silencieux.
  let _bsHdmiCmdSeq = null;
  async function bsPollHdmiCmd() {
    try {
      const r = await fetch(`${LOCAL_BASE}/hdmicmd.json`, { cache: 'no-store' });
      if (!r.ok) return;
      const c = await r.json();
      if (!c || typeof c.seq !== 'number') return;
      if (_bsHdmiCmdSeq === null) { _bsHdmiCmdSeq = c.seq; return; }
      if (c.seq > _bsHdmiCmdSeq) {
        _bsHdmiCmdSeq = c.seq;
        console.log(`[BS][HDMI] local /control command: ${c.mode} (seq ${c.seq})`);
        emit('hdmi_input', { mode: c.mode === 'stop' ? 'stop' : 'start', source: 'local', id_media: null });
      }
    } catch (e) { /* best-effort */ }
  }

  // ── VOD à la demande : exécution d'un play_now (commande WS OU broadcast LAN relayé) ──────
  // Lecture ad-hoc takeover, src résolu offline-first (cache local prioritaire — média
  // pré-caché en Phase 1), repli URL signée. Factorisé : chemin cloud (case 'play_now')
  // ET chemin LAN BrightSign (bsPollVodCmd) passent ici.
  function handlePlayNowParams(p) {
    if (p.mode === 'stop' || !p.id_media) { emit('play_now', { mode: 'stop' }); return; }
    let src = p.url || null;
    if (p.cache_key) {
      if (IS_BS) {
        if (p.url) bsQueue(p.cache_key, p.url);
        if (_bsLocalKeys.has(p.cache_key)) src = bsLocalUrl(p.cache_key);
      } else if (_cachedKeys.has(p.cache_key)) src = localMediaUrl(p.cache_key);
      else if (p.url) queueDownload(p.cache_key, p.url, p.id_media);
    }
    if (!src) { console.log('[play_now] aucun src résolu pour média', p.id_media); return; }
    emit('play_now', {
      id_media: p.id_media, media_type: p.media_type || 'video',
      mode: p.mode === 'loop' ? 'loop' : 'once', src, duration_ms: p.duration_ms || null,
      // Relayes tels quels : le defaut (`!== false`) vit dans le renderer.
      with_sound: p.with_sound, has_audio: p.has_audio,
    });
  }

  // ── VOD LAN BrightSign (2.0.19, autorun v50) ────────────────────────────────────────────
  // Le Store Control Panel d'un player Electron déclenche les pairs par broadcast UDP :7779
  // signé HMAC-SHA256 (vod_lan.js). L'autorun (sourd à la crypto) relaie le paquet BRUT dans
  // /vodcmd.json {seq,packet} ; ICI on fait TOUTE la validation — miroir exact du récepteur
  // Electron (vod_lan.js _onMessage) : cible = MOI, fraîcheur ±30 s, nonce anti-rejeu, HMAC
  // via crypto.subtle (origine http://127.0.0.1 = secure context sur roHtmlWidget).
  let _bsVodMedia = [];
  let _bsVodLan = null;          // { secret, peers } du dernier sync — null = pas de groupe VOD
  let _bsVodCmdSeq = null;       // 1re lecture = adoption du seq courant SANS exécuter
  const _bsVodNonces = new Map();  // nonce -> vu à (anti-rejeu, TTL 60 s)
  async function _bsHmacHex(secret, text) {
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey(
      'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const sig = await crypto.subtle.sign('HMAC', key, enc.encode(text));
    return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  async function bsPollVodCmd() {
    if (!IS_BS) return;
    try {
      const r = await fetch(`${LOCAL_BASE}/vodcmd.json`, { cache: 'no-store' });
      if (!r.ok) return;
      const c = await r.json();
      if (!c || typeof c.seq !== 'number') return;
      if (_bsVodCmdSeq === null) { _bsVodCmdSeq = c.seq; return; }
      if (c.seq <= _bsVodCmdSeq) return;
      // 2.0.21 (autorun v51) : buffer roulant {packets:[{seq,packet}]} — on traite TOUS les
      // paquets pas encore vus. Une rafale multi-cibles (1 paquet UDP par player du site)
      // n'écrase plus le paquet qui NOUS cible (bug v50 : slot unique + drop 250 ms → VOD
      // « site entier » = BS inertes, vu HW par Ed 17/07). Rétro-compat autorun v50 {packet}.
      const lastSeen = _bsVodCmdSeq;
      _bsVodCmdSeq = c.seq;
      const entries = Array.isArray(c.packets)
        ? c.packets.filter((e) => e && typeof e.seq === 'number' && e.seq > lastSeen && typeof e.packet === 'string')
            .sort((a, b) => a.seq - b.seq)
        : (typeof c.packet === 'string' ? [{ seq: c.seq, packet: c.packet }] : []);
      for (const e of entries) await _bsHandleVodPacket(e.packet);
    } catch (e) { /* best-effort */ }
  }
  // Validation + exécution d'UN paquet vod_play — miroir exact du récepteur Electron
  // (vod_lan.js _onMessage) : cible = MOI, fraîcheur ±30 s, nonce anti-rejeu, HMAC.
  async function _bsHandleVodPacket(raw) {
    try {
      if (!raw || !_bsVodLan || !_bsVodLan.secret) return;
      if (!(crypto && crypto.subtle)) { console.log('[BS][VOD] crypto.subtle indisponible — paquet LAN ignoré'); return; }
      let m;
      try { m = JSON.parse(raw); } catch { return; }
      if (!m || m.cmd !== 'vod_play') return;
      const selfId = decodePlayerId(config.player_token);
      if (selfId == null || m.id_player !== selfId) return;                       // ne joue que ce qui ME cible
      if (typeof m.ts !== 'number' || Math.abs(Date.now() - m.ts) > 30000) return; // fraîcheur (anti-rejeu)
      if (!m.nonce || _bsVodNonces.has(m.nonce)) return;                           // nonce déjà vu
      const canonical = `vod_play|${m.id_player}|${m.id_media}|${m.mode}|${m.ts}|${m.nonce}`;
      const expected = await _bsHmacHex(_bsVodLan.secret, canonical);
      if (typeof m.sig !== 'string' || m.sig.toLowerCase() !== expected) return;   // signature invalide
      _bsVodNonces.set(m.nonce, Date.now());
      const cutoff = Date.now() - 60000;
      for (const [n, t] of _bsVodNonces) if (t < cutoff) _bsVodNonces.delete(n);
      console.log(`[BS][VOD] LAN trigger accepté: media=${m.id_media} mode=${m.mode}`);
      const entry = _bsVodMedia.find((e) => e && e.id_media === m.id_media) || {};
      handlePlayNowParams({
        id_media: m.id_media, mode: m.mode,
        media_type: entry.media_type || 'video',
        cache_key: entry.cache_key || null, url: entry.url || null,
        duration_ms: entry.duration_ms || null,
      });
    } catch (e) { /* best-effort */ }
  }

  // — IndexedDB meta (key → {key,size,pinnedAt}) pour l'éviction par budget —
  let _idb = null;
  function idb() {
    if (_idb) return _idb;
    _idb = new Promise((resolve, reject) => {
      const req = indexedDB.open('signflow-store', 1);
      req.onupgradeneeded = () => { req.result.createObjectStore('meta', { keyPath: 'key' }); };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return _idb;
  }
  async function idbAll() {
    const db = await idb();
    return new Promise((res, rej) => {
      const r = db.transaction('meta').objectStore('meta').getAll();
      r.onsuccess = () => res(r.result || []); r.onerror = () => rej(r.error);
    });
  }
  async function idbPut(rec) {
    const db = await idb();
    return new Promise((res, rej) => {
      const t = db.transaction('meta', 'readwrite'); t.objectStore('meta').put(rec);
      t.oncomplete = () => res(); t.onerror = () => rej(t.error);
    });
  }
  async function idbDel(key) {
    const db = await idb();
    return new Promise((res, rej) => {
      const t = db.transaction('meta', 'readwrite'); t.objectStore('meta').delete(key);
      t.oncomplete = () => res(); t.onerror = () => rej(t.error);
    });
  }

  async function loadCachedKeys() {
    try {
      const recs = await idbAll();
      // Réconciliation index↔octets au boot (clé pour la PERSISTANCE AU REBOOT) : l'index
      // IndexedDB peut survivre alors que les octets du Cache API ont disparu (reboot qui ne
      // persiste pas le Cache API sur la SD, ancienne purge, éviction partielle…). On vérifie
      // la présence RÉELLE de chaque média : absent → on purge l'entrée d'index pour forcer un
      // re-téléchargement (download-then-play) au lieu de servir un 504 verrouillé — le code
      // court-circuite le DL quand la clé est « connue », donc un index périmé bloquerait la lecture.
      let cache = null;
      try { cache = (typeof caches !== 'undefined') ? await caches.open(MEDIA_CACHE) : null; } catch { cache = null; }
      let dropped = 0;
      for (const rec of recs) {
        if (cache) {
          let present = false;
          try { present = !!(await cache.match(localMediaUrl(rec.key))); } catch { present = false; }
          if (!present) { idbDel(rec.key).catch(() => {}); dropped++; continue; }
        }
        _cachedKeys.add(rec.key);
        if (rec.id_media != null) _keyToMedia.set(rec.key, rec.id_media);
      }
      console.log(`[store] ${_cachedKeys.size} média(s) en cache${dropped ? ` (${dropped} entrée(s) d'index périmée(s) purgée(s) → re-téléchargement)` : ''}`);
    } catch (e) { console.warn('[store] meta load:', e.message); }
  }

  // État de stockage pour le heartbeat (inventaire par player + sync-readiness Q4, miroir
  // du content_store.js Electron getStorageStatus). Le serveur croise `cached_ids`
  // (id_media) avec la playlist attendue. disk_used_ratio = occupation du stockage navigateur
  // (Cache API + IndexedDB) via navigator.storage.estimate — l'équivalent PWA du disque.
  function getStoreStatus() {
    // BrightSign : le cache est NATIF (serveur loopback + SD), pas le Cache API → l'inventaire et
    // la sync-readiness doivent refléter _bsLocalKeys (médias sur SD) / _bsQueued (en DL), sinon le
    // serveur voit _cachedKeys (SW, vide ici) et marque tout « manquant » alors que ça diffuse.
    const cachedKeys = IS_BS ? _bsLocalKeys : _cachedKeys;
    const dlKeys     = IS_BS ? _bsQueued.keys() : _queued;
    const ids = new Set();
    for (const k of cachedKeys) { const m = _keyToMedia.get(k); if (m != null) ids.add(m); }
    const dl = new Set();
    for (const k of dlKeys) { const m = _keyToMedia.get(k); if (m != null) dl.add(m); }
    const out = {
      disk_used_ratio: _diskRatio,
      storage_pressure: _storagePressure,
      cached_count: ids.size,
      cached_ids: [...ids],
      downloading_ids: [...dl],
      // Médias auxquels on a renoncé : sans eux, l'écran diffuserait une playlist tronquée
      // sans que personne ne sache pourquoi.
      blocked_ids: [..._blockedMedia],
    };
    // Capacité et espace libre ABSOLUS — le ratio seul ne permet pas au serveur de dire
    // « ces 6 vidéos font 1,85 Go, cet écran n'a que 1,2 Go libres ».
    // ⚠️ Jamais sur BrightSign : `navigator.storage.estimate()` y décrit le quota du
    // navigateur, PAS la carte SD qui porte réellement les médias.
    if (!IS_BS && _diskQuotaBytes != null) {
      out.disk_total_bytes = _diskQuotaBytes;
      if (_diskUsageBytes != null) out.free_bytes = Math.max(0, _diskQuotaBytes - _diskUsageBytes);
    }
    // Débit DL mesuré (opt-in) → le serveur calcule l'ETA de sync-readiness (miroir Electron).
    if (_measureBandwidth && _measuredKbps > 0) out.throughput_kbps = Math.round(_measuredKbps);
    return out;
  }

  async function refreshDiskRatio() {
    // BrightSign : l'occupation SD vient de l'autorun (/device.json disk_ratio, posé par bsFetchDevice) —
    // navigator.storage.estimate() renverrait le quota du navigateur, pas la SD → ne pas l'écraser.
    if (IS_BS) return;
    try {
      if (navigator.storage && navigator.storage.estimate) {
        const est = await navigator.storage.estimate();
        if (est && est.quota) {
          _diskRatio = Math.round((est.usage / est.quota) * 100) / 100;
          _diskQuotaBytes = est.quota;
          _diskUsageBytes = est.usage;
        }
      }
    } catch { /* best-effort */ }
  }

  // Réécrit le payload sync pour servir le local + met en file les manquants. Appelé
  // AVANT emit('sync') pour que player.js sauvegarde déjà les urls locales (boot offline).
  function rewriteSyncForStore(msg) {
    if (!_swActive && !IS_BS) return;   // SW pas encore actif → garder les urls MinIO (online OK).
                                        // IS_BS = pas de SW (cache local natif) → on passe quand même.
    const pinned = new Set();
    const handle = (m) => {
      if (!m || !m.cache_key || !m.url) return;
      pinned.add(m.cache_key);
      if (m.id_media != null) _keyToMedia.set(m.cache_key, m.id_media);
      if (IS_BS) {
        // BrightSign : demande le DL au serveur local (POST /queue) ; sert le local si déjà
        // téléchargé, sinon garde l'URL MinIO (repli streaming le temps du download).
        bsQueue(m.cache_key, m.url);
        if (_bsLocalKeys.has(m.cache_key)) m.url = bsLocalUrl(m.cache_key);
        return;
      }
      if (_cachedKeys.has(m.cache_key)) m.url = localMediaUrl(m.cache_key);
      else queueDownload(m.cache_key, m.url, m.id_media);
    };
    const handleItem = (it) => {
      const m = it && it.media;
      if (!m) return;
      handle(m);
      // Feed Display : cache offline-first des vignettes re-hébergées (image_cache_key) → URL
      // locale SW si présente ; sinon l'URL signée MinIO est conservée (online).
      if (m.media_type === 'feed_display' && m.feed_config && Array.isArray(m.feed_config.items)) {
        for (const fi of m.feed_config.items) {
          if (!fi || !fi.image_cache_key || !fi.image_url) continue;
          const proxy = { cache_key: fi.image_cache_key, url: fi.image_url, id_media: m.id_media };
          handle(proxy);
          fi.image_url = proxy.url;
        }
      }
    };
    for (const it of (msg.items || [])) handleItem(it);
    // §25.4 multi-zones : patcher AUSSI les items du bloc template. Après sérialisation JSON ce
    // sont des objets DISTINCTS de msg.items, et le renderer multi-zones lit template.zones[].items
    // (pas msg.items) → sans ça une zone vidéo déjà cachée garde l'URL MinIO et streame.
    if (msg.template && Array.isArray(msg.template.zones)) {
      for (const z of msg.template.zones) for (const it of (z.items || [])) handleItem(it);
    }
    for (const b of (msg.audio_baskets || [])) for (const it of (b.items || [])) handle(it);
    if (msg.fallback && msg.fallback.audio) handle(msg.fallback.audio);
    // VOD à la demande (Feature B) : pré-cache des médias VOD (variante navigateur-safe) — le
    // PWA ne traite pas la liste `prefetch`, donc on télécharge `vod_media` ici (lecture instantanée
    // au déclenchement cloud). cache_key/url/id_media = même forme que les médias d'items.
    for (const m of (msg.vod_media || [])) handle(m);
    _pinnedKeys = pinned;
    // Re-pin (pinnedAt) les clés déjà en cache présentes dans ce sync (fraîcheur LRU).
    for (const k of pinned) if (_cachedKeys.has(k)) idbPut({ key: k, size: 0, pinnedAt: Date.now(), id_media: _keyToMedia.get(k) }).catch(() => {});
    // BrightSign : prefetch look-ahead (P2.7) + fenêtres horaires (P2.8), puis keep-set (Tier 1.1,
    // inclut désormais les clés prefetch → le préchargé n'est pas évincé). bsPrefetch AVANT bsSendKeep
    // pour que _bsPrefetchKeys soit à jour au flush du keep (debounce 1.5 s).
    if (IS_BS) {
      const dc = msg.display_config || {};
      bsPrefetch(msg.prefetch, Array.isArray(dc.download_windows) ? dc.download_windows : []);
      bsSendKeep();
      // LAN sync (Phase 2) : ce player est-il dans un groupe LAN ? (config serveur = source de verite).
      _bsLanEnabled = !!dc.lan_sync_enabled;
      _bsLanGroup   = (dc.lan_sync_group || '').trim();
      _bsLanMaster  = !!dc.lan_sync_master;   // Phase 2b : maitre -> l'autorun diffuse notre sync_play
      startBsLanSync();
      // VOD LAN (2.0.19) : mémorise la liste des médias VOD (résolution offline-first au
      // déclenchement) + le secret HMAC du site (validation des broadcasts :7779 relayés
      // par l'autorun v50 via /vodcmd.json). Cachés offline avec le reste du sync.
      _bsVodMedia = Array.isArray(msg.vod_media) ? msg.vod_media : [];
      _bsVodLan = (msg.vod_lan && msg.vod_lan.secret) ? msg.vod_lan : null;
    }
  }

  // Tous les médias VIDÉO/IMAGE d'un sync sont-ils en cache ? (l'audio des paniers peut streamer ;
  // un média sans cache_key — ex. page web/URL externe — n'est pas téléchargeable et ne bloque pas.)
  function syncContentReady(msg) {
    const have = IS_BS ? _bsLocalKeys : _cachedKeys;   // BrightSign : dispo = téléchargé localement
    for (const it of (msg.items || [])) {
      const m = it && it.media;
      if (m && m.cache_key && (m.media_type === 'video' || m.media_type === 'image')
          && !have.has(m.cache_key)) {
        return false;
      }
    }
    return true;
  }

  // Livre le sync à player.js et mémorise ses clés comme « contenu joué » (protégé de l'éviction
  // pendant qu'un éventuel nouveau contenu se télécharge — cf. ensureRoom).
  function deliverSync(msg) {
    _pendingHold = null;
    _deliveredKeys = new Set(_pinnedKeys);
    emit('sync', msg);
  }

  // Appelé à chaque fin de download : si le contenu retenu est désormais complet, on le livre
  // (URLs ré-écrites vers le local). Tant qu'un média manque (ou échoue à se télécharger), on
  // reste sur le contenu en cours — jamais de lecture partielle.
  function maybeReleaseHold() {
    if (!_pendingHold || !syncContentReady(_pendingHold)) return;
    const msg = _pendingHold;
    _pendingHold = null;
    rewriteSyncForStore(msg);   // ré-écrit : les clés fraîchement cachées passent en URL locale
    console.log('[store] cache complet → livraison du contenu retenu');
    deliverSync(msg);
  }

  function queueDownload(key, url, id_media) {
    // BrightSign : SW media-cache DÉSACTIVÉ (streaming-only). PROUVÉ sur XT1144 : le <video>
    // du roHtmlWidget NE REND PAS un média servi par un Service Worker (écran noir, item
    // suivant) — quelle que soit la forme de réponse (206 streaming OU 200 verbatim), cache
    // 100% local, RAM OK. Ce n'est PAS un pb de RAM (l'OOM arrayBuffer était un symptôme
    // distinct, désormais écarté) → limitation de fond. Vrai cache offline = natif BrightScript
    // (roUrlTransfer → SD → roVideoPlayer/file://), chantier à part. cf. project-brightsign.
    if (IS_BS) return;
    if (_cachedKeys.has(key) || _queued.has(key)) return;
    _queued.add(key);
    _dlQueue.push({ key, url, id_media });
    drain();
  }

  async function drain() {
    if (_draining) return;
    _draining = true;
    while (_dlQueue.length) {
      const job = _dlQueue.shift();
      try { await downloadOne(job); }
      catch (e) { console.warn('[store] DL échec', job.key, e.message); }   // repli : url MinIO conservée
      finally { _queued.delete(job.key); }
    }
    _draining = false;
  }

  // Réponse à débit PLAFONNÉ (QoS Q3, miroir du throttle Electron) : pace la lecture du body via
  // un TransformStream — chaque chunk attend pour ne pas dépasser _bandwidthKbps (octets/s =
  // kbps*125). La backpressure remonte jusqu'au socket → le fetch ralentit, sans bufferiser toute
  // la vidéo en mémoire. Sans plafond / sans body / TransformStream indispo → réponse inchangée.
  function _throttledResponse(resp) {
    const bytesPerSec = _bandwidthKbps > 0 ? _bandwidthKbps * 125 : 0;
    if (!bytesPerSec || !resp.body || typeof TransformStream === 'undefined') return resp;
    const startedAt = Date.now();
    let sent = 0;
    const ts = new TransformStream({
      async transform(chunk, controller) {
        controller.enqueue(chunk);
        sent += chunk.byteLength;
        const wait = (sent / bytesPerSec) * 1000 - (Date.now() - startedAt);
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      },
    });
    return new Response(resp.body.pipeThrough(ts), {
      status: resp.status, statusText: resp.statusText, headers: new Headers(resp.headers),
    });
  }

  async function downloadOne({ key, url, id_media }) {
    const cache = await caches.open(MEDIA_CACHE);
    const local = localMediaUrl(key);
    if (await cache.match(local)) {   // déjà là (index désynchronisé) → juste signaler
      _cachedKeys.add(key);
      if (id_media != null) _keyToMedia.set(key, id_media);
      emit('store-update', { cache_key: key, url: local });
      maybeReleaseHold();
      return;
    }
    // CORS MinIO requis pour LIRE les octets (le streaming <video> marche sans CORS, mais
    // pas un fetch cacheable). Échec (CORS absent / réseau) → throw → repli streaming.
    const resp = await fetch(url, { mode: 'cors', credentials: 'omit' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const size = Number(resp.headers.get('Content-Length')) || 0;
    await ensureRoom(size, key);
    const _t0 = Date.now();
    // FREIN (équivalent du plancher d'espace libre des surfaces natives) : ici c'est le
    // NAVIGATEUR qui refuse l'écriture au-delà du quota d'origine — il ne nous laissera pas
    // saturer la partition, et c'est tant mieux. Mais son refus doit être ATTRAPÉ et REMONTÉ,
    // sinon l'écran renonce à du contenu en silence.
    try {
      await cache.put(local, _throttledResponse(resp));   // consomme le corps (débit plafonné) dans le cache
    } catch (e) {
      const quota = e && (e.name === 'QuotaExceededError' || /quota/i.test(String(e.message || '')));
      if (!quota) throw e;
      _storagePressure = true;
      if (id_media != null) _blockedMedia.add(id_media);
      console.warn(`[store] FREIN STOCKAGE : quota navigateur atteint, ${key} renoncé — `
        + `la diffusion continue sur ce qui est déjà en cache`);
      throw new Error('insufficient-space');
    }
    // Écriture réussie : ce média n'est plus « renoncé ».
    if (id_media != null) _blockedMedia.delete(id_media);
    if (_blockedMedia.size === 0) _storagePressure = false;
    // Mesure passive du débit (opt-in, miroir content_store.js Electron) → EWMA kbit/s remonté au
    // heartbeat ; le serveur (readiness.py) en déduit l'ETA de fin de téléchargement par player.
    if (_measureBandwidth && size > 0) {
      const sec = (Date.now() - _t0) / 1000;
      if (sec > 0.05) {
        const kbps = (size * 8) / 1000 / sec;
        _measuredKbps = _measuredKbps ? 0.6 * _measuredKbps + 0.4 * kbps : kbps;
      }
    }
    await idbPut({ key, size, pinnedAt: Date.now(), id_media });
    _cachedKeys.add(key);
    if (id_media != null) _keyToMedia.set(key, id_media);
    console.log(`[store] caché ${key} (${(size / 1048576).toFixed(1)} Mo)`);
    emit('store-update', { cache_key: key, url: local });
    maybeReleaseHold();
  }

  // Éviction LRU par budget : libère de la place pour `size` octets en supprimant les
  // entrées les plus anciennement épinglées qui NE sont PAS dans le sync courant.
  async function ensureRoom(size, currentKey) {
    if (!size) return;
    try {
      let recs = await idbAll();
      let total = recs.reduce((s, r) => s + (r.size || 0), 0);
      if (total + size <= STORE_BUDGET_BYTES) return;
      const cache = await caches.open(MEDIA_CACHE);
      recs = recs.filter((r) => r.key !== currentKey && !_pinnedKeys.has(r.key)
                                && !_deliveredKeys.has(r.key))   // jamais le contenu en cours de lecture
                 .sort((a, b) => (a.pinnedAt || 0) - (b.pinnedAt || 0));
      for (const r of recs) {
        if (total + size <= STORE_BUDGET_BYTES) break;
        await cache.delete(localMediaUrl(r.key)).catch(() => {});
        await idbDel(r.key).catch(() => {});
        _cachedKeys.delete(r.key);
        total -= (r.size || 0);
        console.log(`[store] évincé ${r.key}`);
      }
    } catch (e) { console.warn('[store] éviction:', e.message); }
  }

  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) { console.log('[SW] non supporté'); return; }
    // BrightSign : streaming-only (le <video> du roHtmlWidget ne lit pas un média servi par un
    // SW → écran noir). On désenregistre tout SW déjà posé + purge le cache média pour ne pas
    // servir de média local inexploitable. cf. project-brightsign (cache natif = roadmap).
    if (IS_BS) {
      navigator.serviceWorker.getRegistrations()
        .then((rs) => rs.forEach((r) => r.unregister().catch(() => {})))
        .catch(() => {});
      if (typeof caches !== 'undefined') {
        caches.delete(MEDIA_CACHE).catch(() => {});
        caches.delete('signflow-shell-v1').catch(() => {});
      }
      return;
    }
    navigator.serviceWorker.register('sw.js').then((reg) => {
      console.log('[SW] enregistré, scope', reg.scope);
      // Robustesse hard reload : un Ctrl+Shift+R charge la page SANS contrôle du SW (controller=null)
      // → pas de service des urls locales NI de téléchargement (rewriteSyncForStore retourne tôt).
      // Si le SW est actif mais ne contrôle pas, on recharge UNE fois (garde anti-boucle session)
      // pour reprendre le contrôle → _swActive=true, downloads démarrent, le local est servi.
      if (reg.active && !navigator.serviceWorker.controller && !sessionStorage.getItem('_sfSwReload')) {
        try { sessionStorage.setItem('_sfSwReload', '1'); } catch (e) { /* ignore */ }
        console.log('[SW] actif sans contrôle (hard reload ?) → reload pour reprendre le contrôle');
        location.reload();
      }
    }).catch((e) => console.warn('[SW] register échec:', e.message));
    // Le SW peut déjà contrôler la page (reload) → actif immédiatement.
    if (navigator.serviceWorker.controller) _swActive = true;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      _swActive = true;
      try { sessionStorage.removeItem('_sfSwReload'); } catch (e) { /* ignore */ }
    });
  }

  // ── WebSocket ────────────────────────────────────────────────────────────────
  let ws = null;
  let reconnectAttempts = 0;
  let reconnectTimer = null;
  let connectTimer = null;       // timeout d'ouverture (ws bloqué en CONNECTING, réseau coupé)
  let heartbeatTimer = null;
  let watchdogTimer = null;
  let _eventQueue = [];          // alertes sortantes en attente (offline) — ex. url_display inaccessible
  let lastMsgAt = 0;
  let connected = false;

  const CONNECT_TIMEOUT_MS = 12000;   // un ws qui n'OUVRE pas sous ce délai = forcé à reconnecter

  function stopWatchdog() { if (watchdogTimer) { clearInterval(watchdogTimer); watchdogTimer = null; } }

  // Détache et ferme le ws courant SANS laisser son onclose tardif interférer (sinon un
  // ancien socket peut re-programmer une reconnexion par-dessus une tentative en cours).
  function cleanupWs() {
    if (ws) {
      try { ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null; ws.close(); } catch {}
      ws = null;
    }
  }

  // Chute de connexion (watchdog silencieux / timeout d'ouverture) → on relance le cycle.
  // cleanupWs() ayant annulé onclose, c'est ICI qu'on (re)programme la reconnexion.
  function dropAndReconnect(reason) {
    console.log(`[WS] drop (${reason}) — reconnexion`);
    clearTimeout(connectTimer);
    stopWatchdog();
    stopHeartbeat();
    cleanupWs();
    if (connected) { connected = false; emit('disconnected'); }
    scheduleReconnect();
  }

  // Le serveur pousse un force_sync toutes les 30s → si RIEN n'arrive sous ce délai, le
  // lien est mort silencieusement (veille réseau, serveur redémarré sans FIN TCP). Le
  // WebSocket navigateur ne le détecte pas toujours via close → watchdog applicatif
  // (cf. bug WS Android jamais reconnecté). On force alors une reconnexion.
  const WATCHDOG_TIMEOUT_MS = 45000;
  const HEARTBEAT_MS = 10000;

  function decodePlayerId(token) {
    try {
      const parts = (token || '').split('.');
      if (parts.length < 2) return null;
      const json = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
      return json.sub ? parseInt(json.sub, 10) : null;
    } catch { return null; }
  }

  async function registerPlayer() {
    // Token de provisioning d'organisation (sfp_…) → l'échange contre un JWT player.
    try {
      console.log('[WS] Provisioning token — registering player...');
      // BrightSign : garantit le n° de série avant l'enregistrement → permet au serveur de RÉ-ATTACHER
      // ce device à son player existant (au lieu de créer un doublon / 409) s'il a perdu son JWT —
      // typiquement après un saut de firmware qui wipe le profil Chromium (localStorage). bsFetchDevice
      // est idempotent ; on l'attend une fois si la série n'est pas encore connue.
      if (IS_BS && !_bsInfo.bs_serial) { try { await bsFetchDevice(); } catch (e) { /* best-effort */ } }
      const res = await fetch(`${config.backend_url}/api/v1/players/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          player_name: (typeof window !== 'undefined' && window.__SF_PLAYER_NAME__) || `chromebox-${(navigator.userAgent.match(/CrOS\s+(\w+)/) || [])[1] || 'pwa'}`,
          player_os: (typeof window !== 'undefined' && window.__SF_PLAYER_OS__) || 'chromeos',
          player_version: REPORTED_VERSION,
          org_token: config.player_token,
          serial: (IS_BS && _bsInfo.bs_serial) || undefined,
        }),
      });
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
      const data = await res.json();
      config.player_token = data.player_token;
      localStorage.setItem(LS_TOKEN, data.player_token);
      bsPersistToken(data.player_token);   // Correctif A : grave le JWT sur la SD (survit au wipe firmware)
      console.log('[WS] Registration OK — connecting with JWT');
      connect();
    } catch (e) {
      console.error('[WS] Registration error:', e.message);
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    const delay = Math.min(30000, 2000 * Math.pow(2, reconnectAttempts));
    reconnectAttempts++;
    reconnectTimer = setTimeout(connect, delay);
  }

  function connect() {
    clearTimeout(reconnectTimer);
    stopWatchdog();
    cleanupWs();   // repart d'un ws propre (annule l'onclose d'un éventuel ancien socket)
    config.backend_url = localStorage.getItem(LS_BACKEND) || config.backend_url;
    config.player_token = localStorage.getItem(LS_TOKEN) || config.player_token;
    bsPersistToken(config.player_token);   // Correctif A : capture le JWT courant sur la SD (dédupé)

    // La PWA est servie par le MÊME origine que le backend (nginx proxie / et /api) →
    // si aucun backend explicite, on cible l'origine de la page. L'URL kiosk se réduit
    // alors à `…/index.html?token=<jwt>`, et le ws:// hérite du scheme de la page (pas de
    // mixed-content possible).
    if (!config.backend_url && typeof location !== 'undefined' && location.origin && location.origin !== 'null') {
      config.backend_url = location.origin;
    }

    if (!config.backend_url || !config.player_token) {
      emit('setup-required');
      return;
    }
    if (config.player_token.startsWith('sfp_')) { registerPlayer(); return; }

    // http→ws / https→wss. La page servie en HTTP (LAN) → ws:// même origine = OK
    // (pas de mixed-content). Servie en HTTPS → wss:// requis (backend derrière TLS).
    const wsUrl = `${config.backend_url.replace(/^http/, 'ws')}/api/v1/ws/player?token=${encodeURIComponent(config.player_token)}`;
    console.log('[WS] Connecting to', wsUrl.replace(/token=[^&]+/, 'token=***'));

    try { ws = new WebSocket(wsUrl); }
    catch (e) { console.error('[WS] construct error:', e.message); scheduleReconnect(); return; }

    // Un WebSocket navigateur peut rester en CONNECTING indéfiniment quand le réseau est
    // coupé (pas toujours d'onclose) → sans ce timeout, aucune reconnexion n'est reprogrammée
    // = player bloqué en "Reconnecting" même après retour réseau. On force la reprise.
    clearTimeout(connectTimer);
    connectTimer = setTimeout(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) dropAndReconnect('open-timeout');
    }, CONNECT_TIMEOUT_MS);

    ws.onopen = () => {
      console.log('[WS] Connected to backend');
      clearTimeout(connectTimer);
      connected = true;
      reconnectAttempts = 0;
      lastMsgAt = Date.now();
      clearTimeout(reconnectTimer);
      // Le serveur reprend le pilotage écran (re-assertion via reset last_power_state
      // au connect) → le pilote offline s'efface et oublie son dernier état appliqué.
      _wsDownSince = null;
      _offlineAppliedPower = null;
      emit('connected');
      startHeartbeat();
      startWatchdog();
      flushEventQueue();   // rejoue les alertes (ex. url_display inaccessible) accumulées offline
    };

    ws.onmessage = (ev) => {
      lastMsgAt = Date.now();
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { console.error('[WS] bad message:', e.message); return; }
      handleServerMessage(msg);
    };

    ws.onclose = (ev) => {
      console.log(`[WS] Disconnected (${ev.code})`);
      clearTimeout(connectTimer);
      connected = false;
      if (!_wsDownSince) _wsDownSince = Date.now();  // début de la fenêtre offline (pilote écran)
      stopHeartbeat();
      stopWatchdog();           // le watchdog ne garde qu'une connexion OUVERTE — sinon il
                                 // fermerait le ws de reconnexion en cours (cause du blocage).
      emit('disconnected');
      scheduleReconnect();
    };

    ws.onerror = (e) => { console.error('[WS] error', e && e.message ? e.message : ''); /* close suit */ };
  }

  // ── OTA §XXX slice 2 (renderers web : BrightSign + ChromeOS PWA + extension Chrome) ────────────
  // La directive `update` est jointe au sync payload par le serveur (ota.directive_for_player) tant que
  // la cible du déploiement est NON terminale. L'apply diffère par plateforme (`otaApply`) mais la
  // machine à états est commune. Aucun téléchargement séparé (code servi par prod / bundlé) → on passe
  // direct `staged` puis `installing`, puis on applique. Après l'apply, le renderer neuf reporte
  // REPORTED_VERSION → le serveur constate la montée de version = succès (mark_success_if_updated).
  //  - BrightSign : `bsCmd('ota_apply')` → l'autorun tire renderer+autorun de prod puis reboote.
  //  - ChromeOS PWA : `location.reload()` → le SW network-first re-tire le renderer frais de prod.
  //  - Extension : `location.reload()` → re-exécute le renderer bundlé (MV3 interdit le code distant ;
  //    l'apply prend effet si le bundle a été mis à jour hors-bande via le Web Store/rechargement).
  // Les players Electron/Android gèrent `msg.update` dans leur main.js natif → ne passent pas ici.
  const LS_OTA = 'signflow_ota';
  const _OTA_MAX_ATTEMPTS = 2;   // applies max avant d'abandonner (anti-boucle reboot/reload)
  let _otaAppliedThisSession = false;

  function _otaLoad() { try { return JSON.parse(localStorage.getItem(LS_OTA) || 'null'); } catch (e) { return null; } }
  function _otaSave(o) { try { if (o) localStorage.setItem(LS_OTA, JSON.stringify(o)); else localStorage.removeItem(LS_OTA); } catch (e) {} }

  function otaSendStatus(id_deployment, status, error) {
    try {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'update:status', id_deployment, status, error: error || undefined }));
      }
    } catch (e) { /* best-effort : un report perdu sera re-déduit du prochain heartbeat/version */ }
  }

  // Compare SemVer M.m.p (aligné semver_key backend + _semverGte des players Electron). a >= b.
  function _otaSemverGte(a, b) {
    const p = (v) => String(v || '0').split('.').map((n) => parseInt(n, 10) || 0);
    const av = p(a), bv = p(b);
    for (let i = 0; i < 3; i++) { if ((av[i] || 0) !== (bv[i] || 0)) return (av[i] || 0) > (bv[i] || 0); }
    return true;   // égales
  }

  // Fenêtre "HH:MM-HH:MM" en HEURE LOCALE du player. null/invalide = toujours autorisé. Minuit-safe.
  function _otaInWindow(win) {
    if (!win) return true;
    const m = /^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$/.exec(String(win));
    if (!m) return true;
    const now = new Date();
    const cur = now.getHours() * 60 + now.getMinutes();
    const s = (+m[1]) * 60 + (+m[2]);
    const e = (+m[3]) * 60 + (+m[4]);
    return s <= e ? (cur >= s && cur < e) : (cur >= s || cur < e);
  }

  // Applique l'update selon la plateforme. BrightSign = pont autorun (reboot) ; ChromeOS/extension =
  // reload de la page (SW network-first re-tire le renderer de prod / re-exécute le bundle).
  function otaApply(update) {
    if (IS_BS) { bsCmd('ota_apply', { version: update.version }); return; }
    try { location.reload(); } catch (e) { /* kiosk sans navigation ? no-op */ }
  }

  // Ré-évaluée à CHAQUE sync (la directive est ré-émise tant que non terminale). Idempotent.
  function handleWebOta(update) {
    // Plus de directive (déploiement terminé/annulé) → on oublie l'état en attente.
    if (!update || typeof update !== 'object' || !update.id_deployment || !update.version) {
      if (_otaLoad()) _otaSave(null);
      return;
    }
    if (update.track === 'server') return;   // track serveur ≠ apply player
    // Firmware (BrightSign) : appliqué par une commande DÉDIÉE `firmware_update` (autorun
    // DoFirmwareUpdate → .bsfw → reboot), succès détecté SERVEUR via `bs_bos` (_reconcile_firmware
    // _targets). Cette machine à états surveille la version RENDERER (2.0.x), qui n'atteint JAMAIS
    // une version BOS (9.1.x) → sans ce garde, elle déclarait un FAUX « apply non effectif après N
    // tentatives » alors que le firmware s'était bien appliqué. On la laisse donc de côté.
    if (update.track === 'firmware') return;
    // Déjà à la version cible (ou au-delà) → rien à faire (nettoie un résidu, ex. après un apply réussi).
    if (_otaSemverGte(REPORTED_VERSION, update.version)) { if (_otaLoad()) _otaSave(null); return; }

    let st = _otaLoad();
    if (!st || st.id_deployment !== update.id_deployment || st.version !== update.version) {
      st = { id_deployment: update.id_deployment, version: update.version, attempt: 0, staged: false };
      _otaSave(st);
    }
    // Rien à télécharger (code servi par prod / bundlé) → on annonce `staged` UNE fois (prêt à
    // installer, en attente de la fenêtre d'install / du force).
    if (!st.staged) { st.staged = true; _otaSave(st); otaSendStatus(st.id_deployment, 'staged'); }

    if (_otaAppliedThisSession) return;   // un seul apply (= un reboot/reload) par session
    if (!(update.force === true || _otaInWindow(update.install_window))) return;   // hors fenêtre → attendre

    if (st.attempt >= _OTA_MAX_ATTEMPTS) {
      // Déjà appliqué N fois sans que la version monte (apply non effectif : mismatch prod, ou bundle
      // d'extension non mis à jour) → échec déclaré (évite la boucle reboot/reload infinie).
      otaSendStatus(st.id_deployment, 'failed', 'apply non effectif apres ' + st.attempt + ' tentative(s)');
      _otaSave(null);
      return;
    }
    st.attempt += 1; _otaSave(st);
    _otaAppliedThisSession = true;
    otaSendStatus(st.id_deployment, 'installing');
    otaApply(update);
  }

  function handleServerMessage(msg) {
    switch (msg.type) {
      case 'player:sync':
        // Offline-first (Phase B) : bascule les médias cachés sur le store local + met en
        // file les manquants, AVANT de forwarder (player.js sauvegarde alors les urls locales).
        rewriteSyncForStore(msg);
        // Responsabilités « main.js » côté bridge : rotation écran (CSS) + planification des
        // captures périodiques — appliquées TOUJOURS, même si le contenu est retenu ci-dessous.
        {
          const dc = msg.display_config || {};
          applyRotation(dc.screen_rotation);          // non-BS : rotation CSS (no-op sur BrightSign)
          if (IS_BS) bsApplyRotation(dc.screen_rotation);   // BrightSign : rotation native (sidecar + reboot)
          applyScreenshotSchedule(dc.screenshot_interval);
          _allowStreaming = dc.allow_streaming === true;   // download-then-play strict par défaut
          const bw = Number(dc.download_bandwidth_kbps);
          _bandwidthKbps = Number.isFinite(bw) && bw > 0 ? bw : 0;   // plafond débit DL (QoS Q3)
          _measureBandwidth = dc.measure_bandwidth === true;   // mesure passive du débit (sync-readiness)
          _popSignServer = dc.pop_sign === true;   // P2 : active la signature Ed25519 des preuves (rollout serveur)
          if (IS_BS) bsApplyVideoMode(dc.bs_video_mode);   // toggle 4K par-player (P2.4/P3.1)
          if (IS_BS) {
            _bsDisplayCfg = dc;                             // contrôle écran RS232 : model/address/baud/port
            // Persisté pour le boot offline (le pilote auto-power a besoin d'offline_power
            // et du type d'écran avant le premier sync serveur).
            try { localStorage.setItem('signflow_dcfg', JSON.stringify(dc || {})); } catch { /* quota */ }
          }
          if (IS_BS) {                                      // sortie audio (point AV 2/3)
            bsApplyAudioOutput(dc.audio_output);
            bsApplyAudioVolume(dc.audio_volume);
            bsApplyAudioMute(dc.audio_mute);
            bsApplyNtp(dc.ntp_server);                      // NTP du site (migr 0071, autorun v42)
            bsApplyHdmiLocalCfg(dc, msg.player_name);       // gate page locale /control (autorun v46, nom v48)
            try { if (msg.player_name) localStorage.setItem('signflow_pname', String(msg.player_name)); } catch { /* quota */ }
          }
          // OTA §XXX (slice 2) : directive jointe au sync par le serveur → machine à états commune aux
          // renderers web (BrightSign = pont autorun/reboot ; ChromeOS/extension = reload). Les players
          // Electron/Android gèrent `msg.update` dans leur main.js natif (ne passent pas par ce bridge).
          handleWebOta(msg.update);
        }
        // Barrière download-then-play STRICT : tant que le contenu du sync n'est pas ENTIÈREMENT
        // caché, on le RETIENT (player.js garde l'ancien contenu / l'idle) → jamais de lecture de
        // média partiel NI de streaming serveur (anti-écroulement BP à l'échelle). On tient MÊME si
        // le SW ne contrôle pas (encore) la page : sans ce gate sans-SW, un hard reload (Ctrl+Shift+R,
        // page non contrôlée) livrait en streaming. L'auto-reload (registerServiceWorker) récupère le
        // contrôle pour télécharger + servir le local. allow_streaming ON = livre en streaming.
        if (!syncContentReady(msg) && !_allowStreaming) {
          _pendingHold = msg;
          console.log('[store] contenu incomplet → maintien (no-stream, download-then-play strict)');
          break;
        }
        deliverSync(msg);
        break;
      case 'player:command':
        handleCommand(msg.command, msg.params || {});
        break;
      case 'player:purge_media':
        // Kill-switch (§Q5) : pas de store local en Phase A (PWA) → no-op (le serveur a déjà retiré
        // le média du sync). BrightSign (Tier 1.3) : on supprime réellement les sfc_* du média ciblé
        // sur la SD via l'autorun (mappés id_media → cache_key par _keyToMedia).
        if (IS_BS && msg.id_media != null) {
          const purgeKeys = [];
          for (const [k, id] of _keyToMedia) if (id === msg.id_media) purgeKeys.push(k);
          for (const k of purgeKeys) { _bsLocalKeys.delete(k); _keyToMedia.delete(k); }
          bsPurge(purgeKeys);
        }
        break;
      case 'token:refresh':
        // Rotation du token machine (« Option B » serveur) : token renouvelé → on le persiste
        // en localStorage. La connexion WS courante reste valide ; le nouveau token sert au
        // prochain reconnect ET aux requêtes HTTP. Aucune coupure d'écran.
        if (msg.token && typeof msg.token === 'string' && msg.token !== config.player_token) {
          config.player_token = msg.token;
          localStorage.setItem(LS_TOKEN, msg.token);
          bsPersistToken(msg.token);   // Correctif A : grave le JWT roté sur la SD (survit au wipe firmware)
          console.log('[Token] renouvelé par le serveur et persisté');
        }
        break;
      default:
        console.log('[WS] Unknown type:', msg.type);
    }
  }

  function handleCommand(command, params) {
    switch (command) {
      case 'restart':
        location.reload();
        break;
      case 'reboot_os':
        // BrightSign : vrai reboot OS via objets natifs / pont autorun.brs (RebootSystem).
        // Appliance x86 Alpine : vrai reboot OS via l'agent local (&agent=). Sinon (PWA/extension
        // managé) : repli = reload (kiosk relance ; reboot réel = policy Google).
        if (IS_BS && bsReboot()) break;
        if (kioskCmd('reboot')) break;
        location.reload();
        break;
      case 'reset_config':
        localStorage.removeItem(LS_TOKEN);
        localStorage.removeItem(LS_BACKEND);
        location.reload();
        break;
      case 'maintenance':
        emit('maintenance', params);
        break;
      case 'quit_app':
        // « Arrêt player » : pas d'app à fermer sur un kiosk (BrightSign/ChromeOS) → on STOPPE la
        // diffusion = écran noir (le renderer libère la vidéo → vide le plan vidéo HW sur BrightSign,
        // sinon le plan masquerait tout fond HTML) jusqu'au prochain « Redémarrer l'application ».
        emit('stop', params);
        break;
      case 'screenshot':
        captureAndUploadScreenshot('manual');
        break;
      case 'toggle_overlay':
        emit('overlay', { device: buildDeviceInfo() });
        break;
      case 'play_now': {
        handlePlayNowParams(params || {});
        break;
      }
      case 'detect_capabilities':
        // ChromeOS gère le décodage HW nativement (rien à détecter/poser). No-op.
        break;
      case 'display_command': {
        // Contrôle écran physique (power/input/brightness…). BrightSign :
        //  - type 'rs232'   → pont autorun → roSerialPort (trame protocole construite ici en JS) ;
        //  - type 'cec'     → bsCmd('cec_power') → autorun roCecInterface (veille/réveil TV) ;
        //  - sans contrôleur → repli « écran non pilotable » bsCmd('video_output') → autorun
        //    roVideoMode.SetPowerSaveMode (coupe/rétablit le sync HDMI, écran en veille).
        // Inerte ailleurs : un PWA ChromeOS/extension ne peut PAS couper la sortie vidéo ;
        // les players Electron gèrent display_command dans main.js (display_control.js).
        if (!IS_BS) break;
        const p = params || {};
        const dcfg = _bsDisplayCfg || {};
        const isPower = p.display_cmd === 'power_on' || p.display_cmd === 'power_off';
        // Auto-OFF du switch HDMI (VOD/override) sur TOUTE coupure écran pilotée serveur
        // (fermeture du site via auto-power, ou commande manuelle) : fin du takeover, la
        // playlist reprend au wall-clock. No-op si aucun switch actif (garde player.js).
        if (p.display_cmd === 'power_off') emit('hdmi_input', { mode: 'stop' });
        // Rallumage : ré-armer un éventuel plan HDMI monté écran éteint (mort-né, bug HW
        // 2026-07-08 — switch démarré sortie coupée → noir au power_on). Conditionnel côté
        // player.js : plan sain (frames décodées) = no-op, pas de clignotement à la
        // ré-assertion de reconnexion.
        if (p.display_cmd === 'power_on') emit('hdmi_input', { mode: 'rearm' });
        if (isPower && dcfg.type === 'cec') {
          bsCmd('cec_power', { on: p.display_cmd === 'power_on' });
        } else if (isPower && dcfg.type !== 'rs232' && dcfg.type !== 'ip') {
          bsCmd('video_output', { on: p.display_cmd === 'power_on' });
        } else if (dcfg.type === 'cec') {
          // CEC : seuls power_on/power_off (+ set_input = redevenir Active Source) ont un sens.
          if (p.display_cmd === 'set_input') bsCmd('cec_power', { on: true });
          else console.log('[BS][Display]', p.display_cmd, 'non supporté via CEC');
        } else {
          bsDisplayCommand(params);
        }
        break;
      }
      case 'hdmi_input': {
        // Entrée HDMI live (point AV 3/3) — affichage dans un <video> du renderer (player.js monte un
        // <video src="tv:brightsign.biz/hdmi">). On NE relaie PLUS à l'autorun : un roVideoPlayer séparé
        // SUR-ALLOUE le décodeur du XT4 quand le roHtmlWidget tourne (doc BrightSign "Mosaic Mode
        // over-allocated" → PlayFile=false ; PROUVÉ HW v22/v23). Le <video> réutilise le plan vidéo déjà
        // alloué. BrightSign à entrée HDMI (XT1144) only.
        if (IS_BS) {
          const hmode = (params && params.mode) === 'stop' ? 'stop' : 'start';
          // source/id_media = traçabilité de la session (vod|drawer|remote ; le média VOD permet
          // le PoP signé au switch OFF). Absents des anciens serveurs → défauts sûrs.
          emit('hdmi_input', {
            mode: hmode,
            source: (params && params.source) || 'remote',
            id_media: (params && params.id_media != null) ? params.id_media : null,
          });
        }
        break;
      }
      case 'set_timezone':
        // BrightSign : l'autorun pose le fuseau (roSystemTime.SetTimeZone) puis REBOOTE
        // (seul moyen fiable de propager la TZ au roHtmlWidget). ChromeOS/extension :
        // la TZ suit le compte/la politique Google — non pilotable depuis un PWA.
        if (IS_BS && params && params.timezone) {
          bsCmd('set_timezone', { tz: params.timezone });
        } else if (!IS_BS) {
          console.log('[TZ] set_timezone non supporté sur', SF_OS);
        }
        break;
      case 'firmware_update':
        // MAJ firmware BrightSign (P1.1) : l'autorun télécharge le .bsfw (URL signée) à la racine
        // SD puis reboote → le BOS l'applique au boot. Spécifique BrightSign → no-op ailleurs.
        if (IS_BS && params && params.url) {
          bsCmd('firmware_update', { url: params.url, version: params.version || '' });
        }
        break;
      default:
        console.log('[WS] Unknown command:', command);
    }
  }

  // Résolution physique de l'écran (capabilities.display_modes) pour la sélection de
  // rendition serveur. ChromeOS expose `screen.width/height` en pixels CSS ; le produit
  // par `devicePixelRatio` donne les pixels physiques réels (un panneau 4K « affiché en
  // 1080p » remonte screen=1920×dpr2 = 3840). Sans cette remontée, le serveur ne connaît
  // pas la définition de l'écran → il sert l'originale (4K) même à un Chromebox 1080p.
  // Format aligné sur Electron/Android : 'WxH' (le serveur parse aussi 'WxH@Hz').
  // Capacité de décodage HEVC du <video> (mémoïsée). `canPlayType('hvc1…')` renvoie
  // 'probably'/'maybe' si supporté, '' sinon. Sur ChromeOS récent avec décodeur HEVC matériel
  // → supporté ; WebView/Chrome sans HEVC → ''. Le serveur n'envoie le 4K HEVC qu'aux 'true'.
  let _hevcSupport = null;
  function canDecodeHevc() {
    if (_hevcSupport === null) {
      // BrightSign : le <video hwz="on"> décode en MATÉRIEL via le plan vidéo (HEVC 4K natif sur
      // XT1144 / Série 4+), même si le canPlayType du Chromium 87 ne l'annonce pas → on déclare le
      // HEVC (le 4K = HEVC only, cf. rendition hevc_4k). Override: __SF_BS_HEVC__===false pour un
      // modèle sans décodeur HEVC. SÛR en sortie FHD (le HEVC n'est servi qu'à une cible 2160).
      if (IS_BS) {
        _hevcSupport = !(typeof window !== 'undefined' && window.__SF_BS_HEVC__ === false);
        return _hevcSupport;
      }
      try {
        const v = document.createElement('video');
        _hevcSupport = !!(v.canPlayType('video/mp4; codecs="hvc1.1.6.L93.B0"')
                          || v.canPlayType('video/mp4; codecs="hev1.1.6.L93.B0"'));
      } catch { _hevcSupport = false; }
    }
    return _hevcSupport;
  }

  // BrightSign : "3840x2160x60p"/"1920x1080x60p" → {w,h,mode:"WxH"}. Le backend parse 'WxH'/'WxH@Hz'
  // (pas le suffixe 'x60p' de BrightSign) → on normalise. null si non parsable.
  function bsModeToWxH(mode) {
    if (!mode || typeof mode !== 'string') return null;
    const p = mode.split('x');
    if (p.length < 2) return null;
    const w = parseInt(p[0], 10), h = parseInt(p[1], 10);
    if (!w || !h) return null;
    return { w, h, mode: `${w}x${h}` };
  }

  function getDisplayInfo() {
    // BrightSign : window.screen du roHtmlWidget remonte la taille LOGIQUE du widget (souvent
    // 1080), PAS la sortie réelle → on déclare le MODE VIDÉO COURANT natif (/device.json) pour que
    // le backend serve la rendition correspondant à ce que l'écran affiche vraiment (FHD→FHD,
    // 4K→hevc_4k). Tant que /device.json n'est pas lu, on ne déclare rien (évite de figer FHD).
    if (IS_BS) {
      const m = bsModeToWxH(_bsDevice.video_mode);
      if (m) return { screen_resolution: m.mode, display_modes: [m.mode] };
      return {};
    }
    try {
      const dpr = window.devicePixelRatio || 1;
      const w = Math.round((window.screen && window.screen.width || 0) * dpr);
      const h = Math.round((window.screen && window.screen.height || 0) * dpr);
      if (w > 0 && h > 0) {
        const mode = `${w}x${h}`;
        return { screen_resolution: mode, display_modes: [mode] };
      }
    } catch {}
    return {};
  }

  // Infos device pour l'overlay de maintenance (§ diag terrain). En navigateur, MAC
  // irrécupérable et IP LAN/WAN inconnues côté page (le backend les connaît) → best-effort.
  function buildDeviceInfo() {
    return {
      id_player: decodePlayerId(config.player_token),
      hostname:  location.hostname,
      os:        _bsInfo.bs_model ? ('BrightSign ' + _bsInfo.bs_model) : (IS_BS ? 'BrightSign' : 'ChromeOS PWA'),
      version:   REPORTED_VERSION,
      ip:        null,
      mac:       null,
      wan_ip:    null,
      decode:    'chromium-native',
      lan:       { enabled: false },
    };
  }

  // ── Screenshot (vignette CMS + diag) ──────────────────────────────────────────
  // Capture l'image en cours via canvas → POST /players/{id}/screenshot (même endpoint
  // qu'Electron/Android). LIMITE : un <video> streamé en cross-origin (MinIO direct, non
  // caché) « teinte » le canvas → toBlob renvoie null (SecurityError). Servi depuis le
  // cache (SW same-origin) → capture OK. Donc sur un player qui met en cache (download-then
  // -play), les vignettes apparaissent dès que le média est caché. Web/PDF non capturés.
  let _screenshotTimer = null;
  let _screenshotIntervalSec = null;   // intervalle actif du timer en cours (garde anti-reset)
  async function captureAndUploadScreenshot(requestId) {
    const id = decodePlayerId(config.player_token);
    if (!id || !config.backend_url) return;
    // BrightSign : la capture canvas est NOIRE (le <video hwz> est sur le plan vidéo HW, hors canvas)
    // → on délègue à l'autorun, qui capture le framebuffer COMPOSITE via le snapshot DWS (LDWS) puis
    // l'upload en natif. Couvre le bouton manuel ET la planification périodique. cf. PARITY_PLAN §2.0.
    if (IS_BS) { bsCmd('screenshot', { id_player: String(id) }); return; }
    try {
      // Multi-zones (§25.4) : #content-area contient plusieurs .mz-zone → composer TOUTES les zones
      // (sinon le capteur mono-vidéo ci-dessous ne verrait que la zone Main et raterait la Sidebar).
      let blob = await _thumbFromMultiZone();
      if (!blob) {
        const vid = document.querySelector('#content-area video');
        const img = document.querySelector('#content-area img');
        if (vid && vid.videoWidth)        blob = await _thumbFromElement(vid, vid.videoWidth, vid.videoHeight);
        else if (img && img.naturalWidth) blob = await _thumbFromElement(img, img.naturalWidth, img.naturalHeight);
      }
      // Rien de pixel-capturable (écran de repli « No content to display », ou page web/PDF en
      // iframe cross-origin) : on envoie QUAND MÊME une vignette d'ÉTAT synthétique. Indispensable
      // pour la maintenance proactive — un player « rien à diffuser » doit rester visible et daté
      // côté CMS (sinon le screenshot s'arrête et le player a l'air mort).
      if (!blob) blob = await _statusThumb();
      if (!blob) { console.log('[Screenshot] rien à capturer → saute'); return; }
      const r = await fetch(`${config.backend_url}/api/v1/players/${id}/screenshot`, {
        method: 'POST',
        headers: { 'Content-Type': 'image/png', 'Authorization': `Bearer ${config.player_token}` },
        body: blob,
      });
      console.log(`[Screenshot] upload ${blob.size}o (${requestId}) → ${r.status}`);
    } catch (e) { console.warn('[Screenshot]', e.message); }
  }

  // Vignette d'un élément <video>/<img> capturable (bornée à 1280 de large). Renvoie un Blob PNG,
  // ou null si le canvas est « teinté » (média cross-origin non caché → SecurityError sur toBlob).
  function _thumbFromElement(src, w, h) {
    const scale = w > 1280 ? 1280 / w : 1;
    const cw = Math.max(1, Math.round(w * scale)), ch = Math.max(1, Math.round(h * scale));
    const canvas = document.createElement('canvas');
    canvas.width = cw; canvas.height = ch;
    try { canvas.getContext('2d').drawImage(src, 0, 0, cw, ch); } catch { return Promise.resolve(null); }
    return new Promise((res) => { try { canvas.toBlob(res, 'image/png'); } catch { res(null); } });
  }

  // Composite multi-zones (§25.4) : redessine chaque .mz-zone à sa position écran. Vidéo/image
  // dessinées telles quelles (object-fit:contain) ; feed/url/autre = fond + titres en texte (le
  // HTML ne se rastérise pas en canvas dans une PWA). Renvoie null si <2 zones (→ chemin mono),
  // ou si le canvas est teinté (vidéo cross-origin non cachée → toBlob null → repli vignette d'état).
  function _thumbFromMultiZone() {
    const area = document.getElementById('content-area');
    const zones = area ? area.querySelectorAll(':scope > .mz-zone') : [];
    if (!area || zones.length < 2) return Promise.resolve(null);
    const aw = area.clientWidth || 1920, ah = area.clientHeight || 1080;
    const scale = aw > 1280 ? 1280 / aw : 1;
    const W = Math.max(1, Math.round(aw * scale)), H = Math.max(1, Math.round(ah * scale));
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
    const ar = area.getBoundingClientRect();
    const TITLE_SEL = '.feed-video-title,.feed-card-title,.feed-grid-title,.feed-cl-title,' +
                      '.feed-full-title,.feed-split-title,.feed-tk-item';
    zones.forEach((z) => {
      const r = z.getBoundingClientRect();
      const zx = (r.left - ar.left) * scale, zy = (r.top - ar.top) * scale;
      const zw = r.width * scale, zh = r.height * scale;
      ctx.save();
      ctx.beginPath(); ctx.rect(zx, zy, zw, zh); ctx.clip();
      ctx.fillStyle = '#0f1117'; ctx.fillRect(zx, zy, zw, zh);
      const vid = z.querySelector('video'), im = z.querySelector('img');
      try {
        if (vid && vid.videoWidth) {
          const s = Math.min(zw / vid.videoWidth, zh / vid.videoHeight);
          const dw = vid.videoWidth * s, dh = vid.videoHeight * s;
          ctx.drawImage(vid, zx + (zw - dw) / 2, zy + (zh - dh) / 2, dw, dh);
        } else if (im && im.naturalWidth) {
          const s = Math.min(zw / im.naturalWidth, zh / im.naturalHeight);
          const dw = im.naturalWidth * s, dh = im.naturalHeight * s;
          ctx.drawImage(im, zx + (zw - dw) / 2, zy + (zh - dh) / 2, dw, dh);
        } else {
          // feed/url/autre : titres visibles de la zone (preuve de contenu, à défaut du rendu HTML)
          const titles = z.querySelectorAll(TITLE_SEL);
          const fs = Math.max(10, Math.round(zh * 0.045));
          const lh = Math.round(fs * 1.5);
          ctx.fillStyle = '#E8EAED'; ctx.textAlign = 'left';
          ctx.font = `600 ${fs}px Inter, Arial, sans-serif`;
          let ty = zy + lh;
          for (let i = 0; i < titles.length && ty < zy + zh - 4; i++) {
            ctx.fillText((titles[i].textContent || '').slice(0, 38), zx + 6, ty);
            ty += lh;
          }
        }
      } catch (e) { /* zone teintée (cross-origin non caché) → laissée en fond */ }
      ctx.restore();
    });
    return new Promise((res) => { try { canvas.toBlob(res, 'image/png'); } catch { res(null); } });
  }

  // Vignette d'ÉTAT synthétique (idle / écran de repli / contenu non capturable) : fond design +
  // logo + message de repli courant + horodatage UTC → preuve de vie datée pour la maintenance.
  function _statusThumb() {
    const fb = document.getElementById('fallback-screen');
    const idle = fb && !fb.classList.contains('hidden');
    const msgEl = document.getElementById('fallback-msg');
    const msg = idle ? ((msgEl && msgEl.textContent) || 'No content to display')
                     : 'Live content (not capturable)';
    const W = 640, H = 360;
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#1C1E2A'; ctx.fillRect(0, 0, W, H);
    ctx.textAlign = 'center';
    ctx.fillStyle = '#4875B4';
    ctx.font = 'bold 30px Inter, Arial, sans-serif';
    ctx.fillText('SignFlow', W / 2, H / 2 - 26);
    ctx.fillStyle = '#E8EAED';
    ctx.font = '18px Inter, Arial, sans-serif';
    String(msg).split('\n').forEach((line, i) => ctx.fillText(line, W / 2, H / 2 + 12 + i * 24));
    ctx.fillStyle = '#9AA0A6';
    ctx.font = '12px Inter, Arial, sans-serif';
    ctx.fillText(new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC', W / 2, H - 16);
    return new Promise((res) => { try { canvas.toBlob(res, 'image/png'); } catch { res(null); } });
  }

  // Planification périodique (display_config.screenshot_interval en SECONDES ; <60 ou 0 = off,
  // absent = défaut 1h comme Electron). NE RIEN relancer si l'intervalle est inchangé : sinon
  // chaque player:sync (heartbeat, force_sync, events) remettrait le timer à zéro et la capture
  // périodique n'arriverait JAMAIS à échéance (bug constaté : 15 min réglés, jamais déclenché).
  function applyScreenshotSchedule(intervalSec) {
    const sec = (intervalSec === undefined || intervalSec === null) ? 3600 : Number(intervalSec);
    const effective = (!sec || sec < 60) ? 0 : sec;
    if (effective === _screenshotIntervalSec) return;
    _screenshotIntervalSec = effective;
    if (_screenshotTimer) { clearInterval(_screenshotTimer); _screenshotTimer = null; }
    if (!effective) return;
    _screenshotTimer = setInterval(() => captureAndUploadScreenshot('periodic'), effective * 1000);
    console.log(`[Screenshot] périodique toutes les ${effective}s`);
  }

  // ── Rotation écran (CSS) ──────────────────────────────────────────────────────
  // Le navigateur ne peut pas tourner la sortie HDMI de l'OS → on tourne la VUE
  // #player-root (miroir EXACT de la rotation CSS Windows/AOpen). display_config.screen_rotation
  // = chaîne xrandr 'normal'|'left'|'right'|'inverted' (PAS des degrés) → left=90, right=270,
  // inverted=180. 90/270 : permute les dimensions (100vh×100vw) + recentre avant de tourner →
  // le canvas portrait remplit l'écran paysage. Réappliquée à chaque sync (idempotent).
  let _appliedRotation = null;
  // BrightSign : rotation NATIVE (roHtmlWidget transform), pas CSS. Le transform CSS ne tourne que la
  // couche HTML, pas le plan video HW (<video hwz>) -> rotation cassee. Mappe screen_rotation
  // (normal/left/right/inverted, meme convention que les autres players) vers le transform BrightSign et
  // demande a l'autorun de le poser (sidecar + reboot) SI different de la rotation courante (anti-boucle
  // via _bsDevice.rotation). ⚠️ sens rot90=horaire A CONFIRMER visuellement (on inverse le mapping sinon).
  let _bsRotationReq = null;
  function bsApplyRotation(rotation) {
    if (!IS_BS) return;
    const cur = _bsDevice.rotation;
    if (!cur) return;                                  // /device.json pas encore lu -> on reessaiera au prochain sync
    // 90° (left/right) -> rot90/rot270 : le plan vidéo HW tourne (validé HW snapshot). 180° (inverted) :
    // BrightSign n'honore PAS rot180 sur le plan vidéo (validé HW : vidéo reste à l'endroit ; seule la
    // couche HTML tournerait = demi-rotation moche sur contenu mixte) -> NEUTRALISÉ en identity (paysage).
    // Le 180 (montage paysage à l'envers) reste non supporté sur BrightSign. cf. project-brightsign.
    const map = { normal: 'identity', left: 'rot90', right: 'rot270', inverted: 'identity' };
    const target = map[rotation || 'normal'] || 'identity';
    if (target === cur) { _bsRotationReq = null; return; }   // deja bonne rotation (anti-boucle)
    if (_bsRotationReq === target) return;             // changement deja demande -> pas de spam reboot
    _bsRotationReq = target;
    console.log('[BS] screen_rotation', rotation, '->', target, '(courant', cur + ') -> set_rotation + reboot');
    bsCmd('set_rotation', { transform: target });      // l'autorun ecrit le sidecar + reboote
  }

  function applyRotation(rotation) {
    if (IS_BS) return;   // BrightSign : rotation native via bsApplyRotation (le CSS ne tourne pas le plan video HW)
    const rot = rotation || 'normal';
    if (rot === _appliedRotation) return;
    _appliedRotation = rot;
    const root = document.getElementById('player-root');
    if (!root) return;
    console.log('[Rotation] contenu', rot);
    const s = root.style;
    s.position = s.top = s.left = s.width = s.height = s.transformOrigin = s.transform = '';
    if (rot === 'left' || rot === 'right') {
      s.position = 'absolute'; s.top = '50%'; s.left = '50%';
      s.width = '100vh'; s.height = '100vw'; s.transformOrigin = 'center center';
      s.transform = `translate(-50%, -50%) rotate(${rot === 'left' ? 90 : 270}deg)`;
    } else if (rot === 'inverted') {
      s.transform = 'rotate(180deg)';
    }
  }

  // ── Heartbeat applicatif (player:status) ──────────────────────────────────────
  // Le `ws.ping()` natif n'existe pas en navigateur ; le message applicatif player:status
  // suffit comme liveness (le backend rafraîchit last_seen_at + status online dessus).
  function startHeartbeat() {
    stopHeartbeat();
    heartbeatTimer = setInterval(() => {
      refreshDiskRatio();   // fire-and-forget → le prochain heartbeat porte un ratio frais
      bsRefreshInfo();      // BrightSign : rafraîchit model/serial/temp/cpu/mem (no-op ailleurs)
      bsFetchStats();       // BrightSign : CPU/RAM réels via /mem.json (fire-and-forget, no-op ailleurs)
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({
            type: 'player:status',
            status: 'online',
            player_version: REPORTED_VERSION,
            // BrightSign : vraie IP LAN + MAC natives (/device.json) — le serveur ne met à jour
            // que si présent (null ailleurs = PWA, l'IP LAN navigateur étant masquée).
            ip_address:  _bsDevice.ip  || null,
            mac_address: _bsDevice.mac || null,
            // BrightSign : charge CPU réelle (load1/ncpu en %, autorun v49 via LDWS) ; indisponible
            // en PWA/extension (null → le CMS n'affiche rien, comme avant).
            cpu: (IS_BS && typeof _bsStats.cpu === 'number') ? _bsStats.cpu : null,
            // BrightSign : % RAM UTILISÉE réel (/mem.json). Ailleurs, repli historique
            // navigator.deviceMemory (Go totaux, grossier) — cpu/disk système indisponibles en PWA.
            // LAN IP/MAC = irrécupérables (le navigateur masque l'IP locale ; WAN déduite serveur).
            ram: IS_BS ? (typeof _bsStats.ram === 'number' ? _bsStats.ram : null)
              : typeof navigator.deviceMemory === 'number' ? navigator.deviceMemory : null,
            capabilities: {
              hw_decode: 'chromium-native', platform: SF_OS,
              // Fuseau horaire OS réel (drawer CMS : mismatch vs site — le pilote offline
              // BrightSign compare ses fenêtres locales à CETTE horloge).
              timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              // Le <video> de CE Chrome décode-t-il le HEVC en HW ? (ChromeOS récent à
              // décodeur HEVC matériel = oui ; HD1024/BrightSign HEVC HW = oui s'il le déclare).
              // Le serveur s'en sert pour servir le 4K HEVC au lieu de rétrograder en FHD H.264
              // (cf. _player_video_can_hevc).
              video_can_hevc: canDecodeHevc(),
              ...getDisplayInfo(),
              store: getStoreStatus(),
              ..._bsInfo,   // BrightSign : model/serial/osversion/temperature/cpu/mem (vide ailleurs)
            },
          }));
        } catch (e) { /* close suivra */ }
      }
    }, HEARTBEAT_MS);
  }
  function stopHeartbeat() { if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; } }

  // File d'événements sortants (player → serveur), ex. alerte url_display inaccessible (§XXV.2).
  // Envoi immédiat si le WS est ouvert, sinon file bornée rejouée à la reconnexion (flushEventQueue).
  function reportPlayerEvent(ev) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: 'player:event', ...ev })); return; } catch (e) { /* close suivra */ }
    }
    _eventQueue.push(ev);
    if (_eventQueue.length > 100) _eventQueue.shift();
  }
  function flushEventQueue() {
    const q = _eventQueue.splice(0);
    for (const ev of q) reportPlayerEvent(ev);
  }

  // ── Proof of Play (§XXIV) — file PERSISTÉE (localStorage) + flush /pop/batch ──
  // Le bridge ChromeOS n'a pas de process Node : la file vit en localStorage (survit reload/
  // boot-à-froid offline) et le flush se fait en fetch direct, comme l'upload screenshot.
  const LS_POP = 'signflow_pop_queue';
  const POP_QUEUE_MAX = 5000, POP_BATCH_MAX = 200, POP_FLUSH_INTERVAL = 60000;
  let _popQueue = [];
  let _popFlushing = false;
  function loadPopQueue() {
    try { const a = JSON.parse(localStorage.getItem(LS_POP) || '[]'); _popQueue = Array.isArray(a) ? a : []; }
    catch { _popQueue = []; }
  }
  function persistPopQueue() {
    try { localStorage.setItem(LS_POP, JSON.stringify(_popQueue)); } catch (e) { /* quota plein → on garde en RAM */ }
  }

  // ── PoP — signature device Ed25519 (P2, Tier 1.2) — GATE OFF par défaut ──────
  // Le backend REJETTE TOUT le lot si une seule signature est invalide → on n'active la
  // signature qu'APRÈS preuve (/pop/verify côté CMS). Activation : display_config.pop_sign=true
  // (poussé serveur → rollout par player, le chemin prod) OU localStorage 'sf_pop_sign'='1'
  // (test device rapide via la console de l'inspector). La clé privée = seed 32o persistée en
  // localStorage (sur SD via storage_path en BrightSign) → ne quitte JAMAIS l'appareil. Le seed
  // sert UNIQUEMENT à signer le message canonique (identique au serveur). Chromium 87 OK : noble
  // (BigInt) + sha512Async/randomBytes via WebCrypto. TOFU : le serveur fixe la clé publique au 1er lot.
  const LS_POP_SEED = 'signflow_pop_seed';
  let _popSignServer = false;        // poussé par display_config.pop_sign
  let _popSeed = null;               // Uint8Array(32) — clé privée (seed)
  let _popPubPem = null;             // clé publique SPKI PEM (envoyée au serveur)
  let _popKeyReady = false;
  function popSignEnabled() {
    if (!window.SFEd25519) return false;
    if (_popSignServer) return true;
    try { return localStorage.getItem('sf_pop_sign') === '1'; } catch { return false; }
  }
  function _hexToBytes(h) { const a = new Uint8Array(h.length / 2); for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; }
  function _bytesToHex(u8) { let s = ''; for (let i = 0; i < u8.length; i++) s += u8[i].toString(16).padStart(2, '0'); return s; }
  function _bytesToB64(u8) { let s = ''; for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]); return btoa(s); }
  function _rawPubToSpkiPem(raw32) {
    // SPKI DER Ed25519 = 12 octets de préfixe fixe + 32 octets de clé brute (RFC 8410).
    const prefix = Uint8Array.from([0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00]);
    const der = new Uint8Array(prefix.length + raw32.length);
    der.set(prefix, 0); der.set(raw32, prefix.length);
    const b64 = _bytesToB64(der).match(/.{1,64}/g).join('\n');
    return '-----BEGIN PUBLIC KEY-----\n' + b64 + '\n-----END PUBLIC KEY-----\n';
  }
  async function ensurePopKey() {
    if (_popKeyReady) return true;
    if (!window.SFEd25519) return false;
    try {
      let hex = null;
      try { hex = localStorage.getItem(LS_POP_SEED); } catch {}
      if (hex && hex.length === 64) {
        _popSeed = _hexToBytes(hex);
      } else {
        _popSeed = window.SFEd25519.utils.randomPrivateKey();
        try { localStorage.setItem(LS_POP_SEED, _bytesToHex(_popSeed)); } catch {}
        console.log('[PoP] clé device Ed25519 générée');
      }
      _popPubPem = _rawPubToSpkiPem(await window.SFEd25519.getPublicKeyAsync(_popSeed));
      _popKeyReady = true;
      return true;
    } catch (e) { console.error('[PoP] keygen échouée:', e && e.message); return false; }
  }
  // Signature base64 d'une preuve — message canonique IDENTIQUE au serveur (played_at en ms epoch).
  async function _signPopEntry(o) {
    if (!_popKeyReady) return null;
    const idP = decodePlayerId(config.player_token);
    if (idP == null) return null;
    try {
      const ms = Date.parse(o.played_at) || Date.now();
      const msg = `${idP}|${o.id_media != null ? o.id_media : ''}|${o.id_playlist != null ? o.id_playlist : ''}|${ms}|${o.duration_ms}`;
      const sig = await window.SFEd25519.signAsync(new TextEncoder().encode(msg), _popSeed);
      return _bytesToB64(sig);
    } catch { return null; }
  }

  function recordPlay(entry) {
    if (!entry || typeof entry !== 'object') return;
    if (entry.id_media == null && entry.id_playlist == null) return;
    _popQueue.push({
      id_media: entry.id_media != null ? entry.id_media : null,
      id_playlist: entry.id_playlist != null ? entry.id_playlist : null,
      duration_ms: Math.max(0, Math.round(entry.duration_ms || 0)),
      played_at: entry.played_at || new Date().toISOString(),
    });
    if (_popQueue.length > POP_QUEUE_MAX) _popQueue.splice(0, _popQueue.length - POP_QUEUE_MAX);
    persistPopQueue();
  }
  async function flushPopQueue() {
    if (_popFlushing || !_popQueue.length) return;
    if (!config.backend_url || !config.player_token) return;
    if (config.player_token.startsWith('sfp_')) return;  // token de provisioning
    _popFlushing = true;
    try {
      const batch = _popQueue.slice(0, POP_BATCH_MAX);
      const body = { logs: batch };
      // P2 (Tier 1.2) : si la signature est activée, on signe les preuves non encore signées du
      // lot (les objets sont des références à la file → la signature est persistée, survit au
      // reload/offline et n'est pas recalculée) + on joint la clé publique (TOFU).
      if (popSignEnabled() && await ensurePopKey()) {
        let signedAny = false;
        for (const o of batch) {
          if (!o.signature) { const s = await _signPopEntry(o); if (s) { o.signature = s; signedAny = true; } }
        }
        if (signedAny) persistPopQueue();
        body.pop_public_key = _popPubPem;
      }
      const res = await fetch(`${config.backend_url}/api/v1/pop/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${config.player_token}` },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        _popQueue.splice(0, batch.length);
        persistPopQueue();
        console.log(`[PoP] ${batch.length} preuve(s) envoyée(s), ${_popQueue.length} en attente`);
      } else {
        console.log(`[PoP] flush refusé (HTTP ${res.status}) — ${_popQueue.length} en attente`);
      }
    } catch (e) {
      // hors-ligne → on garde la file pour le prochain tick
    } finally {
      _popFlushing = false;
    }
  }

  function startWatchdog() {
    stopWatchdog();
    watchdogTimer = setInterval(() => {
      // Ne surveille qu'une connexion OUVERTE silencieuse (zombie). dropAndReconnect arrête
      // le watchdog, nettoie le ws (onclose annulé) et reprogramme lui-même la reconnexion →
      // pas de double-onclose, pas de watchdog qui tourne pendant les tentatives de reconnexion.
      if (Date.now() - lastMsgAt > WATCHDOG_TIMEOUT_MS) dropAndReconnect('watchdog-silence');
    }, 15000);
  }

  // ── Contrat window.signflow (identique au preload Electron) ────────────────────
  window.signflow = {
    onSync:          (cb) => on('sync', cb),
    onConnected:     (cb) => on('connected', cb),
    onDisconnected:  (cb) => on('disconnected', cb),
    onMaintenance:   (cb) => on('maintenance', cb),
    onStop:          (cb) => on('stop', cb),
    onSetupRequired: (cb) => on('setup-required', cb),
    // LAN sync : pas de socket UDP en PWA → jamais émis (les cb sont stockés sans effet).
    onLanAdjust:     (cb) => on('lan-adjust', cb),
    onLanSwitch:     (cb) => on('lan-switch', cb),
    onLanRelease:    (cb) => on('lan-release', cb),
    reportPlaybackPos: (st) => {
      // BrightSign Phase 2b : POST l'etat au serveur autorun -> il diffuse sync_announce (+ relaie notre
      // sync_play si lan_sync_master). Slave : sert juste a informer l'autorun de notre id/groupe (announce
      // + filtre de groupe). Ailleurs (PWA/extension) : no-op (pas d'autorun local). Fire-and-forget.
      if (!IS_BS || !_bsLanEnabled || !st) return;
      const id = decodePlayerId(config.player_token);
      if (!id) return;
      // FAILOVER (item 1) : on envoie TOUJOURS notre position (play), meme en slave. L'autorun ne la
      // DIFFUSE que si on est le maitre EFFECTIF -> si le maitre designe meurt, un slave survivant est
      // promu par l'autorun et se met a diffuser SA position sans changement cote renderer. La priorite
      // du sync_play = priorite DESIGNEE (1 si lan_sync_master, 0 sinon) pour l'election des recepteurs.
      let play = null;
      if (st.id_playlist) {
        // sync_play construit en JS (precision pleine sur switch_at/sent_at) -> l'autorun le relaie BRUT
        // (0 re-serialisation FormatJson). Meme forme que sync_lan.js _sendSync (le slave sait deja le lire).
        play = JSON.stringify({
          type: 'sync_play', group: _bsLanGroup, id_player: id, priority: (_bsLanMaster ? 1 : 0),
          id_playlist: st.id_playlist, start_index: st.currentIndex,
          start_offset_ms: Math.round(st.offsetMs || 0),
          switch_at: st.switchAt || null, next_index: (st.nextIndex != null ? st.nextIndex : null),
          sent_at: Date.now(),
        });
      }
      fetch(`${LOCAL_BASE}/queue`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lan_report: { id, group: _bsLanGroup, master: _bsLanMaster, play } }),
      }).catch(() => {});
    },
    requestResync:   () => {
      // URL média expirée → forcer un sync frais en reconnectant (le backend renvoie un
      // player:sync à la connexion). Debounced côté player.js (30s).
      console.log('[WS] requestResync → reconnect');
      try { ws && ws.close(); } catch {}
    },
    saveWizard:      (cfg) => {
      // Écran de setup (fallback navigateur, hors kiosk) : persiste backend+token et connecte.
      if (cfg && cfg.backend_url) localStorage.setItem(LS_BACKEND, cfg.backend_url.replace(/\/+$/, ''));
      if (cfg && cfg.player_token) localStorage.setItem(LS_TOKEN, cfg.player_token);
      config = { backend_url: localStorage.getItem(LS_BACKEND) || '', player_token: localStorage.getItem(LS_TOKEN) || '' };
      reconnectAttempts = 0;
      connect();
      return Promise.resolve(true);
    },
    // Store Control Panel (§19.3) = Phase C (médié backend) → cb stockés, non câblés.
    onControlApply:    (cb) => on('control-apply', cb),
    sendControlStatus: () => { /* no-op Phase A */ },
    onAudioRestart:    (cb) => on('audio-restart', cb),
    // Offline cache = Phase B → jamais émis.
    onStoreUpdate:     (cb) => on('store-update', cb),
    // Overlay de maintenance — pleinement supporté (déclenché par player:command).
    onOverlay:         (cb) => on('overlay', cb),
    onHdmiInput:       (cb) => on('hdmi_input', cb),
    // v44 : statut AUTORITAIRE de l'entrée HDMI (autorun /hdmiin.json — hotplug HW, modèles à
    // entrée only). null = indisponible (autorun < v44, modèle sans entrée, non-BS) → le renderer
    // retombe sur son heuristique frames/videoWidth (dégradé : perte en cours d'item mal vue).
    hdmiInputStatus:   async () => {
      if (!IS_BS) return null;
      try {
        const r = await fetch(`${LOCAL_BASE}/hdmiin.json`, { cache: 'no-store' });
        if (!r.ok) return null;
        return await r.json();
      } catch (e) { return null; }
    },
    // VOD à la demande (Feature B) : lecture ad-hoc takeover par-dessus la programmation.
    onPlayNow:         (cb) => on('play_now', cb),
    // Alerte sortante (ex. url_display inaccessible §XXV.2) → serveur (ou file si offline).
    reportEvent:       (ev) => reportPlayerEvent(ev),
    // Proof of Play (§XXIV) : lecture remontée par player.js → file persistée + flush différé.
    reportPlay:        (e) => recordPlay(e),
    // PAS de `mpv` : _hasMpv=false dans player.js → vidéo via <video> Chromium (HW natif ChromeOS).
  };

  // ── Boot ───────────────────────────────────────────────────────────────────
  // App shell offline + index des médias cachés (avant le 1er sync pour réécrire les urls).
  registerServiceWorker();
  loadCachedKeys();
  startBsLocalCache();                                // BrightSign : poll du serveur de cache local
  loadPopQueue();                                     // Proof of Play : reprend la file persistée
  setInterval(flushPopQueue, POP_FLUSH_INTERVAL);     // flush périodique best-effort (offline-first)

  // player.js s'attend à recevoir setup-required/connected APRÈS s'être abonné. On laisse
  // le thread courant finir (player.js s'exécute après ce script) avant de connecter.
  setTimeout(() => {
    // backend_url se résout à location.origin dans connect() si absent → on ne déclenche
    // le setup que si le TOKEN manque vraiment (le reste est déductible de l'origine).
    if (!config.player_token) emit('setup-required');
    else connect();
  }, 0);

  // Retour réseau : reconnexion IMMÉDIATE (sans attendre le backoff). C'est le signal le plus
  // fiable du navigateur quand le LAN/WiFi revient (cas : débrancher puis rebrancher le câble) →
  // évite de rester bloqué en "Reconnecting" si le ws de reprise était encore en backoff/CONNECTING.
  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('online', () => {
      if (connected) return;
      console.log('[WS] réseau revenu (online) — reconnexion immédiate');
      reconnectAttempts = 0;
      connect();   // connect() nettoie l'ancien ws + repart proprement
    });
  }

  // ── Filet de sécurité : reconnexion après une indispo SERVEUR prolongée ───────
  // Le handler 'online' ci-dessus ne couvre PAS le cas le plus courant en signage :
  // le LAN/WiFi ne tombe jamais, c'est le SERVEUR qui est down (redémarrage, coupure,
  // panne longue). 'online' ne se déclenche alors pas au retour du serveur → la reprise
  // repose uniquement sur le backoff (setTimeout), que ChromeOS GÈLE/throttle quand l'écran
  // s'éteint ou que l'appareil dort des heures → le player reste figé jusqu'à un Ctrl+R.
  // On ajoute donc deux filets indépendants des timers de backoff :
  //  (a) retour de visibilité (réveil écran/onglet) → reconnexion immédiate ;
  //  (b) un superviseur périodique qui détecte un saut d'horloge (= sortie de veille,
  //      timers gelés) ou un socket mort, et garantit une nouvelle tentative.
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && !connected) {
        console.log('[WS] visibilité revenue — reconnexion immédiate');
        reconnectAttempts = 0;
        connect();
      }
    });
  }

  let _superviseLast = Date.now();
  const SUPERVISE_MS = 30000;
  setInterval(() => {
    const now = Date.now();
    const gap = now - _superviseLast;
    _superviseLast = now;
    if (connected) return;
    // Un socket CONNECTING/OPEN en vol est laissé tranquille (connectTimer le surveille déjà).
    const inFlight = ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN);
    if (inFlight) return;
    // gap >> intervalle ⇒ l'appareil sortait de veille (timers gelés) → les timers de
    // reconnexion en vol ne sont plus fiables. Sinon, ws absent/fermé = on est en backoff
    // throttlé → on garantit une tentative au plus tard toutes les SUPERVISE_MS.
    const resumedFromSleep = gap > SUPERVISE_MS * 2;
    console.log(`[WS] superviseur — lien inactif (gap=${gap}ms, sleep=${resumedFromSleep}) → reconnexion`);
    reconnectAttempts = 0;
    connect();
  }, SUPERVISE_MS);

  // Débloque l'autoplay audio (AudioContext suspendu tant qu'aucun geste). En kiosk managé,
  // activer la policy "Autoriser la lecture automatique" (Google Admin) évite ce besoin ;
  // sinon un seul tap/clic suffit à démarrer l'audio in-store.
  const unlock = () => {
    try { window.signflowAudio && window.signflowAudio.ctx && window.signflowAudio.ctx.resume(); } catch {}
    window.removeEventListener('pointerdown', unlock);
    window.removeEventListener('keydown', unlock);
  };
  window.addEventListener('pointerdown', unlock);
  window.addEventListener('keydown', unlock);

  // ── Masquage actif du curseur (kiosk) ─────────────────────────────────────────
  // `cursor:none` (CSS) masque le curseur, MAIS Chrome ne ré-évalue le curseur système qu'au
  // prochain MOUVEMENT de souris (limite Chromium) → un curseur immobile que Chrome a réaffiché
  // (ex. après un Ctrl+R) reste visible tant qu'on ne bouge pas la souris. On gère donc
  // activement : masqué au boot + ré-affiché au mouvement + re-masqué après 2 s d'inactivité.
  // NB : en PLEIN ÉCRAN réel (PWA installée `display:fullscreen` ou F11), Chrome masque le
  // curseur nativement après inactivité — c'est le mode recommandé en prod.
  (function cursorAutoHide() {
    let t = null;
    const hide = () => { document.body.style.cursor = 'none'; };
    window.addEventListener('mousemove', () => {
      document.body.style.cursor = 'default';   // visible le temps du mouvement
      clearTimeout(t);
      t = setTimeout(hide, 2000);
    }, { passive: true });
    hide();   // masqué d'emblée (utile au boot / reload en plein écran)
  })();
})();
