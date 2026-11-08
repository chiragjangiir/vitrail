#!/usr/bin/env node
/**
 * Comparatif typographique de l'interface — RENDU, pas avis.
 *
 *   node scripts/compare-fonts.mjs [--out DIR]
 *   -> tests/e2e/__shots__/fonts-*.png  +  le tableau des largeurs sur stdout
 *
 * Pourquoi ce script existe : le cadrage (docs/PLAN_DEV_2026-08.md) pose que ces
 * polices « n'ont été jugées que de mémoire, jamais rendues à 11 px sur notre fond
 * sombre ». On les rend donc côte à côte, aux TAILLES RÉELLES du produit
 * (text-[10px]/[11px] de la table du parc et de la recherche), sur le VRAI fond
 * `#0B0C10`, avec les VRAIES chaînes qu'affiche le CMS : IP, MAC, versions `1.0.34`,
 * schémas `0128`, horodatages.
 *
 * Les polices sont embarquées en base64 : la planche est autonome et ne dépend
 * d'aucun réseau — comme doit l'être le produit lui-même sur un site client.
 *
 * ⚠️ Encode Sans est une police VARIABLE : ses trois graisses sont le même fichier
 * (md5 identique, mesuré). La déclarer avec trois `font-weight` fixes ferait rendre
 * les trois au même poids et la condamnerait pour une raison fausse — d'où la
 * syntaxe de PLAGE `font-weight: 400 600` sur une seule déclaration.
 */
import { readFileSync, mkdirSync, existsSync } from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const arg = (n, d) => { const i = process.argv.indexOf(n); return i > -1 ? process.argv[i + 1] : d }
const OUT = arg('--out', 'tests/e2e/__shots__')
const FONT_DIR = 'public/fonts/ui-eval'
const PROMO_DIR = 'public/fonts/promo'

const b64 = (p) => readFileSync(p).toString('base64')
const face = (family, weight, file) =>
  `@font-face{font-family:'${family}';font-weight:${weight};font-style:normal;` +
  `src:url(data:font/woff2;base64,${b64(file)}) format('woff2')}`

/** Les quatre propositions du cadrage, chacune avec sa pile réelle. */
function buildFaces() {
  const css = []
  // Inter — déjà embarquée dans le produit (public/fonts/promo).
  for (const w of [400, 500, 600]) css.push(face('CmpInter', w, `${PROMO_DIR}/inter-${w}.woff2`))
  // Fira Sans — statiques, une par graisse.
  for (const w of [400, 500, 600]) css.push(face('CmpFira', w, `${FONT_DIR}/fira-sans-${w}.woff2`))
  // Fira Mono — le compagnon à chasse fixe.
  for (const w of [400, 500, 700]) css.push(face('CmpFiraMono', w, `${FONT_DIR}/fira-mono-${w}.woff2`))
  // Encode Sans — VARIABLE : une seule déclaration, plage de graisses.
  css.push(
    `@font-face{font-family:'CmpEncode';font-weight:400 600;font-style:normal;` +
    `src:url(data:font/woff2;base64,${b64(`${FONT_DIR}/encode-sans-400.woff2`)}) format('woff2')}`)
  return css.join('\n')
}

const COLUMNS = [
  { key: 'inter', name: 'Inter', sub: 'l’actuelle', stack: `'CmpInter'`,
    mono: `ui-monospace, Consolas, monospace`, note: 'référence' },
  { key: 'fira', name: 'Fira Sans', sub: 'OFL · + Fira Mono', stack: `'CmpFira'`,
    mono: `'CmpFiraMono'`, note: 'une famille pour le texte ET la chasse fixe' },
  { key: 'encode', name: 'Encode Sans', sub: 'OFL · variable', stack: `'CmpEncode'`,
    mono: `ui-monospace, Consolas, monospace`, note: 'pas de compagnon monospace' },
  { key: 'mixed', name: 'Inter + Fira Mono', sub: 'la variante sans risque', stack: `'CmpInter'`,
    mono: `'CmpFiraMono'`, note: 'aucune métrique de mise en page ne bouge' },
]

// Lignes calquées sur la vue liste du parc (colonnes réelles, données réalistes).
const ROWS = [
  ['AOpen Vitrine', 'Site-01', 'windows', '1.6.20', '10.0.0.136', '3 min', 'online'],
  ['RPi Entrée', 'Site-01', 'linux-arm64', '1.6.17', '10.0.0.127', '11 min', 'online'],
  ['NUC Boucherie', 'Site-02', 'linux-x64', '1.5.21', '10.0.0.132', '1 h 04', 'warning'],
  ['BrightSign XT1144', 'Site-02', 'brightsign', '2.0.34', '10.0.0.141', '2 j', 'critical'],
  ['ChromeBox Acer', 'Siège', 'chromeos', '2.0.15', '10.0.0.118', '18 h', 'critical'],
]

function column(c) {
  const st = (s) => `font-family:${s},system-ui,sans-serif`
  return `
  <section class="col">
    <header>
      <h2 style="${st(c.stack)}">${c.name}</h2>
      <p class="sub">${c.sub}</p>
      <p class="note">${c.note}</p>
    </header>

    <div class="lbl">Vue liste du parc &mdash; 11 px, le cas réel le plus dense</div>
    <table style="${st(c.stack)}">
      <thead><tr><th>Écran</th><th>Site</th><th>OS</th><th>Ver.</th><th>Adresse</th><th>Vu</th></tr></thead>
      <tbody>
        ${ROWS.map((r) => `<tr>
          <td class="nm">${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td>
          <td class="num" style="${st(c.mono)}">${r[3]}</td>
          <td class="num" style="${st(c.mono)}">${r[4]}</td>
          <td>${r[5]}</td></tr>`).join('')}
      </tbody>
    </table>

    <div class="lbl">Sous-titres de la recherche &mdash; 10 px</div>
    <p class="tiny" style="${st(c.stack)}">
      AI&nbsp;Generate &middot; 2026-07-02 10:14<br>Video / Divers &middot; 3 playlists, 8 écrans
    </p>

    <div class="lbl">Ambiguïtés dans la police de TEXTE &mdash; 13 px puis 11 px</div>
    <p class="amb" style="${st(c.stack)}" data-sans="${c.key}">Il1 | O0 | rn m | 5S 2Z 8B</p>
    <p class="amb small" style="${st(c.stack)}">Il1 | O0 | rn m | 5S 2Z 8B</p>

    <div class="lbl">Ambiguïtés en CHASSE FIXE &mdash; 32 surfaces (IP, MAC, versions)</div>
    <p class="amb" style="${st(c.mono)}">Il1 | O0 | rn m | 5S 2Z 8B</p>
    <p class="amb small" style="${st(c.mono)}">a4:bb:6d:0f:1e:9c &middot; 0128 &middot; 1.0.34</p>

    <div class="lbl">Les trois graisses réellement utilisées</div>
    <p class="w" style="${st(c.stack)};font-weight:400">400 &mdash; corps de texte, 549 usages</p>
    <p class="w" style="${st(c.stack)};font-weight:500">500 &mdash; libellés</p>
    <p class="w" style="${st(c.stack)};font-weight:600">600 &mdash; 127 titres et en-têtes</p>
    <!-- Sondes du témoin : MÊME chaîne aux deux graisses. Mesurer deux phrases
         différentes ne dirait rien de la graisse, seulement de leur longueur. -->
    <span class="probe" style="${st(c.stack)};font-weight:400" data-w400="${c.key}">Programmes &amp; écrans 0128</span>
    <span class="probe" style="${st(c.stack)};font-weight:600" data-w600="${c.key}">Programmes &amp; écrans 0128</span>

    <div class="lbl">Phrase de l’interface &mdash; 13 px</div>
    <p class="body" style="${st(c.stack)}" data-measure="${c.key}">
      Vos choix ont changé depuis cette proposition&nbsp;: le plan ne couvre plus
      tous les types sélectionnés.
    </p>
  </section>`
}

const HTML = `<!doctype html><meta charset="utf-8"><style>
${buildFaces()}
*{box-sizing:border-box}
body{margin:0;background:#0B0C10;color:#E2E8F0;font-family:system-ui,sans-serif}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:0}
.col{padding:18px 16px;border-right:1px solid rgba(255,255,255,.06)}
.col:last-child{border-right:0}
header{margin-bottom:14px}
h2{margin:0;font-size:19px;font-weight:600}
.sub{margin:2px 0 0;font-size:11px;color:#8A93A6}
.note{margin:4px 0 0;font-size:10.5px;color:#5B6273;font-style:italic}
.lbl{margin:16px 0 5px;font-size:9px;letter-spacing:.09em;text-transform:uppercase;color:#5B6273}
table{width:100%;border-collapse:collapse;font-size:11px}
th{text-align:left;font-weight:600;color:#8A93A6;font-size:10px;padding:4px 5px 4px 0;
   border-bottom:1px solid rgba(255,255,255,.08)}
td{padding:4px 5px 4px 0;border-bottom:1px solid rgba(255,255,255,.04);color:#E2E8F0}
td.nm{font-weight:500}
td.num{font-variant-numeric:tabular-nums;color:#8A93A6}
.tiny{margin:0;font-size:10px;line-height:1.55;color:#8A93A6}
.amb{margin:0 0 4px;font-size:13px;letter-spacing:.02em}
.amb.small{font-size:11px;color:#8A93A6}
.w{margin:0 0 3px;font-size:13px}
.body{margin:0;font-size:13px;line-height:1.5;color:#E2E8F0}
.probe{position:absolute;visibility:hidden;white-space:nowrap;font-size:13px}
</style>
<div class="grid">${COLUMNS.map(column).join('')}</div>`

const run = async () => {
  for (const d of [FONT_DIR, PROMO_DIR]) {
    if (!existsSync(d)) {
      console.error(`!! repertoire absent : ${d}`)
      console.error('')
      console.error('Les polices CANDIDATES (Fira Sans, Encode Sans) ont ete retirees du depot')
      console.error("apres la decision du 2026-08-11 — on n'embarque que ce qu'on sert.")
      console.error('Pour rejouer le comparatif complet, les retelecharger dans ce repertoire :')
      console.error('  Fira Sans 400/500/600, Fira Mono 400/500/700, Encode Sans 400 (variable)')
      console.error('  depuis fonts.googleapis.com, sous-ensemble latin, en woff2.')
      process.exit(1)
    }
  }
  mkdirSync(OUT, { recursive: true })
  // `channel: 'chrome'` = le Chrome du système : le CDN de Playwright est inaccessible
  // depuis ce poste, contrainte déjà documentée pour la suite de tests.
  const browser = await chromium.launch({ channel: 'chrome' })
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2 })   // x2 : on juge du 10 px, il faut pouvoir zoomer sans flou
  await page.setContent(HTML, { waitUntil: 'load' })
  await page.evaluate(() => document.fonts.ready)

  await page.screenshot({ path: path.join(OUT, 'fonts-comparatif.png'), fullPage: true })


  // ── Le coût MESURÉ du changement : de combien les métriques bougent-elles ? ──
  // C'est ce qui déplace les points de troncature, les largeurs de colonnes et
  // périme les captures du manuel. Un chiffre vaut mieux qu'une intuition.
  const measure = (attr) => page.evaluate((a) => {
    const out = {}
    document.querySelectorAll(`[${a}]`).forEach((el) => {
      const r = document.createRange(); r.selectNodeContents(el)
      out[el.getAttribute(a)] = r.getBoundingClientRect().width
    })
    return out
  }, attr)

  const widths = await measure('data-measure')
  const w400 = await measure('data-w400')
  const w600 = await measure('data-w600')
  // ── Planche 2 : les GLYPHES AMBIGUS, agrandis ────────────────────────────────
  // Le cadrage pose « 1/l/I et 0/O doivent se distinguer ». À 10 px on ne peut pas
  // en juger honnêtement — on montre donc la MÊME chaîne à taille réelle ET à 64 px,
  // qui rend la forme des lettres indiscutable.
  const zoomRow = (c) => `
    <div class="z">
      <div class="zh" style="font-family:${c.stack},sans-serif">${c.name}</div>
      <div class="zbig" style="font-family:${c.stack},sans-serif">Il1 O0 rn</div>
      <div class="zbig mono" style="font-family:${c.mono}">Il1 O0 rn</div>
      <div class="zreal" style="font-family:${c.stack},sans-serif">Il1 O0 rn m &middot; 11 px réel</div>
    </div>`
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>
${buildFaces()}
body{margin:0;background:#0B0C10;color:#E2E8F0;font-family:system-ui,sans-serif;padding:26px 30px}
h1{font-size:15px;font-weight:600;margin:0 0 4px}
.intro{font-size:11.5px;color:#8A93A6;margin:0 0 20px}
.z{display:grid;grid-template-columns:190px 1fr 1fr 210px;align-items:center;gap:22px;
   padding:14px 0;border-bottom:1px solid rgba(255,255,255,.06)}
.zh{font-size:16px;font-weight:600}
.zbig{font-size:64px;line-height:1.05;letter-spacing:.02em}
.zbig.mono{color:#8A93A6}
.zreal{font-size:11px;color:#8A93A6}
.leg{margin-top:16px;font-size:11px;color:#5B6273}
</style>
<h1>Glyphes ambigus &mdash; police de texte (blanc) et chasse fixe (gris)</h1>
<p class="intro">I majuscule &middot; l minuscule &middot; chiffre 1 &nbsp;|&nbsp; O majuscule &middot; zéro &nbsp;|&nbsp; r+n contre m</p>
${COLUMNS.map(zoomRow).join('')}
<p class="leg">Colonne de droite : la m&ecirc;me cha&icirc;ne &agrave; 11 px, la taille r&eacute;elle de la vue liste du parc.</p>`,
    { waitUntil: 'load' })
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(OUT, 'fonts-glyphes.png'), fullPage: true })

  await browser.close()

  console.log('\n=== LARGEUR RENDUE DE LA MEME PHRASE (13 px) ===')
  const ref = widths.inter
  for (const c of COLUMNS) {
    const w = widths[c.key]
    const d = ((w - ref) / ref) * 100
    console.log(`${c.name.padEnd(20)} ${w.toFixed(1).padStart(8)} px   ${(d >= 0 ? '+' : '') + d.toFixed(1)} %`)
  }
  console.log('=> une largeur differente deplace les points de troncature et perime les captures du manuel.')

  // ── TEMOIN : le 600 existe-t-il VRAIMENT ? ───────────────────────────────────
  // Le cadrage disqualifie toute famille sans 600 (127 `font-semibold` dans l'UI),
  // et Encode Sans est VARIABLE : si l'axe n'etait pas cable, ses trois graisses
  // rendraient identiques. Un 600 qui ne s'ecarte pas du 400 est un FAUX gras.
  console.log('\n=== TEMOIN : le 600 se distingue-t-il du 400 ? ===')
  for (const c of COLUMNS) {
    const a = w400[c.key], b = w600[c.key]
    const d = ((b - a) / a) * 100
    const ok = Math.abs(d) > 0.4 ? 'OUI' : '!! NON — graisse inerte'
    console.log(`${c.name.padEnd(20)} 400=${a.toFixed(1)}  600=${b.toFixed(1)}  ecart ${d.toFixed(2)} %  ${ok}`)
  }
  console.log(`\nplanche : ${path.join(OUT, 'fonts-comparatif.png')}`)
}

run().catch((e) => { console.error(e); process.exit(1) })
