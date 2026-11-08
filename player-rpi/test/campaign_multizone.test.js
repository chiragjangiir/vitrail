// RETAIL MEDIA x MULTI-ZONES — le spot plein ecran (P3.6, decision Ed 2026-08-06).
//
// L'injection des creatifs etait COUPEE des qu'un template portait 2 zones ou plus, avec un
// commentaire « backlog » qui la faisait passer pour un choix. Or aucun service ne
// connaissait cette notion (mesure le 2026-08-06) : l'occupancy-check, le SOV et le devis
// comptaient ces ecrans comme VENDABLES. Un annonceur pouvait donc etre facture pour des
// ecrans qui ne diffuseraient jamais son spot -- un angle mort de FACTURATION.
//
// Le mode est choisi PAR TEMPLATE (`campaign_placement`, migr 0124) et voyage jusqu'au
// player dans `campaign.fullscreen` :
//   · true  -> le spot RECOUVRE tout l'ecran (seul mode coherent avec la tarification SOV) ;
//   · false -> item normal de la zone principale (menu board : les autres zones restent).
//
// Ce que ce test fige, sur les 7 SURFACES DE RENDU reelles :
//   1. le spot plein ecran ne passe PAS par le rendu en zone (sinon il resterait confine) ;
//   2. les zones sont MUETTES pendant le spot, et retrouvent leur son apres ;
//   3. elles ne sont PAS suspendues -- les suspendre decalerait leur wall-clock et
//      desynchroniserait l'ecran au retour ;
//   4. le Proof of Play part (le spot est FACTURE : sans preuve, il est invendable) ;
//   5. le demontage d'une zone emporte un spot en cours (sinon le creatif reste colle
//      par-dessus le nouveau contenu, zones muettes).
//
// Le test lit les 7 fichiers REELS : il verifie donc aussi qu'aucune copie n'a ete oubliee.
//
// Usage : node player-rpi/test/campaign_multizone.test.js

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

// La copie carte SD BrightSign vit hors du depot (`SD_card_BS/` est gitignore : c'est une
// image de travail, pas du code source). On la controle SI elle est presente, sinon on le
// DIT — un test qui la lirait sans condition echouerait chez tout autre que le poste qui
// l'heberge, et en CI.
const OPTIONAL = ['SD_card_BS/sd_image_clean/sf_rnd_player.js'];

let failures = 0;
function check(label, cond, detail) {
  try { cond = (typeof cond === 'function') ? cond() : cond; }
  catch (e) { cond = false; detail = (detail ? detail + ' ; ' : '') + e.message; }
  if (cond) console.log(`  ok   ${label}`);
  else { failures++; console.log(`  FAIL ${label}${detail ? ' — ' + detail : ''}`); }
}

const PRESENT_OPTIONAL = OPTIONAL.filter((r) => fs.existsSync(path.join(ROOT, r)));
for (const r of OPTIONAL) {
  if (!PRESENT_OPTIONAL.includes(r)) console.log(`
(absent, non verifie : ${r})`);
}

for (const rel of [...SURFACES, ...PRESENT_OPTIONAL]) {
  const name = rel.split('/').slice(-2).join('/');
  console.log(`\n${name}`);
  const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');

  // (1) le branchement existe, AVANT le rendu en zone
  // On raisonne sur le CORPS de `_mzPlayZone` : comparer des positions dans tout le fichier
  // dependait de l'indentation exacte et faisait echouer un code parfaitement juste.
  const playZone = src.slice(src.indexOf('function _mzPlayZone('),
                             src.indexOf('function _mzPlayFullscreenAd('));
  check('le spot fullscreen est detourne AVANT le rendu en zone',
    /item\.campaign\s*&&\s*item\.campaign\.fullscreen/.test(playZone)
    && playZone.indexOf('_mzPlayFullscreenAd(') < playZone.indexOf('_mzRenderInZone('));
  check('la fonction plein ecran existe', /function _mzPlayFullscreenAd\(/.test(src));

  const fn = src.slice(src.indexOf('function _mzPlayFullscreenAd('),
                       src.indexOf("// Rendu d'un item DANS une zone"));

  // (2) mute pendant, restitution apres
  check('les zones sont muettes pendant le spot', /_mzSetMuted\(true\)/.test(fn));
  check('elles retrouvent leur son apres', /_mzSetMuted\(_contentMuted\)/.test(fn));

  // (3) pas de suspension des zones : aucun teardown/arret global dans le chemin du spot
  check('les zones ne sont PAS suspendues (aucun teardown global)',
    !/_mzTeardownZones\(|_vodSuspended/.test(fn));

  // (4) le PoP part -- sans lui le spot est invendable.
  // La forme de l'appel a gagne un 3e argument (marquage « recouvert », migr 0125) : on
  // n'exige donc PAS la parenthese fermante juste apres `dur`. Une assertion collee a la
  // signature exacte se casse a chaque evolution legitime sans rien prouver de plus.
  // Le COMPORTEMENT du marquage est verifie a part : player-rpi/test/pop_covered.test.js.
  check('le Proof of Play est emis', /reportPlay\(item, dur[,)]/.test(fn));

  // (5) le demontage emporte un spot en cours
  check('le demontage d une zone ferme le spot',
    /_mzReleaseZone\(z\)\s*\{[\s\S]{0,400}z\.adOverlay/.test(src));

  // Reutilisation : le rendu passe par le moteur EXISTANT, pas par un second moteur.
  check('reutilise _mzRenderInZone (pas de 2e moteur de rendu)',
    /_mzRenderInZone\(\s*\n?\s*pseudo/.test(fn));
}

console.log(failures === 0 ? '\nTous verts.' : `\n${failures} ECHEC(S).`);
process.exit(failures === 0 ? 0 : 1);
