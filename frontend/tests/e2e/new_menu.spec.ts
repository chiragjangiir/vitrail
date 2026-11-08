import { test, expect } from '@playwright/test'

// +New (NewMenu topbar) — ouvre DIRECTEMENT le drawer de création de la cible :
//  - depuis une autre page  → navigation /cible?new=1 → ouverture au montage + URL nettoyée ;
//  - déjà sur la page cible  → événement sf:new-shortcut → ouverture sans remontage.
// Le Drawer reste monté hors écran (translate-x-full) → on assiste avec toBeInViewport().

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const USER = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

async function setup(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  await page.evaluate((u) => {
    const tk = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
    localStorage.setItem('sf-auth', JSON.stringify({ state: { user: u, accessToken: tk, refreshToken: 'mock_refresh', roles: ['CMS_ORG_ADMIN'] }, version: 0 }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, USER)
  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  // Fallback GÉNÉRIQUE d'abord (Playwright priorise la dernière route ajoutée) → listes vides.
  await page.route('**/api/v1/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill(json({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' })))
  await page.route('**/api/v1/approvals/dashboard', (r) => r.fulfill(json({ pending_review: 0, changes_requested: 0, approved: 0, rejected: 0, published: 0, urgent: 0, is_reviewer: false })))
}

test('+New navigue et ouvre le drawer de la page cible (?new=1)', async ({ page }) => {
  await setup(page)
  await page.goto(`${BASE}/templates`) // page source (bouton create = « New template », pas d'ambiguïté)

  await page.getByRole('button', { name: /^New$/ }).click()
  await page.getByTestId('new-menu').getByRole('button', { name: 'New playlist' }).click()

  // Navigation vers /playlists, drawer ouvert au montage, URL nettoyée (plus de ?new=1).
  await expect(page).toHaveURL(/\/playlists$/)
  await expect(page.getByRole('dialog', { name: 'New playlist' })).toBeInViewport()
})

test('+New rouvre le drawer même déjà sur la page (sans remontage)', async ({ page }) => {
  await setup(page)
  await page.goto(`${BASE}/playlists`)

  const dialog = page.getByRole('dialog', { name: 'New playlist' })
  await expect(dialog).not.toBeInViewport() // fermé au chargement (translaté hors écran)

  await page.getByRole('button', { name: /^New$/ }).click()
  await page.getByTestId('new-menu').getByRole('button', { name: 'New playlist' }).click()

  await expect(dialog).toBeInViewport()
})
