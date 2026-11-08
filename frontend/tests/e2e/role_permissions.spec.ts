import { test, expect } from '@playwright/test'

/**
 * Éditeur de permissions d'un rôle (audit rôles 2026-07-20).
 *
 * Avant : `POST /roles` produisait un rôle vide qu'aucun endpoint ne pouvait
 * garnir — inerte à vie. L'UI proposait le bouton « créer un rôle » sans qu'il
 * mène à quoi que ce soit d'utilisable.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'

const ME = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null,
  totp_enabled: false, locale: 'en', theme: 'dark', is_active: true, is_demo: false,
  id_advertiser: null, last_login_at: null, created_at: new Date().toISOString(),
  org_name: 'Org', roles: ['CMS_ORG_ADMIN'], permissions: [],
}

const ROLES = [
  { id_role: 1, id_org: null, role_key: 'CMS_VIEWER', label: 'Viewer', description: null, is_system: true, is_active: true },
  { id_role: 9, id_org: 1, role_key: 'ops', label: 'Ops', description: null, is_system: false, is_active: true },
]

const CATALOG = [
  { id_permission: 1, module: 'media', operation: 'read', description: null, available: true },
  { id_permission: 2, module: 'media', operation: 'create', description: null, available: true },
  { id_permission: 3, module: 'schedules', operation: 'read', description: null, available: true },
  { id_permission: 4, module: 'spf', operation: 'create', description: null, available: false },
  { id_permission: 5, module: 'spf', operation: 'read', description: null, available: false },
]

async function setup(page: import('@playwright/test').Page) {
  const saved: string[][] = []
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: TOKEN, refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  await page.route('**/api/v1/permissions', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CATALOG) }))
  await page.route('**/api/v1/roles/9/permissions', async (r) => {
    if (r.request().method() === 'PUT') {
      saved.push(JSON.parse(r.request().postData() ?? '{}').permissions)
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(saved.at(-1)) })
    }
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(['media:read']) })
  })
  await page.route('**/api/v1/roles/1/permissions', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(['media:read']) }))
  await page.route('**/api/v1/roles', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ROLES) }))
  await page.route(/\/api\/v1\/(users|groups)(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

  await page.goto(`${BASE}/login`)
  await page.evaluate((tk) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: {
        user: { id_user: 1, id_org: 1, email: 'admin@test.com', roles: ['CMS_ORG_ADMIN'], permissions: [] },
        accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'],
      }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, TOKEN)
  await page.goto(`${BASE}/settings/iam`)
  await page.getByRole('button', { name: /Roles/ }).first().click()
  return saved
}

test.describe('Éditeur de permissions', () => {
  test('custom_role_permissions_are_editable_and_saved', async ({ page }) => {
    const saved = await setup(page)
    await page.getByText('Ops', { exact: true }).click()

    const drawer = page.getByRole('dialog', { name: /Permissions of/ })
    await expect(drawer).toBeVisible()
    // Les droits actuels du rôle sont pré-cochés (sinon un enregistrement les effacerait).
    await expect(drawer.getByRole('checkbox').first()).toBeChecked()

    // On ajoute un droit, on enregistre : le PUT part avec le jeu COMPLET.
    await drawer.getByText('create', { exact: true }).first().click()
    await drawer.getByRole('button', { name: 'Save' }).click()
    await expect.poll(() => saved.length).toBeGreaterThan(0)
    expect(saved[0].sort()).toEqual(['media:create', 'media:read'])
  })

  test('unavailable_permissions_are_not_checkable', async ({ page }) => {
    await setup(page)
    await page.getByText('Ops', { exact: true }).click()
    const drawer = page.getByRole('dialog', { name: /Permissions of/ })
    // `spf:*` = fonctionnalité §XIV spécifiée mais non développée → grisée.
    const spfRow = drawer.locator('label').filter({ hasText: 'coming soon' }).first()
    await expect(spfRow).toBeVisible()
    await expect(spfRow.getByRole('checkbox')).toBeDisabled()
  })

  test('system_role_is_read_only', async ({ page }) => {
    await setup(page)
    await page.getByText('Viewer', { exact: true }).click()
    const drawer = page.getByRole('dialog', { name: /Permissions of/ })
    await expect(drawer.getByText(/System role/)).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Save' })).toHaveCount(0)
    await expect(drawer.getByRole('checkbox').first()).toBeDisabled()
  })
})
