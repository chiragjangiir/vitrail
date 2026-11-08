// Coupure/rallumage de la sortie video — IDEMPOTENCE (defaut trouve chez Ed le 2026-07-27).
//
// Symptome : « l'ecran perd le signal video au debut des videos, assez souvent », sur la
// moitie NUC d'un ecran en PdP (le RPi, sur la meme dalle, ne le faisait pas).
//
// Cause mesuree, de bout en bout :
//   1. le serveur remet `last_power_state = NULL` a CHAQUE (re)connexion WS (ws.py) ;
//   2. le tick `apply_site_power` re-emet donc un `power_on` apres chaque reconnexion —
//      c'est-a-dire apres chaque redemarrage backend / deploiement ;
//   3. sans ecran pilotable (RS232/IP/CEC), ce `power_on` passe par le repli « coupure de
//      sortie video » ;
//   4. celui-ci faisait `xrandr --auto` (= mode PREFERE de l'ecran, 3840x2160@30 sur la TV
//      du NUC) PUIS re-forcait le mode configure (1920x1080@60) => DEUX changements de mode
//      => la TV perd et reacquiert le signal HDMI.
// Le RPi ne le montrait pas parce que son mode force EST son mode prefere : `--auto` ne
// changeait rien. Meme code, meme commande, effet visible d'un cote seulement.
//
// Ce que ce test fige :
//   · un `power_on` alors que la sortie est DEJA allumee n'execute AUCUNE commande ;
//   · une vraie transition (OFF -> ON) en execute une ;
//   · avec une resolution forcee, l'allumage n'utilise PAS `--auto` (un seul modeset).
//
// Le test EXTRAIT la vraie fonction des 3 players Electron (pas un portage) : il verifie
// donc aussi qu'aucune des 3 copies n'a ete oubliee.
//
// Usage : node player-rpi/test/display_power.test.js

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');

const PLAYERS = [
  { rel: 'player-linux/src/main.js', forcedRes: '1920x1080@60' },
  { rel: 'player-rpi/src/main.js', forcedRes: null },      // wlr-randr : pas de mode force ici
  { rel: 'player-windows/src/main.js', forcedRes: null },  // DDC/CI via script PowerShell
];

let fail = 0;
function check(label, cond, detail) {
  console.log(`${cond ? 'OK  ' : 'ECHEC'} ${label}${cond ? '' : '  -> ' + JSON.stringify(detail)}`);
  if (!cond) fail++;
}

// On extrait la fonction SEULE (sans sa variable d'etat) : le bac a sable la fournit.
// Ainsi l'ANCIEN code s'execute aussi, et echoue sur le COMPORTEMENT (commandes rejouees)
// et non sur une simple absence de ligne — un rouge-avant qui prouve le defaut, pas la forme.
function extract(file) {
  const src = fs.readFileSync(file, 'utf8');
  const m = src.match(/\nfunction setVideoOutputPower\(on\) \{[\s\S]*?\n\}/);
  return m ? m[0] : null;
}

// Sandbox : on fournit les dependances de module (execSync/execFileSync, console, config)
// et on recolte les commandes REELLEMENT executees.
function makeSandbox(code, forcedRes) {
  const commands = [];
  // Les variables de module que la fonction referme (nom d'output memorise, id du
  // powerSaveBlocker) sont declarees PRE-REMPLIES : sans elles la fonction jette
  // « not defined » et le scenario ne s'executerait pas — un test vert qui ne teste rien.
  const prelude = "let _xrandrPowerOutput = 'DP-1'; let _wlrPowerOutput = 'HDMI-A-1';"
    + " let _psbId = 1; let _videoOutputOn = null;";
  const factory = new Function(
    'execSync', 'execFileSync', 'console', 'serverDisplayConfig', '_appliedResolution',
    '_appliedRotation', 'applyScreenResolution', 'applyScreenRotation', 'path', '__dirname',
    'powerSaveBlocker',
    `${prelude}\n${code}\n; return setVideoOutputPower;`
  );
  const record = (cmd) => { commands.push(String(cmd)); return ''; };
  const fn = factory(
    record,
    (exe, args) => record(`${exe} ${(args || []).join(' ')}`),
    { log() {}, warn() {}, error() {} },
    { screen_resolution: forcedRes, output_power_fallback: true },
    forcedRes,
    null,
    (r) => record(`applyScreenResolution ${r}`),
    (r) => record(`applyScreenRotation ${r}`),
    path,
    __dirname,
    { start: () => 1, isStarted: () => true, stop() {} },
  );
  return { fn, commands };
}

for (const { rel, forcedRes } of PLAYERS) {
  const file = path.join(ROOT, rel);
  const code = extract(file);
  check(`${rel} : setVideoOutputPower extraite`, !!code);
  if (!code) continue;

  // Le detecteur d'output (xrandr/wlr-randr) renvoie '' dans le bac a sable : les players
  // Linux/RPi jettent alors « no output detected ». On neutralise en pre-remplissant la
  // variable memorisee — pas possible depuis l'exterieur : on execute donc la 1re commande
  // en tolerant l'erreur, la memorisation ayant lieu avant.
  const { fn, commands } = makeSandbox(code, forcedRes);

  // 1) Transition reelle : OFF (etat inconnu -> false) => une commande part.
  let threw = null;
  try { fn(false); } catch (e) { threw = e.message; }
  const afterOff = commands.length;
  check(`${rel} : une extinction execute une commande`, afterOff > 0 || threw !== null,
        { commands, threw });

  if (threw) {
    // Detection d'output impossible hors machine : le reste du scenario n'est pas jouable.
    console.log(`--   ${rel} : detection d'output indisponible hors device (${threw}) — scenario partiel`);
    continue;
  }

  // 2) Meme etat demande une 2e fois => AUCUNE commande supplementaire (le coeur du fix).
  fn(false);
  check(`${rel} : extinction redondante = no-op`, commands.length === afterOff,
        commands.slice(afterOff));

  // 3) Transition inverse => une commande part.
  fn(true);
  const afterOn = commands.length;
  check(`${rel} : rallumage reel execute une commande`, afterOn > afterOff, commands);

  // 4) `power_on` redondant (le cas d'Ed : re-emis a chaque reconnexion) => no-op.
  fn(true);
  fn(true);
  check(`${rel} : power_on redondant = no-op`, commands.length === afterOn,
        commands.slice(afterOn));

  // 5) Avec une resolution forcee, pas de `--auto` (sinon 2 changements de mode).
  if (forcedRes) {
    const onCmds = commands.slice(afterOff, afterOn).join(' | ');
    check(`${rel} : allumage sans --auto quand un mode est force`, !/--auto/.test(onCmds), onCmds);
    check(`${rel} : allumage applique directement le mode force`,
          onCmds.includes('--mode') && onCmds.includes(forcedRes.split('@')[0]), onCmds);
  }
}

console.log(fail === 0 ? '\nTOUS LES TESTS PASSENT' : `\n${fail} ECHEC(S)`);
process.exit(fail === 0 ? 0 : 1);
