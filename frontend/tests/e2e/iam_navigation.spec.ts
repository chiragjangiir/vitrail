import { test, expect } from '@playwright/test'

/**
 * Non-régression : depuis /settings/iam, la navigation vers un autre menu doit marcher.
 *
 * Le défaut (constaté par Ed le 2026-07-22, reproduit et corrigé le 2026-07-23) : `RolePermissionsDrawer`
 * reste MONTÉ en permanence sur cette page (rendu avec role={null}), sa requête est donc
 * désactivée et `data` vaut `undefined`. Un défaut `data: current = []` fabriquait un
 * tableau NEUF à chaque rendu, que l'effet de synchronisation prenait pour un changement
 * → `setSelected(new Set(...))` → nouveau rendu → boucle infinie. React saturait la boucle
 * de rendu, la transition du routeur Next ne s'engageait plus, et AUCUN lien de menu ne
 * répondait — alors que la page elle-même restait manipulable (drawers ouvrables), ce qui
 * rendait le symptôme très trompeur.
 *
 * Ce test verrouille les DEUX faces : plus d'erreur de boucle, et la navigation aboutit.
 * Vérifié rouge sur le code d'origine (URL inchangée + erreurs en rafale).
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 2, id_org: 2, email: 'admin@test.com', full_name: 'Admin',
  avatar_url: null, totp_enabled: true, locale: 'fr', is_active: true,
  last_login_at: null, created_at: new Date().toISOString(),
}

const users = Array.from({ length: 5 }, (_, i) => ({
  id_user: i + 1, id_org: 2, email: `u${i}@x.com`, full_name: `User ${i}`,
  avatar_url: null, totp_enabled: false, is_active: true,
  last_login_at: null, created_at: new Date().toISOString(), roles: [],
}))
const roles = [
  { id_role: 1, id_org: null, role_key: 'CMS_ORG_ADMIN', label: 'Org admin', description: null, is_system: true },
  { id_role: 2, id_org: 2, role_key: 'CUSTOM_X', label: 'Custom X', description: null, is_system: false },
]

test('la navigation depuis /settings/iam n\'est pas bloquee par une boucle de rendu', async ({ page }) => {
  const loopErrors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error' && m.text().includes('Maximum update depth exceeded')) {
      loopErrors.push(m.text())
    }
  })

  await page.goto(`${BASE}/login`)
  await page.evaluate(({ u }) => {
    const b64url = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const r = ['CMS_ORG_ADMIN']
    const tk = [
      b64url({ alg: 'HS256', typ: 'JWT' }),
      b64url({ sub: '2', org: 2, roles: r, locale: 'fr', type: 'access', exp: 9999999999 }),
      'signature',
    ].join('.')
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: 'mock_refresh', roles: r }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, { u: USER })

  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route('**/api/v1/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/users', (r) => r.fulfill(json(users)))
  await page.route('**/api/v1/roles', (r) => r.fulfill(json(roles)))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill(json({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'fr' })))

  await page.goto(`${BASE}/settings/iam`)
  await page.waitForTimeout(1200)

  // 1. La page ne boucle pas sur elle-meme.
  expect(loopErrors, 'boucle de rendu detectee sur /settings/iam').toEqual([])

  // 2. Un lien de menu emmene reellement ailleurs (c'est le symptome vu par Ed).
  await page.locator('a[href="/settings/profile"]').first().click()
  await page.waitForURL('**/settings/profile', { timeout: 8000 })
  expect(page.url()).toContain('/settings/profile')
})
