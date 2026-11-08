import { test, expect } from '@playwright/test'

// S6 Retail Media — Groupes de sites : onglet « Site groups » de la page Sites
// (création, carte avec compteurs, membres, ajout/retrait) + option de cible
// « Site group » dans le drawer campagne.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SITES = [
  { id_site: 1, id_org: 1, site_name: 'Store Bordeaux', address: null, country: null, site_number: null, latitude: null, longitude: null, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 15, power_lag_min: 15, respect_holidays: false, holiday_region: 'FR', created_at: new Date().toISOString(), player_count: 2, hours: [] },
  { id_site: 2, id_org: 1, site_name: 'Store Toulouse', address: null, country: null, site_number: null, latitude: null, longitude: null, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 15, power_lag_min: 15, respect_holidays: false, holiday_region: 'FR', created_at: new Date().toISOString(), player_count: 1, hours: [] },
]

const GROUP = {
  id_site_group: 1, id_org: 1, group_name: 'Sud-Ouest', description: 'Région SO',
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  site_count: 1, player_count: 2,
}

async function mockAuthAndNavigate(page: import('@playwright/test').Page, url: string) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => {
    const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
    const store = {
      state: {
        user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
        accessToken: mockToken,
        refreshToken: 'mock_refresh',
        roles: ['CMS_ORG_ADMIN'],
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

test.describe('Site groups (S6)', () => {
  test('tab_grid_search_and_member_management_in_drawer', async ({ page }) => {
    // Design v2 (retour Ed 10/07) : grille de cartes façon onglet Sites + recherche ;
    // membres gérés dans le DRAWER (pattern « Players rattachés »).
    const GROUP2 = { ...GROUP, id_site_group: 2, group_name: 'Nord-Est', description: null, site_count: 0, player_count: 0 }
    await page.route('**/api/v1/sites', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) })
    })
    await page.route('**/api/v1/site-groups/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([GROUP2, GROUP]) })
    })
    await page.route('**/api/v1/site-groups/1/sites', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({ status: 204, body: '' })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([SITES[0]]) })
      }
    })
    await mockAuthAndNavigate(page, `${BASE}/sites`)

    await page.getByRole('button', { name: /site groups/i }).click()
    // Cartes : nom + compteurs serveur séparés (sites / players)
    await expect(page.locator('text=Sud-Ouest')).toBeVisible()
    await expect(page.locator('text=Nord-Est')).toBeVisible()
    await expect(page.locator('text=1 sites')).toBeVisible()
    await expect(page.locator('text=2 players')).toBeVisible()

    // Recherche : filtre les cartes
    const searchBox = page.getByRole('main').getByPlaceholder(/search/i)
    await searchBox.fill('sud')
    await expect(page.locator('text=Nord-Est')).toHaveCount(0)
    await expect(page.locator('text=Sud-Ouest')).toBeVisible()
    await searchBox.fill('')

    // Clic carte → drawer : membre listé + retrait X ; ajout via select + Attach
    await page.locator('text=Sud-Ouest').click()
    const drawer = page.getByRole('dialog', { name: /edit site group/i })
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('text=Store Bordeaux')).toBeVisible()
    await expect(drawer.getByTitle('Remove from group')).toBeVisible()

    const postReq = page.waitForRequest((r) => r.url().includes('/site-groups/1/sites') && r.method() === 'POST')
    await drawer.locator('select').selectOption({ label: 'Store Toulouse' })
    await drawer.getByRole('button', { name: 'Attach' }).click()
    const req = await postReq
    expect(req.postDataJSON()).toEqual({ id_site: 2 })
  })

  test('topbar_button_creates_group_then_stays_in_edit', async ({ page }) => {
    await page.route('**/api/v1/sites', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) })
    })
    await page.route('**/api/v1/site-groups/', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ ...GROUP, site_count: 0, player_count: 0 }) })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      }
    })
    await page.route('**/api/v1/site-groups/1/sites', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/sites`)

    await page.getByRole('button', { name: /site groups/i }).click()
    // Le bouton topbar suit l'onglet (règle actions primaires en topbar)
    const newBtn = page.getByRole('button', { name: /new site group/i })
    await expect(newBtn).toBeVisible()
    await newBtn.click()

    const postReq = page.waitForRequest((r) => r.url().endsWith('/site-groups/') && r.method() === 'POST')
    const createDrawer = page.getByRole('dialog', { name: /new site group/i })
    await createDrawer.getByPlaceholder(/group name/i).fill('Sud-Ouest')
    // Scope au drawer groupe : le drawer Sites fermé reste monté avec son propre « Save »
    await createDrawer.getByRole('button', { name: 'Save' }).click()
    const req = await postReq
    expect(req.postDataJSON()).toEqual({ group_name: 'Sud-Ouest', description: null })
    // Après création, le drawer reste ouvert en ÉDITION pour ajouter les sites
    await expect(page.getByRole('dialog', { name: /edit site group/i })).toBeVisible()
    await expect(page.locator('text=No sites in this group yet.')).toBeVisible()
  })

  test('campaign_drawer_offers_site_group_target', async ({ page }) => {
    await page.route('**/api/v1/campaigns/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/advertisers/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Dyson', id_folder: null }]) })
    })
    await page.route('**/api/v1/sites', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/player-groups/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/site-groups/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([GROUP]) })
    })
    await page.route('**/api/v1/players/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/campaigns/inventory**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/campaigns/settings', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ creative_approval: false }) })
    })
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.getByRole('button', { name: /new campaign/i }).click()
    const drawer = page.getByRole('dialog')
    // Section Cible ouverte en création : choisir le type « Site group » → le groupe est proposé
    const typeSelect = drawer.locator('select').filter({ has: page.locator('option[value="site_group"]') }).first()
    await typeSelect.selectOption('site_group')
    const entitySelect = drawer.locator('select').filter({ has: page.locator('option', { hasText: 'Sud-Ouest' }) }).first()
    await entitySelect.selectOption({ label: 'Sud-Ouest' })
    await expect(entitySelect).toHaveValue('1')
  })
})
