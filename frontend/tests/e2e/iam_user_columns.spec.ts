import { test, expect } from '@playwright/test'

// Colonnes « Créé le » et « Dernière connexion » de la liste des comptes (demande d'Ed,
// 2026-07-31). Les deux champs étaient DÉJÀ servis par l'API — seul l'affichage manquait.
//
// Le test regarde le RENDU : c'est une capture d'écran qui a révélé que les en-têtes
// sortaient en clé brute (`IAM.COL_CREATED`), le conteneur de dev ne rechargeant pas les
// messages i18n — un défaut que ni tsc ni un test de logique n'auraient vu.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: true, locale: 'en', theme: 'dark', is_active: true, is_demo: false, id_advertiser: null, last_login_at: new Date().toISOString(), created_at: '2026-01-15T09:00:00Z', permissions: [], roles: ['CMS_ORG_ADMIN'] }

function user(id: number, email: string, o: Record<string, unknown> = {}) {
  return {
    id_user: id, id_org: 1, email, full_name: o.full_name ?? null, avatar_url: null,
    totp_enabled: false, locale: 'fr', theme: 'dark', is_active: true, is_demo: false,
    id_advertiser: null, last_login_at: o.last_login_at ?? null,
    created_at: o.created_at ?? '2026-03-02T10:00:00Z',
  }
}

test('iam_list_shows_created_and_last_login', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => {
    const tok = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: true, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }, accessToken: tok, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', tok)
    localStorage.setItem('sf_refresh_token', 'r')
  })
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'x', refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  await page.route(/\/api\/v1\/users(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
      user(2, 'marie@retail.fr', { full_name: 'Marie Dupont', last_login_at: '2026-07-28T08:12:00Z', created_at: '2026-02-20T14:30:00Z' }),
      user(3, 'stagiaire@retail.fr', { full_name: 'Compte stagiaire', created_at: '2026-06-01T09:00:00Z' }),
    ]) }))
  for (const p of [/\/api\/v1\/groups(\?.*)?$/, /\/api\/v1\/roles(\?.*)?$/, /\/api\/v1\/permissions(\?.*)?$/])
    await page.route(p, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.goto(`${BASE}/settings/iam`)

  // Les en-têtes sont TRADUITS (pas `iam.col_created` en clé brute).
  const table = page.locator('table').first()
  await expect(table).toContainText('Created')
  await expect(table).toContainText('Last login')
  await expect(table).not.toContainText('col_created')

  // Les deux dates sont rendues…
  await expect(table).toContainText('02/20/2026')
  await expect(table).toContainText('07/28/2026')
  // …et « jamais connecté » est NOMMÉ : c'est une information, pas une absence.
  await expect(table).toContainText('Never')
})
