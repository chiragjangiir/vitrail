// FIN DE TAKEOVER VOD — l'ecran restait NOIR jusqu'au redemarrage (XT1144, 2026-08-06).
//
// Symptome constate par Ed : la VOD joue (image + son), puis a sa fin l'ecran devient noir et
// n'en repart JAMAIS ; le CMS affiche pourtant le bon programme, et seul « Redemarrer
// l'application » debloque. Mesure a l'appui, dans cet ordre :
//   · capture d'ecran a distance (DWS) : VOD a T+18s, NOIR a T+44s, puis identique pendant 2 min ;
//   · un `force_sync` pousse a la main ne repare RIEN ;
//   · la commande `toggle_overlay`, elle, s'affiche => la page est VIVANTE et sait dessiner ;
//   · journal de l'appareil : `FireEvent 8 MEDIAENDED` puis plus AUCUNE ligne du renderer —
//     donc les syncs arrivent et sont avales AVANT meme la ligne de journal de `onSync`.
//
// Cause : `v.onended = hideVodOverlay`. Un gestionnaire d'evenement est appele AVEC l'objet
// Event, qui atterrit dans le 1er parametre `replacing` (« on enchaine sur une autre VOD, ne
// restaure pas »). Toujours vrai => la fonction efface le filet de securite, retire l'overlay,
// puis SORT avant de remettre `_vodSuspended` a false. Des lors `onSync` avale tous les syncs.
//
// L'invariant fige ici ne parle pas d'un fichier ni d'une plateforme, mais du CONTRAT :
//   « le gestionnaire de fin de VOD doit relancer la programmation MEME appele avec un Event ».
// Il vaut donc pour toute surface, y compris celles ou le parametre n'existe pas encore — le
// jour ou quelqu'un en ajoute un, le test tombe.
//
// Usage : node player-rpi/test/vod_end_of_takeover.test.js

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const SURFACES = [
  'frontend/public/player-chromeos/player.js',   // ChromeOS + BrightSign (meme renderer servi)
  'player-extension/player/player.js',
  'player-linux/src/renderer/player.js',
  'player-rpi/src/renderer/player.js',
  'player-windows/src/renderer/player.js',
  'player-android/app/src/main/assets/player/player.js',
];

let failures = 0;
function check(label, cond, detail) {
  try { cond = (typeof cond === 'function') ? cond() : cond; }
  catch (e) { cond = false; detail = (detail ? detail + ' ; ' : '') + e.message; }
  if (cond) console.log(`  ok   ${label}`);
  else { failures++; console.log(`  FAIL ${label}${detail ? ' -- ' + detail : ''}`); }
}

function extractFn(src, name) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) return null;
  const end = src.indexOf('\n}', start);
  return end < 0 ? null : src.slice(start, end + 2);
}

let tested = 0;

for (const rel of SURFACES) {
  const name = rel.split('/').slice(-2).join('/');
  console.log(`\n${name}`);
  const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
  const show = extractFn(src, 'showVodPlayNow');
  const hide = extractFn(src, 'hideVodOverlay');
  if (!show || !hide) { console.log('  --   pas de takeover VOD ici'); continue; }
  tested++;

  const calls = [];
  const captured = {};
  const mkEl = (tag) => {
    const el = {
      tag, style: { cssText: '' }, dataset: {},
      setAttribute() {}, removeAttribute() {}, appendChild() {}, remove() {},
      addEventListener() {}, load() {}, pause() {}, play: () => ({ catch() {} }),
    };
    if (tag === 'video') captured.video = el;
    return el;
  };
  const env = {
    calls,
    Math, JSON, Date, Number, String, Array, Object, Boolean, Set, Map,
    isFinite, parseInt, parseFloat,
    setTimeout: () => 0, setInterval: () => 0, clearTimeout: () => {}, clearInterval: () => {},
    log: () => {},
    document: { createElement: mkEl, body: { appendChild() {} } },
    contentArea: { innerHTML: '', style: {}, appendChild() {} },
    fallbackScreen: { classList: { add() {}, remove() {} } },
    // Etat AVANT le takeover : une programmation mono-zone tourne.
    _mzActive: false, _mzZones: [],
    playlist: [{ id_item: 1, duration_ms: 10000, media: { id_media: 1, media_type: 'video' } }],
    currentIndex: 0, _activeVideo: null, _contentMuted: false,
    _vodOverlayEl: null, _vodOverlayMedia: null, _vodOverlayTimer: null,
    _vodSuspended: false, _vodExoTakeover: false, _vodExoHidden: false,
    _useExo: false, _exoShowing: false, _connected: true, _IS_BS: false,
    _vodMpvActive: () => false, _flushVodPop: () => {}, _vodDuck: () => {},
    _vodAudioPolicy: () => {},
    _releaseVideo: () => {}, _mzSetMuted: () => {}, _mzTeardownZones: () => {},
    setFallback: () => calls.push('setFallback'),
    playCurrentItem: () => calls.push('playCurrentItem'),
    reRenderCurrentForRenderer: () => calls.push('reRender'),
    scheduleAdvance: () => calls.push('scheduleAdvance'),
    hideVodOverlay: null,   // remplace par la vraie fonction dans le `with`
    window: { signflow: {
      available: true,
      exo: { load() {}, show() {}, hide() {}, stop() {} },
      requestResync: () => calls.push('requestResync'),
    } },
    p: { id_media: 191, mode: 'once', media_type: 'video', src: 'file:///vod.mp4',
         duration_ms: 31000, with_sound: true, has_audio: true },
    captured,
  };
  const scope = new Proxy(env, {
    has: () => true,
    get: (t, k) => (k === Symbol.unscopables ? undefined : (k in t ? t[k] : function () {})),
    set: (t, k, v) => { t[k] = v; return true; },
  });

  let err = null;
  try {
    // eslint-disable-next-line no-new-func
    new Function('scope', `with (scope) {
      ${hide}
      ${show}
      showVodPlayNow(p);
      captured.suspendedPendant = _vodSuspended;
      // Le navigateur appelle TOUJOURS un gestionnaire avec l'objet Event.
      if (captured.video && captured.video.onended) captured.video.onended({ type: 'ended' });
      captured.suspendedApres = _vodSuspended;
    }`)(scope);
  } catch (e) { err = e.message; }

  check('la sequence s\'execute', !err, err);
  if (err) continue;

  // Temoin : sans lui, un bac a sable qui n'aurait rien lance rendrait l'assertion verte.
  check('le takeover a REELLEMENT demarre (programmation suspendue)',
    captured.suspendedPendant === true, JSON.stringify({ p: captured.suspendedPendant }));
  // Certaines surfaces (Android) confient la video a un lecteur NATIF (ExoPlayer) : il n'y a
  // alors aucun <video> DOM, et la fin arrive par un evenement natif. On ne l'exempte pas
  // gratuitement — on VERIFIE que la prise native a bien eu lieu, sinon l'absence de
  // gestionnaire serait un vrai defaut deguise en cas particulier.
  if (!(captured.video && captured.video.onended)) {
    check('takeover NATIF assume (la prise exo a bien eu lieu)', env._vodExoTakeover === true,
      JSON.stringify({ exo: env._vodExoTakeover }));
    console.log('  --   fin de VOD portee par l\'evenement natif, hors perimetre de ce contrat');
    continue;
  }
  check('un gestionnaire de fin est bien pose',
    !!(captured.video && captured.video.onended));

  // L'ASSERTION QUI COMPTE.
  check('appele avec un Event, il RELANCE la programmation (_vodSuspended remis a false)',
    captured.suspendedApres === false,
    JSON.stringify({ apres: captured.suspendedApres, calls }));
}

console.log('');
check(`non vacant : ${tested} surface(s) a takeover VOD testee(s)`, tested >= 5);
console.log(failures === 0 ? '\nTOUT VERT' : `\n${failures} ECHEC(S)`);
process.exit(failures === 0 ? 0 : 1);
