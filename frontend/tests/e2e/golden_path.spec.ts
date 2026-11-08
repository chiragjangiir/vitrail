/**
 * Golden path — end-to-end CMS workflow
 * login (TOTP) → media library → playlist creation → schedule creation → player view
 *
 * All API calls are mocked; no live backend required. Réécrit 2026-07-12 :
 * l'UI a évolué (pagination médiathèque, trailing slashes, requêtes annexes
 * stats/folders/site-groups) → un FALLBACK générique répond [] à tout /api/v1/*
 * non mocké (enregistré en premier = plus faible priorité Playwright), les
 * endpoints à forme objet sont mockés explicitement.
 */
import { test, expect } from '@playwright/test'

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9' +
  '.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0' +
  '.signature'

const MOCK_USER = {
  id_user: 1, id_org: 1, email: 'admin@signflow.app', full_name: 'Admin',
  avatar_url: null, totp_enabled: true, locale: 'en',
  is_active: true, last_login_at: null, created_at: new Date().toISOString(),
}

const MOCK_MEDIA = {
  id_media: 1, media_name: 'promo-video.mp4', media_type: 'video',
  mime_type: 'video/mp4', file_size_bytes: 10_000_000, thumbnail_url: null,
  source: 'upload', attribution_text: null, transcode_status: 'done' as const,
  created_at: new Date().toISOString(),
}

const MOCK_PLAYLIST = {
  id_playlist: 1, id_org: 1, playlist_name: 'Promo Campaign',
  description: null, items: [],
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
}

const MOCK_SCHEDULE = {
  id_schedule: 1, id_org: 1, id_playlist: 1, schedule_name: 'Daily Promo',
  priority: 0, is_active: true,
  rules: [{ id_rule: 1, rule_type: 'always', days_of_week: null, time_start: null, time_end: null }],
  targets: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
}

const MOCK_PLAYER = {
  id_player: 1, id_org: 1, id_site: null, player_name: 'nuc-debian12',
  player_os: 'linux-x64', status: 'online', ip_address: '192.168.1.138',
  mac_address: null, cpu_usage: 5.2, ram_usage: 42.1, disk_usage: 18.7,
  current_playlist_id: 1, player_version: '1.0.0', player_token: null,
  token_expires_at: null, last_seen_at: new Date().toISOString(),
  created_at: new Date().toISOString(),
}

test.describe('Golden path', () => {
  test('golden_path — login → media → playlist → schedule → player', async ({ page }) => {
    // ── Fallback générique (priorité la plus faible) : tout endpoint non mocké
    //    répond une liste vide — les pages annexes ne cassent pas le parcours.
    await page.route('**/api/v1/**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

    // ── Auth ──────────────────────────────────────────────────────────────
    await page.route('**/api/v1/auth/login', async (route, request) => {
      const body = JSON.parse(request.postData() ?? '{}')
      if (body.totp_code) {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({
            access_token: MOCK_TOKEN, refresh_token: 'mock_refresh',
            token_type: 'bearer', locale: 'en',
          }),
        })
      } else {
        await route.fulfill({
          status: 401, contentType: 'application/json',
          body: JSON.stringify({ detail: 'Code TOTP requis' }),
        })
      }
    })
    await page.route('**/api/v1/users/me', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER) }))
    await page.route('**/api/v1/auth/refresh', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: MOCK_TOKEN, refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }) }))

    // ── Endpoints à forme OBJET (le fallback [] les casserait) ────────────
    await page.route('**/api/v1/pop/analytics**', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ period_days: 7, total_plays: 42, total_hours: 1.5, plays_per_day: [], top_media: [] }) }))
    await page.route('**/api/v1/players/stats', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ total: 1, online: 1, offline: 0, warning: 0 }) }))
    await page.route('**/api/v1/media/stats**', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ total: 1, by_type: { video: 1 } }) }))

    // ── Modules du parcours ───────────────────────────────────────────────
    await page.route('**/api/v1/media/?**', (r) => r.request().method() === 'GET'
      ? r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_MEDIA]) })
      : r.fallback())
    // ⚠️ le POST de création part sur /playlists SANS slash final → pattern sans slash
    await page.route('**/api/v1/playlists**', (r) => {
      const p = new URL(r.request().url()).pathname
      if (/\/playlists\/?$/.test(p) && r.request().method() === 'POST') {
        return r.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(MOCK_PLAYLIST) })
      }
      if (/\/playlists\/?$/.test(p)) {
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_PLAYLIST]) })
      }
      if (/\/playlists\/1$/.test(p)) {
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...MOCK_PLAYLIST, items: [] }) })
      }
      return r.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/schedules**', (r) => {
      const p = new URL(r.request().url()).pathname
      if (/\/schedules\/?$/.test(p) && r.request().method() === 'POST') {
        return r.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(MOCK_SCHEDULE) })
      }
      if (/\/schedules\/?$/.test(p)) {
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_SCHEDULE]) })
      }
      return r.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/players/', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_PLAYER]) }))

    // ── 1. Login (email + password → TOTP → dashboard) ────────────────────
    await page.goto(`${BASE}/login`)
    await page.getByLabel('Email').fill('admin@signflow.app')
    await page.getByLabel('Password').fill('Admin1234!')
    await page.getByRole('button', { name: /sign in/i }).click()

    await expect(page.getByLabel(/authenticator code/i)).toBeVisible()
    await page.getByLabel(/authenticator code/i).fill('123456')
    await page.getByRole('button', { name: /confirm/i }).click()
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 })

    // ── 2. Media — la bibliothèque montre le fichier ───────────────────────
    await page.goto(`${BASE}/media`)
    await expect(page.locator('text=promo-video.mp4').first()).toBeVisible()

    // ── 3. Playlists — liste + création → éditeur ──────────────────────────
    await page.goto(`${BASE}/playlists`)
    await expect(page.locator('text=Promo Campaign').first()).toBeVisible()

    await page.getByRole('button', { name: /new playlist/i }).click()
    await page.getByLabel(/playlist name/i).fill('Test Playlist')
    await page.getByRole('button', { name: /create/i }).click()
    await expect(page).toHaveURL(/\/playlists\/1/, { timeout: 10000 })

    // ── 4. Schedules — liste + création ────────────────────────────────────
    await page.goto(`${BASE}/schedules`)
    await expect(page.locator('text=Daily Promo').first()).toBeVisible()

    // ⚠️ Scoper au drawer : le drawer « Simulate a day » est monté dans le DOM
    // avant le formulaire — un `select.first()` global tombait sur SON combobox
    // player, la playlist restait vide et Create restait désactivé.
    await page.getByRole('button', { name: /new schedule/i }).click()
    const drawer = page.getByRole('dialog', { name: /new schedule/i })
    await drawer.getByLabel(/schedule name/i).fill('Morning Show')
    // La playlist se choisit dans le tiroir partagé (recherche serveur + dossiers),
    // plus dans un <select> : bouton du formulaire, puis la ligne de la playlist.
    await drawer.getByTestId('schedule-playlist-select').click()
    await page.getByTestId('content-playlist-1').click()
    await drawer.getByRole('button', { name: /create/i }).click()
    await expect(page.locator('text=Daily Promo').first()).toBeVisible()

    // ── 5. Players — le player online est visible ──────────────────────────
    await page.goto(`${BASE}/players`)
    await expect(page.locator('text=nuc-debian12')).toBeVisible()
    await expect(page.locator('text=Online').first()).toBeVisible()
  })
})
