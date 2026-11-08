/**
 * Captures de l'écran `/promo` en FHD — script de DIAGNOSTIC, relançable.
 *
 * POURQUOI. Demande d'Ed (2026-08-10) après avoir regardé le parcours en étapes : « fais des
 * tests de screenshot afin que tu puisses voir les problèmes visuels avec un écran FHD ».
 * Un défaut de mise en page ne se voit pas dans le code ni dans une assertion Playwright —
 * il se REGARDE. Ce script produit une image par état de l'écran, toujours les mêmes, pour
 * qu'on puisse comparer avant/après un correctif au lieu d'en juger de mémoire.
 *
 * ⚠️ 1920×1080 exactement : c'est la définition où le problème a été signalé (l'ultrawide
 * d'Ed masque les débordements verticaux, un portable les exagère).
 *
 * USAGE
 *   SF_TOKEN=<jeton org-admin> node scripts/capture-promo.mjs
 *
 * VARIABLES
 *   SF_BASE   URL du CMS à capturer     (défaut : http://localhost:8080)
 *   SF_TOKEN  jeton d'accès org-admin   (obligatoire — forgé côté serveur, jamais écrit ici)
 *   SF_OUT    dossier de sortie         (obligatoire : hors du dépôt, ce sont des diagnostics)
 */

import { chromium } from '@playwright/test'
import { mkdir, readFile } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.SF_BASE ?? 'http://localhost:8080'
const TOKEN = process.env.SF_TOKEN
const OUT = process.env.SF_OUT
if (!TOKEN || !OUT) {
  console.error('SF_TOKEN et SF_OUT sont obligatoires.')
  process.exit(1)
}

const step = (page, key) => page.getByTestId(`step-${key}`)
const openOnly = async (page, key) => {
  // Clique l'en-tête d'une étape si elle n'est pas déjà ouverte — on lit l'ÉTAT publié par le
  // composant (`data-open`) plutôt que de supposer, sinon un clic de trop la referme.
  const s = step(page, key)
  if ((await s.getAttribute('data-open')) !== 'true') await s.getByRole('button').first().click()
  await page.waitForTimeout(350)
}

/** Un état = une image. `act` amène l'écran dans l'état voulu. */
const SHOTS = [
  { name: '01-initial', act: async () => {} },
  { name: '02-etape-produit', act: (p) => openOnly(p, 'product') },
  { name: '03-etape-texte-prix', act: (p) => openOnly(p, 'content') },
  { name: '04-etape-mise-en-page', act: (p) => openOnly(p, 'layout') },
  { name: '05-etape-fond', act: (p) => openOnly(p, 'background') },
  {
    name: '06-plusieurs-etapes-ouvertes',
    act: async (p) => { for (const k of ['product', 'content', 'layout', 'background']) await openOnly(p, k) },
  },
  {
    name: '07-tiroir-mediatheque',
    act: async (p) => {
      await openOnly(p, 'product')
      await p.getByTestId('promo-pick-product').click()
      await p.waitForTimeout(1200)
    },
  },
  {
    // Mode série : le tableau avec de vraies lignes, dont une VOLONTAIREMENT sans prix —
    // c'est l'avertissement « écartée » qu'on veut voir sur la capture, pas un tableau parfait.
    name: '09-mode-serie',
    act: async (p) => {
      await p.getByTestId('promo-mode-serie').click()
      await p.getByTestId('serie-paste-toggle').click()
      await p.getByTestId('serie-paste-area').fill([
        'Produit;Prix;Prix barré',
        'Tarte aux pommes;12,90;15,90',
        'Pain au levain 1 kg;5,40;6,20',
        'Coffret café moulu;18,00;22,00',
        'Confiture artisanale;;7,50',
        'Panier petit-déjeuner;24,00;29,00',
      ].join('\n'))
      await p.getByTestId('serie-paste-apply').click()
      await p.waitForTimeout(1500)
    },
  },
  {
    name: '08-tiroir-reglages',
    act: async (p) => {
      await p.getByTestId('promo-open-settings').click()
      await p.waitForTimeout(1200)
    },
  },
]

const meRes = await fetch(`${BASE}/api/v1/users/me`, { headers: { Authorization: `Bearer ${TOKEN}` } })
if (!meRes.ok) { console.error(`users/me -> ${meRes.status}`); process.exit(1) }
const ME = await meRes.json()
console.log(`Session : ${ME.email} (org ${ME.id_org})`)

await mkdir(OUT, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome' })
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })

// Bulles d'aide neutralisées : elles se posent en bas à droite et RECOUVRENT le contenu —
// clés lues DANS le composant, jamais recopiées (une liste figée raterait toute bulle future).
const TIP_KEYS = (await readFile('src/components/layout/DemoTips.tsx', 'utf8'))
  .split(/\r?\n/)
  .map((l) => l.match(/^\s*\['[^']+',\s*'([^']+)'\]/))
  .filter(Boolean)
  .map((m) => m[1])

await context.addInitScript(([tk, me, keys]) => {
  localStorage.setItem('sf_access_token', tk)
  localStorage.setItem('sf_refresh_token', tk)
  localStorage.setItem('sf-auth', JSON.stringify({
    state: { user: me, accessToken: tk, refreshToken: tk, roles: me.roles ?? [] }, version: 0,
  }))
  for (const k of keys) localStorage.setItem(`sf-tip:${k}`, '1')
}, [TOKEN, ME, TIP_KEYS])

const page = await context.newPage()
const res = []
for (const shot of SHOTS) {
  try {
    await page.goto(`${BASE}/promo`, { waitUntil: 'networkidle', timeout: 30000 })
    // On attend que le parcours soit monté, jamais un délai fixe : une attente arbitraire
    // capture soit trop tôt (écran vide), soit pour rien.
    await step(page, 'who').waitFor({ state: 'visible', timeout: 20000 })
    await page.waitForTimeout(900)
    await shot.act(page)
    const file = path.join(OUT, `promo-${shot.name}.png`)
    await page.screenshot({ path: file })
    res.push([shot.name, 'OK'])
  } catch (e) {
    res.push([shot.name, `ECHEC ${String(e).split('\n')[0].slice(0, 90)}`])
  }
}
await browser.close()
for (const [n, r] of res) console.log(`  ${n.padEnd(30)} ${r}`)
const ko = res.filter(([, r]) => r !== 'OK').length
console.log(ko ? `${ko} capture(s) en échec` : `${res.length} captures dans ${OUT}`)
process.exit(ko ? 1 : 0)
