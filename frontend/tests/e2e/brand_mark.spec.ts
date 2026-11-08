import { test, expect } from '@playwright/test'

/**
 * Logo Vitrail dans l'UI (sidebar + page de connexion).
 *
 * Pourquoi un garde : un `<img>` dont la source répond 404 ne casse rien — il ne rend
 * simplement RIEN. Le logo disparaîtrait sans qu'aucune erreur ne le signale. On exige donc
 * que l'image soit RÉELLEMENT décodée (`naturalWidth > 0`), pas seulement présente.
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

/** L'image est-elle réellement décodée par le navigateur ? */
const decoded = (page: import('@playwright/test').Page, src: string) =>
  page.evaluate((s) => {
    const img = [...document.querySelectorAll('img')]
      .find((i) => i.currentSrc.includes(s) || i.src.includes(s)) as HTMLImageElement | undefined
    return img ? { found: true, w: img.naturalWidth } : { found: false, w: 0 }
  }, src)

test('le logo est servi', async ({ request }) => {
  const r = await request.get(`${BASE}/brand/vitrail-logo.svg`)
  expect(r.status(), 'le logo doit etre servi').toBe(200)
  // ⚠️ On vérifie que c'est bien un SVG, pas seulement un 200 : une page d'erreur
  // renvoyée en 200 passerait le premier contrôle.
  expect((await r.text()).trimStart().startsWith('<svg')).toBe(true)
})

test('la page de connexion porte le logo, rendu', async ({ page }) => {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  const r = await decoded(page, 'vitrail-logo')
  expect(r.found, 'aucune image de logo sur /login').toBe(true)
  expect(r.w, "le logo n'est pas decode (fichier absent ?)").toBeGreaterThan(0)
})

test('la sidebar porte le logo, rendu', async ({ page }) => {
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: TOKEN, refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  await page.route(/\/api\/v1\/(?!users\/me|auth)/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

  await page.goto(`${BASE}/login`)
  await page.evaluate((tk) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'a@t.com', roles: ['CMS_ORG_ADMIN'], permissions: [] },
        accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, TOKEN)

  await page.goto(`${BASE}/templates`, { waitUntil: 'networkidle' })
  await expect(page.getByText('Vitrail').first()).toBeVisible()
  const r = await decoded(page, 'vitrail-logo')
  expect(r.found, 'aucune image de logo dans la sidebar').toBe(true)
  expect(r.w).toBeGreaterThan(0)
})
