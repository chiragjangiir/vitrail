import { test, expect } from '@playwright/test'

// S7 Phase A — cartes : placement d'un site (drawer site) + sélection des sites
// cibles sur la carte (drawer campagne). On teste le CÂBLAGE UI (sections, drawer,
// init de la sélection depuis les cibles, Apply) sans dépendre des tuiles CDN.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SITES = [
  { id_site: 1, id_org: 1, site_name: 'Store Bordeaux', address: null, country: null, site_number: null, latitude: 44.8378, longitude: -0.5792, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 15, power_lag_min: 15, respect_holidays: false, holiday_region: 'FR', created_at: new Date().toISOString(), player_count: 2, hours: [] },
  { id_site: 2, id_org: 1, site_name: 'Store Toulouse', address: null, country: null, site_number: null, latitude: null, longitude: null, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 15, power_lag_min: 15, respect_holidays: false, holiday_region: 'FR', created_at: new Date().toISOString(), player_count: 1, hours: [] },
]

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

test.describe('Map pickers (S7 Phase A)', () => {
  test('site_drawer_has_map_place_section', async ({ page }) => {
    await page.route('**/api/v1/sites', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) })
    })
    await page.route('**/api/v1/site-groups/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/sites/1/exceptions', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/sites/1/players', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/players/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/sites`)

    await page.locator('text=Store Bordeaux').click()
    const drawer = page.getByRole('dialog', { name: /edit site/i })
    await expect(drawer).toBeVisible()
    // Section repliée par défaut → l'ouvrir fait apparaître la mini-carte
    await expect(drawer.getByTestId('latlng-picker-map')).toHaveCount(0)
    await drawer.getByRole('button', { name: /place on the map/i }).click()
    await expect(drawer.getByTestId('latlng-picker-map')).toBeVisible()
  })

  test('campaign_map_picker_inits_from_targets_and_applies', async ({ page }) => {
    for (const [pattern, body] of [
      ['**/api/v1/campaigns/', '[]'],
      ['**/api/v1/advertisers/', JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Dyson', id_folder: null }])],
      ['**/api/v1/sites', JSON.stringify(SITES)],
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
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.getByRole('button', { name: /new campaign/i }).click()
    const drawer = page.getByRole('dialog').first()
    // Cible : passer la 1re ligne sur « Site » + Store Bordeaux (via dropdown)
    const typeSelect = drawer.locator('select').filter({ has: page.locator('option[value="site_group"]') }).first()
    await typeSelect.selectOption('site')
    const entitySelect = drawer.locator('select').filter({ has: page.locator('option', { hasText: 'Store Bordeaux' }) }).first()
    await entitySelect.selectOption({ label: 'Store Bordeaux' })

    // Ouvre le sélecteur carte : la sélection est initialisée depuis les cibles SITE
    await drawer.getByRole('button', { name: /pick on the map/i }).click()
    const mapDrawer = page.getByRole('dialog', { name: /pick target sites on the map/i })
    await expect(mapDrawer).toBeVisible()
    await expect(mapDrawer.getByTestId('site-map-selector')).toBeVisible()
    await expect(mapDrawer.locator('text=Store Bordeaux')).toBeVisible()   // chip sélectionné
    // 1 site sans coordonnées signalé
    await expect(mapDrawer.getByText(/1 site\(s\) without coordinates/)).toBeVisible()

    // Retire Bordeaux via la croix du chip puis applique → la cible retombe sur « org »
    await mapDrawer.locator('span', { hasText: 'Store Bordeaux' }).getByTitle('Delete').click()
    await expect(mapDrawer.locator('text=No site selected.')).toBeVisible()
    await mapDrawer.getByRole('button', { name: /apply \(0 targets\)/i }).click()
    // (le Drawer fermé reste monté hors écran → on vérifie l'EFFET, pas sa visibilité)
    // La ligne de cible est revenue à « Entire organization »
    await expect(typeSelect).toHaveValue('org')
  })
})
