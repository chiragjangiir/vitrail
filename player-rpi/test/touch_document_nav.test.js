// NAVIGATION TACTILE DES DOCUMENTS MULTIPAGES (2026-08-14, demande d'Ed).
//
// Un document PDF/PPTX est deroule PAR LE SERVEUR en N items IMAGE contigus partageant le meme
// `id_item` et portant `media.doc_page`. Feuilleter au doigt, c'est donc se deplacer dans ce RUN
// d'items -- le renderer n'a aucune notion de page a inventer.
//
// Ce que ce test protege, et qui ne se voit PAS en relisant :
//
// (A) LA BORNE. Un deplacement doit rester DANS le document. Sans borne, un glisse sur la
//     derniere page ferait sortir vers le contenu suivant de la playlist (ou pire, vers le
//     document VOISIN si deux documents se suivent) : le visiteur perdrait ce qu'il lisait, et
//     l'ecran quitterait la page sans qu'aucune erreur ne soit levee.
//
// (B) LE BOUCLAGE SUR SOI. Arrive au bout en feuilletant, on revient a la premiere page du MEME
//     document. C'est la seule facon de ne pas ejecter quelqu'un d'un geste (decision d'Ed).
//
// (C) LA SORTIE DU GROUPE DE SYNCHRO LAN. Un ecran pilote a la main n'est plus sur l'horloge
//     murale. S'il continuait a appliquer les corrections du leader, il serait ramene de force
//     sur la page du groupe ; et s'il EST leader, il entrainerait les autres ecrans sur les
//     gestes d'un passant. Les 3 chemins LAN (diffusion de ma position, onLanAdjust, onLanSwitch)
//     doivent donc etre gardes -- en oublier UN suffit a ramener l'ecran de force.
//
// (D) L'INERTIE PAR DEFAUT. `touch_navigation` absent ou faux ⇒ AUCUN deplacement possible :
//     le parc entier doit se comporter exactement comme avant tant qu'un operateur ne coche pas
//     la case.
//
// Le test EXTRAIT les fonctions REELLES de chaque fichier de rendu et les EXECUTE, avec les
// VRAIES constantes du fichier (une valeur recopiee ici pourrait diverger du produit sans que
// rien ne le dise).
//
// Usage : node player-rpi/test/touch_document_nav.test.js

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
  try { cond = typeof cond === 'function' ? cond() : cond; }
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

// Constantes REELLES du fichier (jamais recopiees ici : elles doivent pouvoir changer dans le
// produit sans que le test devienne un mensonge).
function extractConsts(src) {
  return (src.match(/^const TOUCH_[A-Z_]+ *= *[^;]+;/gm) || []).join('\n');
}

// ── Fabrique de playlists ────────────────────────────────────────────────────────
function page(idItem, n, total, extra) {
  return Object.assign(
    { id_item: idItem, duration_ms: 15000, touch_navigation: true,
      media: { id_media: 900 + idItem, media_type: 'image', doc_page: n, doc_page_count: total } },
    extra || {},
  );
}
function plain(idItem) {
  return { id_item: idItem, duration_ms: 8000, media: { id_media: 500, media_type: 'image' } };
}

// [image, doc(3 pages), image] — le document occupe les index 1..3
const PL_SIMPLE = [plain(1), page(7, 1, 3), page(7, 2, 3), page(7, 3, 3), plain(2)];
// deux documents QUI SE SUIVENT : 0..1 puis 2..3
const PL_TWO_DOCS = [page(7, 1, 2), page(7, 2, 2), page(9, 1, 2), page(9, 2, 2)];

// Execute les fonctions REELLES avec de VRAIES liaisons pour tout ce qui porte une assertion.
// ⚠️ Le Proxy repond a TOUT identifiant : sans fournir Math/Date explicitement, `Math.abs`
// deviendrait une fonction muette et un temoin passerait au vert sur du code casse.
function run(src, state, expr) {
  const consts = extractConsts(src);
  const fns = ['touchDocRun', 'touchInteracting', 'touchGo']
    .map((n) => extractFn(src, n))
    .filter(Boolean);
  if (fns.length !== 3) return { error: `fonctions manquantes (${fns.length}/3)` };
  const calls = [];
  const env = Object.assign({
    calls, Math, JSON, Date, Number, String, Array, Object, Boolean, Set, Map,
    isFinite, parseInt, parseFloat,
    log: (m) => calls.push('log:' + m),
    playCurrentItem: () => calls.push('playCurrentItem'),
    playlist: null, currentIndex: 0, _touchLastAt: 0,
  }, state);
  const scope = new Proxy(env, {
    has: () => true,
    get: (t, k) => (k === Symbol.unscopables ? undefined : (k in t ? t[k] : function () {})),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  try {
    // eslint-disable-next-line no-new-func
    const out = new Function('scope', `with (scope) { ${consts}\n${fns.join('\n')}\n return (${expr}); }`)(scope);
    return { out, calls, env };
  } catch (e) {
    return { error: e.message, calls, env };
  }
}

function verify(rel, optional) {
  const abs = path.join(ROOT, rel);
  if (!fs.existsSync(abs)) {
    if (optional) { console.log(`\n${rel}\n  (absent du depot — non verifie)`); return; }
    failures++; console.log(`\n${rel}\n  FAIL fichier introuvable`); return;
  }
  const src = fs.readFileSync(abs, 'utf8');
  console.log(`\n${rel}`);

  // (A) borne du run : contigu, meme id_item, pages presentes
  const r = run(src, { playlist: PL_SIMPLE, currentIndex: 2 }, 'touchDocRun(currentIndex)');
  check('(A) le run est borne au document (1..3), pas a la playlist',
    () => r.out && r.out.start === 1 && r.out.end === 3 && r.out.count === 3,
    r.error || JSON.stringify(r.out));

  // (A bis) deux documents qui se suivent ne fusionnent pas
  const r2 = run(src, { playlist: PL_TWO_DOCS, currentIndex: 0 }, 'touchDocRun(currentIndex)');
  const r3 = run(src, { playlist: PL_TWO_DOCS, currentIndex: 3 }, 'touchDocRun(currentIndex)');
  check('(A) deux documents adjacents restent distincts',
    () => r2.out && r3.out && r2.out.end === 1 && r3.out.start === 2,
    `${JSON.stringify(r2.out)} / ${JSON.stringify(r3.out)}`);

  // (D) inertie : sans le drapeau, aucun run — donc aucun deplacement possible
  const off = PL_SIMPLE.map((it) => Object.assign({}, it, { touch_navigation: false }));
  const rOff = run(src, { playlist: off, currentIndex: 2 }, 'touchDocRun(currentIndex)');
  check('(D) touch_navigation absent/faux => aucun run (parc inchange)',
    () => rOff.out === null, JSON.stringify(rOff.out));

  // (D bis) id_item nul (chemins compiles) : refus, sinon tous les sans-id se colleraient
  const noId = [page(null, 1, 2), page(null, 2, 2)];
  const rNo = run(src, { playlist: noId, currentIndex: 0 }, 'touchDocRun(currentIndex)');
  check('(D) id_item nul => refus (ne pas coller les items sans identite)',
    () => rNo.out === null, JSON.stringify(rNo.out));

  // (B) bouclage sur soi : depuis la DERNIERE page, « suivant » revient a la premiere du MEME
  // document — et surtout PAS a l'item 4 de la playlist.
  const rNext = run(src, { playlist: PL_SIMPLE, currentIndex: 3 },
    '(touchGo(1), currentIndex)');
  check('(B) suivant depuis la derniere page => 1re page du meme document (index 1)',
    () => rNext.out === 1, rNext.error || `index=${rNext.out}`);
  check('(B) le minuteur de la page est relance (playCurrentItem appele)',
    () => (rNext.calls || []).includes('playCurrentItem'), JSON.stringify(rNext.calls));

  // (B bis) precedent depuis la premiere page => derniere page du meme document
  const rPrev = run(src, { playlist: PL_SIMPLE, currentIndex: 1 },
    '(touchGo(-1), currentIndex)');
  check('(B) precedent depuis la 1re page => derniere page (index 3)',
    () => rPrev.out === 3, rPrev.error || `index=${rPrev.out}`);

  // (D ter) hors document, touchGo refuse et ne bouge RIEN
  const rPlain = run(src, { playlist: PL_SIMPLE, currentIndex: 0 },
    '[touchGo(1), currentIndex]');
  check('(D) hors document : aucun deplacement',
    () => rPlain.out && rPlain.out[0] === false && rPlain.out[1] === 0,
    JSON.stringify(rPlain.out));

  // (C) fenetre d'interaction : rien avant le 1er geste, vrai juste apres, faux passe le delai.
  // On utilise le delai REEL de l'item (touch_resume_after_s), pas une valeur recopiee.
  const pl30 = PL_SIMPLE.map((it) => (it.media && it.media.doc_page
    ? Object.assign({}, it, { touch_resume_after_s: 30 }) : it));
  const rIdle = run(src, { playlist: pl30, currentIndex: 2, _touchLastAt: 0 },
    'touchInteracting()');
  check('(C) aucun geste => pas d interaction (le parc reste synchronise)',
    () => rIdle.out === false, String(rIdle.out));

  const now = Date.now();
  const rHot = run(src, { playlist: pl30, currentIndex: 2, _touchLastAt: now - 5000 },
    'touchInteracting()');
  check('(C) geste il y a 5 s, delai 30 s => en interaction',
    () => rHot.out === true, String(rHot.out));

  const rCold = run(src, { playlist: pl30, currentIndex: 2, _touchLastAt: now - 31000 },
    'touchInteracting()');
  check('(C) geste il y a 31 s, delai 30 s => plus en interaction (le groupe reprend)',
    () => rCold.out === false, String(rCold.out));

  // (C) LES TROIS CHEMINS LAN + l'avance automatique sont GARDES. Verification structurelle
  // assumee : ces gardes vivent dans des callbacks enregistres aupres du pont natif, qu'on ne
  // peut pas instancier ici. En oublier un ne casse rien visiblement — l'ecran est juste
  // ramene de force sur la page du groupe, ce qu'aucun test de bornes ne verrait.
  const gates = (src.match(/if \(touchInteracting\(\)\) return;/g) || []).length;
  check('(C) les 3 chemins LAN sont gardes (position diffusee, onLanAdjust, onLanSwitch)',
    () => gates === 3, `${gates} garde(s) au lieu de 3`);
  check('(C) l avance auto reste dans le document tant qu il y a interaction',
    () => /_docRun\.end && touchInteracting\(\)/.test(src) || /touchInteracting\(\)\)\s*\{[\s\S]{0,120}_docRun\.start/.test(src),
    'la branche de maintien dans le document est absente');

  // Le geste ne doit pas etre arme sur un ecran sans point de contact.
  check('(D) les ecouteurs ne sont poses que sur un ecran tactile (maxTouchPoints)',
    () => /navigator\.maxTouchPoints > 0/.test(src), 'garde maxTouchPoints absente');

  // (E) LE SWIPE EXIGE DE NEUTRALISER LES GESTES NATIFS. Sans `touch-action: none`, un glisse
  // devient un pan navigateur : Chromium emet `pointercancel` et le `pointerup` qui mesure le
  // delta n'arrive JAMAIS — seul le tap marchait (constat d'Ed sur l'Oppo, 2026-08-14, des le
  // premier essai reel ; aucun test de bornes ne pouvait le voir, c'est un contrat NAVIGATEUR).
  check('(E) bindTouchNav neutralise les gestes natifs (touchAction = none)',
    () => /touchAction *= *'none'/.test(extractFn(src, 'bindTouchNav') || ''),
    'touch-action none absent du bind — le swipe sera avale par le pan natif');
  check('(E) pointercancel abandonne le suivi (pas de delta contre un point de depart mort)',
    () => /pointercancel/.test(src), 'ecouteur pointercancel absent');
}

console.log('NAVIGATION TACTILE DES DOCUMENTS — surfaces de rendu');
SURFACES.forEach((f) => verify(f, false));
OPTIONAL.forEach((f) => verify(f, true));

console.log(`\n${failures === 0 ? 'TOUT VERT' : failures + ' ECHEC(S)'}`);
process.exit(failures === 0 ? 0 : 1);
