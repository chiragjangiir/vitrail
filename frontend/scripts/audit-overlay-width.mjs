// AUDIT — largeur de l'overlay de maintenance des players, MESUREE dans un navigateur.
//
// Pourquoi une sonde et pas une relecture : la regle de largeur etait `min(46vw,560px)`,
// calibree pour un ecran de 1920 de large. Elle ne se lit pas comme un defaut ; elle se VOIT
// des que le viewport est etroit. Ecran configure en portrait (screen_rotation=right/left),
// le renderer est mis en layout portrait, donc :
//   - stick Google TV 1920x1080 densite 320 -> 960x540 dp -> viewport 540 de large
//   - telephone Oppo 2400x1080 densite ~420 -> ~914x411 dp -> viewport 411 de large
// A 411 de large, 46vw = 189 px pour une colonne de libelles de 84 px et des valeurs en
// `word-break:break-all` : illisible. Constate par Ed le 2026-08-14 sur les DEUX appareils.
//
// La sonde EXTRAIT le vrai `cssText` et les vraies fonctions de rendu de lignes du fichier de
// rendu (elle ne peut donc pas deriver du produit), rend le panneau dans Chromium a plusieurs
// viewports, MESURE, et ecrit une capture par viewport.
//
// TEMOIN INTEGRE : avec `--baseline <player.js d'avant correctif>`, la sonde mesure AUSSI la
// version d'avant et EXIGE qu'elle echoue en portrait. Sans ce temoin, un "0 constat" serait
// garanti quel que soit le produit. Elle exige en plus que le rendu PAYSAGE soit identique
// avant/apres : un correctif du portrait qui changerait l'apparence de tout le parc paysage
// existant serait une regression, pas un correctif.
//
// Usage :
//   node scripts/audit-overlay-width.mjs [chemin/player.js] [--baseline chemin] [--out DIR]
//
// Pour rejouer le TEMOIN, extraire la version d'avant correctif depuis git :
//   git show <commit>:frontend/public/player-chromeos/player.js > /tmp/base.js
//   node scripts/audit-overlay-width.mjs --baseline /tmp/base.js

import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const ROOT = path.resolve(process.cwd(), '..');
const args = process.argv.slice(2);
function opt(name) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
}
const OUT = opt('--out') || path.join(ROOT, 'frontend', 'tests', 'e2e', '__shots__');
const BASELINE = opt('--baseline');
const positional = args.filter((a, i) => !a.startsWith('--') && !args[i - 1]?.startsWith('--'));
const TARGET = path.resolve(
  positional[0] || path.join(ROOT, 'frontend', 'public', 'player-chromeos', 'player.js'),
);

// Viewports REELS du parc, pas des valeurs rondes inventees.
// `wasReadable` = appareils ou Ed a constate que l'overlay etait DEJA correct avant correctif.
// Pour ceux-la l'exigence n'est pas "ca doit s'ameliorer" mais "ca ne doit pas bouger".
const VIEWPORTS = [
  { name: 'paysage-fhd', w: 1920, h: 1080, note: 'NUC/BrightSign 1920x1080 densite 160', wasReadable: true },
  { name: 'portrait-minix', w: 1080, h: 1920, note: 'Minix 4K rote (3840x2160 dp/2) — deja lisible avant', wasReadable: true },
  { name: 'portrait-stick', w: 540, h: 960, note: 'stick Google TV rote (1080x1920 dp/2) — illisible avant', wasReadable: false },
  { name: 'portrait-oppo', w: 411, h: 914, note: 'Oppo CPH2173 rote — illisible avant', wasReadable: false },
];

// 320 px = plancher de lisibilite : en dessous, la colonne de libelles (84 px) plus une valeur
// utile ne tiennent plus sur une ligne, tout part en `word-break:break-all`.
const MIN_PANEL_PX = 320;
const MIN_RIGHT_MARGIN_PX = 16;

function fail(msg) {
  console.error(`\x1b[31mERREUR\x1b[0m ${msg}`);
  process.exit(2);
}

// --- Extraction depuis le VRAI fichier de rendu -------------------------------------------
function harness(file) {
  if (!fs.existsSync(file)) fail(`introuvable : ${file}`);
  const src = fs.readFileSync(file, 'utf8');

  const cssStart = src.indexOf('_overlayEl.style.cssText = [');
  if (cssStart < 0) fail(`${file} : bloc \`_overlayEl.style.cssText = [\` introuvable`);
  const cssEnd = src.indexOf("].join(';')", cssStart);
  if (cssEnd < 0) fail(`${file} : fin du bloc cssText introuvable`);
  let cssText;
  try {
    cssText = new Function(`return ${src.slice(src.indexOf('[', cssStart), cssEnd + 1)}`)().join(';');
  } catch (e) {
    fail(`${file} : cssText non evaluable — ${e.message}`);
  }

  const fns = ['_ovEsc', '_ovRow', '_ovNet']
    .map((name) => {
      const start = src.indexOf(`function ${name}(`);
      if (start < 0) fail(`${file} : fonction ${name} introuvable`);
      const end = src.indexOf('\n}', start);
      if (end < 0) fail(`${file} : fin de ${name} introuvable`);
      return src.slice(start, end + 2);
    })
    .join('\n');

  return { cssText, fns };
}

// Valeurs realistes (longueurs representatives du terrain : nom de fichier, MAC, WAN).
const ROWS_JS = `
  _ovRow('Player', 'Oppo Find X3 Pro  (#2)')
  + _ovRow('Device', 'localhost \\u00b7 android v2.5.30')
  + _ovNet('Network', [['LAN', '192.168.1.140'], ['MAC', 'a4:50:46:1c:9d:33'], ['WAN', '82.65.144.21']])
  + _ovRow('Display', '540\\u00d7960 \\u00b7 decode hevc,h264')
  + _ovRow('LAN sync', 'group "showroom" \\u00b7 follower')
  + _ovRow('Program', 'Governance (compiled program)')
  + _ovRow('Playlist', 'Vitrine portrait (#41) \\u00b7 item 3/12')
  + _ovRow('Media', 'Teaser vertical 9:16 (video)')
  + _ovRow('Playback', '2160\\u00d73840 \\u00b7 12s / 1m05s')
  + _ovRow('File', 'a3f9c1e0-teaser-vertical-2160x3840-h265.mp4')
`;

async function measure(browser, h, vp, shotPath) {
  const page = await browser.newPage({ viewport: { width: vp.w, height: vp.h } });
  await page.setContent(
    `<!doctype html><html><head><meta charset="utf-8">
     <style>html,body{margin:0;padding:0;height:100%;overflow:hidden;background:#101828}</style>
     </head><body><script>
       ${h.fns}
       const el = document.createElement('div');
       el.id = 'sf-maint-overlay';
       el.style.cssText = ${JSON.stringify(h.cssText)};
       el.innerHTML = '<div style="font-weight:600;color:#7fb0ff;margin-bottom:6px;letter-spacing:.5px">SignFlow \\u00b7 MAINTENANCE</div>' + (${ROWS_JS});
       document.body.appendChild(el);
     </script></body></html>`,
    { waitUntil: 'load' },
  );
  const m = await page.locator('#sf-maint-overlay').evaluate((el) => {
    const r = el.getBoundingClientRect();
    return {
      w: Math.round(r.width),
      h: Math.round(r.height),
      right: Math.round(r.right),
      overflow: el.scrollWidth - el.clientWidth,
      maxWidth: getComputedStyle(el).maxWidth,
    };
  });
  if (shotPath) await page.screenshot({ path: shotPath });
  await page.close();
  return m;
}

// --- Execution -----------------------------------------------------------------------------
const cur = harness(TARGET);
const base = BASELINE ? harness(path.resolve(BASELINE)) : null;

const browser = await chromium.launch({ channel: 'chrome' });
fs.mkdirSync(OUT, { recursive: true });

let failures = 0;
console.log(`Cible    : ${path.relative(ROOT, TARGET)}`);
console.log(`Regle    : ${(cur.cssText.match(/max-width:[^;]+/) || ['(aucune)'])[0]}`);
if (base) console.log(`Baseline : ${(base.cssText.match(/max-width:[^;]+/) || ['(aucune)'])[0]}`);
console.log('');

for (const vp of VIEWPORTS) {
  const shot = path.join(OUT, `overlay-${vp.name}.png`);
  const m = await measure(browser, cur, vp, shot);
  const b = base ? await measure(browser, base, vp, null) : null;

  console.log(`${vp.name}  ${vp.w}x${vp.h}  (${vp.note})`);
  console.log(
    `   panneau : ${b ? `${b.w}px  ->  ` : ''}${m.w}x${m.h}px   (max-width calcule : ${m.maxWidth})`,
  );

  const checks = [
    [`largeur >= ${MIN_PANEL_PX}px`, m.w >= MIN_PANEL_PX, `${m.w}px`],
    [
      `marge droite >= ${MIN_RIGHT_MARGIN_PX}px`,
      m.right <= vp.w - MIN_RIGHT_MARGIN_PX,
      `bord droit a ${m.right} pour ${vp.w}`,
    ],
    ['aucun debordement horizontal', m.overflow <= 1, `${m.overflow}px`],
  ];
  if (b && vp.wasReadable) {
    // Non-regression MESUREE (et non un nombre magique) : les ecrans qui allaient deja bien
    // — tout le parc paysage, et le Minix 4K en portrait — ne doivent pas bouger d'un pixel.
    checks.push(['rendu inchange vs baseline', m.w === b.w && m.h === b.h, `${b.w}x${b.h} -> ${m.w}x${m.h}`]);
  }
  if (b && !vp.wasReadable) {
    // TEMOIN : la baseline DOIT echouer ici, sinon la sonde ne prouve rien.
    checks.push([
      'temoin : la baseline etait bien sous le plancher',
      b.w < MIN_PANEL_PX,
      `baseline ${b.w}px (doit etre < ${MIN_PANEL_PX})`,
    ]);
  }
  for (const [label, ok, detail] of checks) {
    if (!ok) failures++;
    console.log(`   ${ok ? '\x1b[32mok  \x1b[0m' : '\x1b[31mFAIL\x1b[0m'} ${label} -- ${detail}`);
  }
  console.log(`   capture : ${path.relative(ROOT, shot)}\n`);
}

await browser.close();

if (failures) {
  console.log(`\x1b[31m${failures} constat(s).\x1b[0m`);
  process.exit(1);
}
console.log('\x1b[32m0 constat.\x1b[0m');
if (!base) {
  console.log(
    "\x1b[33mSans --baseline, ce '0 constat' n'est pas temoigne :\x1b[0m rejouer avec\n" +
      '  --baseline <copie du player.js d\'avant correctif>  pour exiger que la sonde sache echouer.',
  );
}
