// PROOF OF PLAY SOUS UN OVERLAY PLEIN ECRAN (migr 0125, decision Ed 2026-08-06).
//
// Depuis P3.6, un spot de campagne peut RECOUVRIR tout l'ecran par-dessus un template
// multi-zones. Les autres zones ne sont volontairement pas suspendues -- les suspendre
// decalerait leur wall-clock et desynchroniserait l'ecran au retour -- donc chaque item qui
// demarre dessous appelle `reportPlay` : on atteste la diffusion d'un contenu que personne
// ne voit. Chiffre sur la playlist reelle d'Ed : ~11 % du temps de cycle.
//
// Le TAKEOVER VOD est la meme classe de defaut, et pire : mesure le 2026-08-07,
// `_mzScheduleAdvance` n'a AUCUNE garde `_vodSuspended`, donc les zones continuent d'avancer
// sous un overlay opaque, parfois plusieurs minutes. (Le mono-zone, lui, est sain : le
// takeover y fait `clearTimeout(itemTimer)`, plus rien ne demarre donc plus rien n'est emis.)
//
// Ce n'est PAS une fraude annonceur : les spots ne sont injectes que dans la zone 0, jamais
// un spot facture n'est masque par un autre. Le cout est ailleurs -- ces preuves gonflent le
// DENOMINATEUR du SOV ⇒ le SOV servi ressort sous-evalue ⇒ fausse alerte de sous-diffusion.
//
// CE QUE CE TEST FIGE, sur les surfaces de rendu REELLES, en EXECUTANT leurs fonctions :
//   1. une zone qui demarre sous un spot plein ecran est marquee `covered` ;
//   2. le SPOT LUI-MEME ne l'est pas -- il est le couvreur, pas un couvert. C'est le piege
//      de ce correctif : `z.adOverlay` est deja pose quand le spot emet sa preuve, donc un
//      test global aurait fait disparaitre des comptages un spot FACTURE ;
//   3. une zone qui demarre sous un takeover VOD est marquee, y compris dans la fenetre ou
//      `_vodSuspended` est pose mais l'overlay pas encore monte dans le DOM ;
//   4. un spot RECOUVERT PAR UNE VOD est marque -- le couvreur peut etre couvert, et cette
//      sous-diffusion-la est reelle ;
//   5. hors overlay, rien n'est marque (sinon on retirerait de l'antenne du contenu vu) ;
//   6. le marquage n'abime pas le reste de la preuve (temoin de non-regression).
//
// Usage : node player-rpi/test/pop_covered.test.js

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

// Copie carte SD BrightSign : hors depot (gitignore). Verifiee SI presente, sinon on le DIT --
// un test qui la lirait sans condition echouerait chez tout autre que le poste qui l'heberge.
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

// Execute les fonctions REELLES du renderer dans un bac a sable.
//
// ⚠️ PAS de `with (proxy)` ici, malgre le patron des tests voisins : mesure le 2026-08-07,
// un Proxy `has: () => true` intercepte AUSSI les fonctions declarees dans le bloc, si bien
// que `_coveredNow` etait remplace par un stub muet et rendait des verdicts incoherents sur
// du code parfaitement juste. Meme classe de piege que le `Math.max` muet du 06/08 : un bac
// a sable qui repond a tout ne peut pas dire ce qui manque.
//
// Ici les variables libres sont de VRAIES liaisons. Un identifiant oublie leve une
// ReferenceError bruyante au lieu de rendre une assertion verte par accident.
function callReport(src, state, callExpr) {
  const rp = extractFn(src, 'reportPlay');
  if (!rp) throw new Error('reportPlay introuvable');
  // `_coveredNow` absent → on injecte un substitut inerte plutot que de refuser de tourner.
  // Sans cela, le temoin de non-regression ci-dessous echouerait sur le code d'ORIGINE pour
  // une raison qui n'est pas la sienne (fonction manquante) — et un temoin qui ne survit pas
  // a l'A/B ne prouve rien. Son absence est signalee par sa propre assertion, nommement.
  const cn = extractFn(src, '_coveredNow') || 'function _coveredNow() { return false; }';
  const fns = `${cn}\n${rp}`;

  const sent = [];
  const st = Object.assign({
    _popPlaylistId: 27,
    _vodSuspended: false,
    _vodOverlayEl: null,
    _mzZones: [],
    item: ITEM, spot: SPOT,
  }, state);

  // eslint-disable-next-line no-new-func
  new Function('st', 'sent', `
    let _vodSuspended = st._vodSuspended;
    let _vodOverlayEl = st._vodOverlayEl;
    let _mzZones = st._mzZones;
    const _popPlaylistId = st._popPlaylistId;
    const item = st.item, spot = st.spot;
    const window = { signflow: { reportPlay: (e) => sent.push(e) } };
    ${fns}
    ${callExpr}
  `)(st, sent);
  return sent;
}

const ITEM = { id_item: 5, media: { id_media: 143, media_type: 'image' } };
const SPOT = { id_item: 9, media: { id_media: 900, media_type: 'video' }, campaign: { id_campaign: 3, fullscreen: true } };

const PRESENT_OPTIONAL = OPTIONAL.filter((r) => fs.existsSync(path.join(ROOT, r)));
for (const r of OPTIONAL) {
  if (!PRESENT_OPTIONAL.includes(r)) console.log(`\n(absent, non verifie : ${r})`);
}

for (const rel of [...SURFACES, ...PRESENT_OPTIONAL]) {
  const abs = path.join(ROOT, rel);
  console.log(`\n${rel}`);
  if (!fs.existsSync(abs)) { failures++; console.log('  FAIL fichier introuvable'); continue; }
  const src = fs.readFileSync(abs, 'utf8');

  // L'overlay du spot, tel que `_mzPlayFullscreenAd` le pose sur la zone qui le declenche.
  const ownAd = { el: {}, close() {} };
  const zoneWithAd = () => [{ adOverlay: ownAd }, { adOverlay: null }];

  // (0) La surface porte bien le predicat (aucune copie oubliee).
  check('la surface definit _coveredNow', () => extractFn(src, '_coveredNow') !== null);

  // (1) Une zone qui demarre pendant un spot plein ecran : marquee.
  check('zone sous un spot plein ecran → covered', () => {
    const sent = callReport(src, { _mzZones: zoneWithAd() }, 'reportPlay(item, 10000);');
    return sent.length === 1 && sent[0].covered === true;
  }, 'la preuve d\'une zone masquee doit etre marquee');

  // (2) LE PIEGE : le spot lui-meme n'est PAS couvert par son propre overlay.
  check('le spot plein ecran lui-meme → NON covered', () => {
    const sent = callReport(src, { _mzZones: zoneWithAd() },
      'reportPlay(spot, 8000, _coveredNow(_mzZones[0].adOverlay));');
    return sent.length === 1 && sent[0].covered === false;
  }, 'un spot FACTURE ne doit jamais s\'exclure lui-meme des comptages');

  // (3) Takeover VOD : overlay monte, ET fenetre ou seul _vodSuspended est pose.
  check('zone sous un takeover VOD (overlay monte) → covered', () => {
    const sent = callReport(src, { _vodOverlayEl: {}, _mzZones: [{ adOverlay: null }] },
      'reportPlay(item, 10000);');
    return sent.length === 1 && sent[0].covered === true;
  });
  check('zone sous un takeover VOD (avant montage overlay) → covered', () => {
    const sent = callReport(src, { _vodSuspended: true, _vodOverlayEl: null, _mzZones: [{ adOverlay: null }] },
      'reportPlay(item, 10000);');
    return sent.length === 1 && sent[0].covered === true;
  }, '_vodSuspended est pose AVANT le montage : la fenetre doit etre fermee');

  // (4) Le couvreur peut etre couvert : un spot sous une VOD n'a pas ete vu.
  check('spot recouvert par une VOD → covered', () => {
    const sent = callReport(src, { _vodOverlayEl: {}, _mzZones: zoneWithAd() },
      'reportPlay(spot, 8000, _coveredNow(_mzZones[0].adOverlay));');
    return sent.length === 1 && sent[0].covered === true;
  }, 'la sous-diffusion signalee ici est reelle');

  // (5) Cas nominal : rien ne recouvre → rien n'est retire de l'antenne.
  check('aucun overlay → NON covered', () => {
    const sent = callReport(src, { _mzZones: [{ adOverlay: null }, { adOverlay: null }] },
      'reportPlay(item, 10000);');
    return sent.length === 1 && sent[0].covered === false;
  });
  check('mono-zone (aucune zone) → NON covered', () => {
    const sent = callReport(src, {}, 'reportPlay(item, 10000);');
    return sent.length === 1 && sent[0].covered === false;
  });

  // (6) TEMOIN DE NON-REGRESSION — VERT AVANT COMME APRES le correctif (verifie par A/B) :
  //     le marquage ne doit pas abimer le reste de la preuve. Sans lui, un `reportPlay` casse
  //     rendrait toutes les assertions ci-dessus « rouges » pour la mauvaise raison.
  check('temoin : la preuve porte toujours media / playlist / duree', () => {
    const sent = callReport(src, { _mzZones: zoneWithAd() }, 'reportPlay(item, 10000);');
    return sent.length === 1
      && sent[0].id_media === 143
      && sent[0].id_playlist === 27
      && sent[0].duration_ms === 10000
      && typeof sent[0].played_at === 'string';
  });
}

console.log(`\n${failures === 0 ? 'TOUS LES TESTS PASSENT' : failures + ' ECHEC(S)'}`);
process.exit(failures === 0 ? 0 : 1);
