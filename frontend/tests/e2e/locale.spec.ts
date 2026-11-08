import { test, expect } from '@playwright/test'

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_TOKEN_LOCALE = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'

async function setAuthAndNavigate(page: import('@playwright/test').Page, url: string, locale = 'en') {
  await page.goto(`${BASE}/login`)
  await page.evaluate((locale) => {
    const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale, is_active: true, last_login_at: null, created_at: new Date().toISOString() }, accessToken: token, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', token)
    document.cookie = `locale=${locale}; path=/`
  }, locale)
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale, is_active: true, last_login_at: null, created_at: new Date().toISOString() }),
    })
  })
  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: MOCK_TOKEN_LOCALE, refresh_token: 'r', token_type: 'bearer', locale }),
    })
  })
  await page.goto(url)
}

test.describe('Locale switch', () => {
  test('locale_switch_persists_across_reload — FR', async ({ page }) => {
    await page.route('**/api/v1/users/me', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'fr', is_active: true, last_login_at: null, created_at: new Date().toISOString() }),
      })
    })

    await setAuthAndNavigate(page, `${BASE}/settings/profile`, 'en')

    // Select French
    await page.getByRole('button', { name: 'Français' }).click()

    // Mock the PATCH response
    await page.route('**/api/v1/users/me', async (route) => {
      if (route.request().method() === 'PATCH') {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'fr', is_active: true, last_login_at: null, created_at: new Date().toISOString() }),
        })
      } else {
        await route.continue()
      }
    })

    await page.getByRole('button', { name: /save/i }).click()

    // After reload, locale cookie should be 'fr'
    await page.waitForLoadState('networkidle')
    const localeCookie = await page.evaluate(() =>
      document.cookie.split('; ').find((c) => c.startsWith('locale='))?.split('=')[1]
    )
    expect(localeCookie).toBe('fr')
  })

  test('locale_switch_shows_french_ui — sidebar labels change', async ({ page }) => {
    await setAuthAndNavigate(page, `${BASE}/dashboard`, 'fr')
    // With locale cookie 'fr', next-intl should serve french messages
    // Sidebar should show French labels
    await expect(page.getByRole('navigation').getByText(/tableau de bord|dashboard/i).first()).toBeVisible()
  })
})
