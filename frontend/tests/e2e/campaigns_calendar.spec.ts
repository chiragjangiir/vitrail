import { test, expect } from '@playwright/test'

// S6 Retail Media — calendrier des campagnes : bouton toggle, bandeau de charge
// par jour (occupancy-daily), barres par campagne, clic → drawer.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

// Format LOCAL (pas toISOString : minuit local convertit en UTC = jour précédent)
function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const today = new Date()
const monthStart = new Date(today.getFullYear(), today.getMonth(), 1)
const monthEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0)

const CAMPAIGN = {
  id_campaign: 1, id_advertiser: 1, campaign_name: 'Brightwell Calendar', status: 'live',
  starts_on: iso(monthStart), ends_on: iso(monthEnd), daily_hours: null,
  sov_percent: 20, pricing_model: 'sov', price_amount: 1500, price_currency: 'EUR',
  cpm_rate: null, priority: 50, advertiser_name: 'Brightwell', creative_count: 1,
  target_player_count: 3,
  targets: [{ id_target: 1, target_type: 'org', target_id: null }],
}

async function mockAuthAndNavigate(page: import('@playwright/test').Page, url: string) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => {
    const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
    const store = {
      state: {
        user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
        accessToken: mockToken, refreshToken: 'mock_refresh', roles: ['CMS_ORG_ADMIN'],
      },
      version: 0,
    }
    localStorage.setItem('sf-auth', JSON.stringify(store))
    localStorage.setItem('sf_access_token', mockToken)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  })
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER_ME) })
  })
  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }),
    })
  })
  await page.goto(url)
}

test.describe('Campaign calendar (S6)', () => {
  test('toggle_shows_month_bars_and_daily_load', async ({ page }) => {
    for (const [pattern, body] of [
      ['**/api/v1/campaigns/', JSON.stringify([CAMPAIGN])],
      ['**/api/v1/advertisers/', JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Brightwell', id_folder: null }])],
      ['**/api/v1/sites', '[]'],
      ['**/api/v1/player-groups/', '[]'],
      ['**/api/v1/site-groups/', '[]'],
      ['**/api/v1/players/', '[]'],
      ['**/api/v1/campaigns/inventory**', '[]'],
      ['**/api/v1/campaigns/settings', JSON.stringify({ creative_approval: false })],
    ] as const) {
      await page.route(pattern, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body })
      })
    }
    let occQuery = ''
    await page.route('**/api/v1/campaigns/occupancy-daily**', async (route) => {
      occQuery = new URL(route.request().url()).search
      const days = [
        { date: iso(monthStart), max_pct: 20 },
        { date: iso(new Date(monthStart.getFullYear(), monthStart.getMonth(), 10)), max_pct: 85 },
        { date: iso(new Date(monthStart.getFullYear(), monthStart.getMonth(), 15)), max_pct: 110 },
      ]
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ days }) })
    })
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.getByRole('button', { name: 'Calendar' }).click()
    // Le panneau interroge le mois courant
    await expect.poll(() => occQuery).toContain(`date_from=${iso(monthStart)}`)
    expect(occQuery).toContain(`date_to=${iso(monthEnd)}`)
    // Bandeau de charge + barre de la campagne visibles
    await expect(page.getByText('Inventory load', { exact: true })).toBeVisible()
    const bar = page.getByRole('button', { name: 'Brightwell Calendar' }).first()
    await expect(bar).toBeVisible()
    // Clic sur la campagne → drawer
    await bar.click()
    await expect(page.getByRole('dialog', { name: 'Brightwell Calendar' })).toBeVisible()
  })
})
