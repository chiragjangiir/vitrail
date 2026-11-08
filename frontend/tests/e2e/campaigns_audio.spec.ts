import { test, expect } from '@playwright/test'

// S2 Retail Media AUDIO (migr 0094) — drawer campagne : type Audio → champ spots/h,
// occupancy-check en spots (plafond par écran) + « spots/h réalisables » ; liste = badge /h.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const today = new Date()
const nextWeek = new Date(today.getTime() + 7 * 86400_000)

const AUDIO_CAMPAIGN = {
  id_campaign: 7, id_advertiser: 1, campaign_name: 'Radio Acme', status: 'live',
  starts_on: iso(today), ends_on: iso(nextWeek), daily_hours: null,
  sov_percent: 10, pricing_model: 'flat', price_amount: 900, price_currency: 'EUR',
  cpm_rate: null, priority: 50, advertiser_name: 'Acme', creative_count: 1,
  campaign_kind: 'audio', spots_per_hour: 6, target_player_count: 2,
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

async function mockCommon(page: import('@playwright/test').Page) {
  for (const [pattern, body] of [
    ['**/api/v1/campaigns/', JSON.stringify([AUDIO_CAMPAIGN])],
    ['**/api/v1/advertisers/', JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Acme', id_folder: null }])],
    ['**/api/v1/sites', '[]'],
    ['**/api/v1/player-groups/', '[]'],
    ['**/api/v1/site-groups/', '[]'],
    ['**/api/v1/players/', '[]'],
    ['**/api/v1/campaigns/inventory**', '[]'],
    ['**/api/v1/campaigns/settings', JSON.stringify({
      creative_approval: false, sov_daily_rate: null, max_creatives: 20,
      creative_max_mb: 1024, portal_player_selection: false,
      creative_max_duration_s: 30, audio_spots_cap: 12, audio_spot_daily_rate: null,
    })],
  ] as const) {
    await page.route(pattern, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body })
    })
  }
}

test.describe('Audio campaigns (S2)', () => {
  test('list_shows_spots_per_hour_and_sold_column', async ({ page }) => {
    await mockCommon(page)
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)
    await expect(page.getByRole('cell', { name: '6/h' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Sold' })).toBeVisible()
  })

  test('create_audio_campaign_spots_field_and_occupancy', async ({ page }) => {
    await mockCommon(page)
    let occBody: Record<string, unknown> | null = null
    await page.route('**/api/v1/campaigns/occupancy-check', async (route) => {
      occBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          blocked: true, warning: true, max_projected_pct: 116.67,
          players: [{
            id_player: 4, player_name: 'RPi', current_pct: 66.67, projected_pct: 116.67,
            cap_pct: 100, current_spots: 8, projected_spots: 14, cap_spots: 12,
          }],
          price: null, achievable: null, achievable_spots_per_hour: 4,
        }),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.getByRole('button', { name: 'New campaign' }).click()
    // Type de campagne : Audio → le champ SOV disparaît, spots/h apparaît
    await page.getByRole('button', { name: 'Audio', exact: true }).click()
    await expect(page.getByLabel('Spots / hour')).toBeVisible()
    await expect(page.getByLabel('Share of voice (%)')).toHaveCount(0)

    await page.getByLabel('Campaign name').fill('Radio test')
    await page.locator('input[type="date"]').first().fill(iso(today))
    await page.locator('input[type="date"]').nth(1).fill(iso(nextWeek))

    // L'occupancy-check part avec kind=audio + spots_per_hour, et le bandeau
    // affiche le détail en spots (plafond par écran) + la suggestion réalisable.
    await expect.poll(() => occBody).not.toBeNull()
    expect(occBody!.campaign_kind).toBe('audio')
    expect(occBody!.spots_per_hour).toBe(6)
    await expect(page.getByText('8 → 14 spots/h (cap 12)')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Use 4 spots/h' })).toBeVisible()
    // Suggestion → le champ passe à 4
    await page.getByRole('button', { name: 'Use 4 spots/h' }).click()
    await expect(page.getByLabel('Spots / hour')).toHaveValue('4')
  })
})
