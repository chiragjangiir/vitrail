import { test, expect } from '@playwright/test'

// VOD — ciblage par SITE entier (migr 0096) : pills de mode dans le drawer, sélecteur de
// site avec aperçu des players résolus, et corps POST envoyé au serveur.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SITES = [
  { id_site: 1, id_org: 1, site_name: 'Store Paris', address: null, country: null, site_number: null, latitude: null, longitude: null, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
  { id_site: 2, id_org: 1, site_name: 'Store Lyon', address: null, country: null, site_number: null, latitude: null, longitude: null, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
]

const PLAYERS = [
  { id_player: 10, id_org: 1, player_name: 'Paris Window', player_os: 'linux', status: 'online', id_site: 1, ip_address: '192.168.1.10', capabilities: {} },
  { id_player: 11, id_org: 1, player_name: 'Paris Counter', player_os: 'linux', status: 'offline', id_site: 1, ip_address: '192.168.1.11', capabilities: {} },
  { id_player: 20, id_org: 1, player_name: 'Lyon Window', player_os: 'linux', status: 'online', id_site: 2, ip_address: '192.168.2.10', capabilities: {} },
]

const MEDIA = [
  { id_media: 100, media_name: 'promo.mp4', media_type: 'video', mime_type: 'video/mp4', file_size_bytes: 1, duration_ms: 10000, thumbnail_url: null, source: 'upload', attribution_text: null, transcode_status: 'done', encode_mode: 'auto', conformance_status: 'ready', not_before_utc: null, embargo_event_id: null, embargo_event_name: null, tags: [], id_folder: null, created_at: new Date().toISOString() },
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

async function mockVodPage(page: import('@playwright/test').Page) {
  await page.route(/\/api\/v1\/vod(\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') return  // laissé au test
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route(/\/api\/v1\/sites(\/)?(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) })
  })
  await page.route(/\/api\/v1\/players\/(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) })
  })
  await page.route(/\/api\/v1\/media\/(\?.*)?$/, async (route) => {
    // Le double HONORE `media_type` : le tiroir partagé lance une requête PAR TYPE, et un
    // double qui rend tout à chaque fois ferait apparaître le même média plusieurs fois.
    const ty = new URL(route.request().url()).searchParams.get('media_type')
    const items = ty ? MEDIA.filter((m) => m.media_type === ty) : MEDIA
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items) })
  })
  await page.route(/\/api\/v1\/media\/folders/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route(/\/api\/v1\/media\/stats/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 1, by_type: { video: 1 } }) })
  })
}

test.describe('VOD site targeting', () => {
  test('site_mode_resolves_players_and_posts_site_target', async ({ page }) => {
    let postBody: Record<string, unknown> | null = null
    await mockVodPage(page)
    await page.route(/\/api\/v1\/vod$/, async (route) => {
      if (route.request().method() === 'POST') {
        postBody = route.request().postDataJSON()
        return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id_vod: 1 }) })
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/vod`)

    await page.getByRole('button', { name: /New|Nouveau/ }).first().click()
    await page.getByLabel('Name').fill('Site VOD')

    // Bascule en ciblage « site entier ».
    await page.getByRole('button', { name: 'Entire site' }).click()

    // Le choix d'un site affiche les players RÉSOLUS de ce site, et eux seuls.
    await page.locator('select').selectOption('1')
    await expect(page.getByText('Paris Window')).toBeVisible()
    await expect(page.getByText('Paris Counter')).toBeVisible()
    await expect(page.getByText('Lyon Window')).toHaveCount(0)

    // Sélection d'un média via le TIROIR PARTAGÉ (phase C) — le geste change, l'assertion
    // sur le corps envoyé au serveur reste identique : c'est elle qui prouve le refactor.
    await page.getByTestId('vod-content-select').click()

    // Le tiroir de SÉLECTION doit avoir la même largeur que le tiroir d'ÉDITION qui
    // l'ouvre (constat d'Ed 2026-07-29 : il paraissait plus étroit). On mesure la largeur
    // RENDUE, pas la classe : c'est ce que l'œil voit qui compte.
    const pickerWidth = await page.getByTestId('content-picker')
      .evaluate((el) => (el.closest('aside') as HTMLElement).getBoundingClientRect().width)
    expect(pickerWidth).toBe(560)
    await page.getByTestId('content-media-100').click()
    await page.getByTestId('content-picker-add').click()
    await page.getByRole('button', { name: /^Save$|^Enregistrer$/ }).click()

    // Le corps envoyé porte la CIBLE SITE, pas une liste de players figée.
    await expect.poll(() => postBody).toMatchObject({
      vod_name: 'Site VOD', target_mode: 'site', id_site: 1, id_medias: [100],
    })
    expect(postBody).not.toHaveProperty('id_players')
  })

  test('players_mode_remains_default', async ({ page }) => {
    await mockVodPage(page)
    await mockAuthAndNavigate(page, `${BASE}/vod`)

    await page.getByRole('button', { name: /New|Nouveau/ }).first().click()
    // Par défaut on reste en sélection player-par-player : les cases à cocher sont là,
    // et les players de TOUS les sites sont proposés (contrainte même-site gérée au clic).
    await expect(page.locator('input[type="checkbox"]').first()).toBeVisible()
    await expect(page.getByText('Lyon Window')).toBeVisible()
  })
})
