import { test, expect } from '@playwright/test'

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const TEST_EMAIL = process.env.TEST_USER_EMAIL ?? 'admin@signflow.test'
const TEST_PASSWORD = process.env.TEST_USER_PASSWORD ?? 'password123'

test.describe('Login flow', () => {
  test.beforeEach(async ({ page }) => {
    // Clear auth state
    await page.goto(`${BASE}/login`)
    await page.evaluate(() => {
      localStorage.removeItem('sf-auth')
      localStorage.removeItem('sf_access_token')
      localStorage.removeItem('sf_refresh_token')
    })
    await page.reload()
  })

  test('login_redirect_to_dashboard — valid credentials redirect to /dashboard', async ({ page }) => {
    // Mock API responses
    await page.route('**/api/v1/auth/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature',
          refresh_token: 'refresh_mock',
          token_type: 'bearer',
          locale: 'en',
        }),
      })
    })
    await page.route('**/api/v1/users/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id_user: 1, id_org: 1, email: TEST_EMAIL, full_name: 'Admin User',
          avatar_url: null, totp_enabled: false, locale: 'en',
          is_active: true, last_login_at: null, created_at: new Date().toISOString(),
        }),
      })
    })

    await page.goto(`${BASE}/login`)
    await page.getByLabel('Email').fill(TEST_EMAIL)
    await page.getByLabel('Password').fill(TEST_PASSWORD)
    await page.getByRole('button', { name: /sign in/i }).click()

    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('login_invalid_credentials — shows error message', async ({ page }) => {
    await page.route('**/api/v1/auth/login', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Identifiants invalides' }),
      })
    })

    await page.goto(`${BASE}/login`)
    await page.getByLabel('Email').fill('wrong@example.com')
    await page.getByLabel('Password').fill('wrongpass')
    await page.getByRole('button', { name: /sign in/i }).click()

    await expect(page.locator('text=Identifiants invalides')).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('login_totp_required — shows TOTP step on 401 TOTP', async ({ page }) => {
    let callCount = 0
    await page.route('**/api/v1/auth/login', async (route) => {
      callCount++
      if (callCount === 1) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Code TOTP requis' }),
        })
      } else {
        // ⚠️ Le token doit porter CMS_ORG_ADMIN : depuis landingPath (20/07), un
        // compte sans rôle atterrit sur /settings/profile, pas /dashboard.
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            access_token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig',
            refresh_token: 'refresh_mock',
            token_type: 'bearer',
            locale: 'en',
          }),
        })
      }
    })
    await page.route('**/api/v1/users/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id_user: 1, id_org: 1, email: TEST_EMAIL, full_name: null, avatar_url: null, totp_enabled: true, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }),
      })
    })

    await page.goto(`${BASE}/login`)
    await page.getByLabel('Email').fill(TEST_EMAIL)
    await page.getByLabel('Password').fill(TEST_PASSWORD)
    await page.getByRole('button', { name: /sign in/i }).click()

    // TOTP step should appear
    await expect(page.getByLabel(/authenticator code/i)).toBeVisible()
    await page.getByLabel(/authenticator code/i).fill('123456')
    await page.getByRole('button', { name: /confirm/i }).click()

    await expect(page).toHaveURL(/\/dashboard/)
  })
})
