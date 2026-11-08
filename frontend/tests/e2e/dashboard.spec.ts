import { test, expect } from '@playwright/test'

// Dashboard « Mission Control » (recompo 2026-07-18) : hero, 5 KPI cards (sparkline +
// évolution hebdo), Fleet Status (nœuds lumineux), Recent Activity, table players,
// panneau média latéral. Données mockées ; vérifie le rendu + capture un screenshot.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const USER = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SUMMARY = {
  generated_at: '2026-07-18T09:00:00Z',
  players_online: { key: 'players_online', value: 1248, delta_pct: 8.4, spark: [1100, 1150, 1180, 1200, 1210, 1230, 1240, 1248] },
  players_offline: { key: 'players_offline', value: 153, delta_pct: -12.1, spark: [180, 175, 170, 165, 160, 158, 155, 153] },
  players_warning: { key: 'players_warning', value: 42, delta_pct: 5.0, spark: [30, 32, 35, 38, 40, 41, 44, 42] },
  active_campaigns: { key: 'active_campaigns', value: 16, delta_pct: 14.2, spark: [10, 11, 12, 13, 14, 15, 14, 16] },
  proof_of_play: { key: 'proof_of_play', value: 9830, delta_pct: 1.6, spark: [9000, 9200, 9400, 9500, 9600, 9700, 9750, 9830] },
}

const ago = (min: number) => new Date(Date.now() - min * 60000).toISOString()
const ACTIVITY = { items: [
  { id: 1, action: 'publish', resource_type: 'playlist', resource_id: '12', user_name: 'Metro East Mall', source: 'cms', created_at: ago(2) },
  { id: 2, action: 'campaign_started', resource_type: 'campaign', resource_id: '3', user_name: 'Olivia Rhye', source: 'cms', created_at: ago(5) },
  { id: 3, action: 'player_offline', resource_type: 'player', resource_id: '21', user_name: null, source: 'cms', created_at: ago(28) },
  { id: 4, action: 'schedule_updated', resource_type: 'schedule', resource_id: '7', user_name: 'High Street Store', source: 'cms', created_at: ago(58) },
  { id: 5, action: 'media_uploaded', resource_type: 'media', resource_id: '88', user_name: 'Ethan Park', source: 'cms', created_at: ago(130) },
] }

const NOC = {
  total: 1413, online: 1248, warning: 42, offline: 153, maintenance: 12,
  rows: [
    { id_player: 1, player_name: 'SF-Player-0001', site_name: 'Times Square Flagship', player_os: 'linux', player_version: '2.8.7', status: 'online', last_seen_at: ago(2) },
    { id_player: 21, player_name: 'SF-Player-0021', site_name: 'Westfield London', player_os: 'brightsign', player_version: '2.8.7', status: 'warning', last_seen_at: ago(15) },
    { id_player: 33, player_name: 'SF-Player-0033', site_name: 'Dubai Mall', player_os: 'windows', player_version: '2.6', status: 'offline', last_seen_at: ago(64) },
    { id_player: 44, player_name: 'SF-Player-0044', site_name: 'Sunset Plaza', player_os: 'rpi', player_version: '2.8.7', status: 'online', last_seen_at: ago(1) },
    { id_player: 88, player_name: 'SF-Player-0088', site_name: 'Shibuya Crossing', player_os: 'android', player_version: '2.8.7', status: 'online', last_seen_at: ago(5) },
    { id_player: 90, player_name: 'SF-Player-0090', site_name: 'Berlin Mitte', player_os: 'chromeos', player_version: '2.0.4', status: 'maintenance', last_seen_at: ago(120) },
  ],
}

const MEDIA_PANEL = { groups: [
  { media_type: 'video', total: 32, items: [
    { id_media: 1, media_name: 'Summer Promo 2026 — Master Cut', media_type: 'video', thumbnail_url: null },
    { id_media: 2, media_name: 'Back to School', media_type: 'video', thumbnail_url: null },
    { id_media: 3, media_name: 'Lifestyle Video', media_type: 'video', thumbnail_url: null },
  ] },
  { media_type: 'image', total: 120, items: [
    { id_media: 4, media_name: 'Sale 30% Off', media_type: 'image', thumbnail_url: null },
    { id_media: 5, media_name: 'New Arrivals Spring Collection Poster A4', media_type: 'image', thumbnail_url: null },
    { id_media: 6, media_name: 'Store Locator', media_type: 'image', thumbnail_url: null },
  ] },
  { media_type: 'audio', total: 8, items: [
    { id_media: 7, media_name: 'Ambient Loop', media_type: 'audio', thumbnail_url: null },
  ] },
  { media_type: 'document', total: 5, items: [
    { id_media: 8, media_name: 'Menu Board.pdf', media_type: 'document', thumbnail_url: null },
  ] },
] }

const GEO = { unplaced: 0, sites: [
  { id_site: 1, site_name: 'Times Square Flagship', country: 'USA', site_number: 'NY01', latitude: 40.758, longitude: -73.985, players_total: 4, players_online: 4, players_warning: 0, players_offline: 0, players_maintenance: 0 },
  { id_site: 2, site_name: 'Westfield London', country: 'UK', site_number: 'LDN1', latitude: 51.507, longitude: -0.221, players_total: 6, players_online: 5, players_warning: 1, players_offline: 0, players_maintenance: 0 },
  { id_site: 3, site_name: 'Dubai Mall', country: 'UAE', site_number: 'DXB1', latitude: 25.197, longitude: 55.279, players_total: 12, players_online: 6, players_warning: 0, players_offline: 6, players_maintenance: 0 },
  { id_site: 4, site_name: 'Sunset Plaza', country: 'USA', site_number: 'LA01', latitude: 34.09, longitude: -118.38, players_total: 3, players_online: 3, players_warning: 0, players_offline: 0, players_maintenance: 0 },
  { id_site: 5, site_name: 'Shibuya Crossing', country: 'Japan', site_number: 'TKY1', latitude: 35.659, longitude: 139.7, players_total: 8, players_online: 8, players_warning: 0, players_offline: 0, players_maintenance: 0 },
  { id_site: 6, site_name: 'Berlin Mitte', country: 'Germany', site_number: 'BER1', latitude: 52.52, longitude: 13.405, players_total: 2, players_online: 0, players_warning: 0, players_offline: 0, players_maintenance: 2 },
] }

async function setup(
  page: import('@playwright/test').Page,
  roles: string[] = ['CMS_ORG_ADMIN'],
) {
  await page.goto(`${BASE}/login`)
  // ⚠️ Le store lit les rôles DANS LE JETON (`rolesFromActiveToken`), pas dans l'état
  // persisté : forger seulement `state.roles` produirait une spec VACANTE, qui passerait
  // même sur un code régressé (piège vécu le 2026-07-23 sur les specs super-admin).
  await page.evaluate(({ u, roles }) => {
    const b64 = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const tk = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${b64({
      sub: '1', org: 1, roles, locale: 'en', type: 'access', exp: 9999999999,
    })}.signature`
    localStorage.setItem('sf-auth', JSON.stringify({ state: { user: u, accessToken: tk, refreshToken: 'mock_refresh', roles }, version: 0 }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, { u: USER, roles })
  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill(json({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' })))
  await page.route('**/api/v1/approvals/dashboard', (r) => r.fulfill(json({ pending_review: 3, changes_requested: 0, approved: 0, rejected: 0, published: 0, urgent: 0, is_reviewer: true })))
  await page.route('**/api/v1/dashboard/summary', (r) => r.fulfill(json(SUMMARY)))
  await page.route('**/api/v1/dashboard/activity**', (r) => r.fulfill(json(ACTIVITY)))
  await page.route('**/api/v1/analytics/noc', (r) => r.fulfill(json(NOC)))
  await page.route('**/api/v1/analytics/geo', (r) => r.fulfill(json(GEO)))
  await page.route('**/api/v1/dashboard/media', (r) => r.fulfill(json(MEDIA_PANEL)))
  await page.route('**/api/v1/search**', (r) => r.fulfill(json({ query: 'sum', groups: [
    { kind: 'media', items: [{ id: 1, label: 'Summer Promo 2026', sublabel: null, href: '/media' }] },
    { kind: 'campaign', items: [{ id: 3, label: 'Summer Sale', sublabel: null, href: '/campaigns' }] },
  ] })))
}

test('dashboard mission control renders', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1200 })
  await setup(page)
  await page.goto(`${BASE}/dashboard`)

  // Hero
  await expect(page.getByRole('heading', { name: /Olivia/ })).toBeVisible()
  // KPI cards
  await expect(page.getByText('1,248')).toBeVisible()
  await expect(page.getByText('+8.4%')).toBeVisible()
  await expect(page.getByText('Active Campaigns')).toBeVisible()
  // Fleet Status + activity + table
  await expect(page.getByText('Fleet Status')).toBeVisible()
  await expect(page.getByText('Recent Activity')).toBeVisible()
  await expect(page.getByText('Times Square Flagship')).toBeVisible()
  // +New menu present in topbar
  await expect(page.getByRole('button', { name: /^New/ })).toBeVisible()

  await page.waitForTimeout(2500) // laisse charger Leaflet + tuiles + aurora/stagger
  await page.screenshot({ path: 'test-results/dashboard-mission-control.png', fullPage: true })
})

test('global search dropdown', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await page.goto(`${BASE}/dashboard`)
  const input = page.getByPlaceholder(/Search players/i)
  await expect(input).toBeVisible()
  await input.fill('sum')
  await expect(page.getByRole('button', { name: /Summer Promo 2026/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Summer Sale/ })).toBeVisible()
})

// ── Audit du Dashboard (2026-07-28) ──────────────────────────────────────────

test('super-admin is sent to the provisioning console, not the dashboard', async ({ page }) => {
  // Le tableau de bord est scopé à `id_org` ; le rattachement du super-admin à une
  // organisation n'est qu'une formalité de schéma. Il y lisait donc « 0 écran / 0 média »
  // alors que la plateforme en gère plusieurs — l'écran affirmait quelque chose de faux.
  // Le menu ne lui propose pas l'entrée : ce test couvre l'arrivée par URL directe.
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, ['CMS_SUPER_ADMIN'])
  await page.route('**/api/v1/orgs**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

  await page.goto(`${BASE}/dashboard`)
  await expect(page).toHaveURL(/\/settings\/orgs/)
})

test('a truncated fleet table says so', async ({ page }) => {
  // Les compteurs portent sur le parc entier, la table est plafonnée : sans ce message,
  // une table tronquée se lit comme un parc complet.
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await page.route('**/api/v1/analytics/noc', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...NOC, total: 2413, rows_truncated: true }),
    }))

  await page.goto(`${BASE}/dashboard`)
  await expect(page.getByText(/Showing 6 of 2,?413 screens/i)).toBeVisible()
})

test('the fleet map page has a way back', async ({ page }) => {
  // Constat d'Ed : « View all » au-dessus de la carte ouvre le parc en grand, et une fois
  // dedans le seul moyen de revenir était de rouvrir le menu.
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await page.route('**/api/v1/analytics/**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GEO) }))

  await page.goto(`${BASE}/dashboard`)
  await page.getByRole('link', { name: /View all/i }).first().click()
  await expect(page).toHaveURL(/\/reports\/geo/)

  // Le retour ramène d'où l'on vient — pas vers un parent codé en dur, la page étant
  // atteignable aussi bien par le menu que par le tableau de bord.
  await page.getByRole('button', { name: 'Back', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard/)
})
