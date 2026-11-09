import { test, expect } from '@playwright/test'

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'

async function setAuthAndNavigate(page: import('@playwright/test').Page, url: string, locale = 'fr') {
  await page.goto(`${BASE}/login`)
  await page.evaluate((locale) => {
    const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale, is_active: true, last_login_at: null, created_at: new Date().toISOString() }, accessToken: token, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', token)
    document.cookie = `locale=${locale}; path=/`
  }, locale)
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale, is_active: true, last_login_at: null, created_at: new Date().toISOString() }),
    })
  })
  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: MOCK_TOKEN, refresh_token: 'r', token_type: 'bearer', locale }),
    })
  })
  await page.goto(url)
}

test.describe('User manual (/help)', () => {
  test('help_page_renders_french_manual_with_toc', async ({ page }) => {
    await setAuthAndNavigate(page, `${BASE}/help`, 'fr')

    // Entrée sidebar présente
    await expect(page.getByRole('navigation', { name: 'Main navigation' })
      .getByText('Manuel utilisateur')).toBeVisible()

    // Le manuel FR se charge : titres de sections clés rendus
    await expect(page.getByRole('heading', { name: 'Bienvenue dans Vitrail' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Campagnes (retail media)' })).toBeVisible()

    // Sommaire : le lien d'ancre de la section campagnes existe
    await expect(page.locator('aside a[href="#campagnes-retail-media"]')).toBeVisible()
  })

  test('help_search_filters_sections', async ({ page }) => {
    await setAuthAndNavigate(page, `${BASE}/help`, 'fr')
    await expect(page.getByRole('heading', { name: 'Bienvenue dans Vitrail' })).toBeVisible()

    await page.getByPlaceholder('Rechercher dans le manuel…').fill('Jeanine')
    await expect(page.getByRole('heading', { name: 'Assistant IA et Jeanine' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Bienvenue dans Vitrail' })).toHaveCount(0)
  })

  test('help_screenshots_render_and_are_clickable', async ({ page }) => {
    await setAuthAndNavigate(page, `${BASE}/help`, 'fr')
    await expect(page.getByRole('heading', { name: 'Bienvenue dans Vitrail' })).toBeVisible()

    // La capture du dashboard est rendue, chargée (pas de 404) et ouvre la pleine taille.
    const shot = page.locator('img[src="/help/img/fr/dashboard.webp"]')
    await expect(shot).toBeVisible()
    await expect
      .poll(async () => shot.evaluate((el: HTMLImageElement) => el.naturalWidth))
      .toBeGreaterThan(0)
    await expect(page.locator('a[href="/help/img/fr/dashboard.webp"]')).toHaveAttribute('target', '_blank')

    // Légende affichée sous la capture.
    await expect(page.getByText('Le tableau de bord : indicateurs du réseau', { exact: false })).toBeVisible()
  })

  // Garde : le renderer de /help ne supporte NI les tableaux `|…|` NI l'italique `*x*`.
  // Un manuel qui en contient les affiche en TEXTE BRUT (pipes et astérisques visibles) —
  // vécu jusqu'au 2026-08-16 : 3 tableaux (28 lignes × 5 locales) rendus en vrac.
  // Ce test lit les 5 manuels tels que servis et refuse tout construct non supporté.
  test('help_manuals_use_only_supported_markdown', async ({ page }) => {
    for (const loc of ['fr', 'en', 'es', 'pt', 'de']) {
      const res = await page.request.get(`${BASE}/help/manual.${loc}.md`)
      expect(res.ok(), `manual.${loc}.md doit être servi`).toBeTruthy()
      const md = await res.text()
      const lines = md.split('\n')
      const pipes = lines.filter((l) => l.trim().startsWith('|'))
      expect(pipes, `manual.${loc}.md : lignes de tableau non supportées`).toHaveLength(0)
      // Italique simple : un astérisque restant une fois les **gras** retirés.
      const noBold = md.replace(/\*\*[^*]+\*\*/g, '')
      expect(noBold.includes('*'), `manual.${loc}.md : italique *x* non supporté`).toBeFalsy()
      // Puce enveloppée : une ligne de continuation indentée casse la liste au rendu.
      const wrapped = lines.filter((l) => /^\s+\S/.test(l) && !l.trim().startsWith('!['))
      expect(wrapped, `manual.${loc}.md : continuation de puce indentée`).toHaveLength(0)
    }
  })

  test('help_governance_roles_render_as_list', async ({ page }) => {
    await setAuthAndNavigate(page, `${BASE}/help`, 'fr')
    await expect(page.getByRole('heading', { name: 'Bienvenue dans Vitrail' })).toBeVisible()

    // Les ex-tableaux (rôles gouvernance + rôles fournis) rendent en <li>, sans pipe visible.
    await expect(page.locator('#help-content li', { hasText: 'Gouvernance — Directeur' })).toBeVisible()
    await expect(page.locator('#help-content li', { hasText: "Administrateur d'organisation" }).first()).toBeVisible()
    const raw = await page.locator('#help-content').innerText()
    expect(raw.includes('|---'), 'séparateur de tableau visible dans le rendu').toBeFalsy()
  })

  test('help_page_english_manual', async ({ page }) => {
    await setAuthAndNavigate(page, `${BASE}/help`, 'en')
    await expect(page.getByRole('heading', { name: 'Welcome to Vitrail' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'AI assistant and Jeanine' })).toBeVisible()
  })
})
