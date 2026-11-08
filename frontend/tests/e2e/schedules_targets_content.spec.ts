import { test, expect } from '@playwright/test'

// Programmes — filet « picker de playlist + carte de ciblage » (audit menu ⑧, harmonisation
// demandée par Ed : « pouvoir ajouter une recherche des cibles avec la carte serait un plus »).
//
// Ces specs affirment le RÉSULTAT (le corps envoyé au serveur), jamais le widget : le
// <select> de playlist est devenu un tiroir de recherche serveur, et la carte alimente les
// MÊMES familles de cibles que les listes — donc le même corps.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SITES = [
  { id_site: 2, site_name: 'Store Lyon', latitude: 45.76, longitude: 4.83 },
  { id_site: 3, site_name: 'Store Paris', latitude: 48.85, longitude: 2.35 },
]
const PLAYERS = [
  { id_player: 9, player_name: 'Lyon Entrance', status: 'online', player_os: 'linux', id_site: 2 },
  { id_player: 10, player_name: 'Lyon Butcher', status: 'online', player_os: 'linux', id_site: 2 },
  { id_player: 11, player_name: 'Paris Lobby', status: 'online', player_os: 'linux', id_site: 3 },
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
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER_ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }),
    }))
  await page.goto(url)
}

async function mockSchedulesPage(
  page: import('@playwright/test').Page,
  opts: { onPost?: (b: Record<string, unknown>) => void } = {},
) {
  // ⚠️ Regex, pas glob : les globs ne matchent pas les query strings (piège § Frontend).
  await page.route(/\/api\/v1\/schedules(\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      opts.onPost?.(route.request().postDataJSON())
      return route.fulfill({
        status: 201, contentType: 'application/json',
        body: JSON.stringify({
          id_schedule: 99, id_org: 1, schedule_name: 'Cree', schedule_kind: 'content',
          id_playlist: 10, playlist_name: 'PL', id_governance_node: null, priority: 0,
          is_active: true, valid_from: null, valid_until: null,
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
          rules: [], targets: [], baskets: [],
        }),
      })
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route(/\/api\/v1\/events(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/campaigns\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/playlists\/(\?.*)?$/, (r) =>
    r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{ id_playlist: 10, playlist_name: 'PL', sync_mode: 'wall_clock', sync_ready: true }]),
    }))
  await page.route(/\/api\/v1\/sites(\/)?(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) }))
  await page.route(/\/api\/v1\/players\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) }))
  await page.route(/\/api\/v1\/player-groups\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/site-groups\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/audio-baskets(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/governance\/nodes(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/schedules\/hdmi-check/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ has_hdmi_item: false, incompatible_players: [] }) }))
  // Tuiles carte = service externe : on coupe, marqueurs et recherche restent locaux.
  await page.route(/tile\.|openstreetmap|basemaps/, (r) => r.abort())
}

test.describe('Programmes — picker de playlist + carte (audit menu ⑧)', () => {
  test('playlist_picker_sends_id_playlist', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockSchedulesPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/schedules`)

    await page.getByRole('button', { name: 'New schedule' }).click()
    const drawer = page.getByRole('dialog', { name: 'New schedule' })
    await drawer.getByRole('textbox').first().fill('Prog picker')
    await drawer.getByTestId('schedule-playlist-select').click()
    await page.getByTestId('content-playlist-10').click()
    // Le bouton affiche le nom retenu (fourni par le tiroir, pas par la liste paginée).
    await expect(drawer.getByTestId('schedule-playlist-select')).toContainText('PL')

    await drawer.getByRole('button', { name: 'Create' }).click()
    await expect.poll(() => body).toMatchObject({ id_playlist: 10 })
  })

  test('map_players_feeds_player_targets', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockSchedulesPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/schedules`)

    await page.getByRole('button', { name: 'New schedule' }).click()
    const drawer = page.getByRole('dialog', { name: 'New schedule' })
    await drawer.getByRole('textbox').first().fill('Prog carte ecrans')
    await drawer.getByTestId('schedule-playlist-select').click()
    await page.getByTestId('content-playlist-10').click()

    // La carte en mode ÉCRANS : désigner le site par la recherche (focus), puis cocher
    // ses écrans dans le panneau qui s'ouvre — c'est le chemin qui marche aussi pour un
    // site sans coordonnées (aucun marqueur à cliquer).
    await drawer.getByTestId('schedule-target-map-players').click()
    const map = page.getByTestId('target-map')
    await expect(map).toBeVisible()
    await page.getByPlaceholder('Search a site…').fill('Lyon')
    await page.getByRole('button', { name: 'Store Lyon' }).click()
    await map.getByText('Lyon Entrance').click()
    await map.getByText('Lyon Butcher').click()
    await page.getByTestId('target-map-apply').click()

    // La sélection de la carte est visible dans la liste (pastille de la famille).
    await expect(drawer.getByRole('button', { name: /Target players/ })).toContainText('2')

    await drawer.getByRole('button', { name: 'Create' }).click()
    await expect.poll(() => body).not.toBeNull()
    const targets = (body!.targets ?? []) as { target_type: string; target_id: number }[]
    expect(targets.filter((t) => t.target_type === 'player').map((t) => t.target_id).sort((a, b) => a - b))
      .toEqual([9, 10])
  })

  test('map_sites_feeds_site_targets', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockSchedulesPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/schedules`)

    await page.getByRole('button', { name: 'New schedule' }).click()
    const drawer = page.getByRole('dialog', { name: 'New schedule' })
    await drawer.getByRole('textbox').first().fill('Prog carte sites')
    await drawer.getByTestId('schedule-playlist-select').click()
    await page.getByTestId('content-playlist-10').click()

    // La carte en mode SITES : le même geste alimente la famille « sites ».
    await drawer.getByTestId('schedule-target-map-sites').click()
    await expect(page.getByTestId('target-map')).toBeVisible()
    await page.getByPlaceholder('Search a site…').fill('Paris')
    await page.getByRole('button', { name: 'Store Paris' }).click()
    await page.getByTestId('target-map-toggle-focused').click()
    await page.getByTestId('target-map-apply').click()

    await drawer.getByRole('button', { name: 'Create' }).click()
    await expect.poll(() => body).not.toBeNull()
    const targets = (body!.targets ?? []) as { target_type: string; target_id: number }[]
    expect(targets).toEqual([{ target_type: 'site', target_id: 3 }])
  })
})
