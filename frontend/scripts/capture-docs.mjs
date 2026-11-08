/**
 * Captures d'écran de présentation (`docs/screenshots/`) — script relançable.
 *
 * Même principe que `capture-manual.mjs` (les captures se REJOUENT, jamais à la main),
 * mais pour le jeu PROSPECT : 19 PNG pleine page (1920×1080) utilisés par le bundle
 * `Signflow_docs_FR-EN.zip` et les présentations. Le jeu précédent datait du 2026-06-30,
 * AVANT la refonte « Mission Control » du 17/07 — dix-neuf images d'un thème disparu.
 *
 * USAGE (depuis frontend/)
 *   node scripts/capture-docs.mjs                 # tout
 *   node scripts/capture-docs.mjs 01_dashboard    # une sélection
 *
 * VARIABLES
 *   SF_BASE   URL du CMS à capturer   (défaut : http://localhost:8080)
 *   SF_TOKEN  jeton d'accès org-admin (obligatoire, forgé côté serveur, expire en ~15 min)
 *   SF_OUT    dossier de sortie       (défaut : ../docs/screenshots)
 *
 * ⚠️ Sortie en PNG (contrairement au manuel qui sert du WebP) : c'est le format que le
 * bundle et les présentations consomment.
 */

import { chromium } from '@playwright/test'
import { mkdir, readFile } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.SF_BASE ?? 'http://localhost:8080'
const TOKEN = process.env.SF_TOKEN
const OUT = process.env.SF_OUT ?? path.join(process.cwd(), '..', 'docs', 'screenshots')

if (!TOKEN) {
  console.error('SF_TOKEN manquant — forge un jeton org-admin et passe-le par l’environnement.')
  process.exit(1)
}

// Les 19 vues du jeu prospect. Les chemins sont ceux de la sidebar (Sidebar.tsx), vérifiés.
const SHOTS = [
  { name: '01_dashboard', url: '/dashboard' },
  { name: '02_players', url: '/players' },
  { name: '03_proof_of_play', url: '/reports/proof-of-play' },
  { name: '04_studio', url: '/studio' },
  {
    name: '05_assistant',
    url: '/dashboard',
    // Le widget assistant s'ouvre au raccourci documenté — on capture son état d'accueil
    // (aucune question envoyée : pas d'appel IA facturé sur la prod pour une capture).
    act: async (page) => {
      await page.keyboard.press('Control+Shift+A')
      await page.waitForTimeout(2000)
    },
  },
  { name: '06_media', url: '/media' },
  { name: '07_playlists', url: '/playlists' },
  { name: '08_schedules', url: '/schedules' },
  { name: '09_templates', url: '/templates' },
  { name: '10_feeds', url: '/feeds' },
  {
    name: '11_governance',
    url: '/governance',
    // Sans sélection, la page dit juste « Sélectionnez un nœud » : on ouvre le premier
    // nœud de l'arbre pour montrer réglages + programme compilé.
    act: async (page) => {
      await page.locator('main [class*="cursor-pointer"], main button, main li').first()
        .click({ timeout: 10000 })
      await page.waitForTimeout(1500)
    },
  },
  { name: '12_reports', url: '/reports/executive' },
  { name: '13_events', url: '/events' },
  { name: '14_audio_baskets', url: '/audio-baskets' },
  { name: '15_provisioning', url: '/settings/players/provisioning' },
  { name: '16_url_display', url: '/url-display' },
  { name: '17_vod', url: '/vod' },
  { name: '18_firmware', url: '/settings/firmware' },
  { name: '19_ai_keys', url: '/settings/ai-keys' },
]

// Le garde de route exige le magasin `sf-auth` complet, pas le seul jeton (cf. capture-manual).
const meRes = await fetch(`${BASE}/api/v1/users/me`, {
  headers: { Authorization: `Bearer ${TOKEN}` },
})
if (!meRes.ok) {
  console.error(`Jeton refusé par ${BASE} (HTTP ${meRes.status}) — forge-en un neuf, ils expirent vite.`)
  process.exit(1)
}
const ME = await meRes.json()
console.log(`Session : ${ME.email} (org ${ME.id_org}), rôles ${(ME.roles ?? []).join(', ')}`)

await mkdir(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome' })
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })

// Bulles d'aide neutralisées — lues DANS le composant, comme capture-manual.mjs.
const TIP_KEYS = (await readFile('src/components/layout/DemoTips.tsx', 'utf8'))
  .split(/\r?\n/)
  .map((l) => l.match(/^\s*\['[^']+',\s*'([^']+)'\]/))
  .filter(Boolean)
  .map((m) => m[1])

await context.addInitScript(([tk, me, tips]) => {
  localStorage.setItem('sf_access_token', tk)
  localStorage.setItem('sf_refresh_token', tk)
  localStorage.setItem('sf-auth', JSON.stringify({
    state: { user: me, accessToken: tk, refreshToken: tk, roles: me.roles ?? [] },
    version: 0,
  }))
  for (const k of tips) localStorage.setItem(`sf-tip:${k}`, '1')
}, [TOKEN, ME, TIP_KEYS])

const page = await context.newPage()
const only = process.argv.slice(2)
const resultats = []

for (const shot of SHOTS) {
  if (only.length && !only.includes(shot.name)) continue
  try {
    await page.goto(`${BASE}${shot.url}`, { waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForSelector('main, [role="main"], h1, h2', { timeout: 15000 })
    await page.waitForTimeout(1200)
    if (shot.act) await shot.act(page)
    // Une capture de /login est un ÉCHEC, pas une réussite (leçon capture-manual).
    if (page.url().includes('/login')) {
      resultats.push([shot.name, 'ECHEC session perdue', page.url()])
      continue
    }
    await page.screenshot({ path: path.join(OUT, `${shot.name}.png`) })
    resultats.push([shot.name, 'OK', page.url()])
  } catch (err) {
    resultats.push([shot.name, `ÉCHEC ${String(err).slice(0, 80)}`, page.url()])
  }
}

await browser.close()

console.log('\n--- résultat ---')
for (const [n, s, u] of resultats) console.log(`  ${s.padEnd(12)} ${n.padEnd(22)} ${u}`)
const ko = resultats.filter(([, s]) => s !== 'OK').length
console.log(`\n${resultats.length - ko} capture(s) réussie(s), ${ko} en échec.`)
process.exit(ko ? 1 : 0)
