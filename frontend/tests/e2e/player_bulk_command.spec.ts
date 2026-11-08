import { test, expect } from '@playwright/test'

// Commandes players EN MASSE + garde PIN (migr 0097) : apercu de la cible, PIN exige
// pour les commandes destructives seulement, corps envoye au serveur.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SITES = [
  { id_site: 1, id_org: 1, site_name: 'Store Paris', address: null, country: null, site_number: null, latitude: null, longitude: null, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
  { id_site: 2, id_org: 1, site_name: 'Store Lyon', address: null, country: null, site_number: null, latitude: null, longitude: null, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
]

const PLAYERS = [
  { id_player: 10, id_org: 1, player_name: 'Paris Window', player_os: 'linux', status: 'online', id_site: 1, capabilities: {}, alert_reasons: [] },
  { id_player: 11, id_org: 1, player_name: 'Paris Counter', player_os: 'linux', status: 'offline', id_site: 1, capabilities: {}, alert_reasons: [] },
  { id_player: 20, id_org: 1, player_name: 'Lyon Window', player_os: 'linux', status: 'online', id_site: 2, capabilities: {}, alert_reasons: [] },
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

async function mockPlayersPage(page: import('@playwright/test').Page) {
  await page.route(/\/api\/v1\/players\/(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) })
  })
  await page.route(/\/api\/v1\/sites(\/)?(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) })
  })
  await page.route(/\/api\/v1\/site-groups\/(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route(/\/api\/v1\/player-groups\/(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route(/\/api\/v1\/players\/alert-settings.*/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
}

test.describe('Bulk player commands', () => {
  test('site_target_preview_and_no_pin_for_screenshot', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockPlayersPage(page)
    await page.route('**/api/v1/players/commands', async (route) => {
      body = route.request().postDataJSON()
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ command: 'screenshot', dispatched: [10, 11], count: 2 }) })
    })
    await mockAuthAndNavigate(page, `${BASE}/players`)

    await page.getByRole('button', { name: 'Bulk commands' }).click()

    // Cible « Site » -> Paris : seuls les 2 players de Paris apparaissent dans l'apercu.
    await page.getByRole('button', { name: 'Site', exact: true }).click()
    await page.locator('select').last().selectOption('1')
    // Scope au drawer : les noms de players apparaissent aussi sur les cartes derriere.
    const drawer = page.getByLabel('Bulk commands')
    await expect(drawer.getByText('2 player(s) targeted')).toBeVisible()
    await expect(drawer.getByText('Paris Window')).toBeVisible()
    await expect(drawer.getByText('Lyon Window')).toHaveCount(0)

    // screenshot = inoffensif -> aucun champ PIN, envoi direct.
    await expect(page.getByLabel('Confirmation PIN')).toHaveCount(0)
    await page.getByRole('button', { name: 'Send' }).click()

    await expect.poll(() => body).toMatchObject({
      command: 'screenshot', targets: [{ target_type: 'site', target_id: 1 }],
    })
    expect(body).not.toHaveProperty('pin')
  })

  test('destructive_command_requires_pin_and_confirmation', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockPlayersPage(page)
    await page.route('**/api/v1/players/commands', async (route) => {
      body = route.request().postDataJSON()
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ command: 'reboot_os', dispatched: [10, 11, 20], count: 3 }) })
    })
    await mockAuthAndNavigate(page, `${BASE}/players`)

    await page.getByRole('button', { name: 'Bulk commands' }).click()
    await page.getByRole('button', { name: 'Organisation' }).click()
    await page.locator('select').first().selectOption('reboot_os')

    // Garde destructive : avertissement + case + PIN, et Envoyer reste DESACTIVE.
    await expect(page.getByText(/Irreversible action on 3 screen/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled()

    await page.getByRole('checkbox').check()
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled()  // PIN manquant

    await page.getByLabel('Confirmation PIN').fill('246813')
    await page.getByRole('button', { name: 'Send' }).click()

    await expect.poll(() => body).toMatchObject({
      command: 'reboot_os', targets: [{ target_type: 'org' }], pin: '246813',
    })
  })

  test('missing_pin_shows_actionable_message', async ({ page }) => {
    await mockPlayersPage(page)
    await page.route('**/api/v1/players/commands', async (route) => {
      await route.fulfill({ status: 412, contentType: 'application/json', body: JSON.stringify({ detail: 'PIN requis' }) })
    })
    await mockAuthAndNavigate(page, `${BASE}/players`)

    await page.getByRole('button', { name: 'Bulk commands' }).click()
    await page.getByRole('button', { name: 'Organisation' }).click()
    await page.locator('select').first().selectOption('reboot_os')
    await page.getByRole('checkbox').check()
    await page.getByLabel('Confirmation PIN').fill('246813')
    await page.getByRole('button', { name: 'Send' }).click()

    // 412 = pas de PIN au profil -> message d'ACTION, pas « PIN incorrect ».
    await expect(page.getByText(/No PIN set/)).toBeVisible()
  })
})
