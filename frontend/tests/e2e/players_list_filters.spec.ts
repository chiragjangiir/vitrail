import { test, expect } from '@playwright/test'

// Vue LISTE + panneau de FILTRES du parc (demande d'Ed, 2026-07-31 : « j'apprécierai
// d'avoir une vue liste et un filtre à l'image de ce que l'on a fait pour Media »).
//
// Les specs affirment le RÉSULTAT visible, pas le widget : quels écrans restent affichés.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

function player(id: number, name: string, over: Record<string, unknown> = {}) {
  return {
    id_player: id, id_org: 1, id_site: 1, player_name: name,
    player_os: 'linux-x64', player_version: '1.5.16', player_role: 'content',
    status: 'online', last_seen_at: new Date().toISOString(),
    ip_address: '192.168.1.10', wan_ip: null, mac_address: null,
    screenshot_url: null, display_config: {}, alert_reasons: [],
    disk_usage: null, created_at: new Date().toISOString(), ...over,
  }
}

const PLAYERS = [
  player(1, 'Lyon Entrance'),
  player(2, 'Lyon Butcher', { status: 'offline', player_os: 'android-armeabi-v7a' }),
  player(3, 'Paris Lobby', { id_site: 2, status: 'warning' }),
]
const SITES = [
  { id_site: 1, id_org: 1, site_name: 'Store Lyon', address: null, country: 'FR', site_number: null, latitude: 45.76, longitude: 4.83, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0, power_lag_min: 0, respect_holidays: false },
  { id_site: 2, id_org: 1, site_name: 'Store Paris', address: null, country: 'FR', site_number: null, latitude: 48.85, longitude: 2.35, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0, power_lag_min: 0, respect_holidays: false },
]

async function mockAndGo(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => {
    const tok = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }, accessToken: tok, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', tok)
    localStorage.setItem('sf_refresh_token', 'r')
    // Repartir d'une préférence de vue NEUVE : le choix cartes/liste est persisté,
    // un test ne doit pas dépendre de ce qu'un test précédent a laissé.
    localStorage.removeItem('sf-players-view')
  })
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER_ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'x', refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  await page.route(/\/api\/v1\/players\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) }))
  await page.route(/\/api\/v1\/sites(\/)?(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) }))
  await page.route(/\/api\/v1\/player-groups\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/tags\/namespaces(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/schedules(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.goto(`${BASE}/players`)
  await expect(page.getByText('Lyon Entrance').first()).toBeVisible()
}

test.describe('Parc — vue liste et filtres', () => {
  test('list_view_shows_sortable_columns', async ({ page }) => {
    await mockAndGo(page)
    // Par défaut : cartes (pas de tableau).
    await expect(page.getByTestId('players-list')).toHaveCount(0)

    await page.getByTestId('players-view-list').click()
    const list = page.getByTestId('players-list')
    await expect(list).toBeVisible()
    // Les colonnes que la carte ne donne pas : site, OS, version, dernier contact.
    await expect(list).toContainText('Store Lyon')
    await expect(list).toContainText('android-armeabi-v7a')
    await expect(list).toContainText('1.5.16')

    // Tri par nom : le premier écran change de sens au 2e clic.
    const firstName = () => list.locator('tbody tr').first().locator('td').first().innerText()
    expect((await firstName()).trim()).toBe('Lyon Butcher')      // tri asc par défaut
    await page.getByTestId('players-sort-name').click()  // bascule desc
    expect((await firstName()).trim()).toBe('Paris Lobby')
  })

  test('filters_combine_status_and_site', async ({ page }) => {
    await mockAndGo(page)
    await page.getByTestId('players-view-list').click()
    await page.getByTestId('players-filters-toggle').click()
    const panel = page.getByTestId('player-filters')
    await expect(panel).toBeVisible()

    // Un filtre de SITE : seuls les écrans de Lyon restent.
    await panel.getByRole('button', { name: /Store Lyon/ }).click()
    const list = page.getByTestId('players-list')
    await expect(list).toContainText('Lyon Entrance')
    await expect(list).not.toContainText('Paris Lobby')

    // Combiné avec un STATUT — c'est ce qu'une barre de recherche ne sait pas exprimer.
    await panel.getByRole('button', { name: /^Offline/ }).click()
    await expect(list).toContainText('Lyon Butcher')
    await expect(list).not.toContainText('Lyon Entrance')

    // Le compteur du bouton dit combien de filtres sont actifs.
    await expect(page.getByTestId('players-filters-toggle')).toContainText('2')
  })

  test('view_choice_is_persisted', async ({ page }) => {
    await mockAndGo(page)
    await page.getByTestId('players-view-list').click()
    await expect(page.getByTestId('players-list')).toBeVisible()
    await page.reload()
    // Préférence de travail : on la retrouve, on ne la repose pas à chaque visite.
    await expect(page.getByTestId('players-list')).toBeVisible()
  })

  // Verrouillage au viewport (règle du design system, appliquée le 31/07) : les compteurs
  // et les onglets restent visibles pendant qu'on parcourt un grand parc.
  test('page_is_locked_to_viewport', async ({ page }) => {
    await mockAndGo(page)
    await page.getByTestId('players-view-list').click()
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollHeight - document.documentElement.clientHeight)
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
