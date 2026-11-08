import { test, expect } from '@playwright/test'

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_AUTH_SETTINGS = {
  id_org: 1, auth_2fa_policy: 'optional', session_lifetime: 480,
  max_sessions: 5, password_min_len: 10,
  password_policy: { uppercase: true, digit: true, special: false },
  ip_allowlist: null, updated_at: new Date().toISOString(),
}

test.describe('2FA policy UI', () => {
  test('2fa_policy_required_shows_setup_screen', async ({ page }) => {
    await page.route('**/api/v1/auth/login', async (route) => {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: { message: '2FA obligatoire', force_2fa_setup: true },
        }),
        headers: { 'X-Force-2FA-Setup': 'true' },
      })
    })

    await page.goto(`${BASE}/login`)
    await page.getByLabel('Email').fill('admin@test.com')
    await page.getByLabel('Password').fill('password')
    await page.getByRole('button', { name: /sign in/i }).click()

    // Should show the 2FA setup required screen
    await expect(
      page.locator('text=/two-factor authentication required/i')
        .or(page.locator('text=/double authentification requise/i'))
    ).toBeVisible({ timeout: 5000 })

    // Back button should return to credentials step
    await page.getByRole('button', { name: /back/i }).click()
    await expect(page.getByLabel('Email')).toBeVisible()
  })

  test('security_page_shows_2fa_policy_controls', async ({ page }) => {
    await page.route('**/api/v1/orgs/*/auth-settings', async (route) => {
      if (route.request().method() === 'PUT') {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ ...MOCK_AUTH_SETTINGS, auth_2fa_policy: 'required' }),
        })
      } else {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(MOCK_AUTH_SETTINGS),
        })
      }
    })

    await page.goto(`${BASE}/login`)
    await page.evaluate(() => {
      const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'
      localStorage.setItem('sf-auth', JSON.stringify({
        state: {
          user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: null, avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
          accessToken: token, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'],
        },
        version: 0,
      }))
      localStorage.setItem('sf_access_token', token)
    })
    await page.goto(`${BASE}/settings/security`)

    await expect(page.getByRole('button', { name: /required/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /optional/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /disabled/i })).toBeVisible()

    await page.getByRole('button', { name: /required/i }).click()
    await page.getByRole('button', { name: /save settings/i }).click()

    await expect(page.locator('text=/saved/i')).toBeVisible({ timeout: 5000 })
  })
})
