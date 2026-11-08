import { test, expect } from '@playwright/test'

// REFUSER UNE SUPPRESSION EN NOMMANT CE QUI LA RETIENT (P3.3).
//
// Deux principes d'Ed, et ces specs affirment le RÉSULTAT AFFICHÉ, jamais la structure :
//  · « quand on efface, on efface » — le bouton s'appelait « Supprimer » et DÉSACTIVAIT ;
//    les deux gestes sont maintenant distincts et nommés pour ce qu'ils font ;
//  · jamais un bouton qui ne peut QU'échouer — quand la porte est fermée par construction,
//    le bouton est grisé ET la raison est écrite à côté.
//
// Le tiroir montre les TROIS natures de lien. Ne montrer que « bloqué » cacherait qu'une
// suppression d'organisation emporterait une trentaine de tables en cascade.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye', avatar_url: null,
  totp_enabled: false, locale: 'en', is_active: true, last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  permissions: ['users:read', 'users:create', 'users:edit', 'users:delete'],
}

const OTHER = {
  id_user: 7, id_org: 1, email: 'bob@test.com', full_name: 'Bob', avatar_url: null,
  totp_enabled: false, locale: 'en', is_active: true, last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
}

const HELD = {
  can_delete: false,
  blocking: [{ table: 'cms_media', column: 'created_by', count: 14, kind: 'blocking' }],
  cascade: [{ table: 'cms_campaigns', column: 'id_org', count: 3, kind: 'cascade' }],
  detach: [{ table: 'cms_audit_log', column: 'id_user', count: 91, kind: 'detach' }],
  blocking_total: 14, cascade_total: 3, detach_total: 91,
  closed_reason: null, deactivate_available: true,
}

const FREE = {
  can_delete: true, blocking: [], cascade: [], detach: [],
  blocking_total: 0, cascade_total: 0, detach_total: 0,
  closed_reason: null, deactivate_available: true,
}

const LAST_ADMIN = { ...FREE, can_delete: false, closed_reason: 'last_org_admin' }

async function setup(page: import('@playwright/test').Page, impact: unknown) {
  await page.goto(`${BASE}/login`)
  await page.evaluate((u) => {
    const b64 = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const tk = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${b64({
      sub: '1', org: 1, roles: ['CMS_ORG_ADMIN'], locale: 'en', type: 'access', exp: 9999999999,
    })}.sig`
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, USER)

  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  // ⚠️ ORDRE : Playwright résout les routes de la DERNIÈRE enregistrée à la première. Le
  // glob générique doit donc être posé EN PREMIER, sinon il avale `/users/me` (la page
  // recevait un tableau à la place du compte connecté et ne rendait rien).
  await page.route('**/api/v1/users**', (r) => r.fulfill(json([USER, OTHER])))
  await page.route('**/api/v1/users/*/deletion-impact**', (r) => r.fulfill(json(impact)))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill(json({ access_token: 'x', refresh_token: 'r', token_type: 'bearer', locale: 'en' })))
  await page.route('**/api/v1/groups**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/roles**', (r) => r.fulfill(json([])))
}

test('les deux gestes sont DISTINCTS et nommes pour ce qu ils font', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, FREE)
  await page.goto(`${BASE}/settings/iam`)

  // Le défaut d'origine : UN bouton « Supprimer » qui désactivait. Il y en a deux, et le
  // geste réversible ne s'appelle plus « supprimer ».
  await expect(page.getByTitle('Deactivate account')).toBeVisible()
  await expect(page.getByTitle('Delete permanently')).toBeVisible()
})

test('le tiroir NOMME ce qui retient, ce qui partirait et ce qui serait delie', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, HELD)
  await page.goto(`${BASE}/settings/iam`)
  await page.getByTestId('purge-user-7').click()

  // Les trois natures, séparées — « bloqué » seul cacherait la cascade.
  await expect(page.getByTestId('impact-blocking')).toContainText('cms_media')
  await expect(page.getByTestId('impact-blocking')).toContainText('14')
  await expect(page.getByTestId('impact-cascade')).toContainText('cms_campaigns')
  await expect(page.getByTestId('impact-detach')).toContainText('cms_audit_log')
})

test('un bouton qui ne peut qu echouer est GRISE et la raison est ecrite', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, LAST_ADMIN)
  await page.goto(`${BASE}/settings/iam`)
  await page.getByTestId('purge-user-7').click()

  await expect(page.getByTestId('purge-btn')).toBeDisabled()
  // Grisé ne suffit pas : la cause doit être lisible.
  await expect(page.getByTestId('purge-blocked-reason'))
    .toContainText('last active administrator')
})

test('quand rien ne retient, la suppression est POSSIBLE', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, FREE)
  await page.goto(`${BASE}/settings/iam`)
  await page.getByTestId('purge-user-7').click()

  // Témoin : sans lui, un tiroir qui griserait TOUJOURS passerait la spec précédente.
  await expect(page.getByTestId('purge-btn')).toBeEnabled()
  await expect(page.getByTestId('purge-blocked-reason')).toHaveCount(0)
})

test('la suppression reelle passe bien par purge=true', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, FREE)
  let purgeUrl: string | null = null
  await page.route('**/api/v1/users/7?purge=true', (r) => {
    purgeUrl = r.request().url()
    return r.fulfill({ status: 204, body: '' })
  })
  await page.goto(`${BASE}/settings/iam`)
  await page.getByTestId('purge-user-7').click()
  await page.getByTestId('purge-btn').click()

  // C'est le RÉSULTAT qui compte : le geste part sur le chemin qui supprime vraiment,
  // pas sur celui qui désactive.
  await expect.poll(() => purgeUrl).toContain('purge=true')
})
