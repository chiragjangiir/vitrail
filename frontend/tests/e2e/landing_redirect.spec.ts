import { test, expect } from '@playwright/test'

/**
 * Après connexion, tout le monde atterrissait sur `/dashboard` — dont les données
 * sont gatées org-admin. Un rôle métier y voyait des cartes vides ET des phrases
 * FAUSSES (« aucun player », « aucun média ») : côté UI, un 403 est
 * indistinguable d'un parc vide. Constaté par Ed le 2026-07-20.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

function tok(roles: string[]): string {
  const p = Buffer.from(JSON.stringify({
    sub: '1', org: 1, roles, locale: 'en', type: 'access', exp: 9999999999,
  })).toString('base64url')
  return `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${p}.sig`
}

async function goDashboard(
  page: import('@playwright/test').Page, roles: string[], permissions: string[]
) {
  const t = tok(roles)
  const me = {
    id_user: 1, id_org: 1, email: 'u@t.com', full_name: 'U', avatar_url: null,
    totp_enabled: false, locale: 'en', theme: 'dark', is_active: true, is_demo: false,
    id_advertiser: null, last_login_at: null, created_at: new Date().toISOString(),
    org_name: 'Org', roles, permissions,
  }
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(me) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: t, refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  // Reproduit le serveur : le tableau de bord est gaté org-admin.
  await page.route(/\/api\/v1\/(dashboard|analytics)\//, (r) =>
    r.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"denied"}' }))
  await page.route(/\/api\/v1\/(?!users\/me|auth|dashboard|analytics)/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

  await page.goto(`${BASE}/login`)
  await page.evaluate(([tk, m]) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: m, accessToken: tk, refreshToken: 'r', roles: (m as { roles: string[] }).roles },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', tk as string)
    localStorage.setItem('sf_refresh_token', 'r')
  }, [t, me] as const)
  await page.goto(`${BASE}/dashboard`)
}

test.describe('Page d’atterrissage selon le rôle', () => {
  test('approver_is_sent_to_approvals_not_the_empty_dashboard', async ({ page }) => {
    await goDashboard(page, ['CMS_APPROVER'],
      ['approvals:review', 'media:read', 'playlists:read', 'templates:read'])
    await expect(page).toHaveURL(/\/approvals/)
  })

  test('scheduler_is_sent_to_schedules', async ({ page }) => {
    await goDashboard(page, ['CMS_SCHEDULER'],
      ['schedules:read', 'events:read', 'players:read', 'media:read'])
    await expect(page).toHaveURL(/\/schedules/)
  })

  test('a_role_with_no_readable_surface_lands_on_its_profile', async ({ page }) => {
    await goDashboard(page, ['CMS_API_USER'], [])
    await expect(page).toHaveURL(/\/settings\/profile/)
  })

  test('org_admin_keeps_the_dashboard', async ({ page }) => {
    await goDashboard(page, ['CMS_ORG_ADMIN'], [])
    await expect(page).toHaveURL(/\/dashboard/)
  })
})
