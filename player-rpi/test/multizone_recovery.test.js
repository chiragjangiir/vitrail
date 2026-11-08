// MULTI-ZONES : LE CONTENU JOUAIT, PERSONNE NE POUVAIT LE VOIR (2026-08-06, retour d'Ed sur P3.6).
//
// Deux defauts distincts, tous deux constates a l'ecran sur le stick Google TV ET le Minix
// pendant que le RPi, lui, diffusait normalement.
//
// (A) DEMARRAGE. Sur Android le repli visible n'est pas le `#fallback-screen` HTML (inerte
//     ici : la WebView des box Amlogic cesse de composer quand rien ne bouge, d'ou le choix
//     d'une vue NATIVE) mais une vue Android OPAQUE ajoutee en dernier, donc au-dessus de la
//     WebView. `enterMultiZone`, porte depuis un renderer sans vue native, ne masquait que le
//     repli HTML. MESURE : les zones demarrent et decodent vraiment (« Multi-zone: 2 zone(s)
//     started », MediaCodec actif) derriere un ecran qui affiche « No content to display ».
//
// (B) RETOUR DE VOD — le plus grave, car DEFINITIF. `enterMultiZone` met `playlist = null` ;
//     le retour de takeover appelait `playCurrentItem(0)`, dont la premiere ligne est
//     `if (!playlist ...) { setFallback(); return; }`. Or `setFallback()` fait
//     `contentArea.innerHTML = ''` : il DETRUIT les zones. Et comme `_mzActive`/`_mzFP` ne
//     changent pas, tout sync suivant repond « same content already playing » ⇒ les zones ne
//     sont JAMAIS rebaties. Symptome rapporte par Ed : VOD lancee puis arretee ⇒ « No content
//     to display » definitif ; VOD relancee ⇒ on ENTEND le son sans rien voir (la vue native
//     de repli fait `bringToFront()`, donc elle couvre aussi la surface video).
//
// Les invariants sont formules sur la CAPACITE, pas sur la plateforme (« tout renderer qui
// PEUT afficher l'ecran natif doit le retirer », « aucun retour de VOD ne doit repasser par la
// restauration mono-zone quand le multi-zones est actif ») : le jour ou la vue native est
// portee ailleurs — elle existe a cause d'un defaut de composition WebView, pas d'Android — le
// test l'attrape sans etre reecrit.
//
// Ce test EXTRAIT les fonctions reelles de chaque fichier de rendu et les EXECUTE.
//
// Usage : node player-rpi/test/multizone_recovery.test.js

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

// Copie carte SD BrightSign : hors depot (gitignore). Verifiee SI presente, sinon on le DIT.
const OPTIONAL = ['SD_card_BS/sd_image_clean/sf_rnd_player.js'];

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

const TMPL = {
  id_template: 2, canvas_width: 1920, canvas_height: 1080, layout_type: 'sidebar_r',
  zones: [
    { index: 0, x: 0, y: 0, w: 1440, h: 1080, label: 'Main', start_index: 0,
      items: [{ id_item: 1, media: { id_media: 141, media_type: 'video' } }] },
    { index: 1, x: 1440, y: 0, w: 480, h: 1080, label: 'Side', start_index: 0,
      items: [{ id_item: 2, media: { id_media: 143, media_type: 'image' } }] },
  ],
};

// Execute une fonction REELLE du renderer. Les internes hors sujet (timers, precache, mpv) sont
// neutralises par le Proxy ; tout ce qui porte une assertion est fourni EXPLICITEMENT et
// instrumente — un stub muet ne peut donc pas rendre une assertion verte par accident.
function run(src, fnName, overrides, callExpr) {
  const fn = extractFn(src, fnName);
  if (!fn) return { error: `${fnName} introuvable` };
  const calls = [];
  const env = Object.assign({
    calls,
    // Globales standard : le Proxy repond a TOUT identifiant, donc sans elles `Math.max`
    // devient une fonction muette et le temoin echoue sur un code parfaitement juste.
    Math, JSON, Date, Number, String, Array, Object, Boolean, Set, Map, Image: function () {},
    isFinite, parseInt, parseFloat,
    log: () => {},
    setTimeout: () => 0, setInterval: () => 0,
    clearTimeout: () => {}, clearInterval: () => {},
    document: { createElement: () => ({ className: '', style: { cssText: '' } }) },
    contentArea: { innerHTML: '', style: {}, appendChild() {} },
    fallbackScreen: { classList: { add: (c) => calls.push('fallback.' + c) } },
    setFallback: () => calls.push('setFallback'),
    playCurrentItem: () => calls.push('playCurrentItem'),
    reRenderCurrentForRenderer: () => calls.push('reRender'),
    scheduleAdvance: () => calls.push('scheduleAdvance'),
    _mzSetMuted: () => calls.push('mzSetMuted'),
    _mzPlayZone: (z) => calls.push('playZone:' + (z && z.def && z.def.label)),
    enterMultiZone: () => calls.push('enterMultiZone'),
    _mzFingerprint: () => 'fp2',
    _blockedMedia: new Set(),
    saveSync: () => calls.push('saveSync'),
    window: {
      signflow: {
        available: true,
        exo: { stop() {}, show() {}, hide: () => calls.push('exo.hide') },
        idle: { hide: () => calls.push('idle.hide'), show: () => calls.push('idle.show') },
      },
    },
  }, overrides);
  const scope = new Proxy(env, {
    has: () => true,
    get: (t, k) => (k === Symbol.unscopables ? undefined : (k in t ? t[k] : function () {})),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  try {
    // eslint-disable-next-line no-new-func
    new Function('scope', `with (scope) { ${fn}\n ${callExpr} }`)(scope);
  } catch (e) {
    return { error: e.message, calls, env };
  }
  return { calls, env };
}

const PRESENT_OPTIONAL = OPTIONAL.filter((r) => fs.existsSync(path.join(ROOT, r)));
for (const r of OPTIONAL) {
  if (!PRESENT_OPTIONAL.includes(r)) console.log(`(absent, non verifie : ${r})`);
}

let nativeIdleSurfaces = 0;
let vodSurfaces = 0;

for (const rel of [...SURFACES, ...PRESENT_OPTIONAL]) {
  const name = rel.split('/').slice(-2).join('/');
  console.log(`\n${name}`);
  const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');

  // ── (A) demarrage du multi-zones ───────────────────────────────────────────
  const usesNativeIdle = /signflow\.idle\.show\(/.test(src);
  const a = run(src, 'enterMultiZone', {
    payload: { type: 'player:sync', id_playlist: 20, template: TMPL },
    tmpl: TMPL,
    _mzZones: [], _mzActive: false,
    _idleShown: true,                     // etat REEL au demarrage : le repli est a l'ecran
  }, "enterMultiZone(payload, tmpl, 'fp');");

  check('A. enterMultiZone s\'execute', !a.error, a.error);
  if (!a.error) {
    // Temoin : sans lui, un bac a sable casse rendrait toutes les assertions vertes pour rien.
    check('A. le moteur a REELLEMENT demarre (2 zones jouees)',
      a.env._mzActive === true
      && a.calls.filter((c) => c.startsWith('playZone:')).length === 2, JSON.stringify(a.calls));
    check('A. le repli HTML est masque', a.calls.includes('fallback.hidden'));
    if (usesNativeIdle) {
      nativeIdleSurfaces++;
      check('A. l\'ecran idle NATIF est retire (sinon il masque les zones qui jouent)',
        a.calls.includes('idle.hide'), JSON.stringify(a.calls));
      check('A. _idleShown repasse a false (sinon un overlay le fait reapparaitre)',
        a.env._idleShown === false);
    } else {
      console.log('  --   A. pas d\'ecran idle natif ici (repli HTML seul)');
    }
  }

  // ── (B) retour d'un takeover VOD alors que le multi-zones tourne ───────────
  if (!extractFn(src, 'hideVodOverlay')) { console.log('  --   B. pas de takeover VOD ici'); continue; }
  vodSurfaces++;
  const vodEnv = {
    _mzActive: true,
    playlist: null,                       // etat REEL en multi-zones
    currentIndex: 0,
    _mzPayload: { template: TMPL },
    _mzFP: 'fp',
    _contentMuted: false,
    _activeVideo: null,
    _vodOverlayEl: null, _vodOverlayMedia: null, _vodOverlayTimer: null,
    _vodExoHidden: false, _vodExoTakeover: true,   // la VOD a joue sur la surface NATIVE
    _vodSuspended: true, _vodMpvLowered: false, _vodDucked: false, _vodWantsSound: true,
    _useExo: false, _exoShowing: true,
    _connected: false,                    // hors ligne : le pire cas (pas de resync possible)
    _IS_BS: /_IS_BS/.test(src) && rel.includes('chromeos'),
    _vodMpvActive: () => false,
    _flushVodPop: () => {}, _vodDuck: () => {},
  };
  const b = run(src, 'hideVodOverlay', vodEnv, 'hideVodOverlay();');
  check('B. hideVodOverlay s\'execute', !b.error, b.error);
  if (!b.error) {
    check('B. les zones ne sont PAS detruites (aucun setFallback)',
      !b.calls.includes('setFallback'), JSON.stringify(b.calls));
    check('B. pas de restauration MONO-ZONE (playCurrentItem) avec playlist = null',
      !b.calls.includes('playCurrentItem'), JSON.stringify(b.calls));
    check('B. les zones retrouvent leur son', b.calls.includes('mzSetMuted'));
  }

  // Temoin de conditionnalite : HORS multi-zones, le retour de VOD doit continuer de faire son
  // travail. Sans ce controle, « ne rien faire du tout » passerait les assertions ci-dessus.
  const c = run(src, 'hideVodOverlay', Object.assign({}, vodEnv, {
    _mzActive: false,
    playlist: [{ id_item: 1, duration_ms: 10000, media: { id_media: 1, media_type: 'video' } }],
  }), 'hideVodOverlay();');
  check('B. temoin : hors multi-zones, la programmation est bien reprise',
    !c.error && (c.calls.includes('playCurrentItem') || c.calls.includes('scheduleAdvance')
                 || c.calls.includes('reRender')),
    c.error || JSON.stringify(c.calls));

  // ── (C) DEPART d'un takeover VOD : BrightSign doit LIBERER les zones ───────
  // Les videos de zone portent `hwz` ET `pcmaudio` (routage audio EXCLUSIF sur BS). Les muter
  // ne rend pas la route : la VOD s'affiche mais reste MUETTE (XT1144, 2 decodeurs) — et sur un
  // HD/LS, qui n'a qu'UN plan video, elle serait NOIRE. Ailleurs, au contraire, les zones
  // doivent continuer de tourner sous le takeover (leur wall-clock doit rester vrai).
  if (!extractFn(src, 'showVodPlayNow')) { console.log('  --   C. pas de showVodPlayNow ici'); continue; }
  // Qui tourne REELLEMENT sur BrightSign : le renderer chromeos, et lui seul — c'est un fait
  // du parc, pas une heuristique. (`_IS_BS` apparait aussi dans le fichier de l'extension, qui
  // n'est jamais un BrightSign ; et la copie SD locale est une image de travail que l'appareil
  // rafraichit depuis le serveur depuis 2026-07-22, elle ne fait pas foi.)
  const isBsCapable = rel === 'frontend/public/player-chromeos/player.js';
  if (PRESENT_OPTIONAL.includes(rel)) { console.log('  --   C. copie SD locale : informative, non asserte'); continue; }
  const startEnv = {
    _mzActive: true, playlist: null, currentIndex: 0, _activeVideo: null,
    _contentMuted: true, _vodOverlayEl: null, _vodOverlayMedia: null, _vodOverlayTimer: null,
    _vodSuspended: false, _vodExoTakeover: false, _vodExoHidden: false, _useExo: false,
    _vodMpvActive: () => false, _flushVodPop: () => {}, _vodDuck: () => {},
    _vodAudioPolicy: () => {},
    _mzTeardownZones: () => calls_C.push('mzTeardown'),
    hideVodOverlay: () => {},
    p: { id_media: 191, mode: 'once', media_type: 'video', src: 'file:///x.mp4',
         duration_ms: 31000, with_sound: true, has_audio: true },
  };
  const calls_C = [];
  const mkEl = () => ({
    style: { cssText: '' }, dataset: {},
    setAttribute() {}, removeAttribute() {}, appendChild() {}, remove() {},
    addEventListener() {}, load() {}, play: () => ({ catch() {} }),
  });
  const d = run(src, 'showVodPlayNow', Object.assign({}, startEnv, {
    calls: calls_C,
    _IS_BS: isBsCapable,
    document: { createElement: mkEl, body: { appendChild() {} } },
  }), 'showVodPlayNow(p);');
  if (isBsCapable) {
    check('C. BrightSign : les zones sont LIBEREES (plan video + route audio rendus)',
      !d.error && calls_C.includes('mzTeardown'), d.error || JSON.stringify(calls_C));
  } else {
    check('C. hors BrightSign : les zones NE sont PAS demontees (leur wall-clock doit tenir)',
      !d.error && !calls_C.includes('mzTeardown'), d.error || JSON.stringify(calls_C));
  }
}

// ── (D) l'empreinte doit CHANGER quand le placement des spots change ────────────
// Basculer `campaign_placement` (plein ecran <-> zone principale) ne modifie NI le media, NI
// la duree, NI l'URL — et un spot de campagne n'a meme pas d'`id_item` (mesure prod : le
// serveur envoie `item=None`). Si l'empreinte ignore le marquage campagne, `handleMultiZoneSync`
// repond « same content already playing » et le changement n'atteint JAMAIS l'ecran : c'est ce
// qu'Ed a constate le 2026-08-06, template bascule en plein ecran et spot toujours dans la zone,
// alors que le serveur envoyait bien `campaign.fullscreen = true`.
console.log('\n── (D) empreinte multi-zones et placement des spots ──');

function fingerprintWith(src, fullscreen) {
  const itemFP = extractFn(src, '_mzItemFP');
  const fp = extractFn(src, '_mzFingerprint');
  if (!itemFP || !fp) return { error: '_mzItemFP / _mzFingerprint introuvable' };
  const tmpl = {
    id_template: 2, layout_type: 'sidebar_r', canvas_width: 1920, canvas_height: 1080,
    zones: [
      { index: 0, x: 0, y: 0, w: 1440, h: 1080, items: [
        { id_item: 185, duration_ms: 30000, media: { id_media: 141, cache_key: 'k1', url: 'signflow://k1' } },
        // Le spot : PAS d'id_item, media/duree/url identiques d'un placement a l'autre.
        { id_item: null, duration_ms: 27000, campaign: { fullscreen },
          media: { id_media: 80, cache_key: 'k2', url: 'signflow://k2' } },
      ] },
      { index: 1, x: 1440, y: 0, w: 480, h: 1080, items: [
        { id_item: 345, duration_ms: 30000, media: { id_media: 143, cache_key: 'k3', url: 'signflow://k3' } },
      ] },
    ],
  };
  const env = { JSON, Math, tmpl, _servedLoc: (u) => (/^https?:/i.test(u || '') ? 'R' : 'L') };
  const scope = new Proxy(env, {
    has: () => true,
    get: (t, k) => (k === Symbol.unscopables ? undefined : (k in t ? t[k] : function () {})),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  try {
    // eslint-disable-next-line no-new-func
    return { fp: new Function('scope', `with (scope) { ${itemFP}\n${fp}\nreturn _mzFingerprint(tmpl); }`)(scope) };
  } catch (e) { return { error: e.message }; }
}

for (const rel of SURFACES) {
  const name = rel.split('/').slice(-2).join('/');
  const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
  if (!extractFn(src, '_mzItemFP')) { console.log(`  --   ${name} : pas d'empreinte multi-zones`); continue; }
  const a = fingerprintWith(src, false);
  const b = fingerprintWith(src, true);
  const c = fingerprintWith(src, false);   // temoin : meme entree => meme empreinte
  check(`${name} : l'empreinte CHANGE quand le spot passe en plein ecran`,
    !a.error && !b.error && a.fp !== b.fp, a.error || b.error || `identique: ${a.fp}`);
  check(`${name} : temoin, une entree identique donne la MEME empreinte`,
    !c.error && a.fp === c.fp, c.error);
}

// Gardes de non-vacuite : si plus aucune surface ne declare ces capacites, les assertions
// centrales ne s'executeraient nulle part et le test passerait en ne prouvant RIEN.
console.log('');
check(`non vacant : ${nativeIdleSurfaces} surface(s) a ecran idle natif`, nativeIdleSurfaces >= 1);
check(`non vacant : ${vodSurfaces} surface(s) a takeover VOD`, vodSurfaces >= 5);

console.log(failures === 0 ? '\nTOUT VERT' : `\n${failures} ECHEC(S)`);
process.exit(failures === 0 ? 0 : 1);
