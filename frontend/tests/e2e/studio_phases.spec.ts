import { test, expect } from '@playwright/test'

/**
 * Refonte du Studio de campagne (décision d'Ed le 2026-08-11 : « on fait B, et l'entrée
 * de C »). L'écran épouse désormais son flux réel — deux appels serveur séparés par une
 * décision humaine — au lieu d'empiler des blocs dans un défilement de page :
 *
 *   1. Brief       une seule question à l'écran, réglages dans un tiroir
 *   2. Plan        on relit et on corrige ce que l'IA a compris, plein écran
 *   3. Génération  la file d'avancement
 *
 * Ce que ces specs figent, et pourquoi :
 *  · le PLAN PÉRIMÉ — défaut réel trouvé en lisant le code : `toggleType` ne touchait pas
 *    à `plan`, donc cocher « vidéo » APRÈS avoir proposé laissait `video_prompt: null` et
 *    « Générer » partait quand même. Une vidéo PAYANTE lancée sans prompt ;
 *  · les BOUTONS GRISÉS QUI DISENT LEUR RAISON (règle P3.3) — `canPlan`/`canExec`
 *    cumulaient jusqu'à quatre conditions sans qu'aucune ne s'affiche.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

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
      pricing: { mode: 'per_video', usd: 0.2 }, params: [], input: 'text' },
  ],
}

const PLAN = {
  concepts: [
    { title: 'Concept un', prompt: 'prompt un' },
    { title: 'Concept deux', prompt: 'prompt deux' },
    { title: 'Concept trois', prompt: 'prompt trois' },
  ],
  video_prompt: null,          // ← l'IA n'a PAS reçu « vidéo » : c'est tout le sujet
  voiceover: null,
  music_prompt: null,
}

async function boot(page: import('@playwright/test').Page) {
  // ⚠️ Playwright résout les routes de la DERNIÈRE à la première : générique d'abord.
  await page.route(/\/api\/v1\/(?!generation|users\/me|auth)/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route('**/api/v1/generation/catalog', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CATALOG) }))
  await page.route('**/api/v1/generation/campaigns', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route('**/api/v1/generation/campaign/plan', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAN) }))
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
  await page.goto(`${BASE}/studio`)
}

const stepState = (page: import('@playwright/test').Page, key: string) =>
  page.locator(`[data-step="${key}"]`).getAttribute('data-state')

test('le parcours passe du brief au plan, et le plan occupe l ecran', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await boot(page)

  // Temps 1 — une seule question à l'écran.
  await expect(page.getByRole('heading', { name: /what do you want to announce/i }))
    .toBeVisible({ timeout: 10_000 })
  expect(await stepState(page, 'brief')).toBe('current')
  expect(await stepState(page, 'plan')).toBe('todo')

  await page.getByTestId('brief-input').fill('Soldes ete running')
  await page.getByTestId('propose').click()

  // Temps 2 — les concepts sont là, éditables, et le bandeau a avancé.
  await expect(page.getByRole('heading', { name: /review what the ai understood/i }))
    .toBeVisible()
  expect(await stepState(page, 'brief')).toBe('done')
  expect(await stepState(page, 'plan')).toBe('current')
  await expect(page.getByLabel('Concept 1 title')).toHaveValue('Concept un')
  await expect(page.getByLabel('Concept 3 title')).toHaveValue('Concept trois')
})

test('changer les types apres la proposition rend le plan PERIME et bloque la generation',
  async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })

    // Témoin : la génération ne doit JAMAIS partir sur un plan périmé. C'est le
    // défaut réel — une vidéo payante lancée avec `video_prompt: null`.
    let generatePosted = 0
    await page.route('**/api/v1/generation/campaign', (r) => {
      if (r.request().method() === 'POST') generatePosted += 1
      return r.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ id_campaign: 1, brief: 'x', ratios: [], status: 'pending',
          total_cost_usd: null, jobs_total: 1, jobs_ready: 0, jobs_failed: 0 }) })
    })
    await boot(page)

    await page.getByTestId('brief-input').fill('Soldes ete running')
    await page.getByTestId('propose').click()
    await expect(page.getByRole('heading', { name: /review what the ai understood/i })).toBeVisible()

    // Rien n'a changé : aucun avertissement. Un bandeau permanent ne dirait rien.
    await expect(page.getByTestId('stale-plan')).toHaveCount(0)
    await expect(page.getByTestId('generate')).toBeEnabled()

    // On revient au brief et on coche « Vidéo », que le plan ne couvre pas.
    await page.getByTestId('back-to-brief').click()
    await page.locator('[data-type="video"]').click()
    await expect(page.getByTestId('brief-stale')).toBeVisible()

    // 🔑 On revient au plan SANS reproposer : les corrections déjà faites survivent.
    await page.getByTestId('back-to-plan').click()
    await expect(page.getByLabel('Concept 1 title')).toHaveValue('Concept un')

    // Le plan se déclare périmé et la génération est refusée EN LE DISANT.
    await expect(page.getByTestId('stale-plan')).toBeVisible()
    await expect(page.getByTestId('generate-blocker'))
      .toHaveText(/does not cover every selected type/i)
    await expect(page.getByTestId('generate')).toBeDisabled()

    // Le témoin : aucun appel de génération n'est parti.
    expect(generatePosted).toBe(0)

    // Reproposer réaligne le plan et débloque le bouton.
    await page.getByTestId('replan').click()
    await expect(page.getByTestId('stale-plan')).toHaveCount(0)
    await expect(page.getByTestId('generate')).toBeEnabled()
  })

test('le bouton grise DIT sa raison', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await boot(page)

  // Brief vide : la raison est écrite, pas seulement le bouton éteint.
  await expect(page.getByTestId('propose-blocker'))
    .toHaveText(/describe your campaign/i, { timeout: 10_000 })
  await expect(page.getByTestId('propose')).toBeDisabled()

  // Brief rempli : la raison disparaît et le bouton s'arme.
  await page.getByTestId('brief-input').fill('Soldes ete running')
  await expect(page.getByTestId('propose-blocker')).toHaveCount(0)
  await expect(page.getByTestId('propose')).toBeEnabled()

  // Plus aucun type coché : la raison change, elle ne disparaît pas.
  await page.locator('[data-type="image"]').click()
  await expect(page.getByTestId('propose-blocker')).toHaveText(/at least one content type/i)
})

test('les reglages sont hors du flux, dans un tiroir', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await boot(page)

  // Le nombre de concepts n'encombre plus la page : il vit dans « Advanced settings ».
  await expect(page.getByRole('heading', { name: /what do you want to announce/i }))
    .toBeVisible({ timeout: 10_000 })

  // ⚠️ Un tiroir FERMÉ n'est pas démonté : il est translaté hors champ. Playwright le
  // compte donc « visible » (boîte non nulle) — `not.toBeVisible()` échouerait sur un
  // produit parfaitement juste. On juge ce qui compte : le champ est-il DANS le cadre ?
  const concepts = page.locator('input[type="number"][max="6"]')
  const width = page.viewportSize()!.width
  const closed = await concepts.boundingBox()
  expect(closed, 'le champ doit exister, mais hors du cadre').not.toBeNull()
  expect(closed!.x).toBeGreaterThanOrEqual(width)

  await page.getByRole('button', { name: /advanced settings/i }).first().click()
  await expect.poll(async () => (await concepts.boundingBox())!.x).toBeLessThan(width)
})
