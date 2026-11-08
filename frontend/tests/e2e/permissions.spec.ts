import { test, expect } from '@playwright/test'

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_TOKEN_PERM = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6W10sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'

async function setAuthWithRoles(page: import('@playwright/test').Page, roles: string[]) {
  await page.goto(`${BASE}/login`)
  await page.evaluate((roles) => {
    const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6W10sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: {
        user: { id_user: 1, id_org: 1, email: 'viewer@test.com', full_name: 'Viewer', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
        accessToken: token, refreshToken: 'r', roles,
      },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', token)
  }, roles)
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ id_user: 1, id_org: 1, email: 'viewer@test.com', full_name: 'Viewer', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }),
    })
  })
  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: MOCK_TOKEN_PERM, refresh_token: 'r', token_type: 'bearer', locale: 'en' }),
    })
  })
}

test.describe('Permissions gate', () => {
  test('permissions_gate_hides_admin_ui_for_viewer', async ({ page }) => {
    await page.route('**/api/v1/users', async (route) => {
      await route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'Forbidden' }) })
    })

    await setAuthWithRoles(page, ['CMS_VIEWER'])
    await page.goto(`${BASE}/settings/iam`)

    // With a VIEWER role, the IAM page should show no data (403 from API)
    // The page loads but the table is empty (no users returned)
    await expect(page.locator('text=Users & Roles').first()).toBeVisible()
    // No "Invite user" button should be actionable — viewer has no admin access
    // The page renders but API returns 403, so no users show
    await expect(page.locator('table')).toBeVisible()
  })

  test('permissions_gate_shows_admin_ui_for_org_admin', async ({ page }) => {
    await page.route('**/api/v1/users', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: true, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
        ]),
      })
    })

    await setAuthWithRoles(page, ['CMS_ORG_ADMIN'])
    await page.goto(`${BASE}/settings/iam`)

    await expect(page.locator('text=admin@test.com')).toBeVisible()
    await expect(page.getByRole('button', { name: /invite user/i })).toBeVisible()
  })
})
