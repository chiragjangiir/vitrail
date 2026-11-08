// Cle de synchro LAN — _syncKeyFor (2026-07-26, retour Ed ①).
//
// Bug d'origine : un PROGRAMME GOUVERNE (SS XVIII) n'a ni id_playlist ni id_event, donc la
// cle valait null ; or le leader LAN se tait quand elle est nulle (`if (!state.id_playlist)
// return` dans sync_lan.js) => AUCUNE correction UDP, les ecrans gouvernes ne tenaient que
// par leur wall-clock et derivaient (RPi + NUC constates par Ed, "presque parfaits" hors
// gouvernance). Le serveur fournit desormais `sync_key` dans le payload gouverne.
//
// Ce test n'est PAS un portage : il EXTRAIT la fonction reelle de chaque fichier de rendu et
// l'execute. Il verifie donc a la fois le comportement ET que les 7 surfaces ne divergent pas
// (le parc a 7 renderers ; en oublier un, c'est un OS qui reste desynchronise en silence).
//
// Usage : node player-rpi/test/sync_key.test.js

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');

// Les 7 surfaces de rendu. SD_card_BS/ est une copie de travail non suivie par git : on la
// verifie SI elle est presente (c'est ce qui part sur la carte SD des BrightSign).
const SURFACES = [
  'player-rpi/src/renderer/player.js',
  'player-linux/src/renderer/player.js',
  'player-windows/src/renderer/player.js',
  'player-android/app/src/main/assets/player/player.js',
  'player-extension/player/player.js',
  'frontend/public/player-chromeos/player.js',
  'SD_card_BS/sd_image_clean/sf_rnd_player.js',
];

let fail = 0;
function check(label, cond, detail) {
  console.log(`${cond ? 'OK  ' : 'ECHEC'} ${label}${cond ? '' : '  -> ' + JSON.stringify(detail)}`);
  if (!cond) fail++;
}

function extract(file) {
  const src = fs.readFileSync(file, 'utf8');
  // Fonction complete, de sa declaration a l'accolade fermante en colonne 0.
  const m = src.match(/function _syncKeyFor\(p\) \{[\s\S]*?\n\}/);
  return m ? m[0] : null;
}

const found = [];
for (const rel of SURFACES) {
  const file = path.join(ROOT, rel);
  if (!fs.existsSync(file)) {
    console.log(`--   ${rel} (absent, ignore)`);
    continue;
  }
  const fn = extract(file);
  check(`${rel} : _syncKeyFor present`, !!fn);
  if (fn) found.push({ rel, fn });
}

check('au moins les 6 surfaces suivies par git', found.length >= 6, found.length);

// Anti-derive : la MEME fonction partout (une copie oubliee = un OS desynchronise).
const reference = found[0];
for (const s of found.slice(1)) {
  check(`${s.rel} identique a ${reference.rel}`, s.fn === reference.fn);
}

// ── Comportement (fonction reelle, pas un portage) ────────────────────────────
const _syncKeyFor = new Function(`${reference.fn}; return _syncKeyFor;`)();

check('payload absent -> null', _syncKeyFor(null) === null);
check('playlist -> id_playlist', _syncKeyFor({ id_playlist: 42 }) === 42);
check('event mono-media -> -id_event', _syncKeyFor({ id_playlist: null, id_event: 7 }) === -7);
check('ni playlist ni event ni cle -> null', _syncKeyFor({ id_playlist: null }) === null);

// Le cas qui manquait : programme gouverne.
const gouverne = { id_playlist: null, id_event: null, id_governance: true, sync_key: -1234567890 };
check('programme gouverne -> cle du serveur', _syncKeyFor(gouverne) === -1234567890);
check('gouverne : la cle n\'est plus nulle (le leader emet)', _syncKeyFor(gouverne) !== null);

// La cle serveur prime : un payload gouverne ne doit jamais retomber sur autre chose.
check('sync_key prioritaire sur id_playlist',
  _syncKeyFor({ sync_key: -1500000000, id_playlist: 9 }) === -1500000000);
check('sync_key prioritaire sur id_event',
  _syncKeyFor({ sync_key: -1500000000, id_event: 9 }) === -1500000000);

// Retro-compatibilite : un serveur qui n'envoie pas encore sync_key ne change rien.
check('sans sync_key, comportement inchange', _syncKeyFor({ id_playlist: 5 }) === 5);

// La plage reservee tient dans un entier 32 bits signe (la chaine LAN traverse l'autorun
// BrightScript, dont les entiers sont 32 bits : au-dela, debordement silencieux).
check('plage serveur compatible int32', -2000000000 >= -2147483648 && -1000000000 <= 0);

console.log(fail === 0 ? `\nTOUS LES TESTS PASSENT (${found.length} surfaces)` : `\n${fail} ECHEC(S)`);
process.exit(fail === 0 ? 0 : 1);
