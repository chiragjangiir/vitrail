import { test, expect } from '@playwright/test'

// Gate firmware = EXPLOITANT du serveur (`require_server_operator`).
//
// Sur une install autonome (aucun super-admin), l'org-admin EST l'exploitant et doit
// pouvoir importer un firmware BrightSign. Entrée de menu adminOnly, le serveur filtre
// via `/meta/operator`, et la page EXPLIQUE au non-exploitant (org-admin d'une
// organisation hébergée sur un serveur mutualisé) au lieu de montrer des formulaires
// qui finiraient tous en 403.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye',
  avatar_url: null, totp_enabled: false, locale: 'en', is_active: true,
  last_login_at: null, created_at: new Date().toISOString(),
}

async function setup(page: import('@playwright/test').Page, isHolder: boolean) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(({ u }) => {
    const b64url = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const tk = [
      b64url({ alg: 'HS256', typ: 'JWT' }),
      b64url({ sub: '1', org: 1, roles: ['CMS_ORG_ADMIN'], locale: 'en', type: 'access', exp: 9999999999 }),
      'signature',
    ].join('.')
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: 'mock_refresh', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, { u: USER })

  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route('**/api/v1/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill(json({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' })))
  await page.route('**/api/v1/meta/operator', (r) => r.fulfill(json({ is_operator: isHolder })))
  await page.route('**/api/v1/firmware/versions', (r) => r.fulfill(json([])))
}

test("l'org-admin EXPLOITANT (install autonome) voit le menu et le formulaire d'import", async ({ page }) => {
  await setup(page, true)
  await page.goto(`${BASE}/media`)
  const link = page.getByRole('navigation').getByRole('link', { name: 'Firmware' })
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/settings\/firmware$/)
  await expect(page.getByText('Register a firmware version')).toBeVisible()
})

test("l'org-admin NON exploitant (serveur mutualisé) voit l'explication, pas les formulaires", async ({ page }) => {
  await setup(page, false)
  await page.goto(`${BASE}/settings/firmware`)
  await expect(page.getByText(/reserved for the operator of this server/i)).toBeVisible()
  await expect(page.getByText('Register a firmware version')).toHaveCount(0)
})
