'use strict';

function log(msg) {
  const ts = new Date().toTimeString().slice(0, 8);
  console.log(`[${ts}] ${msg}`);
}

const contentArea    = document.getElementById('content-area');
const fallbackScreen = document.getElementById('fallback-screen');
const fallbackMsg    = document.getElementById('fallback-msg');
const fallbackLogo   = document.querySelector('.fallback-logo');
const statusBar      = document.getElementById('status-bar');
const statusDot      = document.getElementById('status-dot');
const statusText     = document.getElementById('status-text');

let playlist          = null;
let currentIndex      = 0;
let itemTimer         = null;
// Event « joue une fois » (payload.play_once) : en fin de liste on tient la derniere
// image au lieu de reboucler, et on demande une synchro fraiche. Sans ce drapeau le
// player relancait la video d'un event play-once avant que le serveur ne la coupe.
let _playOnce         = false;
let _currentContentFP = null;
let _pendingSync      = null;  // payload queued for graceful switch at next item boundary
let _activeVideo      = null;  // <video> en cours (pour LAN sync playbackRate)
let _nextPreload      = null;  // { index, el } prochain média préchargé (#2 LAN sync precache)
let _preloadArea      = null;  // conteneur caché pour le double-buffer
let _currentSwitchAt  = null;  // instant absolu (ms) de la prochaine bascule (#2b)
let _currentNextIndex = 0;     // index de l'item suivant (#2b)
let _rateResetTimer   = null;  // timer de retour a playbackRate 1.0
let _currentPlaylistId = null; // clé synthétique LAN (id_playlist ?? -id_event) — report de position LAN
let _popPlaylistId    = null;  // VRAI id_playlist en cours (null pour event mono-média) — Proof of Play
let _lastResyncAt     = 0;     // anti-boucle : derniere demande de re-sync (URLs expirees)
let _connected        = true;  // etat connexion backend (offline = ne pas demander de resync)
let _contentMuted     = false; // son des contenus standards coupé (display_config.content_sound)
let _subtitleLang        = null;   // langue sous-titres préférée (display_config.subtitle_lang, §7)
let _subtitleFallback    = 'none'; // 'none' | 'default' si la langue absente
let _subtitleDefaultLang = null;   // langue de repli si fallback='default'
let _fallback         = null;  // config de repli serveur (§17.5) : { video_message, video_config, audio }
let _lastSync         = null;  // dernier payload player:sync (overlay de maintenance)
let _audioBaskets     = [];    // paniers audio courants (réf partagée avec audio_player) → patch offline
let _urlRefreshTimer  = null;  // intervalle de rafraîchissement d'un url_display (§XXV.2)
let _feedTimer        = null;  // intervalle d'avance d'un feed_display carrousel (§XXV.3)
const WEB_LOAD_TIMEOUT_MS = 8000;  // page web/HTML : si pas chargée sous ce délai → sauter (inaccessible)
let _blockedMedia     = new Set();  // ids média en quarantaine (§ Q5) — jamais diffusés
let _lanHeld          = null;  // payload retenu par la barrière de sync LAN (Q1)
let _audioSinkRole    = 'auto';// sortie audio physique demandée (auto|hdmi|jack|usb)
let _audioSinkId      = '';    // deviceId résolu (setSinkId) — '' = sortie par défaut OS

// Routage audio physique (Windows §XIX) : résout un rôle de sortie (hdmi/jack/usb) vers
// un deviceId réel via enumerateDevices(), puis applique setSinkId au contenu (<video>) ET
// au runtime des paniers (AudioContext). Le matching se fait sur le LABEL du périphérique
// (heuristique par mots-clés) — les labels exacts dépendent de la carte son de la box, d'où
// le log de tous les périphériques + du choix pour diagnostic/ajustement terrain.
// 'auto' → deviceId '' (sortie par défaut Windows). setSinkId est dispo en Electron 30
// (Chromium 124) pour HTMLMediaElement ET AudioContext.
const _SINK_MATCH = {
  hdmi: /hdmi|display\s*audio|digital\s*display|nvidia/i,
  jack: /speaker|realtek|headphone|analog|high\s*definition\s*audio/i,
  usb:  /usb/i,
};
async function applyAudioSink(role) {
  role = role || 'auto';
  _audioSinkRole = role;
  let deviceId = '';
  try {
    if (role !== 'auto' && navigator.mediaDevices?.enumerateDevices) {
      const devs = (await navigator.mediaDevices.enumerateDevices())
        .filter((d) => d.kind === 'audiooutput' && d.deviceId !== 'default' && d.deviceId !== 'communications');
      log(`[AudioSink] outputs: ${devs.map((d) => d.label || '(no-label)').join(' | ') || '(aucun/labels masqués)'}`);
      const re = _SINK_MATCH[role];
      const hit = re && devs.find((d) => re.test(d.label || ''));
      if (hit) deviceId = hit.deviceId;
      else log(`[AudioSink] role='${role}' : aucun périphérique correspondant → sortie par défaut`);
    }
  } catch (e) {
    log(`[AudioSink] enumerateDevices échec: ${e.message}`);
  }
  _audioSinkId = deviceId;
  log(`[AudioSink] role='${role}' → deviceId='${deviceId || '(défaut)'}'`);
  // Contenu vidéo en cours
  if (_activeVideo && typeof _activeVideo.setSinkId === 'function') {
    _activeVideo.setSinkId(deviceId).catch((e) => log(`[AudioSink] video.setSinkId échec: ${e.message}`));
  }
  // Runtime des paniers audio
  if (window.signflowAudio && window.signflowAudio.setSink) window.signflowAudio.setSink(deviceId);
}

/** Injecte un <track> par sous-titre + active celui du pays du player (§7). */
function applySubtitles(video, subtitles) {
  if (!Array.isArray(subtitles) || subtitles.length === 0) return;
  for (const sub of subtitles) {
    if (!sub || !sub.url) continue;
    const track = document.createElement('track');
    track.kind = 'subtitles';
    track.srclang = sub.lang || '';
    track.label = sub.label || sub.lang || '';
    track.src = sub.url;
    video.appendChild(track);
  }
  const pick = (lang) => {
    if (!lang) return null;
    const tt = video.textTracks;
    for (let i = 0; i < tt.length; i++) {
      if ((tt[i].language || '').toLowerCase() === String(lang).toLowerCase()) return tt[i];
    }
    return null;
  };
  const activate = () => {
    const tt = video.textTracks;
    for (let i = 0; i < tt.length; i++) tt[i].mode = 'disabled';
    let chosen = pick(_subtitleLang);
    if (!chosen && _subtitleFallback === 'default') chosen = pick(_subtitleDefaultLang);
    if (chosen) chosen.mode = 'showing';
  };
  if (video.textTracks.length) activate();
  video.addEventListener('loadedmetadata', activate, { once: true });
}

// Sur erreur média (souvent : média non caché + serveur/MinIO injoignable), on saute
// vite au suivant après ce délai — au lieu d'attendre la durée complète de l'item et de
// précharger d'autres médias cassés (qui empilaient des <video> → OOM/gel).
const ERROR_SKIP_MS = 2500;

// Demande un player:sync frais quand un media echoue a charger (URL MinIO signee
// expiree apres son TTL). Debounce 30s pour eviter une boucle si l'erreur persiste.
function requestResyncDebounced(reason) {
  // Offline : un resync est inutile (pas de serveur pour répondre) et ne ferait que défaire le
  // backoff WS côté main → martèlement de reconnexion (serveur « à moitié coupé » → 502-storm) →
  // jank event-loop → perte des broadcasts du master → flip-flop d'élection LAN. Le backoff
  // ramènera des URLs fraîches au retour serveur ; l'item se skippe sur erreur sans toucher au WS.
  if (!_connected) return;
  const now = Date.now();
  if (now - _lastResyncAt < 30000) return;
  _lastResyncAt = now;
  log(`[Resync] Requesting fresh sync (${reason})`);
  window.signflow.requestResync();
}

function _getContentFP(payload) {
  // cache_key (= objet réellement servi) inclus dans l'empreinte : sans ça, ajouter
  // une rendition FHD à un média ne change pas les id_item → le renderer ignorerait
  // le nouveau payload et continuerait de jouer le 4K. cache_key est stable au
  // re-signage d'URL (ne change qu'au vrai changement d'objet servi).
  // duration_ms inclus AUSSI : régler la durée d'expo d'une image/PDF (sans toucher le
  // média) ne change ni id_item ni cache_key → sans ça le nouveau délai serait ignoré.
  // Feed Display : les items du flux vivent dans feed_config (média sans cache_key) → sans les
  // intégrer, un changement de mode/config OU l'arrivée de nouveaux items ne change pas l'empreinte
  // → le renderer ignore le sync et le feed ne se rafraîchit JAMAIS sans restart. On prend le mode,
  // la config et l'identité STABLE des items (link_url/published_at, PAS image_url qui change à
  // chaque re-signature/bascule cache).
  const items = (payload.items || []).map((i) => {
    let extra = '';
    const fc = i.media?.feed_config;
    if (fc) {
      const fi = (fc.items || []).map((x) => `${x.link_url || x.title || ''}@${x.published_at || ''}@${x.summary ? 1 : 0}@${x.image_cache_key || ''}@${x.image_url && /^https?:/i.test(x.image_url) ? 'R' : 'L'}`).join('~');
      extra = `#feed:${fc.display_mode || ''}:${JSON.stringify(fc.display_config || {})}:${fi}`;
    }
    return `${i.id_item}@${i.media?.cache_key ?? ''}@${i.duration_ms ?? ''}${extra}`;
  }).join(',');
  return `${payload.id_event ?? '_'}:${payload.id_playlist ?? '_'}:${payload.id_media ?? '_'}:${items}`;
}

// Clé de synchro LAN. Un event mono-média (id_media sans playlist) a id_playlist=null : sans clé,
// le leader ne diffuse PAS de sync_play (gate `!state.id_playlist` dans sync_lan) et les slaves ne
// suivent pas (compare `adj.id_playlist === _currentPlaylistId`) → AUCUNE correction UDP continue,
// donc un esclave qui Restart App saute à la position wall-clock vraie et ne rejoint jamais le
// groupe (qui a dérivé). On dérive une clé synthétique de l'id_event (négatif = jamais en collision
// avec un id_playlist réel, toujours positif) pour faire profiter le mono-média de la MÊME
// machinerie UDP que les playlists wall_clock.
function _syncKeyFor(p) {
  if (!p) return null;
  // 3ᵉ cas de figure : PROGRAMME GOUVERNÉ (§XVIII). Il n'a ni id_playlist ni id_event, il tombait
  // donc sur null ⇒ le leader n'émettait AUCUN sync_play et les écrans gouvernés ne tenaient que
  // par leur wall-clock (constaté par Ed le 25/07 : RPi + NUC désynchronisés sous gouvernance,
  // « presque parfaits » sans). La clé vient du SERVEUR (plage réservée [-2e9, -1e9], dérivée des
  // couches actives) : identique pour tous les écrans qui jouent le même programme compilé,
  // différente dès qu'il diffère.
  if (p.sync_key != null) return p.sync_key;
  if (p.id_playlist != null) return p.id_playlist;
  return p.id_event != null ? -p.id_event : null;
}

// ── Offline cache ─────────────────────────────────────────────────────────────

const CACHE_KEY = 'signflow_last_sync';

function saveSync(payload) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
  } catch (e) {
    log(`Cache write failed: ${e.message}`);
  }
}

function loadSync() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    log(`Cache read failed: ${e.message}`);
    return null;
  }
}

// ── Connection ────────────────────────────────────────────────────────────────

window.signflow.onConnected(() => {
  log('Connected to backend');
  statusBar.classList.add('hidden');
  statusDot.className = 'status-dot online';
  _connected = true;
});

window.signflow.onDisconnected(() => {
  log('Disconnected from backend -- reconnecting...');
  statusBar.classList.remove('hidden');
  statusDot.className = 'status-dot offline';
  statusText.textContent = 'Reconnecting...';
  _connected = false;
});

window.signflow.onSetupRequired(() => {
  log('Setup required: no token configured');
  setFallback('Setup required\nCreate this player in the Vitrail web interface and enter the token in config.json');
});

window.signflow.onMaintenance(() => {
  log('Maintenance mode');
  setFallback('Maintenance mode');
});

// ── VOD à la demande (Feature B) : lecture ad-hoc TAKEOVER ───────────────────────
// Affiche un média (vidéo/image) plein écran PAR-DESSUS la programmation (qui continue
// dessous, muette le temps du takeover). `once` = joue une fois puis rend la main ;
// `loop` = boucle jusqu'à un stop ou un nouveau sync (l'opérateur reprend la main) ;
// `stop` = ferme l'overlay. Le src est résolu offline-first par main.js (cache local).
// Bloc PORTABLE (linux/rpi/windows) : gardes `typeof` pour mpv (présent linux uniquement).
let _vodOverlayEl    = null;
let _vodOverlayMedia = null;
let _vodOverlayTimer = null;
let _vodMpvLowered   = false;
let _vodSuspended    = false;   // la programmation est suspendue (avance stoppée) le temps du takeover
const _vodHasMpv = !!(window.signflow && window.signflow.mpv);
function _vodMpvActive() { try { return _vodHasMpv && typeof _mpvActive !== 'undefined' && _mpvActive; } catch { return false; } }

// PoP du takeover VOD (§XXIV) : armé au démarrage RÉEL, émis à la fin avec la durée
// réellement diffusée (une VOD coupée au bout de 5 s ne doit pas compter comme jouée en
// entier). Sans ça, une diffusion VOD était totalement invisible du système.
let _vodPop = null;
// Mémorise si on a fait baisser la musique, pour ne la remonter que si on l'a baissée.
let _vodDucked = false;
// Politique audio du takeover (2026-07-19) : le son de la VOD CEDE le passage a tout overlay
// audio -- jingle, SPOT DE CAMPAGNE (diffuse comme un jingle synthetique, AD_BASKET_ID -100),
// message, alerte. Raison technique : les overlays passent par messageGain, que le ducking
// (music/ambiance uniquement) ne peut PAS baisser -> sans ca les deux sons se MELANGENT.
// Raison metier : un spot FACTURE, dont le PoP atteste la diffusion, ne doit jamais etre
// couvert ; et une alerte reste prioritaire par definition.
let _vodWantsSound = false;   // l'operateur a demande le son pour CE takeover
let _vodHasAudio   = true;    // le media porte-t-il une piste audio (has_audio, calcule serveur)

function _vodAudioPolicy() {
  let prio = 0;
  try {
    prio = (window.signflowAudio && window.signflowAudio.getOverlayPriority)
      ? (window.signflowAudio.getOverlayPriority() || 0) : 0;
  } catch {}
  // Un overlay parle -> VOD muette ET musique NON baissee (on ne baisse pas pour du silence).
  const audible = _vodWantsSound && prio === 0;
  if (_vodOverlayMedia && 'muted' in _vodOverlayMedia) {
    try { _vodOverlayMedia.muted = !audible; } catch {}
  }
  _vodDuck(audible && _vodHasAudio, {});
}

// Le runtime audio previent a chaque debut/fin d'overlay -> on re-applique la politique : un
// message declenche PENDANT une VOD la fait taire, et a la fin de ce message elle reprend.
try {
  if (window.signflowAudio) {
    window.signflowAudio.onOverlayChange = () => { if (_vodOverlayMedia) _vodAudioPolicy(); };
  }
} catch {}

function _flushVodPop() {
  const pop = _vodPop;
  _vodPop = null;
  if (!pop) return;
  try {
    if (!window.signflow || !window.signflow.reportPlay) return;
    window.signflow.reportPlay({
      id_media: pop.id_media,
      id_playlist: null,          // lecture ad-hoc : hors playlist
      duration_ms: Math.max(0, Math.round(Date.now() - pop.started)),
      played_at: new Date(pop.started).toISOString(),
    });
  } catch {}
}

function _vodDuck(on, cfg) {
  try {
    if (!window.signflowAudio || !window.signflowAudio.duckForVisualOverlay) return;
    if (on === _vodDucked) return;
    window.signflowAudio.duckForVisualOverlay(on, cfg || {});
    _vodDucked = on;
  } catch {}
}

function hideVodOverlay() {
  _flushVodPop();
  _vodWantsSound = false;
  _vodDuck(false);
  if (_vodOverlayTimer) { clearTimeout(_vodOverlayTimer); _vodOverlayTimer = null; }
  if (_vodOverlayMedia) {
    try { if (_vodOverlayMedia.pause) { _vodOverlayMedia.pause(); _vodOverlayMedia.removeAttribute('src'); _vodOverlayMedia.load && _vodOverlayMedia.load(); } } catch {}
  }
  if (_vodOverlayEl) { try { _vodOverlayEl.remove(); } catch {} }
  _vodOverlayEl = null; _vodOverlayMedia = null;
  // Rend le son à la programmation sous-jacente (politique content_sound).
  if (_activeVideo) _activeVideo.muted = _contentMuted;
  if (_mzActive) _mzSetMuted(_contentMuted);   // démute les vidéos des zones (multi-zones §25.4)
  if (_vodMpvActive()) {
    window.signflow.mpv.setMute(_contentMuted);
    if (_vodMpvLowered) { try { window.signflow.mpv.raise(); } catch {} _vodMpvLowered = false; }
  }
  // Reprend la programmation suspendue : re-render de l'item courant (restaure visuel + audio +
  // ré-arme l'avance d'item stoppée pendant le takeover). Anti écran-noir au retour.
  if (_vodSuspended) {
    _vodSuspended = false;
    const item = (playlist && playlist[currentIndex]) || null;
    if (item) {
      let posMs = 0;
      if (_vodMpvActive()) posMs = _mpvTimePosMs || 0;
      else if (_activeVideo && isFinite(_activeVideo.currentTime)) posMs = (_activeVideo.currentTime || 0) * 1000;
      const rem = Math.max(0, (item.duration_ms || 10000) - posMs);
      try { scheduleAdvance(item, rem); } catch (e) { log('VOD resume error: ' + e); }
    }
  }
}

function showVodPlayNow(p) {
  if (!p || p.mode === 'stop' || !p.src) { hideVodOverlay(); return; }
  hideVodOverlay();   // remplace toute lecture ad-hoc en cours
  log(`VOD play_now: media=${p.id_media} mode=${p.mode} type=${p.media_type}`);
  // Suspend la programmation le temps du takeover : stoppe l'avance d'item ET met en pause/coupe
  // le contenu courant → pas de fuite audio ni d'avance parasite ; re-render propre au retour.
  clearTimeout(itemTimer);
  _vodSuspended = true;
  // On COUPE le son de la programmation mais on NE la met PAS en pause : elle reste visible
  // dessous (anti écran-noir au retour). L'avance d'item est stoppée (clearTimeout) → pas de
  // nouvelle vidéo créée ni de re-raise mpv sous l'overlay.
  if (_activeVideo) _activeVideo.muted = true;
  if (_mzActive) _mzSetMuted(true);   // coupe les vidéos des zones pendant le takeover VOD (§25.4)
  // En mode mpv, la vidéo mpv est une fenêtre X11 AU-DESSUS du kiosk → on la descend (et la coupe).
  if (_vodMpvActive()) {
    window.signflow.mpv.setMute(true);
    try { window.signflow.mpv.lower(); _vodMpvLowered = true; } catch {}
  }

  const el = document.createElement('div');
  el.id = 'vod-overlay';
  el.style.cssText = 'position:fixed;inset:0;z-index:2147483600;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden;';
  const loop = p.mode === 'loop';

  if (p.media_type === 'document') {
    // PDF : viewer Chromium en iframe (comme renderItem), chrome masquée.
    const f = document.createElement('iframe');
    f.src = p.src + '#toolbar=0&navpanes=0&scrollbar=0&view=Fit';
    f.style.cssText = 'width:100%;height:100%;border:none;background:#fff';
    el.appendChild(f);
    _vodOverlayMedia = null;   // rien à mettre en pause (el.remove suffit)
    if (!loop) {
      const ms = (p.duration_ms && p.duration_ms > 0) ? p.duration_ms : 10000;
      _vodOverlayTimer = setTimeout(hideVodOverlay, ms);
    }
  } else if (p.media_type === 'image') {
    const img = document.createElement('img');
    img.src = p.src;
    img.style.cssText = 'max-width:100%;max-height:100%;object-fit:contain;';
    img.onerror = () => { log('VOD overlay image error'); hideVodOverlay(); };
    el.appendChild(img);
    _vodOverlayMedia = img;
    _vodPop = { id_media: p.id_media, started: Date.now() };
    if (!loop) {
      const ms = (p.duration_ms && p.duration_ms > 0) ? p.duration_ms : 10000;
      _vodOverlayTimer = setTimeout(hideVodOverlay, ms);
    }
  } else {
    const v = document.createElement('video');
    // Son du takeover : choisi À CHAQUE DÉCLENCHEMENT par l'opérateur (`with_sound`), et non
    // plus forcé. Absent du payload (serveur ancien) => true : on préserve le comportement
    // historique plutôt que de rendre muettes les VOD d'un parc pas encore à jour.
    const vodSound = p.with_sound !== false;
    // Ducking §XIX.5 : le son de cette vidéo ne passe PAS par le runtime audio, il ne peut donc
    // pas être mixé automatiquement. Sans duck explicite, un player à la fois content ET audio
    // superpose musique de fond et VOD (constaté sur le RPi, 2026-07-19).
    // MAIS on ne ducke QUE si le média a réellement une piste audio (`has_audio`, calculé par le
    // serveur depuis media_metadata) : sinon on baisserait la musique pour du silence.
    const vodDuckable = vodSound && p.has_audio !== false;
    v.src = p.src; v.autoplay = true; v.loop = loop; v.controls = false; v.muted = !vodSound;
    _vodWantsSound = vodSound;
    _vodHasAudio = p.has_audio !== false;
    // Etat initial (differe : l'element doit etre pose dans _vodOverlayMedia) -> si un message,
    // une alerte ou un spot joue DEJA, la VOD demarre muette au lieu de se superposer.
    setTimeout(() => { if (_vodOverlayMedia === v) _vodAudioPolicy(); }, 0);
    v.addEventListener('playing', () => {
      if (_vodOverlayMedia === v && !_vodPop) _vodPop = { id_media: p.id_media, started: Date.now() };
    }, { once: true });
    v.style.cssText = 'width:100%;height:100%;object-fit:contain;background:#000;';
    v.onerror = () => { log('VOD overlay video error'); hideVodOverlay(); };
    if (!loop) {
      v.onended = hideVodOverlay;
      // Filet de sécurité si 'ended' ne se déclenche pas (codec capricieux).
      if (p.duration_ms && p.duration_ms > 0) _vodOverlayTimer = setTimeout(hideVodOverlay, p.duration_ms + 3000);
    }
    el.appendChild(v);
    _vodOverlayMedia = v;
    // Si l'autoplay SONORE est bloqué (ex. ChromeOS sans geste) → repli muet plutôt que rien.
    try {
      const pr = v.play();
      if (pr && pr.catch) pr.catch(() => {
        v.muted = true;
        _vodDuck(false);   // repli muet => plus de raison de garder la musique baissée
        v.play().catch(() => {});
      });
    } catch {}
  }
  _vodOverlayEl = el;   // INDISPENSABLE : sans ça hideVodOverlay ne peut pas retirer l'overlay → écran noir résiduel
  document.body.appendChild(el);
}

window.signflow.onPlayNow(showVodPlayNow);

// Rotation du CONTENU (CSS) — universelle, indépendante du driver/OS. L'OS rotation
// (ChangeDisplaySettings) échoue sur les box à API display muette (ex. AOpen Intel HD 6000,
// RC=-1) → on rote #player-root comme le player Android : 90/270 permutent les dimensions
// (100vh×100vh) + recentrage, 180 = simple rotate. Piloté par main (player:rotate à chaque sync).
if (window.signflow.onRotate) {
  window.signflow.onRotate(({ rotation }) => {
    const root = document.getElementById('player-root');
    if (!root) return;
    root.classList.remove('sf-rot-90', 'sf-rot-180', 'sf-rot-270');
    const cls = { left: 'sf-rot-90', inverted: 'sf-rot-180', right: 'sf-rot-270' }[rotation];
    if (cls) root.classList.add(cls);
    log(`[Rotation] contenu '${rotation || 'normal'}'`);
  });
}

// ── Video Wall (compensation de bezel) — rendu Chromium (CSS transform) ─────────
// Applique le sous-rectangle / overscan calculé serveur (display_config.wall_transform) au
// #content-area via une transform CSS. mode 'overscan' (B, défaut) = scale + transform-origin
// ancré sur le bord extérieur (pousse le contenu hors des joints intérieurs) ; mode 'crop'
// (A, source unique) = scale+translate pour n'afficher que le sous-rect [x..x+w]×[y..y+h].
// Windows décode en natif (D3D11, pas de mpv) → le chemin CSS est TOUJOURS actif. La rotation
// est portée par #player-root (parent) et la transform wall par #content-area (enfant) : elles
// se composent sans conflit. overflow:hidden du body clippe le débordement. Idempotent.
let _appliedWallCss = null;
function applyWallCss(tf) {
  const key = tf ? JSON.stringify(tf) : null;
  if (key === _appliedWallCss) return;
  _appliedWallCss = key;
  if (!contentArea) return;
  const s = contentArea.style;
  if (!tf) { s.transform = ''; s.transformOrigin = ''; return; }
  if (tf.mode === 'crop') {
    const w = tf.w || 1, h = tf.h || 1, x = tf.x || 0, y = tf.y || 0;
    s.transformOrigin = '0 0';
    s.transform = `translate(${(-x / w) * 100}%, ${(-y / h) * 100}%) scale(${1 / w}, ${1 / h})`;
  } else { // overscan (B)
    const ox = tf.align_x < 0 ? '0%' : tf.align_x > 0 ? '100%' : '50%';
    const oy = tf.align_y < 0 ? '0%' : tf.align_y > 0 ? '100%' : '50%';
    s.transformOrigin = `${ox} ${oy}`;
    s.transform = `scale(${tf.scale_x || 1}, ${tf.scale_y || 1})`;
  }
}

// ── Config d'affichage + audio ────────────────────────────────────────────────
// Applique la politique d'affichage/audio d'un payload de sync (son des contenus,
// sous-titres, fallback, quarantaine, volumes, paniers audio). Extrait de onSync pour
// être rejoué AUSSI au boot depuis le cache offline : sinon, serveur injoignable au
// démarrage → le son de la vidéo n'est pas coupé et les paniers audio restent muets
// jusqu'au premier sync live. Re-mute aussi la vidéo déjà en cours (_activeVideo).
function applyConfig(payload) {
  const dc = payload.display_config || {};
  _contentMuted = dc.content_sound === 'muted';
  if (_activeVideo) _activeVideo.muted = _contentMuted;
  if (_mzActive) _mzSetMuted(_contentMuted);   // multi-zones (§25.4) : re-mute live des videos de zone
  // Video Wall (compensation bezel) : transform CSS sur le contenu (Windows = décodage natif D3D11).
  applyWallCss(dc.wall_transform);
  // Sous-titres (§7) : langue préférée + politique de repli (pays du player)
  _subtitleLang        = dc.subtitle_lang || null;
  _subtitleFallback    = dc.subtitle_fallback || 'none';
  _subtitleDefaultLang = dc.subtitle_default_lang || null;
  // Config de repli (§17.5) : message vidéo custom + piste audio de secours
  _fallback = payload.fallback || null;
  // Quarantaine / kill-switch (§ Q5) : garde côté player (défense en profondeur).
  _blockedMedia = new Set(payload.blocked_media || []);
  // Audio in-store (§XIX) : paniers audio indépendants du contenu vidéo
  if (window.signflowAudio) {
    try {
      // Volume persisté (Store Control Panel §19.3) — avant setBaskets (1re piste au bon volume).
      if (typeof dc.audio_volume === 'number') {
        window.signflowAudio.setVolume(dc.audio_volume);
      }
      // Volumes par famille (trim fin Music/Ambiance, persistés comme le volume général)
      if (window.signflowAudio.setFamilyVolume) {
        if (typeof dc.audio_music_volume === 'number')
          window.signflowAudio.setFamilyVolume('music', dc.audio_music_volume);
        if (typeof dc.audio_ambiance_volume === 'number')
          window.signflowAudio.setFamilyVolume('ambiance', dc.audio_ambiance_volume);
      }
      if (window.signflowAudio.setBasketOutput) {
        window.signflowAudio.setBasketOutput(dc.audio_basket_output || 'auto');
      }
      // Routage audio physique (résout role→deviceId puis setSinkId contenu + paniers).
      // Ne ré-applique que si le rôle a changé (enumerateDevices à chaque sync = inutile).
      if ((dc.audio_basket_output || 'auto') !== _audioSinkRole) {
        applyAudioSink(dc.audio_basket_output || 'auto');
      }
      // Piste de secours (§17.5) avant setBaskets : jouée en boucle si aucun panier musical
      if (window.signflowAudio.setFallback) {
        window.signflowAudio.setFallback(_fallback && _fallback.audio ? _fallback.audio : null);
      }
      // Garde quarantaine (§ Q5) : retire les pistes bloquées des paniers audio.
      // Réf module → onStoreUpdate patche les urls vers signflow:// quand l'audio est caché.
      _audioBaskets = (payload.audio_baskets || []).map((b) => ({
        ...b, items: (b.items || []).filter((i) => !_blockedMedia.has(i.id_media)),
      }));
      window.signflowAudio.setBaskets(_audioBaskets);
    } catch (e) { log(`Audio baskets error: ${e.message}`); }
  }
}

// ── Playlist ──────────────────────────────────────────────────────────────────

window.signflow.onSync((payload) => {
  // VOD takeover : un nouveau sync = reprise opérateur → ferme l'overlay. On lève _vodSuspended
  // d'abord pour que hideVodOverlay NE re-render PAS (onSync rend le nouveau contenu lui-même).
  if (_vodSuspended) { _lastSync = payload; return; }
  const n = payload.items?.length ?? 0;
  _currentPlaylistId = _syncKeyFor(payload);   // clé synthétique pour les events mono-média (sync LAN)
  _popPlaylistId = payload.id_playlist ?? null; // Proof of Play : vrai id_playlist (null = mono-média)
  _lastSync = payload;  // overlay de maintenance
  if (_overlayEl) refreshOverlay();
  log(`Sync received: ${n} item(s) | playlist=${payload.id_playlist ?? 'none'} preemptive=${payload.preemptive ?? false}`);

  applyConfig(payload);

  // §25.4 : un template multi-zones prend le relais (chaque zone = sous-playlist Chromium
  // indépendante). Sinon on démonte d'éventuelles zones avant de reprendre le chemin mono-zone.
  if (handleMultiZoneSync(payload)) return;
  exitMultiZone();

  if (n === 0) {
    _currentContentFP = null;
    _pendingSync = null;
    clearPreload();
    playlist = null;
    // Contenu retiré côté serveur (sync vide EXPLICITE, pas une coupure) : purge le cache de
    // lecture pour ne JAMAIS rejouer cette playlist périmée au prochain (re)démarrage offline-first.
    // Les octets médias du store local restent (éviction séparée) mais ne sont plus pointés.
    try { localStorage.removeItem(CACHE_KEY); } catch {}
    setFallback();
    return;
  }
  // Barrière de sync LAN (Q1) : en groupe, main.js pose `lan_hold` tant que tout le
  // groupe n'a pas le contenu en cache. On retient le démarrage du NOUVEAU contenu
  // (le contenu en cours continue) ; on démarre à l'ouverture de la barrière
  // (player:lan-release) ou au timeout (géré côté LAN). Hors groupe = jamais de hold.
  if (payload.lan_hold) {
    _lanHeld = payload;
    log('LAN barrier: holding new content until group ready');
    return;
  }
  applyPlayback(payload);
});

// Applique la décision de lecture d'un payload de sync (immédiate ou graceful selon
// preemptive). Extrait pour pouvoir être déclenché à l'ouverture de la barrière LAN.
function applyPlayback(payload) {
  const newFP = _getContentFP(payload);
  if (newFP === _currentContentFP) {
    log(`Sync ignored: same content already playing (FP=${newFP})`);
    return;
  }
  if (payload.preemptive !== false || playlist === null) {
    // Apply immediately: preemptive=true, initial sync (preemptive=undefined), or nothing playing
    _pendingSync = null;
    _currentContentFP = newFP;
    saveSync(payload);
    clearPreload();
    playlist = payload.items;
    _playOnce = payload.play_once === true;
    currentIndex = payload.start_index ?? 0;
    playCurrentItem(payload.start_offset_ms ?? 0);
  } else {
    // Graceful: preemptive===false AND content is playing — queue for next item boundary
    log(`Graceful sync queued (FP=${newFP})`);
    _pendingSync = payload;
  }
}

// Barrière LAN ouverte (groupe prêt ou timeout) → démarrer le contenu retenu.
window.signflow.onLanRelease(() => {
  if (!_lanHeld) return;
  const p = _lanHeld;
  _lanHeld = null;
  log('LAN barrier released — starting content');
  applyPlayback(p);
});

// Store local (offline-first) : quand un média arrive en cache, main.js envoie son
// URL signflow://. On patche les items EN PLACE (par cache_key) SANS toucher la
// lecture en cours → l'item bascule sur le local à sa prochaine création (boucle /
// avance / précache suivant). Le repli streaming reste actif entre-temps.
window.signflow.onStoreUpdate(({ cache_key, url }) => {
  if (!cache_key || !url) return;
  let patched = 0;
  const patch = (items) => {
    for (const it of (items || [])) {
      if (it && it.media && it.media.cache_key === cache_key && it.media.url !== url) {
        it.media.url = url;
        patched++;
      }
    }
  };
  patch(playlist);
  if (_pendingSync) patch(_pendingSync.items);
  if (_lastSync && _lastSync.items !== playlist) patch(_lastSync.items);
  // Multi-zones (§25.4) : patcher les items de chaque zone (la prochaine (ré)avance de
  // la zone basculera sur l'URL signflow:// locale, sans interrompre la lecture en cours).
  if (_mzActive) { for (const z of _mzZones) patch(z.items); }
  // Paniers audio : items = media-like (pas de .media). audio_player partage la réf.
  for (const b of _audioBaskets) {
    for (const it of (b.items || [])) {
      if (it && it.cache_key === cache_key && it.url !== url) { it.url = url; patched++; }
    }
  }
  if (patched) {
    log(`Store update: ${patched} item(s) -> local`);
    if (_lastSync) saveSync(_lastSync);  // persiste les URLs locales pour le boot offline
  }
});

function setFallback(msg) {
  clearTimeout(itemTimer);
  _releaseVideo(_activeVideo); _activeVideo = null;   // libère le WebMediaPlayer (crbug 1144736)
  contentArea.innerHTML = '';
  // Message : argument explicite (ex. 'Maintenance mode') > message custom serveur
  // (§17.5 fallback.video_message) > défaut embarqué.
  const fb  = _fallback || {};
  const cfg = fb.video_config || {};
  fallbackMsg.textContent = msg || fb.video_message || 'No content to display';
  // Style optionnel piloté par video_config (couleurs, masquage du logo).
  fallbackScreen.style.background = cfg.background_color || '';
  fallbackMsg.style.color = cfg.text_color || '';
  if (fallbackLogo) fallbackLogo.style.display = cfg.hide_logo ? 'none' : '';
  fallbackScreen.classList.remove('hidden');
}

// ── Précache double-buffer (#2 LAN Sync) ──────────────────────────────────────
// Préchauffe le cache du prochain média dans un élément caché : la création fraîche
// à la bascule tape alors le cache disque → quasi plus de trou de décodage (surtout
// RPi). Purement local (chaque player connaît déjà sa playlist) ; aucun impact sur
// le protocole de sync. Repli gracieux : si le cache n'est pas prêt, comportement
// identique à avant.
function _getPreloadArea() {
  if (!_preloadArea) {
    _preloadArea = document.createElement('div');
    _preloadArea.style.cssText = 'position:absolute;left:-9999px;top:0;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none';
    document.body.appendChild(_preloadArea);
  }
  return _preloadArea;
}

function clearPreload() {
  if (_nextPreload && _nextPreload.el) {
    try {
      _nextPreload.el.removeAttribute('src');
      if (_nextPreload.el.load) _nextPreload.el.load();
      _nextPreload.el.remove();
    } catch {}
  }
  _nextPreload = null;
}

function precacheNext() {
  if (!playlist || playlist.length <= 1) return;
  const nextIndex = (currentIndex + 1) % playlist.length;
  if (_nextPreload && _nextPreload.index === nextIndex) return;  // déjà préchargé
  const media = playlist[nextIndex] && playlist[nextIndex].media;
  if (!media || !media.url) return;
  clearPreload();
  if (media.media_type === 'video') {
    const v = document.createElement('video');
    v.preload = 'auto';
    v.muted = true;            // bufferise sans nécessiter de geste utilisateur
    v.src = media.url;
    _getPreloadArea().appendChild(v);
    try { v.load(); } catch {}
    _nextPreload = { index: nextIndex, el: v };
  } else if (media.media_type === 'image') {
    const img = new Image();
    img.src = media.url;       // préchauffe le cache HTTP de l'image
    _nextPreload = { index: nextIndex, el: img };
  }
}

function playCurrentItem(seekMs = 0) {
  if (!playlist || playlist.length === 0) {
    setFallback();
    return;
  }

  // Garde quarantaine (§ Q5) : ne JAMAIS jouer un média bloqué, même hors-ligne.
  if (_blockedMedia.size > 0) {
    let guard = 0;
    while (guard < playlist.length && _blockedMedia.has(playlist[currentIndex]?.media?.id_media)) {
      log(`Blocked media skipped (quarantine): ${playlist[currentIndex]?.media?.id_media}`);
      currentIndex = (currentIndex + 1) % playlist.length;
      guard++;
    }
    if (guard >= playlist.length) { setFallback(); return; }
  }

  fallbackScreen.classList.add('hidden');
  clearTimeout(itemTimer);
  _currentSwitchAt = null;   // re-armé par renderItem→onReady ; tant que null, pas de report LAN

  const item = playlist[currentIndex];
  const dur = item.duration_ms || 10000;
  const effectiveDur = Math.max(0, dur - seekMs);
  log(`Playing [${currentIndex + 1}/${playlist.length}] ${item.media?.media_name ?? item.id_item} (${(effectiveDur/1000).toFixed(1)}s | ${item.media?.media_type ?? '?'})`);

  renderItem(item, () => {
    precacheNext();   // précharge le prochain média dès que l'item courant joue
    // #2b : instant absolu de la prochaine bascule (le maître le diffuse, les
    // slaves s'y alignent). Ancré sur le démarrage réel de l'item courant.
    _currentSwitchAt = Date.now() + effectiveDur;
    _itemStartedAt = Date.now();   // ancre la grâce de frontière (anti seek transitoire au démarrage)
    _currentNextIndex = playlist ? (currentIndex + 1) % playlist.length : 0;
    reportPlay(item, effectiveDur);   // Proof of Play : le média démarre réellement (offline-first côté main)
    scheduleAdvance(item, effectiveDur);
  }, () => {
    // onError : média injouable (non caché + serveur down, URL expirée…). On NE précharge
    // PAS (sinon empilement de <video> cassés → OOM) et on saute vite au suivant pour ne
    // jamais figer le mur. requestResync (dans renderItem) ramènera des URLs fraîches si
    // le serveur revient.
    clearPreload();
    scheduleAdvance(item, ERROR_SKIP_MS);
  }, seekMs);
}

// Avance vers l'item suivant (ou applique un sync graceful en attente). Extrait
// pour pouvoir être reprogrammé sur le switch_at du maître (#2b).
function advanceFromItem(item) {
  if (_pendingSync) {
    // Graceful switch: apply the queued sync payload at this item boundary
    const pending = _pendingSync;
    _pendingSync = null;
    const newFP = _getContentFP(pending);
    _currentContentFP = newFP;
    saveSync(pending);
    clearPreload();
    playlist = pending.items;
    _playOnce = pending.play_once === true;
    currentIndex = pending.start_index ?? 0;
    log(`Pending sync applied at item boundary (FP=${newFP})`);
    applyTransition(item.transition_type, () => playCurrentItem(pending.start_offset_ms ?? 0));
  } else if (_playOnce && currentIndex + 1 >= playlist.length) {
    // ── EVENT « JOUE UNE FOIS » : on ne reboucle PAS. ────────────────────────
    // Le player avancait sur un minuteur regle sur item.duration_ms et rebouclait
    // toujours en fin de liste. Pour un event play-once, la video se relancait donc
    // a la fin, et le serveur la coupait 0-30 s plus tard quand le beat `expire_events`
    // finissait par la faire expirer : « ca recommence a la fin pour s'arreter quelques
    // secondes apres » (constat d'Ed, 11/08). Le « une fois » n'existait que cote
    // serveur — le payload ne le disait pas au player.
    // On tient la derniere image et on demande une synchro fraiche : le serveur, qui
    // ne sert plus un event echu, renvoie la programmation normale.
    // ⛔ NE PAS appeler requestResync ici. Cette primitive ne « demande » pas une
    // synchro : elle TUE LA WEBSOCKET et se reconnecte (ecrite pour un cas d'erreur
    // rare, une URL MinIO expiree). L'employer a chaque fin d'event de routine, c'est
    // une coupure de WS toutes les 30 min sur chaque ecran, PLUS les 0-5 s de jitter
    // de connexion poses par P3.12 — d'ou une derniere image figee « quelques
    // secondes » qui se lit comme une panne (constat d'Ed a l'ecran, 2026-08-11), et
    // un generateur de rafale de reconnexions.
    // C'est le SERVEUR qui reprend la main : depuis le meme correctif, il programme
    // l'expiration de l'event a la seconde pres (event_worker) au lieu d'attendre son
    // battement de 30 s. La bascule arrive donc au moment ou le media se termine.
    log('[PlayOnce] Event finished — waiting for the server to hand back the schedule');
    // ⚠️ FILET : si la bascule n'arrive pas (hors ligne, worker arrete), on ne fige pas
    // l'ecran indefiniment — mieux vaut reboucler que rester bloque.
    clearTimeout(itemTimer);
    itemTimer = setTimeout(function () {
      log('[PlayOnce] No hand-back — resuming the loop rather than freezing');
      _playOnce = false;
      currentIndex = 0;
      playCurrentItem();
    }, 20000);
  } else {
    // Feuilletage en cours : on ne retire pas le document des mains du visiteur. Arrive a la
    // derniere page, on repart a la premiere TANT QU'IL INTERAGIT ; passe le delai sans geste,
    // la branche normale reprend et la diffusion continue. Sans ce delai, un objet pose sur la
    // dalle immobiliserait l'ecran sur un document (decision d'Ed 2026-08-14).
    const _docRun = touchDocRun(currentIndex);
    if (_docRun && currentIndex === _docRun.end && touchInteracting()) {
      currentIndex = _docRun.start;
      applyTransition(item.transition_type, playCurrentItem);
      return;
    }
    currentIndex = (currentIndex + 1) % playlist.length;
    applyTransition(item.transition_type, playCurrentItem);
  }
}

function scheduleAdvance(item, delayMs) {
  clearTimeout(itemTimer);
  itemTimer = setTimeout(() => advanceFromItem(item), Math.max(0, delayMs));
}

// Proof of Play (§XXIV) : à chaque média qui DÉMARRE réellement, on remonte une preuve de
// diffusion {id_media, id_playlist, played_at, duration_ms}. main.js la met en file persistée
// (offline-first) et la flushe vers POST /pop/batch. id_playlist = null pour un event mono-média.
// Un overlay PLEIN ECRAN masque-t-il la programmation en ce moment ? (migr 0125)
//
// Deux overlays recouvrent tout l'ecran : le takeover VOD, et le spot de campagne plein
// ecran de P3.6. Dans les DEUX cas les zones d'un template multi-zones ne sont PAS
// suspendues -- les suspendre decalerait leur wall-clock et desynchroniserait l'ecran au
// retour -- donc chaque item qui demarre dessous appelle reportPlay et atteste une
// diffusion que personne ne voit. On marque ces preuves : le serveur les conserve (chaine
// Merkle intacte) mais ne les compte jamais comme de l'antenne.
//
// `exceptAd` = l'overlay de la zone appelante. Un spot plein ecran est le COUVREUR, pas un
// couvert : sans cette exception il se marquerait lui-meme et un spot FACTURE disparaitrait
// des comptages. Le passer en parametre plutot que de tester un drapeau global rend
// l'exception explicite et impossible a « simplifier » par megarde.
function _coveredNow(exceptAd) {
  // _vodSuspended est pose AVANT que l'overlay ne soit monte dans le DOM : tester les deux
  // ferme la fenetre ou une zone demarrerait pile entre les deux.
  if (_vodSuspended || _vodOverlayEl) return true;
  for (const z of _mzZones) { if (z.adOverlay && z.adOverlay !== exceptAd) return true; }
  return false;
}

function reportPlay(item, durationMs, covered) {
  try {
    const idMedia = item && item.media && item.media.id_media;
    if (idMedia == null || !window.signflow || !window.signflow.reportPlay) return;
    window.signflow.reportPlay({
      id_media: idMedia,
      id_playlist: _popPlaylistId,
      duration_ms: Math.max(0, Math.round(durationMs || 0)),
      played_at: new Date().toISOString(),
      // Defaut = on interroge l'etat des overlays (migr 0125). Seul le spot plein ecran
      // passe une valeur explicite, pour s'exclure lui-meme.
      covered: covered === undefined ? _coveredNow(null) : !!covered,
    });
  } catch {}
}

// Libère le WebMediaPlayer d'un <video> AVANT de le retirer du DOM. `innerHTML=''` seul
// ne libère PAS la ressource média Chromium → au fil des bascules/resyncs les <video>
// s'accumulent jusqu'au plafond (~75, crbug 1144736) → erreurs en boucle + spike mémoire.
// pause+removeAttribute(src)+load() force la libération immédiate.
function _releaseVideo(v) {
  if (!v) return;
  try {
    // Couper les handlers AVANT load() : sinon, au plafond WebMediaPlayer, le load()
    // re-déclenche onerror → re-_releaseVideo → load() → boucle serrée qui crée ~75
    // players en quelques secondes (cause du gel OOM). Handlers off = pas de ré-entrée.
    v.onerror = null; v.oncanplay = null; v.onseeked = null;
    v.pause(); v.removeAttribute('src'); v.load();
  } catch {}
}

function renderItem(item, onReady, onError, seekMs = 0) {
  const media = item.media;
  _releaseVideo(_activeVideo);   // libère la vidéo précédente avant tout remplacement
  _activeVideo = null;
  if (_urlRefreshTimer) { clearInterval(_urlRefreshTimer); _urlRefreshTimer = null; }  // url_display précédent
  if (_feedTimer) { clearInterval(_feedTimer); _feedTimer = null; }                    // feed_display précédent

  // feed_display n'a pas de media.url (le contenu = items dans feed_config) → exempté du garde.
  if (!media || (!media.url && media.media_type !== 'feed_display')) {
    log(`ERROR: media unavailable for item ${item.id_item}`);
    contentArea.innerHTML = '<div class="slide-error">Media unavailable</div>';
    onError();   // saute vite au suivant (pas de durée complète sur un item sans média)
    return;
  }

  contentArea.innerHTML = '';
  const t0 = Date.now();
  log(`Loading ${media.media_type}: ${media.media_name}`);

  if (media.media_type === 'video') {
    const video = document.createElement('video');
    video.src = media.url;
    video.autoplay = true;
    video.playsInline = true;
    video.muted = _contentMuted;   // son des contenus standards (display_config.content_sound)
    // Routage audio physique : route le son du contenu sur la sortie résolue (HDMI/jack/USB).
    if (_audioSinkId && typeof video.setSinkId === 'function') {
      video.setSinkId(_audioSinkId).catch((e) => log(`[AudioSink] video.setSinkId échec: ${e.message}`));
    }
    video.style.cssText = 'width:100%;height:100%;object-fit:contain;background:#000';
    if (seekMs > 0) video.style.visibility = 'hidden';
    video.oncanplay = () => {
      video.oncanplay = null;
      if (seekMs > 0) {
        video.currentTime = seekMs / 1000;
        video.onseeked = () => { video.onseeked = null; video.style.visibility = 'visible'; };
      }
      log(`Video ready in ${Date.now()-t0}ms`);
      onReady();
    };
    video.onerror = (e) => {
      log(`ERROR video: ${e.type} code=${video.error?.code}`);
      // _releaseVideo coupe onerror AVANT load() → pas de boucle ; puis retire du DOM.
      _releaseVideo(video);
      try { video.remove(); } catch {}
      _activeVideo = null;
      requestResyncDebounced('video load error');
      onError();
    };
    applySubtitles(video, media.subtitles);   // sous-titres multi-langues (§7)
    contentArea.appendChild(video);
    _activeVideo = video;  // pour le LAN sync (playbackRate nudge + report position)

  } else if (media.media_type === 'image') {
    _activeVideo = null;
    const img = document.createElement('img');
    img.src = media.url;
    img.alt = media.media_name || '';
    img.style.cssText = 'width:100%;height:100%;object-fit:contain;background:#000';
    img.onload = () => { log(`Image ready in ${Date.now()-t0}ms`); onReady(); };
    img.onerror = () => {
      log(`ERROR image: failed to load`);
      try { img.removeAttribute('src'); img.remove(); } catch {}
      requestResyncDebounced('image load error');
      onError();
    };
    contentArea.appendChild(img);

  } else if (media.media_type === 'url_display') {
    _activeVideo = null;
    renderUrlDisplay(media, onReady, onError, t0);

  } else if (media.media_type === 'feed_display') {
    _activeVideo = null;
    renderFeed(media, onReady);

  } else if (media.media_type === 'html_package') {
    // Web / HTML (§XXV) : SAUTER si inaccessible (timeout) au lieu de figer. Non caché (web).
    _activeVideo = null;
    const iframe = document.createElement('iframe');
    iframe.src = media.url;
    iframe.style.cssText = 'width:100%;height:100%;border:none;background:#000';
    let _webDone = false;
    const webTimer = setTimeout(() => {
      if (_webDone) return;
      _webDone = true;
      log(`Web/HTML inaccessible (timeout ${WEB_LOAD_TIMEOUT_MS}ms) — skip`);
      try { iframe.src = 'about:blank'; iframe.remove(); } catch {}
      onError();
    }, WEB_LOAD_TIMEOUT_MS);
    iframe.onload = () => {
      if (_webDone) return;
      _webDone = true; clearTimeout(webTimer);
      log(`HTML ready in ${Date.now()-t0}ms`); onReady();
    };
    iframe.onerror = () => {
      if (_webDone) return;
      _webDone = true; clearTimeout(webTimer);
      try { iframe.src = 'about:blank'; iframe.remove(); } catch {}
      onError();
    };
    contentArea.appendChild(iframe);

  } else if (media.media_type === 'document') {
    // PDF / document (upload type "document") : viewer PDF Chromium en iframe, chrome masquée
    // (#toolbar=0). Multi-pages = 1re page affichée pour la durée de l'item (cycle de pages =
    // évolution future). Garde-fou timeout comme html_package (l'iframe n'a pas d'onerror fiable).
    _activeVideo = null;
    const docFrame = document.createElement('iframe');
    docFrame.src = `${media.url}#toolbar=0&navpanes=0&scrollbar=0&view=Fit`;
    docFrame.style.cssText = 'width:100%;height:100%;border:none;background:#fff';
    let _docDone = false;
    const docTimer = setTimeout(() => {
      if (_docDone) return;
      _docDone = true;
      log(`Document inaccessible (timeout ${WEB_LOAD_TIMEOUT_MS}ms) — skip`);
      try { docFrame.src = 'about:blank'; docFrame.remove(); } catch {}
      onError();
    }, WEB_LOAD_TIMEOUT_MS);
    docFrame.onload = () => {
      if (_docDone) return;
      _docDone = true; clearTimeout(docTimer);
      log(`Document ready in ${Date.now()-t0}ms`); onReady();
    };
    contentArea.appendChild(docFrame);

  } else {
    _activeVideo = null;
    log(`ERROR: unsupported type ${media.media_type}`);
    contentArea.innerHTML = `<div class="slide-error">Unsupported type: ${media.media_type}</div>`;
    onError();   // saute vite (pas de durée complète sur un type injouable)
  }
}

// Site Web (url_display §XXV.2) — webview offline-first. La config (url + render) voyage dans
// le sync persisté → serveur coupé, on continue d'afficher (si le site est joignable). Sonde
// d'accès au site AVANT affichage : inaccessible → on SAUTE l'item (onError → suivant de la
// playlist) + ALERTE serveur (mise en file par main.js si serveur down, rejouée à la reconnexion).
// Mode screenshot_server (§XXV.2) : le serveur a capturé la page (Playwright) → on affiche
// l'IMAGE. media.url = signflow:// si cachée (offline-first), sinon URL signée MinIO. Marche
// partout (aucune contrainte de framing). Échec de chargement → skip + alerte.
function renderUrlScreenshot(media, onReady, onError, t0) {
  const img = document.createElement('img');
  img.src = media.url;
  img.alt = media.media_name || '';
  img.style.cssText = 'width:100%;height:100%;object-fit:contain;background:#000';
  img.onload = () => { log(`url_display screenshot ready in ${Date.now() - t0}ms`); onReady(); };
  img.onerror = () => {
    log('url_display screenshot inaccessible — skip + alerte');
    try {
      window.signflow.reportEvent &&
        window.signflow.reportEvent({ event: 'url_display_unreachable', id_media: media.id_media, url: media.url, error: 'screenshot load error' });
    } catch (e) {}
    try { img.removeAttribute('src'); img.remove(); } catch {}
    onError();
  };
  contentArea.appendChild(img);
}

function renderUrlDisplay(media, onReady, onError, t0) {
  const cfg = media.url_config || {};
  if (cfg.render_mode === 'screenshot_server') { renderUrlScreenshot(media, onReady, onError, t0); return; }
  const url = media.url;
  const timeoutMs = Math.max(1000, (parseInt(cfg.reachability_timeout_s, 10) || 8) * 1000);

  const reportUnreachable = (reason) => {
    log(`url_display inaccessible (${reason}) — skip + alerte: ${url}`);
    try {
      window.signflow.reportEvent &&
        window.signflow.reportEvent({ event: 'url_display_unreachable', id_media: media.id_media, url, error: reason });
    } catch (e) {}
  };

  const buildIframe = () => {
    const iframe = document.createElement('iframe');
    iframe.src = url;
    const zoom = (typeof cfg.zoom === 'number' && cfg.zoom > 0) ? cfg.zoom : 1;
    const inv = 100 / zoom;   // zoom : agrandit le contenu, cadre plein écran (origine haut-gauche)
    const interaction = (cfg.interaction_blocked !== false);   // défaut true (signage = non cliquable)
    iframe.style.cssText =
      `position:absolute;top:0;left:0;width:${inv}%;height:${inv}%;border:none;background:#000;` +
      `transform:scale(${zoom});transform-origin:0 0;` + (interaction ? 'pointer-events:none;' : '');
    let _done = false;
    const webTimer = setTimeout(() => {
      if (_done) return; _done = true;
      // Sonde désactivée : on n'évince pas (on garde la page même sans onload fiable).
      if (cfg.reachability_enabled === false) { log('url_display: timeout, sonde off → on garde la page'); onReady(); return; }
      try { iframe.src = 'about:blank'; iframe.remove(); } catch {}
      reportUnreachable(`load timeout ${timeoutMs}ms`);
      onError();
    }, timeoutMs);
    iframe.onload = () => {
      if (_done) return; _done = true; clearTimeout(webTimer);
      log(`url_display ready in ${Date.now() - t0}ms`); onReady();
    };
    iframe.onerror = () => {
      if (_done) return; _done = true; clearTimeout(webTimer);
      try { iframe.src = 'about:blank'; iframe.remove(); } catch {}
      reportUnreachable('iframe error'); onError();
    };
    contentArea.style.position = 'relative';
    contentArea.appendChild(iframe);
    // Rafraîchissement périodique (dashboards) : recharge la page sans changer d'item.
    const refreshS = parseInt(cfg.refresh_interval_s, 10) || 0;
    if (refreshS > 0) {
      _urlRefreshTimer = setInterval(() => { try { iframe.src = url; } catch (e) {} }, refreshS * 1000);
    }
  };

  // PAS de sonde fetch préalable : un fetch HEAD depuis l'origine du renderer (file://) est rejeté
  // pour des sites pourtant joignables (origine/CORS) → faux « inaccessible » + skip. On laisse
  // l'IFRAME elle-même juger : onload = OK ; onerror / timeout = inaccessible → skip + alerte.
  buildIframe();
}

// ── Feed Display (§XXV.3) — RSS/Atom rendu offline-first ────────────────────────────────
// Les items voyagent dans le sync persisté (media.feed_config = {display_mode, display_config,
// items}) → serveur coupé, le feed continue de s'afficher avec ses derniers items. Deux modes :
// 'ticker' (bandeau de titres défilant) et 'card_carousel' (cartes auto-rotatives). Aucun réseau
// requis hormis les vignettes (chargées en ligne, tranche 1). onReady immédiat : la durée
// d'affichage = celle de l'item de playlist (comme une image).
function _feedEscape(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function _feedCssUrl(u) { return String(u || '').replace(/['"\\)]/g, ''); }
function _feedDate(iso) {
  try {
    const d = new Date(iso), now = new Date();
    return d.toDateString() === now.toDateString()
      ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString([], { day: '2-digit', month: 'short' });
  } catch (e) { return ''; }
}
function _injectFeedStyles() {
  if (document.getElementById('feed-styles')) return;
  const st = document.createElement('style');
  st.id = 'feed-styles';
  st.textContent = `
.feed-root{position:absolute;inset:0;background:#1C1E2A;color:#F8F7F5;font-family:Inter,system-ui,sans-serif;overflow:hidden}
.feed-empty{display:flex;align-items:center;justify-content:center;height:100%;font-size:3vw;opacity:.6}
.feed-ticker{position:absolute;inset:0;display:flex;align-items:center;overflow:hidden}
.feed-tk-track{display:inline-flex;white-space:nowrap;will-change:transform}
.feed-tk-seq{display:inline-flex;align-items:center}
.feed-tk-item{font-size:5.5vh;font-weight:600;padding:0 .15em}
.feed-tk-sep{font-size:5.5vh;color:#4875B4;padding:0 .35em}
@keyframes feedTkScroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.feed-carousel{position:absolute;inset:0}
.feed-card{position:absolute;inset:0;display:flex;flex-direction:column}
.feed-card-img{flex:1;background-size:cover;background-position:center;background-color:#0f1117}
.feed-card-noimg{background:linear-gradient(135deg,#23264a,#1C1E2A)}
.feed-card-body{padding:3vh 4vw;background:#1C1E2A}
.feed-card-title{font-size:3.6vh;font-weight:600;line-height:1.22;max-height:2.6em;overflow:hidden}
.feed-card-meta{margin-top:1.2vh;font-size:2.1vh;color:#9aa3b2}
.feed-fade{animation:feedFade .5s ease}
.feed-slide{animation:feedSlide .5s ease}
@keyframes feedFade{from{opacity:0}to{opacity:1}}
@keyframes feedSlide{from{opacity:0;transform:translateX(4vw)}to{opacity:1;transform:translateX(0)}}
.feed-grid{position:absolute;inset:0;display:grid;gap:1.2vh;padding:1.2vh;box-sizing:border-box}
.feed-grid-cell{background:#23264a;border-radius:.6vh;overflow:hidden;display:flex;flex-direction:column;min-height:0}
.feed-grid-img{flex:1;background-size:cover;background-position:center;background-color:#0f1117;min-height:0}
.feed-grid-body{padding:1vh 1vw}
.feed-grid-title{font-size:2.1vh;font-weight:600;line-height:1.2;max-height:3.6em;overflow:hidden}
.feed-grid-meta{margin-top:.5vh;font-size:1.5vh;color:#9aa3b2}
.feed-full{position:absolute;inset:0;background-size:cover;background-position:center;background-color:#0f1117}
.feed-full-shade{position:absolute;left:0;right:0;bottom:0;padding:5vh 6vw 6vh;background:linear-gradient(to top,rgba(12,14,23,.93),rgba(12,14,23,.5) 55%,rgba(12,14,23,0))}
.feed-full-title{font-size:5vh;font-weight:600;line-height:1.15;max-height:2.4em;overflow:hidden}
.feed-full-desc{margin-top:2vh;font-size:2.6vh;line-height:1.4;color:#d4d8e0;max-height:4.3em;overflow:hidden}
.feed-full-meta{margin-top:2vh;font-size:2.1vh;color:#9aa3b2}
.feed-split{position:absolute;inset:0;display:flex}
.feed-split.img-right{flex-direction:row-reverse}
.feed-split-img{flex:0 0 48%;background-size:cover;background-position:center;background-color:#0f1117}
.feed-split-body{flex:1;display:flex;flex-direction:column;justify-content:center;padding:5vh 4vw}
.feed-split-title{font-size:4vh;font-weight:600;line-height:1.2;max-height:3.6em;overflow:hidden}
.feed-split-desc{margin-top:2.5vh;font-size:2.6vh;line-height:1.45;color:#d4d8e0;max-height:7.4em;overflow:hidden}
.feed-split-meta{margin-top:2.5vh;font-size:2.1vh;color:#9aa3b2}
.feed-compact{position:absolute;inset:0;padding:3vh 4vw;display:flex;flex-direction:column;overflow:hidden}
.feed-cl-row{display:flex;align-items:baseline;gap:1.5vw;padding:1.4vh 0;border-bottom:1px solid rgba(255,255,255,.08)}
.feed-cl-title{flex:1;font-size:3vh;font-weight:500;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.feed-cl-meta{flex:0 0 auto;font-size:2vh;color:#9aa3b2}
.feed-video-grid{position:absolute;top:0;left:0;right:0;bottom:0;display:grid;gap:1.2vh;padding:1.2vh;box-sizing:border-box}
.feed-video-cell{background:#23264a;border-radius:.6vh;overflow:hidden;display:flex;flex-direction:column;min-height:0}
.feed-video-thumb{position:relative;flex:1;background-size:cover;background-position:center;background-color:#0f1117;min-height:0;display:flex;align-items:center;justify-content:center}
.feed-video-play{width:5vh;height:5vh;border-radius:50%;background:rgba(12,14,23,.6);color:#fff;display:flex;align-items:center;justify-content:center;font-size:2.2vh;padding-left:.3vh}
.feed-video-body{padding:1vh 1vw}
.feed-video-title{font-size:2vh;font-weight:600;line-height:1.2;max-height:2.5em;overflow:hidden}
.feed-video-meta{margin-top:.5vh;font-size:1.5vh;color:#9aa3b2}`;
  document.head.appendChild(st);
}
function renderFeed(media, onReady) {
  const fc = media.feed_config || {};
  const mode = fc.display_mode || 'ticker';
  const cfg = fc.display_config || {};
  const items = Array.isArray(fc.items) ? fc.items : [];
  _injectFeedStyles();
  contentArea.style.position = 'relative';
  const root = document.createElement('div');
  root.className = 'feed-root';
  if (items.length === 0) {
    root.innerHTML = `<div class="feed-empty">${_feedEscape(media.media_name || 'Feed')}</div>`;
    contentArea.appendChild(root);
    log('feed_display: aucun item (pas encore fetché ?)'); onReady(); return;
  }
  if (mode === 'card_carousel') renderFeedCarousel(root, items, cfg);
  else if (mode === 'card_grid') renderFeedGrid(root, items, cfg);
  else if (mode === 'full_item') renderFeedFull(root, items, cfg);
  else if (mode === 'split_layout') renderFeedSplit(root, items, cfg);
  else if (mode === 'compact_list') renderFeedCompact(root, items, cfg);
  else if (mode === 'social_wall') renderFeedSocialWall(root, items, cfg);
  else if (mode === 'data_chart') renderFeedChart(root, items, cfg);
  else if (mode === 'video_feed') renderFeedVideo(root, items, cfg);
  else renderFeedTicker(root, items, cfg);
  contentArea.appendChild(root);
  log(`feed_display ready: mode=${mode}, ${items.length} item(s)`);
  onReady();
}
function renderFeedTicker(root, items, cfg) {
  const sep = cfg.separator || ' ◆ ';
  const speed = Math.max(10, parseInt(cfg.scroll_speed_px_s, 10) || 80);
  const showSource = cfg.show_source !== false;
  const sepHtml = `<span class="feed-tk-sep">${_feedEscape(sep)}</span>`;
  const parts = items.map((it) => {
    const src = (showSource && it.source) ? ` (${_feedEscape(it.source)})` : '';
    return `<span class="feed-tk-item">${_feedEscape(it.title || '')}${src}</span>`;
  });
  const seq = `<span class="feed-tk-seq">${parts.join(sepHtml)}${sepHtml}</span>`;
  const wrap = document.createElement('div');
  wrap.className = 'feed-ticker';
  const track = document.createElement('div');
  track.className = 'feed-tk-track';
  track.innerHTML = seq + seq;
  wrap.appendChild(track);
  root.appendChild(wrap);
  requestAnimationFrame(() => {
    const seqEl = track.querySelector('.feed-tk-seq');
    const w = seqEl ? seqEl.getBoundingClientRect().width : (track.scrollWidth / 2);
    const dur = Math.max(8, w / speed);
    track.style.animation = `feedTkScroll ${dur}s linear infinite`;
  });
}
function renderFeedCarousel(root, items, cfg) {
  const durS = Math.max(2, parseInt(cfg.item_duration_s, 10) || 8);
  const showImage = cfg.show_image !== false;
  const showDate = cfg.show_date !== false;
  const showSource = cfg.show_source !== false;
  const stage = document.createElement('div');
  stage.className = 'feed-carousel';
  root.appendChild(stage);
  let idx = 0;
  const render = () => {
    const it = items[idx % items.length];
    const card = document.createElement('div');
    card.className = 'feed-card ' + (cfg.transition === 'fade' ? 'feed-fade' : 'feed-slide');
    const img = (showImage && it.image_url)
      ? `<div class="feed-card-img" style="background-image:url('${_feedCssUrl(it.image_url)}')"></div>`
      : '<div class="feed-card-img feed-card-noimg"></div>';
    const meta = [];
    if (showSource && it.source) meta.push(_feedEscape(it.source));
    if (showDate && it.published_at) meta.push(_feedEscape(_feedDate(it.published_at)));
    card.innerHTML = `${img}<div class="feed-card-body">`
      + `<div class="feed-card-title">${_feedEscape(it.title || '')}</div>`
      + (meta.length ? `<div class="feed-card-meta">${meta.join(' · ')}</div>` : '')
      + '</div>';
    stage.innerHTML = '';
    stage.appendChild(card);
  };
  render();
  if (items.length > 1) {
    _feedTimer = setInterval(() => { idx = (idx + 1) % items.length; render(); }, durS * 1000);
  }
}

// Texte brut depuis une description RSS (souvent du HTML) : strip balises + entités, SANS toucher
// au DOM (pas de chargement de ressource déclenché). Le résultat repasse ensuite par _feedEscape.
// data_chart / social_wall (§25.3) — feeds proxy (crypto/financier/meteo, socials)
function _feedClamp(s, n) {
  s = String(s == null ? '' : s);
  return (n > 0 && s.length > n) ? s.slice(0, n - 1).trimEnd() + '…' : s;
}
function _feedNum(n) {
  if (typeof n !== 'number' || !isFinite(n)) return '';
  const abs = Math.abs(n);
  const dec = abs >= 1000 ? 0 : (abs >= 1 ? 2 : 6);
  try { return n.toLocaleString(undefined, { maximumFractionDigits: dec }); } catch (e) { return String(n); }
}
function _feedSparkSvg(series, w, h, color) {
  const pts = (series || []).map(Number).filter((x) => isFinite(x));
  if (pts.length < 2) return '';
  const min = Math.min.apply(null, pts), max = Math.max.apply(null, pts), span = (max - min) || 1;
  const coords = pts.map((p, i) => `${(i / (pts.length - 1) * 100).toFixed(2)},${(100 - (p - min) / span * 100).toFixed(2)}`).join(' ');
  return `<svg viewBox="0 0 100 100" preserveAspectRatio="none" style="width:${w};height:${h};display:block">`
    + `<polyline points="${coords}" fill="none" stroke="${color}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}
// social_wall : mosaique de posts (image + legende en surimpression), paginee comme card_grid.
function renderFeedSocialWall(root, items, cfg) {
  const cols = Math.min(6, Math.max(1, parseInt(cfg.grid_columns, 10) || 3));
  const rows = Math.min(4, Math.max(1, parseInt(cfg.grid_rows, 10) || 2));
  const per = cols * rows;
  const durS = Math.max(2, parseInt(cfg.item_duration_s, 10) || 8);
  const maxCap = (cfg.caption_max_chars == null) ? 140 : parseInt(cfg.caption_max_chars, 10);
  const grid = document.createElement('div');
  grid.style.cssText = 'width:100%;height:100%;display:grid;gap:1vmin;padding:1vmin;box-sizing:border-box;'
    + `grid-template-columns:repeat(${cols},1fr);grid-template-rows:repeat(${rows},1fr);`;
  root.appendChild(grid);
  const pages = Math.max(1, Math.ceil(items.length / per));
  let page = 0;
  const render = () => {
    const slice = items.slice(page * per, page * per + per);
    grid.innerHTML = slice.map((it) => {
      const bg = it.image_url
        ? `background-image:url('${_feedCssUrl(it.image_url)}');background-size:cover;background-position:center;`
        : 'background:#232636;';
      const cap = (maxCap > 0) ? _feedClamp(_feedText(it.summary || it.description || it.title || ''), maxCap) : '';
      const author = it.author ? `<div style="font-size:1.5vmin;color:#9db4d0;margin-top:.4vmin">${_feedEscape(it.author)}</div>` : '';
      return `<div style="position:relative;border-radius:1vmin;overflow:hidden;${bg}">`
        + `<div style="position:absolute;left:0;right:0;bottom:0;padding:1.2vmin;background:linear-gradient(rgba(28,30,42,0),rgba(28,30,42,.92));color:#F8F7F5;font:500 1.8vmin/1.3 Inter,sans-serif">`
        + (cap ? `<div>${_feedEscape(cap)}</div>` : '') + author
        + '</div></div>';
    }).join('');
  };
  render();
  if (pages > 1) _feedTimer = setInterval(() => { page = (page + 1) % pages; render(); }, durS * 1000);
}
// data_chart : valeurs numeriques (crypto/financier/meteo). bars (defaut) | line | gauge.
function renderFeedChart(root, items, cfg) {
  const type = cfg.chart_type || 'bars';
  const showChange = cfg.show_change !== false;
  const wrap = document.createElement('div');
  wrap.style.cssText = 'width:100%;height:100%;box-sizing:border-box;padding:3vmin;color:#F8F7F5;'
    + 'font-family:Inter,sans-serif;display:flex;flex-direction:column;gap:2vmin;';
  root.appendChild(wrap);
  const nums = items.filter((it) => typeof it.value_num === 'number' && isFinite(it.value_num));
  if (nums.length === 0) {
    wrap.style.alignItems = 'center'; wrap.style.justifyContent = 'center';
    wrap.innerHTML = '<div style="color:#9db4d0;font-size:2.4vmin">No data</div>'; return;
  }
  const chg = (c) => (typeof c === 'number')
    ? `<span style="color:${c >= 0 ? '#3FB984' : '#E5484D'};font-weight:600">${c >= 0 ? '▲' : '▼'} ${Math.abs(c).toFixed(2)}%</span>` : '';
  const val = (it) => `${_feedNum(it.value_num)}${it.value_unit ? ' ' + _feedEscape(it.value_unit) : ''}`;
  const withSeries = nums.find((x) => Array.isArray(x.series) && x.series.length > 1);
  if (type === 'gauge') {
    const it = nums[0];
    wrap.style.alignItems = 'center'; wrap.style.justifyContent = 'center'; wrap.style.textAlign = 'center';
    const spark = (Array.isArray(it.series) && it.series.length > 1)
      ? `<div style="margin-top:2vmin">${_feedSparkSvg(it.series, '60vw', '18vh', '#4875B4')}</div>` : '';
    wrap.innerHTML = `<div style="font-size:3vmin;color:#9db4d0;margin-bottom:1vmin">${_feedEscape(it.title || '')}</div>`
      + `<div style="font-size:12vmin;font-weight:700;line-height:1">${val(it)}</div>`
      + (showChange ? `<div style="font-size:3.5vmin;margin-top:1vmin">${chg(it.change_pct)}</div>` : '') + spark;
  } else if (type === 'line' && withSeries) {
    const it = withSeries;
    wrap.innerHTML = `<div style="font-size:3vmin;font-weight:600">${_feedEscape(it.title || '')} `
      + `<span style="color:#9db4d0;font-size:2.4vmin">${val(it)} ${showChange ? chg(it.change_pct) : ''}</span></div>`
      + `<div style="flex:1;min-height:0">${_feedSparkSvg(it.series, '100%', '100%', (it.change_pct >= 0 ? '#3FB984' : '#4875B4'))}</div>`;
  } else {
    const max = Math.max.apply(null, nums.map((x) => Math.abs(x.value_num))) || 1;
    wrap.innerHTML = nums.map((it) => {
      const pct = Math.max(2, Math.min(100, Math.abs(it.value_num) / max * 100));
      const col = (typeof it.change_pct === 'number') ? (it.change_pct >= 0 ? '#3FB984' : '#E5484D') : '#4875B4';
      return '<div style="display:flex;align-items:center;gap:2vmin">'
        + `<div style="width:24%;font-size:2.2vmin;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${_feedEscape(it.title || '')}</div>`
        + `<div style="flex:1;background:#232636;border-radius:1vmin;height:4vmin"><div style="width:${pct}%;height:100%;background:${col};border-radius:1vmin"></div></div>`
        + `<div style="width:26%;text-align:right;font-size:2.2vmin;font-weight:600">${val(it)} ${showChange ? chg(it.change_pct) : ''}</div>`
        + '</div>';
    }).join('');
  }
}
function _feedText(s) {
  return String(s == null ? '' : s)
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>').replace(/&quot;/gi, '"').replace(/&#39;|&apos;/gi, "'")
    .replace(/&[a-z0-9#]+;/gi, '')
    .replace(/\s+/g, ' ').trim();
}
function _feedMeta(it, cfg) {
  const m = [];
  if (cfg.show_source !== false && it.source) m.push(_feedEscape(it.source));
  if (cfg.show_date !== false && it.published_at) m.push(_feedEscape(_feedDate(it.published_at)));
  return m;
}
function _feedImgStyle(it) {
  return (it && it.image_url) ? `background-image:url('${_feedCssUrl(it.image_url)}')` : '';
}
// card_grid : grille cols×rows, paginée automatiquement s'il y a plus d'items qu'une page.
function renderFeedGrid(root, items, cfg) {
  const cols = Math.min(6, Math.max(1, parseInt(cfg.grid_columns, 10) || 3));
  const rows = Math.min(4, Math.max(1, parseInt(cfg.grid_rows, 10) || 2));
  const per = cols * rows;
  const durS = Math.max(2, parseInt(cfg.item_duration_s, 10) || 8);
  const showImage = cfg.show_image !== false;
  const grid = document.createElement('div');
  grid.className = 'feed-grid';
  grid.style.gridTemplateColumns = `repeat(${cols},1fr)`;
  grid.style.gridTemplateRows = `repeat(${rows},1fr)`;
  root.appendChild(grid);
  const pages = Math.max(1, Math.ceil(items.length / per));
  let page = 0;
  const render = () => {
    const slice = items.slice(page * per, page * per + per);
    grid.innerHTML = slice.map((it) => {
      const img = (showImage && it.image_url)
        ? `<div class="feed-grid-img" style="${_feedImgStyle(it)}"></div>`
        : '<div class="feed-grid-img feed-card-noimg"></div>';
      const meta = _feedMeta(it, cfg);
      return '<div class="feed-grid-cell">' + img + '<div class="feed-grid-body">'
        + `<div class="feed-grid-title">${_feedEscape(it.title || '')}</div>`
        + (meta.length ? `<div class="feed-grid-meta">${meta.join(' · ')}</div>` : '')
        + '</div></div>';
    }).join('');
  };
  render();
  if (pages > 1) {
    _feedTimer = setInterval(() => { page = (page + 1) % pages; render(); }, durS * 1000);
  }
}
// full_item : 1 item plein écran (image de fond + titre / description / méta en surimpression).
// Ajuste la police d'un bloc texte de feed (titre/desc) pour que TOUT le contenu tienne
// dans `maxLines` lignes : réduction par paliers tant que ça déborde (mesure pixel → OK
// aussi en multi-zones). Évite les titres coupés en plein milieu (retour terrain : titres
// longs Le Monde « Présidentielle 2027 : … »).
function _feedFit(el, maxLines) {
  if (!el) return;
  el.style.overflow = 'hidden';
  const lh = () => { const cs = getComputedStyle(el); const v = parseFloat(cs.lineHeight); return isNaN(v) ? parseFloat(cs.fontSize) * 1.25 : v; };
  let guard = 18;
  while (el.scrollHeight > lh() * maxLines + 1 && guard-- > 0) {
    const cur = parseFloat(getComputedStyle(el).fontSize);
    if (cur <= 13) break;
    el.style.fontSize = (cur * 0.9).toFixed(1) + 'px';
  }
  el.style.maxHeight = Math.ceil(lh() * maxLines) + 'px';
}
function renderFeedFull(root, items, cfg) {
  const durS = Math.max(2, parseInt(cfg.item_duration_s, 10) || 8);
  const showImage = cfg.show_image !== false;
  const showDesc = cfg.show_description !== false;
  const stage = document.createElement('div');
  stage.className = 'feed-carousel';
  root.appendChild(stage);
  let idx = 0;
  const render = () => {
    const it = items[idx % items.length];
    const el = document.createElement('div');
    el.className = 'feed-full ' + (cfg.transition === 'fade' ? 'feed-fade' : 'feed-slide');
    if (showImage && it.image_url) el.style.backgroundImage = `url('${_feedCssUrl(it.image_url)}')`;
    else el.classList.add('feed-card-noimg');
    const meta = _feedMeta(it, cfg);
    const desc = (showDesc && (it.summary || it.description))
      ? `<div class="feed-full-desc">${_feedEscape(_feedText(it.summary || it.description))}</div>` : '';
    el.innerHTML = '<div class="feed-full-shade">'
      + `<div class="feed-full-title">${_feedEscape(it.title || '')}</div>`
      + desc
      + (meta.length ? `<div class="feed-full-meta">${meta.join(' · ')}</div>` : '')
      + '</div>';
    stage.innerHTML = '';
    stage.appendChild(el);
    _feedFit(el.querySelector('.feed-full-title'), 4);
    _feedFit(el.querySelector('.feed-full-desc'), 6);
  };
  render();
  if (items.length > 1) {
    _feedTimer = setInterval(() => { idx = (idx + 1) % items.length; render(); }, durS * 1000);
  }
}
// split_layout : image d'un côté, texte de l'autre (côté de l'image = cfg.split_side).
function renderFeedSplit(root, items, cfg) {
  const durS = Math.max(2, parseInt(cfg.item_duration_s, 10) || 8);
  const showImage = cfg.show_image !== false;
  const showDesc = cfg.show_description !== false;
  const imgRight = cfg.split_side === 'right';
  const stage = document.createElement('div');
  stage.className = 'feed-carousel';
  root.appendChild(stage);
  let idx = 0;
  const render = () => {
    const it = items[idx % items.length];
    const el = document.createElement('div');
    el.className = 'feed-split ' + (imgRight ? 'img-right ' : '')
      + (cfg.transition === 'fade' ? 'feed-fade' : 'feed-slide');
    const img = (showImage && it.image_url)
      ? `<div class="feed-split-img" style="${_feedImgStyle(it)}"></div>`
      : '<div class="feed-split-img feed-card-noimg"></div>';
    const meta = _feedMeta(it, cfg);
    const desc = (showDesc && (it.summary || it.description))
      ? `<div class="feed-split-desc">${_feedEscape(_feedText(it.summary || it.description))}</div>` : '';
    el.innerHTML = img + '<div class="feed-split-body">'
      + `<div class="feed-split-title">${_feedEscape(it.title || '')}</div>`
      + desc
      + (meta.length ? `<div class="feed-split-meta">${meta.join(' · ')}</div>` : '')
      + '</div>';
    stage.innerHTML = '';
    stage.appendChild(el);
    _feedFit(el.querySelector('.feed-split-title'), 4);
    _feedFit(el.querySelector('.feed-split-desc'), 8);
  };
  render();
  if (items.length > 1) {
    _feedTimer = setInterval(() => { idx = (idx + 1) % items.length; render(); }, durS * 1000);
  }
}
// compact_list : liste statique titre + méta (façon sidebar info). Pas de rotation.
function renderFeedCompact(root, items, cfg) {
  const list = document.createElement('div');
  list.className = 'feed-compact';
  list.innerHTML = items.map((it) => {
    const meta = _feedMeta(it, cfg);
    return '<div class="feed-cl-row">'
      + `<div class="feed-cl-title">${_feedEscape(it.title || '')}</div>`
      + (meta.length ? `<div class="feed-cl-meta">${meta.join(' · ')}</div>` : '')
      + '</div>';
  }).join('');
  root.appendChild(list);
}

// video_feed : grille de vignettes vidéo (chaîne YouTube). Poster (media:thumbnail) + badge ▶
// + titre + méta. On NE lit PAS la vidéo (YouTube non framable) → affichage des dernières vidéos.
// Paginée comme card_grid (grid_columns × grid_rows, rotation item_duration_s).
function renderFeedVideo(root, items, cfg) {
  const cols = Math.min(6, Math.max(1, parseInt(cfg.grid_columns, 10) || 3));
  const rows = Math.min(4, Math.max(1, parseInt(cfg.grid_rows, 10) || 2));
  const per = cols * rows;
  const durS = Math.max(2, parseInt(cfg.item_duration_s, 10) || 8);
  const grid = document.createElement('div');
  grid.className = 'feed-video-grid';
  grid.style.gridTemplateColumns = `repeat(${cols},1fr)`;
  grid.style.gridTemplateRows = `repeat(${rows},1fr)`;
  root.appendChild(grid);
  const pages = Math.max(1, Math.ceil(items.length / per));
  let page = 0;
  const render = () => {
    const slice = items.slice(page * per, page * per + per);
    grid.innerHTML = slice.map((it) => {
      const thumbCls = it.image_url ? 'feed-video-thumb' : 'feed-video-thumb feed-card-noimg';
      const playIcon = cfg.show_play_icon !== false ? '<div class="feed-video-play">▶</div>' : '';
      const thumb = `<div class="${thumbCls}" style="${_feedImgStyle(it)}">${playIcon}</div>`;
      const meta = _feedMeta(it, cfg);
      return '<div class="feed-video-cell">' + thumb + '<div class="feed-video-body">'
        + `<div class="feed-video-title">${_feedEscape(it.title || '')}</div>`
        + (meta.length ? `<div class="feed-video-meta">${meta.join(' · ')}</div>` : '')
        + '</div></div>';
    }).join('');
  };
  render();
  if (pages > 1) {
    _feedTimer = setInterval(() => { page = (page + 1) % pages; render(); }, durS * 1000);
  }
}

function applyTransition(type, cb) {
  if (type === 'fade') {
    contentArea.style.opacity = '0';
    setTimeout(() => { cb(); contentArea.style.opacity = '1'; }, 150);
  } else {
    cb();
  }
}

// ── Zones de template (§25.4) — moteur multi-zones ──────────────────────────────
//
// Un template à PLUSIEURS zones (payload.template) → on rend chaque zone simultanément :
// un conteneur DOM positionné (% du canvas) par zone, chacun déroulant SA sous-playlist
// (items filtrés par zone_index côté serveur) avec SON wall-clock (start_index/offset par
// zone) et SA boucle d'avance. Rendu 100 % Chromium (image/<video>/feed/url/PDF) — JAMAIS
// mpv/exo (une fenêtre/surface native ne se confine pas proprement dans une sous-zone) : le
// HW decode mpv/exo reste réservé au plein écran mono-zone. Module ISOLÉ : il ne touche pas
// le chemin mono-zone (LAN sync / mpv / VOD), qui reste intact. Pas de sync LAN inter-players
// en multi-zones (chaque zone est déterministe via son wall-clock → cohérente sans broadcast).
let _mzActive  = false;   // un template multi-zones est en cours de rendu
let _mzFP      = null;    // empreinte du contenu multi-zones courant (anti-restart)
let _mzZones   = [];      // runtime par zone : { def, el, items, index, timer, video, feedTimer, urlTimer }
let _mzPayload = null;    // dernier payload multi-zones (patch offline-first + persistance)

// Empreinte d'un item (identique à _getContentFP : id_item + objet servi + durée + identité feed).
function _mzItemFP(it) {
  let extra = '';
  const fc = it.media && it.media.feed_config;
  if (fc) {
    const fi = (fc.items || []).map((x) => `${x.link_url || x.title || ''}@${x.published_at || ''}@${x.summary ? 1 : 0}@${x.image_cache_key || ''}@${x.image_url && /^https?:/i.test(x.image_url) ? 'R' : 'L'}`).join('~');
    extra = `#feed:${fc.display_mode || ''}:${JSON.stringify(fc.display_config || {})}:${fi}`;
  }
  // offline-first : inclure si l'URL est servie en LOCAL (signflow:// / file:// / SW) vs MinIO
  // (http). Une bascule remote→local (mise en cache) DOIT re-render la zone, sinon la vidéo
  // continue de streamer et gèle puis passe au noir hors-ligne. On code le FLAG, pas l'URL (la
  // signature de l'URL signée MinIO change à chaque sync → re-render parasite sinon).
  const _u = (it.media && it.media.url) || '';
  const _loc = /^https?:/i.test(_u) ? 'R' : 'L';
  // P3.6 : le MARQUAGE campagne fait partie de l'identite de l'item. Sans lui, basculer
  // `campaign_placement` (plein ecran <-> zone principale) laisse une empreinte IDENTIQUE --
  // meme media, meme duree, meme URL, et un spot n'a meme pas d'`id_item` -- donc
  // `handleMultiZoneSync` repond « same content already playing » et le changement
  // n'atteint JAMAIS l'ecran (constate par Ed le 2026-08-06 : template bascule en plein
  // ecran, spot toujours rendu dans la zone, alors que le serveur envoyait bien
  // `campaign.fullscreen = true` -- mesure sur les 3 players).
  const _ad = it.campaign ? `#ad:${it.campaign.fullscreen ? 1 : 0}` : '';
  return `${_ad}${it.id_item}@${it.media && it.media.cache_key ? it.media.cache_key : ''}@${it.duration_ms ?? ''}@${_loc}${extra}`;
}

function _mzFingerprint(tmpl) {
  const zones = (tmpl.zones || []).map((z) => {
    const items = (z.items || []).map(_mzItemFP).join(',');
    return `${z.index}|${z.x},${z.y},${z.w},${z.h}|${items}`;
  }).join(';');
  return `tpl:${tmpl.id_template ?? '_'}:${tmpl.layout_type ?? ''}:${tmpl.canvas_width}x${tmpl.canvas_height}:${zones}`;
}

// Point d'entrée appelé par onSync. Retourne true si le multi-zones prend le relais.
function handleMultiZoneSync(payload) {
  const tmpl = payload && payload.template;
  if (!tmpl || !Array.isArray(tmpl.zones) || tmpl.zones.length <= 1) return false;
  _mzPayload = payload;                  // réf pour le patch offline-first (même si contenu identique)
  const fp = _mzFingerprint(tmpl);
  if (_mzActive && fp === _mzFP) {
    log('Multi-zone sync ignored: same content already playing');
    return true;
  }
  enterMultiZone(payload, tmpl, fp);
  return true;
}

function enterMultiZone(payload, tmpl, fp) {
  // Démonte le chemin mono-zone (vidéo/mpv/feed/url/préchargement/avance) sans rien rejouer.
  clearTimeout(itemTimer);
  _releaseVideo(_activeVideo); _activeVideo = null;
  if (typeof mpvHide === 'function') mpvHide();   // mpv = linux/NUC only ; absent ici → garde anti-ReferenceError (sinon enterMultiZone throw → écran noir)
  if (_urlRefreshTimer) { clearInterval(_urlRefreshTimer); _urlRefreshTimer = null; }
  if (_feedTimer) { clearInterval(_feedTimer); _feedTimer = null; }
  clearPreload();
  playlist = null; _pendingSync = null; _currentContentFP = null;
  _mzTeardownZones();   // démonte d'éventuelles zones précédentes

  saveSync(payload);    // boot offline-first : on rejouera ce payload (zones incluses)
  fallbackScreen.classList.add('hidden');
  _injectFeedStyles();
  contentArea.innerHTML = '';
  contentArea.style.position = 'relative';
  contentArea.style.background = '#000';

  const cw = tmpl.canvas_width || 1920;
  const ch = tmpl.canvas_height || 1080;
  _mzZones = [];
  for (const def of tmpl.zones) {
    const el = document.createElement('div');
    el.className = 'mz-zone';
    el.style.cssText =
      `position:absolute;overflow:hidden;background:#000;` +
      `left:${(def.x / cw) * 100}%;top:${(def.y / ch) * 100}%;` +
      `width:${(def.w / cw) * 100}%;height:${(def.h / ch) * 100}%;`;
    contentArea.appendChild(el);
    // Garde quarantaine (§ Q5) : ne jamais jouer un média bloqué, même offline.
    const items = (def.items || []).filter((it) => !_blockedMedia.has(it.media && it.media.id_media));
    const z = {
      def, el, items,
      index: def.start_index || 0,
      timer: null, video: null, feedTimer: null, urlTimer: null,
    };
    _mzZones.push(z);
    _mzPlayZone(z, def.start_offset_ms || 0);
  }
  _mzActive = true;
  _mzFP = fp;
  log(`Multi-zone: ${_mzZones.length} zone(s) started (${cw}x${ch})`);
}

function exitMultiZone() {
  if (!_mzActive) return;
  _mzTeardownZones();
  contentArea.innerHTML = '';
  contentArea.style.transform = '';
  _mzActive = false; _mzFP = null; _mzPayload = null;
  _currentContentFP = null;   // force le re-render du contenu mono-zone par applyPlayback
  log('Multi-zone torn down → back to single-zone');
}

function _mzTeardownZones() {
  for (const z of _mzZones) _mzReleaseZone(z);
  _mzZones = [];
}

function _mzReleaseZone(z) {
  // Un spot plein ecran en cours doit partir avec la zone : sinon un nouveau sync
  // laisserait le creatif colle par-dessus le nouveau contenu, et les zones muettes.
  if (z.adOverlay) { try { z.adOverlay.close(); } catch (e) {} z.adOverlay = null; }
  if (z.timer) { clearTimeout(z.timer); z.timer = null; }
  if (z.feedTimer) { clearInterval(z.feedTimer); z.feedTimer = null; }
  if (z.urlTimer) { clearInterval(z.urlTimer); z.urlTimer = null; }
  if (z.video) { _releaseVideo(z.video); z.video = null; }
  try { z.el.innerHTML = ''; } catch {}
}

function _mzScheduleAdvance(z, delayMs) {
  if (z.timer) clearTimeout(z.timer);
  z.timer = setTimeout(() => {
    if (!z.items || z.items.length === 0) return;
    z.index = (z.index + 1) % z.items.length;
    _mzPlayZone(z, 0);
  }, Math.max(0, delayMs));
}

// Mute/démute les vidéos des zones (takeover VOD par-dessus le multi-zones).
function _mzSetMuted(muted) {
  for (const z of _mzZones) { if (z.video) { try { z.video.muted = muted; } catch {} } }
}

function _mzPlayZone(z, seekMs) {
  // Libère l'item précédent de CETTE zone (vidéo / timers feed-url).
  if (z.timer) { clearTimeout(z.timer); z.timer = null; }
  if (z.feedTimer) { clearInterval(z.feedTimer); z.feedTimer = null; }
  if (z.urlTimer) { clearInterval(z.urlTimer); z.urlTimer = null; }
  if (z.video) { _releaseVideo(z.video); z.video = null; }
  z.el.innerHTML = '';
  if (!z.items || z.items.length === 0) return;   // zone vide → rien à jouer

  const item = z.items[z.index % z.items.length];
  const dur = item.duration_ms || 10000;
  const effectiveDur = Math.max(0, dur - (seekMs || 0));
  // P3.6 — Retail Media x multi-zones. Un spot marque `fullscreen` par le serveur
  // (campaign_placement du template) RECOUVRE tout l'ecran : c'est le seul mode coherent
  // avec la tarification au SOV, qui suppose une exposition plein ecran. Les autres zones
  // continuent de tourner DESSOUS (leur wall-clock reste vrai, donc aucune derive au
  // retour) : elles sont couvertes et muettes, jamais suspendues.
  // `fullscreen: false` (mode `zone`) = item normal de la zone principale -> chemin habituel.
  if (item.campaign && item.campaign.fullscreen) {
    _mzPlayFullscreenAd(z, item, effectiveDur, seekMs || 0);
    return;
  }
  _mzRenderInZone(
    z, item,
    () => { reportPlay(item, effectiveDur); _mzScheduleAdvance(z, effectiveDur); },  // Proof of Play par zone
    () => _mzScheduleAdvance(z, ERROR_SKIP_MS),
    seekMs || 0,
  );
}

// P3.6 — spot de campagne PLEIN ECRAN par-dessus les zones.
//
// On reutilise `_mzRenderInZone` en lui passant un conteneur plein ecran comme s'il
// s'agissait d'une zone : toute la gestion des types de media (image / video / feed / url /
// document) est ainsi partagee. Ecrire un second moteur de rendu ici aurait garanti qu'il
// diverge du premier.
//
// Le spot appartient a la timeline de la ZONE PRINCIPALE (c'est elle qui le declenche) ;
// le recouvrement n'est qu'un mode d'affichage. Les autres zones ne sont pas suspendues :
// les suspendre decalerait leur wall-clock et desynchroniserait l'ecran au retour.
function _mzPlayFullscreenAd(z, item, dur, seekMs) {
  const el = document.createElement('div');
  el.className = 'mz-ad-overlay';
  el.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;z-index:50;background:#000;';
  contentArea.appendChild(el);
  _mzSetMuted(true);            // les zones se taisent le temps du spot (politique du takeover VOD)

  const pseudo = { el, items: [item], index: 0, video: null };
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    if (pseudo.video) { try { _releaseVideo(pseudo.video); } catch (e) {} pseudo.video = null; }
    try { el.remove(); } catch (e) {}
    _mzSetMuted(_contentMuted);  // on rend le son aux zones
    z.adOverlay = null;
  };
  z.adOverlay = { el, close };

  _mzRenderInZone(
    pseudo, item,
    () => {
      // Proof of Play : le spot est facture, sa preuve doit partir. `z.adOverlay` est le
      // SIEN (pose juste au-dessus) => il ne se marque pas lui-meme ; mais un takeover VOD
      // par-dessus le marquerait, et c'est juste : ce spot-la n'a pas ete vu.
      reportPlay(item, dur, _coveredNow(z.adOverlay));
      if (z.timer) clearTimeout(z.timer);
      z.timer = setTimeout(() => {
        close();
        if (!z.items || z.items.length === 0) return;
        z.index = (z.index + 1) % z.items.length;
        _mzPlayZone(z, 0);
      }, Math.max(0, dur));
    },
    () => { close(); _mzScheduleAdvance(z, ERROR_SKIP_MS); },
    seekMs || 0,
  );
}

// Rendu d'un item DANS une zone (Chromium uniquement). Calque renderItem mais scoppé au
// conteneur de zone (pas de mpv, pas de _activeVideo global, pas de sous-titres en zone).
function _mzRenderInZone(z, item, onReady, onError, seekMs) {
  const media = item.media;
  if (!media || (!media.url && media.media_type !== 'feed_display')) {
    z.el.innerHTML = '<div class="slide-error">Media unavailable</div>';
    onError();
    return;
  }
  const t0 = Date.now();

  if (media.media_type === 'video') {
    const v = document.createElement('video');
    v.src = media.url; v.autoplay = true; v.playsInline = true; v.muted = _contentMuted;
    // loop=true : la vidéo de zone ne doit JAMAIS atteindre l'état "ended" (Chromium 83 y dessine
    // son bouton replay, que la CSS ne masque pas toujours sur Amlogic). L'avance d'item reste
    // pilotée par le timer _mzScheduleAdvance(duration_ms) → la boucle est juste un filet pour le
    // créneau, jamais visible si duration_ms = durée réelle.
    v.loop = true; v.controls = false;
    v.style.cssText = 'width:100%;height:100%;object-fit:contain;background:#000';
    // Caché jusqu'à la 1re frame réellement présentée → la WebView Chromium 83 n'affiche pas son
    // bouton "play" (cercle + flèche) en surimpression au démarrage de chaque vidéo de zone (parité
    // avec le chemin mono-zone). `playing` précède la 1re frame peinte → on révèle sur `timeupdate`
    // (currentTime > 0 et lecture non pausée). Repli anti-écran-noir : révéler après 3s sans event.
    v.style.visibility = 'hidden';
    let _shown = false;
    const reveal = () => {
      if (_shown || v.paused || !(v.currentTime > 0)) return;
      _shown = true;
      v.removeEventListener('timeupdate', reveal);
      v.removeEventListener('playing', reveal);
      v.style.visibility = 'visible';
    };
    v.addEventListener('timeupdate', reveal);
    v.addEventListener('playing', reveal);
    const startPlay = () => {
      v.play().catch(() => { v.muted = true; v.play().catch(() => {}); });
    };
    v.oncanplay = () => {
      v.oncanplay = null;
      if (seekMs > 0) {
        v.onseeked = () => { v.onseeked = null; startPlay(); };
        v.currentTime = seekMs / 1000;
      } else { startPlay(); }
      onReady();
      setTimeout(() => { if (!_shown) { _shown = true; v.style.visibility = 'visible'; } }, 3000);
    };
    v.onerror = () => { _releaseVideo(v); try { v.remove(); } catch {} z.video = null; requestResyncDebounced('zone video error'); onError(); };
    z.el.appendChild(v);
    z.video = v;

  } else if (media.media_type === 'image') {
    const img = document.createElement('img');
    img.src = media.url; img.alt = media.media_name || '';
    img.style.cssText = 'width:100%;height:100%;object-fit:contain;background:#000';
    img.onload = () => onReady();
    img.onerror = () => { try { img.removeAttribute('src'); img.remove(); } catch {} requestResyncDebounced('zone image error'); onError(); };
    z.el.appendChild(img);

  } else if (media.media_type === 'feed_display') {
    const fc = media.feed_config || {};
    const mode = fc.display_mode || 'ticker';
    const cfg = fc.display_config || {};
    const items = Array.isArray(fc.items) ? fc.items : [];
    const root = document.createElement('div');
    root.className = 'feed-root';
    if (items.length === 0) {
      root.innerHTML = `<div class="feed-empty">${_feedEscape(media.media_name || 'Feed')}</div>`;
      z.el.appendChild(root); onReady(); return;
    }
    // Les renderers de feed posent leur intervalle de rotation sur le global _feedTimer (chemin
    // mono-zone). En multi-zones on le « vole » juste après l'appel pour le gérer par zone (sinon
    // deux feeds dans deux zones se piétineraient l'unique _feedTimer).
    if (mode === 'card_carousel') renderFeedCarousel(root, items, cfg);
    else if (mode === 'card_grid') renderFeedGrid(root, items, cfg);
    else if (mode === 'full_item') renderFeedFull(root, items, cfg);
    else if (mode === 'split_layout') renderFeedSplit(root, items, cfg);
    else if (mode === 'compact_list') renderFeedCompact(root, items, cfg);
    else if (mode === 'social_wall') renderFeedSocialWall(root, items, cfg);
  else if (mode === 'data_chart') renderFeedChart(root, items, cfg);
  else if (mode === 'video_feed') renderFeedVideo(root, items, cfg);
    else renderFeedTicker(root, items, cfg);
    if (_feedTimer) { z.feedTimer = _feedTimer; _feedTimer = null; }
    z.el.appendChild(root);
    onReady();

  } else if (media.media_type === 'url_display') {
    const cfg = media.url_config || {};
    if (cfg.render_mode === 'screenshot_server') {
      const img = document.createElement('img');
      img.src = media.url;
      img.style.cssText = 'width:100%;height:100%;object-fit:contain;background:#000';
      img.onload = () => onReady();
      img.onerror = () => { try { img.remove(); } catch {} onError(); };
      z.el.appendChild(img);
    } else {
      const iframe = document.createElement('iframe');
      iframe.src = media.url;
      const zoom = (typeof cfg.zoom === 'number' && cfg.zoom > 0) ? cfg.zoom : 1;
      const inv = 100 / zoom;
      const interaction = (cfg.interaction_blocked !== false);
      iframe.style.cssText =
        `position:absolute;top:0;left:0;width:${inv}%;height:${inv}%;border:none;background:#000;` +
        `transform:scale(${zoom});transform-origin:0 0;` + (interaction ? 'pointer-events:none;' : '');
      let done = false;
      const timer = setTimeout(() => { if (done) return; done = true; onReady(); }, WEB_LOAD_TIMEOUT_MS);
      iframe.onload = () => { if (done) return; done = true; clearTimeout(timer); onReady(); };
      iframe.onerror = () => { if (done) return; done = true; clearTimeout(timer); try { iframe.remove(); } catch {} onError(); };
      const refreshS = parseInt(cfg.refresh_interval_s, 10) || 0;
      if (refreshS > 0) z.urlTimer = setInterval(() => { try { iframe.src = media.url; } catch {} }, refreshS * 1000);
      z.el.appendChild(iframe);
    }

  } else if (media.media_type === 'document' || media.media_type === 'html_package') {
    const iframe = document.createElement('iframe');
    iframe.src = media.media_type === 'document'
      ? `${media.url}#toolbar=0&navpanes=0&scrollbar=0&view=Fit` : media.url;
    iframe.style.cssText = `width:100%;height:100%;border:none;background:${media.media_type === 'document' ? '#fff' : '#000'}`;
    let done = false;
    const timer = setTimeout(() => { if (done) return; done = true; try { iframe.src = 'about:blank'; iframe.remove(); } catch {} onError(); }, WEB_LOAD_TIMEOUT_MS);
    iframe.onload = () => { if (done) return; done = true; clearTimeout(timer); onReady(); };
    z.el.appendChild(iframe);

  } else {
    z.el.innerHTML = `<div class="slide-error">Unsupported: ${media.media_type}</div>`;
    onError();
  }
}


// ── LAN sync : report de position + ajustement fin par playbackRate ───────────
//
// Piste B : au lieu de seeker (latence de decodage ~200ms sur RPi, micro-stutter),
// on nudge la vitesse de lecture du slave vers la cible du leader.
//   drift > MAX_SEEK_MS  → seek brutal (gros ecart, ex. demarrage decale)
//   drift > DEAD_ZONE_MS → playbackRate 1.05 / 0.95 sur ~2s puis retour a 1.0
//   drift <= DEAD_ZONE   → rien (deja aligne)

const DEAD_ZONE_MS = 40;     // en-deca, on ne touche a rien (imperceptible)
// Seuil du SEEK dur RELEVE 400ms → 3000ms. Sur un player lent (ex. AOpen Intel HD 6000,
// decode logiciel), un seek GELE la video ~1.5s ; pendant ce gel le master avance d'autant
// → re-drift ~1.5s → re-seek → BOUCLE qui ne converge jamais (le master diffuse pourtant une
// timeline parfaitement lineaire, verifie au sniff UDP). En-dessous de ce seuil on NUDGE la
// vitesse (sans gel) → suit la timeline en douceur. Le seek dur est reserve aux VRAIS gros
// decrochages (demarrage, mauvais item, post-pause) ou un gel ponctuel est acceptable.
const MAX_SEEK_MS  = 3000;
// Nudge adaptatif : le taux varie avec le drift (au lieu d'un +/-5% fixe qui mettait ~8s a
// rattraper 400ms et ne refermait jamais un drift de 1.5s) — vise une convergence en ~6s,
// plafonnee a +/-12% (au-dela c'est audible/visible). Re-evalue a chaque broadcast (2s).
const NUDGE_MIN_RATE  = 0.05;   // taux plancher (petits ecarts)
const NUDGE_MAX_RATE  = 0.12;   // taux plafond (gros ecarts, < seuil de seek)
const NUDGE_CONVERGE_MS = 6000; // fenetre de convergence visee
// Cooldown anti-rafale : apres un seek, la video gele ~200-600ms (decodage). Pendant
// ce temps le leader avance → drift artificiel → re-seek → cercle vicieux d'oscillation.
// On ignore toute correction pendant ce delai pour laisser le decodage se stabiliser.
const SEEK_COOLDOWN_MS = 3000;
// Grâce de frontière : juste après un (re)démarrage d'item (notamment une boucle sur une
// vidéo courte), un gros drift est souvent un TRANSITOIRE de chargement (les players ne
// rebouclent pas à la ms près + gap de décodage). On évite le SEEK dur (saut visible) pendant
// ce délai et on laisse switch_at aligner la bascule + le nudge absorber le reste. Passé la
// grâce, un gros écart est un vrai décrochage → seek.
const BOUNDARY_GRACE_MS = 1500;

let _lastSeekAt = 0;  // timestamp du dernier seek (pour le cooldown)
let _itemStartedAt = 0;  // timestamp du (re)démarrage de l'item courant (grâce de frontière)
let _lastLanJumpAt = 0;            // timestamp du dernier saut d'item LAN (anti-thrash)
const LAN_JUMP_COOLDOWN_MS = 3000; // laisse le nouvel item démarrer avant un nouveau saut
let _lanCatchupIdx   = -1;          // index cible d'un décalage LAN en cours d'observation
let _lanCatchupSince = 0;           // depuis quand ce décalage persiste
const LAN_CATCHUP_CONFIRM_MS = 4000; // ne sauter que si le décalage PERSISTE (anti-oscillation de frontière)

// Remonte la position video reelle au main process toutes les secondes
setInterval(() => {
  // On reporte AUSSI sur les items non-vidéo (image, PDF/document, web). Sans ça, le maître
  // ne diffusait pas le switch_at pendant une image → les followers dérivaient sur leur timer
  // local et se rattrapaient à la vidéo suivante. Pour un item sans vidéo, offsetMs n'a pas de
  // sens (0) ; seul le switch_at aligne la bascule (onLanSwitch est agnostique au type).
  if (playlist && _currentSwitchAt != null) {
    const onVideo = _activeVideo && !_activeVideo.paused;
    // Feuilletage en cours : ne PAS diffuser ma position. Si je suis leader, j'entrainerais
    // tout le groupe sur les gestes d'un passant.
    if (touchInteracting()) return;
    window.signflow.reportPlaybackPos({
      id_playlist:  _currentPlaylistId,
      currentIndex: currentIndex,
      offsetMs:     onVideo ? Math.round(_activeVideo.currentTime * 1000) : 0,
      switchAt:     _currentSwitchAt,   // #2b : instant absolu de la prochaine bascule
      nextIndex:    _currentNextIndex,
    });
  }
}, 1000);

window.signflow.onLanAdjust((adj) => {
  // Feuilletage en cours : cet ecran est pilote a la main, il n'est plus sur l'horloge du
    // groupe -- le laisser corriger le ramenerait de force sur la page du leader.
    if (touchInteracting()) return;
    // Rattrapage d'item (catch-up) : même playlist mais MAUVAIS item → on a pris un item
  // de retard/avance (frontière switch_at ratée, démarrage décalé sur une machine lente…).
  // onLanAdjust (offset seul) et onLanSwitch ignorent tout index différent → sans ce saut
  // dur, la désync est PERMANENTE. On saute directement à l'item + offset du leader, comme
  // un sync serveur. Le leader rediffuse toutes les 2s → ré-alignement ≤2s, sans serveur.
  if (playlist && adj.id_playlist === _currentPlaylistId &&
      adj.start_index !== currentIndex && playlist[adj.start_index] && !_pendingSync) {
    // Anti-oscillation : à une frontière d'item, leader et slave la franchissent à un instant
    // près → décalage d'index TRANSITOIRE (résolu seul par switch_at/advance). Ne sauter que si
    // le MÊME décalage PERSISTE ≥ LAN_CATCHUP_CONFIRM_MS (slave réellement bloqué un item derrière).
    if (_lanCatchupIdx !== adj.start_index) { _lanCatchupIdx = adj.start_index; _lanCatchupSince = Date.now(); return; }
    if (Date.now() - _lanCatchupSince < LAN_CATCHUP_CONFIRM_MS) return;
    if (Date.now() - _lastLanJumpAt < LAN_JUMP_COOLDOWN_MS) return;  // laisse le nouvel item démarrer
    _lastLanJumpAt = Date.now(); _lanCatchupIdx = -1;
    log(`[LAN] Item catch-up: ${currentIndex} → ${adj.start_index} @ ${Math.round(adj.start_offset_ms || 0)}ms`);
    currentIndex = adj.start_index;
    playCurrentItem(adj.start_offset_ms || 0);
    return;
  }
  _lanCatchupIdx = -1;   // aligné (ou autre playlist) → reset l'observation de décalage
  if (!_activeVideo || _activeVideo.paused) return;
  // Ne corriger que si on est sur le bon item
  if (adj.start_index !== currentIndex) return;

  // Cooldown post-seek : ne pas surcorriger pendant que le decodage se stabilise
  const sinceSeek = Date.now() - _lastSeekAt;
  if (sinceSeek < SEEK_COOLDOWN_MS) return;

  // La vidéo BOUCLE (playlist mono-item, ou item rejoué via advanceFromItem toutes les
  // duration_ms). Le leader peut diffuser un offset HORS BORNE (ex. extrapolation de
  // getLanSyncState qui s'emballe à l'EOF → 65000ms pour une vidéo de 22s). On RAMÈNE la cible
  // ET ma position dans [0, durée) AVANT tout calcul (modulo) : sinon _activeVideo.currentTime=65s
  // sur une vidéo de 22s = hors borne → écran noir + image sporadique (RPi/AOpen). Puis drift
  // CIRCULAIRE : à la frontière de boucle un player a rebouclé (offset≈0) alors que l'autre finit
  // l'item (offset≈durée) — tous deux au MÊME index → un drift LINÉAIRE valait ≈ ±durée
  // (200ms vs 21900ms = -21700ms) → seek catastrophique (flip-flop). On le ramène dans
  // [-durée/2, +durée/2] = -380ms réel → nudge.
  const loopMs = (playlist[currentIndex] && playlist[currentIndex].duration_ms) || 0;
  const _wrap = (x) => (loopMs > 1000 ? ((x % loopMs) + loopMs) % loopMs : x);
  const targetOffsetMs = _wrap(adj.start_offset_ms);   // borné dans [0, durée)
  const myOffsetMs     = _wrap(_activeVideo.currentTime * 1000);
  let drift = targetOffsetMs - myOffsetMs;  // >0 : je suis en retard
  if (loopMs > 1000) {
    if (drift >  loopMs / 2) drift -= loopMs;
    else if (drift < -loopMs / 2) drift += loopMs;
  }
  const absDrift = Math.abs(drift);

  if (absDrift <= DEAD_ZONE_MS) {
    return;  // deja aligne
  }

  if (absDrift > MAX_SEEK_MS && (Date.now() - _itemStartedAt) >= BOUNDARY_GRACE_MS) {
    // Gros ecart (hors grâce de frontière) : seek direct
    log(`[LAN] Seek correction: drift=${Math.round(drift)}ms → seek to ${Math.round(targetOffsetMs)}ms`);
    _activeVideo.currentTime = Math.max(0, targetOffsetMs / 1000);
    _activeVideo.playbackRate = 1.0;
    _lastSeekAt = Date.now();  // demarre le cooldown
    if (_rateResetTimer) { clearTimeout(_rateResetTimer); _rateResetTimer = null; }
    return;
  }

  // Ecart moyen (40ms..3s) : nudge la vitesse pour rattraper SANS gel (le seek geleait la
  // video et entretenait l'oscillation sur les players lents). Taux ADAPTATIF : proportionnel
  // au drift (convergence ~NUDGE_CONVERGE_MS), borne [NUDGE_MIN_RATE, NUDGE_MAX_RATE].
  const rateDelta = Math.min(NUDGE_MAX_RATE,
                             Math.max(NUDGE_MIN_RATE, absDrift / NUDGE_CONVERGE_MS));
  const rate = drift > 0 ? (1 + rateDelta) : (1 - rateDelta);
  // Duree du nudge = temps pour resorber le drift a ce taux (borne) ; re-evalue au prochain sync.
  const nudgeMs = Math.min(6000, Math.round(absDrift / rateDelta));
  log(`[LAN] Rate nudge: drift=${Math.round(drift)}ms rate=${rate.toFixed(2)} for ${nudgeMs}ms`);
  _activeVideo.playbackRate = rate;
  if (_rateResetTimer) clearTimeout(_rateResetTimer);
  _rateResetTimer = setTimeout(() => {
    if (_activeVideo) _activeVideo.playbackRate = 1.0;
    _rateResetTimer = null;
  }, nudgeMs);
});

// #2b : aligne la bascule d'item du slave sur celle du maître (switch_at absolu).
// Corrige l'offset constant à la transition (le maître, loop plus chargé, basculait
// après le slave). Repli gracieux : si switch_at absent/aberrant → timer local inchangé.
if (window.signflow.onLanSwitch) {
  window.signflow.onLanSwitch((hint) => {
    if (!playlist || playlist.length === 0 || _pendingSync) return;
    if (touchInteracting()) return;   // feuilletage : hors du groupe de synchro
    if (!hint || hint.start_index !== currentIndex) return;  // pas sur le même item
    const item = playlist[currentIndex];
    if (!item) return;
    const dur = item.duration_ms || 10000;
    let delay = hint.switch_at - Date.now();
    // Garde-fous : ignore si aberrant (message périmé ou hors plage de l'item)
    if (delay < -1000 || delay > dur + 2000) return;
    _currentSwitchAt = hint.switch_at;
    scheduleAdvance(item, delay);   // recale la bascule sur l'instant du maître
  });
}

// ── Boot from cache ───────────────────────────────────────────────────────────

const cached = loadSync();
if (cached?.items?.length > 0) {
  log(`Offline cache: ${cached.items.length} item(s) | playlist=${cached.id_playlist ?? 'none'} — waiting for live sync`);
  _lastSync = cached;     // overlay de maintenance + ré-application de la config offline
  _currentPlaylistId = _syncKeyFor(cached);   // contexte LAN sync offline (mono-média inclus, sinon le leader ne diffuse pas sync_play)
  _popPlaylistId = cached.id_playlist ?? null; // Proof of Play offline (vrai id_playlist)
  applyConfig(cached);    // content_sound (mute son vidéo) + paniers audio AVANT la 1re lecture
  // §25.4 : un template multi-zones caché redémarre en multi-zones (offline-first).
  if (!handleMultiZoneSync(cached)) {
    playlist = cached.items;
    currentIndex = 0;
    playCurrentItem();
  }
}

// ── Store Control Panel LAN (§19.3) ───────────────────────────────────────────
//
// Le serveur de controle local (main process) applique les actions de l'operateur
// via 'control:apply' et lit l'etat audio via 'control:status' (pousse ici toutes
// les 2s). Le runtime audio (window.signflowAudio) est la source de l'etat.

if (window.signflow.onControlApply) {
  window.signflow.onControlApply((action) => {
    const a = window.signflowAudio;
    if (!a || !action) return;
    try {
      if (action.action === 'toggle_basket') a.setActiveBasket(action.id_basket, action.is_active);
      else if (action.action === 'set_ratio') a.setBasketRatio(action.id_basket, action.mix_ratio);
      else if (action.action === 'set_ratios' && Array.isArray(action.ratios)) {
        action.ratios.forEach((r) => a.setBasketRatio(r.id_basket, r.mix_ratio));
      }
      else if (action.action === 'set_volume') a.setVolume(action.volume);
      else if (action.action === 'set_family_volume') a.setFamilyVolume(action.family, action.volume);
      else if (action.action === 'trigger_event') {
        if (action.id_basket != null) a.triggerBasket(action.id_basket);
        else a.toggleEmergency();   // compat ancien bouton générique
      }
      else if (action.action === 'set_output') {
        if (action.basket_output && a.setBasketOutput) a.setBasketOutput(action.basket_output);
        if (action.content_sound) { _contentMuted = action.content_sound === 'muted'; if (_activeVideo) _activeVideo.muted = _contentMuted; }
      }
    } catch (e) { log(`Control action error: ${e.message}`); }
  });

  // Redémarrage audio demandé par le main (compat linux/rpi ; sur Windows = no-op routage)
  if (window.signflow.onAudioRestart) {
    window.signflow.onAudioRestart(() => {
      try { window.signflowAudio?.restart(); } catch (e) {}
    });
  }

  setInterval(() => {
    if (window.signflowAudio && window.signflow.sendControlStatus) {
      try { window.signflow.sendControlStatus({ ...window.signflowAudio.getStatus(), content_sound: _contentMuted ? 'muted' : 'on' }); }
      catch (e) {}
    }
  }, 2000);
}

// -- Documents multipages : feuilletage au doigt (SS 3.2, migr 0129) ------------
//
// Un document (PDF/PPTX) est deroule PAR LE SERVEUR en N items IMAGE contigus qui partagent le
// meme `id_item` et portent `media.doc_page`. Naviguer, c'est donc se deplacer dans ce RUN
// d'items : aucune notion de page n'a besoin d'exister cote renderer, et le pre-cache, le
// wall-clock et les preuves de diffusion restent ceux d'items ordinaires.
//
// L'autorisation vient du CONTENU (`item.touch_navigation`, coche sur l'item de playlist), la
// dalle tactile du PLAYER : sans point de contact, tout ce bloc reste inerte. C'est le
// croisement voulu (decision d'Ed 2026-08-14) -- un reglage par player seul n'aurait pas permis
// de rendre un document navigable et un autre non sur le meme ecran.
//
// PENDANT L'INTERACTION, L'ECRAN SORT DE SON GROUPE DE SYNCHRO LAN. Un player pilote a la main
// n'est plus sur l'horloge murale : lui appliquer les corrections du leader le ramenerait de
// force sur la page du groupe, et s'il EST leader il entrainerait les autres sur les gestes
// d'un passant. Il se realigne seul a la boucle suivante -- la synchro derive du wall-clock,
// ce n'est pas un etat negocie qu'il faudrait reconstruire.
const TOUCH_RESUME_DEFAULT_S = 60;   // delai sans geste par defaut, si l'item n'en precise pas
const TOUCH_SWIPE_MIN_PX     = 40;   // en deca : ce n'est pas un glisse
const TOUCH_TAP_MAX_PX       = 12;   // au dela : ce n'est pas un tap
const TOUCH_TAP_MAX_MS       = 700;
let _touchLastAt = 0;                // dernier geste du visiteur (0 = aucun depuis le demarrage)
let _touchBound  = false;

// Run d'items du document affiche a `index`, ou null. Borne aux items CONTIGUS partageant le
// meme id_item : deux documents qui se suivent ne se melangent pas, et un item ordinaire
// termine le run.
function touchDocRun(index) {
  if (!playlist || !playlist.length) return null;
  const it = playlist[index];
  if (!it || !it.touch_navigation) return null;
  const key = it.id_item;
  // id_item nul (chemins compiles : gouvernance, campagnes, event mono-media) : sans identite
  // on ne peut pas borner un run -- on refuse plutot que de coller ensemble tous les sans-id.
  if (key === null || key === undefined) return null;
  const sameDoc = (x) => !!(x && x.id_item === key && x.media && x.media.doc_page != null);
  if (!sameDoc(it)) return null;
  let a = index, b = index;
  while (a > 0 && sameDoc(playlist[a - 1])) a--;
  while (b < playlist.length - 1 && sameDoc(playlist[b + 1])) b++;
  const resumeS = it.touch_resume_after_s || TOUCH_RESUME_DEFAULT_S;
  return { start: a, end: b, count: b - a + 1, resumeAfterMs: resumeS * 1000 };
}

// Un visiteur est-il en train de feuilleter ? Fenetre = le delai de reprise de l'item courant.
function touchInteracting() {
  if (!_touchLastAt) return false;
  const run = touchDocRun(currentIndex);
  const windowMs = run ? run.resumeAfterMs : TOUCH_RESUME_DEFAULT_S * 1000;
  return (Date.now() - _touchLastAt) < windowMs;
}

// Deplacement RELATIF borne au document. Il boucle sur lui-meme : feuilleter au-dela de la
// derniere page ramene a la premiere plutot que d'ejecter le visiteur hors du document.
function touchGo(delta) {
  const run = touchDocRun(currentIndex);
  if (!run) return false;
  _touchLastAt = Date.now();
  const rel = (((currentIndex - run.start + delta) % run.count) + run.count) % run.count;
  currentIndex = run.start + rel;
  log(`[Touch] page ${rel + 1}/${run.count}`);
  playCurrentItem();   // relance le minuteur de la page depuis zero (exigence d'Ed)
  return true;
}

function bindTouchNav() {
  if (_touchBound) return;
  // Ecran non tactile : on ne pose meme pas les ecouteurs. `maxTouchPoints` est le signal
  // universel (une box TV rapporte 0, une dalle tactile > 0) et ne demande aucune plomberie
  // serveur : le meme payload est servi a tout le monde, il ne fait rien la ou il n'y a
  // personne pour toucher.
  if (!(typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0)) return;
  _touchBound = true;
  // ⚠️ SANS CECI, LE SWIPE N'EXISTE PAS (constat d'Ed sur l'Oppo, 2026-08-14, 1er essai reel) :
  // des que le doigt GLISSE, Chromium requalifie le geste en pan natif, emet `pointercancel`
  // et ne delivre JAMAIS le `pointerup` qui mesure le delta — seul le tap (doigt immobile)
  // atteignait nos ecouteurs. `touch-action: none` dit au navigateur de ne s'approprier AUCUN
  // geste ici et de tout nous delivrer. Le player est plein ecran sans defilement : couper
  // les gestes natifs est sans perte. Pose au bind (donc seulement sur ecran tactile).
  try {
    document.documentElement.style.touchAction = 'none';
    if (document.body) document.body.style.touchAction = 'none';
  } catch (e) { /* style indisponible : le tap reste fonctionnel */ }
  let sx = 0, sy = 0, st = 0, tracking = false;
  const down = (e) => {
    if (!touchDocRun(currentIndex)) return;
    tracking = true; sx = e.clientX; sy = e.clientY; st = Date.now();
  };
  const up = (e) => {
    if (!tracking) return;
    tracking = false;
    if (!touchDocRun(currentIndex)) return;
    const dx = e.clientX - sx, dy = e.clientY - sy;
    if (Math.abs(dx) >= TOUCH_SWIPE_MIN_PX && Math.abs(dx) > Math.abs(dy)) {
      touchGo(dx < 0 ? 1 : -1);   // glisse vers la GAUCHE = page suivante
      return;
    }
    if (Math.abs(dx) <= TOUCH_TAP_MAX_PX && Math.abs(dy) <= TOUCH_TAP_MAX_PX &&
        Date.now() - st <= TOUCH_TAP_MAX_MS) {
      const w = window.innerWidth || 1;
      // Tiers gauche = precedent, tiers droit = suivant, tiers CENTRAL = rien : un tap au
      // milieu est le plus probable des gestes accidentels.
      if (e.clientX < w / 3) touchGo(-1);
      else if (e.clientX > (2 * w) / 3) touchGo(1);
    }
  };
  document.addEventListener('pointerdown', down, { passive: true });
  document.addEventListener('pointerup', up, { passive: true });
  // Filet : si un pointercancel survient malgre tout (OS qui reprend la main), on abandonne
  // le suivi proprement au lieu de juger le prochain pointerup contre un point de depart mort.
  document.addEventListener('pointercancel', () => { tracking = false; }, { passive: true });
  log('[Touch] navigation tactile armee (ecran tactile detecte)');
}
try { bindTouchNav(); } catch (e) { /* ecouteurs indisponibles : la diffusion continue */ }

// ── Overlay de maintenance (§ diag terrain) ─────────────────────────────────────
// Panneau semi-transparent affiché par-dessus le contenu, déclenché depuis le CMS
// (commande player:toggle_overlay → main → 'player:overlay'). Toggle ON/OFF + auto-hide
// de sécurité après 5 min (jamais laissé sur l'écran d'un client par oubli). Combine
// les infos device (envoyées par le main) + le dernier player:sync + l'état de lecture.
let _overlayEl      = null;
let _overlayDevice  = null;  // { id_player, hostname, os, version, ip, mac, wan_ip, decode, lan }
let _overlayTimer   = null;  // auto-hide 5 min
let _overlayRefresh = null;  // rafraîchissement 1 s
const OVERLAY_AUTOHIDE_MS = 5 * 60 * 1000;

function _ovMs(ms) {
  if (ms === null || ms === undefined || isNaN(ms)) return '—';
  const s = Math.floor(ms / 1000), m = Math.floor(s / 60);
  return m > 0 ? `${m}m${String(s % 60).padStart(2, '0')}s` : `${s}s`;
}
function _ovEsc(s) {
  return String(s ?? '—').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}
function _ovRow(label, val) {
  return `<div style="display:flex;gap:8px;line-height:1.5">`
    + `<span style="color:#9db4d0;min-width:84px;flex:0 0 auto">${label}</span>`
    + `<span style="color:#fff;word-break:break-all">${_ovEsc(val)}</span></div>`;
}
// Multi-line block (e.g. Network): one value per line, label only on the first row,
// sub-key indented; empty/null entries are skipped (e.g. MAC absent on Android).
function _ovNet(label, entries) {
  const rows = entries.filter((e) => e[1]);
  if (!rows.length) return _ovRow(label, '—');
  return rows.map((e, i) =>
    `<div style="display:flex;gap:8px;line-height:1.5">`
    + `<span style="color:#9db4d0;min-width:84px;flex:0 0 auto">${i === 0 ? label : ''}</span>`
    + `<span style="color:#7fa0c0;min-width:40px;flex:0 0 auto">${e[0]}</span>`
    + `<span style="color:#fff;word-break:break-all">${_ovEsc(e[1])}</span></div>`
  ).join('');
}

function refreshOverlay() {
  if (!_overlayEl) return;
  const p = _lastSync || {};
  const dev = _overlayDevice || {};
  const item = (playlist && playlist[currentIndex]) ? playlist[currentIndex] : null;
  const media = item ? item.media : null;
  const v = _activeVideo;
  const program = p.event_name ? `Event: ${p.event_name}`
    : p.id_governance ? 'Governance (compiled program)'
    : (p.schedule_name || '—');
  const playlistLabel = p.playlist_name
    ? `${p.playlist_name}${p.id_playlist ? ` (#${p.id_playlist})` : ''}`
    : (p.id_playlist ? `#${p.id_playlist}` : '—');
  const count = playlist ? `${currentIndex + 1}/${playlist.length}` : '0/0';
  const playedRes = (v && v.videoWidth) ? `${v.videoWidth}×${v.videoHeight}` : (media && media.media_type !== 'video' ? media.media_type : '—');
  // Vidéo : position réelle. Image/PDF/web (pas de _activeVideo) : écoulé/durée déduit du
  // switch_at (#2b) — l'overlay montrait un '—' pour ces types.
  const itemDurMs = item ? (item.duration_ms || 10000) : 0;
  let playPos = '—';
  if (v) {
    playPos = `${_ovMs((v.currentTime || 0) * 1000)} / ${_ovMs((v.duration || 0) * 1000)}`;
  } else if (item && _currentSwitchAt) {
    const elapsed = Math.max(0, itemDurMs - (_currentSwitchAt - Date.now()));
    playPos = `${_ovMs(elapsed)} / ${_ovMs(itemDurMs)}`;
  }
  const file = (media && media.url) ? media.url.split('?')[0].split('/').pop() : '—';
  const lan = dev.lan && dev.lan.enabled
    ? `group "${dev.lan.group || '?'}" · ${dev.lan.master ? 'leader' : 'follower'}`
    : 'disabled';
  const screen = `${window.screen?.width || '?'}×${window.screen?.height || '?'}`;

  _overlayEl.innerHTML =
    `<div style="font-weight:600;color:#7fb0ff;margin-bottom:6px;letter-spacing:.5px">`
    + `Vitrail · MAINTENANCE</div>`
    + _ovRow('Player', `${p.player_name || dev.hostname || '—'}  (#${dev.id_player ?? '—'})`)
    + _ovRow('Device', `${dev.hostname || '—'} · ${dev.os || ''} v${dev.version || '?'}`)
    + _ovNet('Network', [['LAN', dev.ip], ['MAC', dev.mac], ['WAN', dev.wan_ip]])
    + _ovRow('Display', `${screen} · decode ${dev.decode || '—'}`)
    + _ovRow('LAN sync', lan)
    + _ovRow('Program', program)
    + _ovRow('Playlist', `${playlistLabel} · item ${count}`)
    + _ovRow('Media', media ? `${media.media_name} (${media.media_type})` : '—')
    + _ovRow('Playback', `${playedRes} · ${playPos}`)
    + _ovRow('File', file);
}

function showOverlay() {
  if (!_overlayEl) {
    _overlayEl = document.createElement('div');
    _overlayEl.id = 'sf-maint-overlay';
    _overlayEl.style.cssText = [
      'position:fixed', 'top:24px', 'left:24px', 'z-index:2147483647',
      'pointer-events:none', 'background:rgba(16,20,28,.82)', 'color:#fff',
      'font:13px/1.4 ui-monospace,Menlo,Consolas,monospace', 'padding:14px 18px',
      'border-radius:10px', 'border:1px solid rgba(127,176,255,.35)',
      'box-shadow:0 6px 24px rgba(0,0,0,.45)',
      // Largeur : le panneau prend la place que son contenu demande, MAIS ne depasse jamais
      // l'ecran moins ses marges. L'ancienne regle min(46vw,560px) etait calibree pour un
      // viewport de 1920 : sur un ecran configure en PORTRAIT (screen_rotation), le renderer
      // est mis en layout portrait (540 dp sur un stick, 411 sur un telephone) et 46vw n'y
      // laissait que 189 a 248 px pour une colonne de libelles de 84 px -> illisible (constat
      // d'Ed 2026-08-14, sur le stick ET l'Oppo). box-sizing:border-box pour que la marge de
      // droite soit REELLEMENT de 24 px (padding + bordure compris).
      'box-sizing:border-box', 'max-width:min(560px,calc(100vw - 48px))',
      'backdrop-filter:blur(2px)',
    ].join(';');
    document.body.appendChild(_overlayEl);
  }
  refreshOverlay();
  if (_overlayRefresh) clearInterval(_overlayRefresh);
  _overlayRefresh = setInterval(refreshOverlay, 1000);
  if (_overlayTimer) clearTimeout(_overlayTimer);
  _overlayTimer = setTimeout(hideOverlay, OVERLAY_AUTOHIDE_MS);
}

function hideOverlay() {
  if (_overlayRefresh) { clearInterval(_overlayRefresh); _overlayRefresh = null; }
  if (_overlayTimer) { clearTimeout(_overlayTimer); _overlayTimer = null; }
  if (_overlayEl) { _overlayEl.remove(); _overlayEl = null; }
}

function toggleOverlay(data) {
  if (data && data.device) _overlayDevice = data.device;
  if (_overlayEl) hideOverlay(); else showOverlay();
}

if (window.signflow.onOverlay) {
  window.signflow.onOverlay((data) => {
    try { toggleOverlay(data); } catch (e) { log(`Overlay error: ${e.message}`); }
  });
}
