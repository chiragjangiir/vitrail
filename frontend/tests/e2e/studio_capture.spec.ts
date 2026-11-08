import { test } from '@playwright/test'
import fs from 'node:fs'

/**
 * Captures des trois temps du Studio, pour REGARDER le rendu au lieu de le supposer.
 * Ce n'est PAS un test — il ne porte aucune assertion, donc il ne prouve rien sur le
 * produit ; les propriétés sont prouvées par `studio_phases.spec.ts`. C'est un outil
 * rejouable, qui fait accessoirement office de canari : il parcourt le chemin complet
 * (brief → plan → périmé → reproposer → générer), donc il tombe si un maillon disparaît.
 *
 *   npx playwright test studio_capture --reporter=list
 *   -> tests/e2e/__shots__/studio-*.png
 *
 * Hauteur 950 px en plus du 1080 : c'est la hauteur utile d'un navigateur plein
 * écran sur une dalle FHD, celle qui révèle les débordements (leçon du 10/08).
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const OUT = 'tests/e2e/__shots__'

const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'

const ME = {
  id_user: 1, id_org: 1, email: 'a@t.com', full_name: 'A', avatar_url: null,
  totp_enabled: false, locale: 'en', theme: 'dark', is_active: true, is_demo: false,
  id_advertiser: null, last_login_at: null, created_at: new Date().toISOString(),
  org_name: 'Org', roles: ['CMS_ORG_ADMIN'], permissions: [],
}

const CATALOG = {
  providers: ['fal'],
  models: [
    { id: 'img-a', kind: 'image', provider: 'fal', label: 'FLUX 1.1', tier: 'moderate',
      pricing: { mode: 'per_image', usd: 0.02 }, params: [], input: 'text', max_refs: 4 },
    { id: 'vid-a', kind: 'video', provider: 'fal', label: 'Kling 2.1', tier: 'high',
      pricing: { mode: 'per_video', usd: 0.2 }, params: [], input: 'text',
      supports_negative_prompt: true },
  ],
}

// Concepts longs exprès : une capture sur du texte court ne montre jamais un débordement.
const PLAN = {
  concepts: [
    { title: 'Coureuse au lever du jour',
      prompt: 'Plan large, lumiere rasante, ville qui s eveille, palette chaude, 35 mm, grain leger, silhouette de dos, bitume humide qui renvoie la lumiere.' },
    { title: 'Detail chaussure sur bitume mouille',
      prompt: 'Macro, reflets, contraste eleve, fond neutre, profondeur de champ courte, gouttes en suspension.' },
    { title: 'Groupe d amis, fin de seance',
      prompt: 'Ambiance complice, grain leger, heure doree, cadrage a hauteur d epaule, sourires naturels, arriere-plan urbain flou.' },
  ],
  video_prompt: 'Travelling lateral sur la coureuse, 5 s, lumiere doree, mouvement fluide.',
  voiceover: null,
  music_prompt: null,
}

const CAMPAIGNS = [
  { id_campaign: 1, brief: 'Soldes ete running', ratios: ['16:9'], status: 'processing',
    total_cost_usd: 0.42, jobs_total: 8, jobs_ready: 5, jobs_failed: 0 },
  { id_campaign: 2, brief: 'Rentree scolaire', ratios: ['9:16'], status: 'ready',
    total_cost_usd: 0.31, jobs_total: 6, jobs_ready: 6, jobs_failed: 0 },
]

test('captures des trois temps du studio', async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true })

  await page.route(/\/api\/v1\/(?!generation|users\/me|auth)/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route('**/api/v1/generation/catalog', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CATALOG) }))
  await page.route('**/api/v1/generation/campaigns', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CAMPAIGNS) }))
  await page.route('**/api/v1/generation/campaign/plan', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAN) }))
  await page.route('**/api/v1/generation/campaign', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ id_campaign: 1, brief: 'x', ratios: [], status: 'pending',
        total_cost_usd: null, jobs_total: 8, jobs_ready: 0, jobs_failed: 0 }) }))
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: TOKEN, refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))

  await page.goto(`${BASE}/login`)
  await page.evaluate((tk) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'a@t.com', roles: ['CMS_ORG_ADMIN'], permissions: [] },
        accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, TOKEN)

  // ── Hauteur RÉDUITE : c'est elle qui révèle les débordements. ──────────────
  await page.setViewportSize({ width: 1920, height: 950 })
  await page.goto(`${BASE}/studio`)
  await page.getByRole('heading', { name: /what do you want to announce/i })
    .waitFor({ timeout: 15_000 })
  await page.screenshot({ path: `${OUT}/studio-1-brief.png` })

  // Réglages avancés (tiroir), avec vidéo cochée pour en montrer le contenu réel.
  await page.locator('[data-type="video"]').click()
  await page.getByRole('button', { name: /advanced settings/i }).first().click()
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}/studio-1b-settings.png` })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // Temps 2 — le plan, avec trois concepts + le bloc vidéo.
  await page.getByTestId('brief-input').fill(
    'Soldes ete sur la gamme running, ton dynamique, cible 25-40 ans, mise en avant du -30%')
  await page.getByTestId('propose').click()
  await page.getByRole('heading', { name: /review what the ai understood/i }).waitFor()
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${OUT}/studio-2-plan.png` })

  // Temps 2 bis — l'état PÉRIMÉ, celui qui ferme le défaut.
  await page.getByTestId('back-to-brief').click()
  await page.locator('[data-type="video"]').click()   // on la RETIRE -> plan perime
  await page.getByTestId('back-to-plan').click()
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${OUT}/studio-2b-perime.png` })

  // Temps 3 — la file de génération.
  await page.getByTestId('replan').click()
  await page.getByTestId('generate').click()
  await page.getByRole('heading', { name: /recent/i }).waitFor()
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}/studio-3-run.png` })
})
