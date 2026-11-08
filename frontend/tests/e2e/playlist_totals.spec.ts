import { test, expect } from '@playwright/test'

// Durées visibles (demande Ed 2026-08-15) :
// - carte /playlists : « N items · durée totale » (item_count + total_duration_ms)
// - éditeur : une VIDÉO sans override affiche sa durée NATIVE (media_duration_ms),
//   et l'en-tête « Items » porte le total vivant
// - carte /audio-baskets : durée totale des pistes à côté du nombre

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

function playlistItem(idItem: number, idMedia: number, name: string, overrides: Record<string, unknown> = {}) {
  return {
    id_item: idItem, id_playlist: 1, id_media: idMedia, item_type: 'media',
    id_child_playlist: null, sort_order: idItem, duration_ms: null, zone_index: 0,
    transition_type: 'cut', created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(), media_name: name,
    media_type: 'image', conformance_status: 'ready', has_rules: false,
    ...overrides,
  }
}

const DETAIL = {
  id_playlist: 1, id_org: 1, playlist_name: 'Main Loop', description: null,
  id_template: null, sync_mode: 'wall_clock', total_duration_ms: 57_000,
  sync_ready: true, has_item_rules: false, sync_windowed: false,
  has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1,
  used_as_child: false,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  items: [
    // Vidéo SANS override manuel : la ligne doit montrer la durée native 42 s.
    playlistItem(1, 10, 'clip.mp4', { media_type: 'video', media_duration_ms: 42_000 }),
    playlistItem(2, 11, 'img.png', { duration_ms: 5_000 }),
    playlistItem(3, 12, 'my-webpage', { media_type: 'url_display' }),
  ],
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

test.describe('Playlist & basket totals', () => {
  test('playlist_card_shows_item_count_and_total_duration', async ({ page }) => {
    await mockAuthAndNavigate(page, `${BASE}/login`)
    await page.route(/\/api\/v1\/playlists\/(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify([{
          id_playlist: 1, id_org: 1, playlist_name: 'Main Loop', description: null,
          id_template: null, sync_mode: 'wall_clock', total_duration_ms: 57_000,
          item_count: 3, sync_ready: true, has_draft_changes: false,
          rotation_mode: 'all', items_per_turn: 1, used_as_child: false,
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        }]),
      })
    })
    await page.goto(`${BASE}/playlists`)
    await expect(page.getByText('Main Loop')).toBeVisible()
    await expect(page.getByText('3 items · 57s')).toBeVisible()
  })

  test('editor_shows_native_video_duration_and_header_total', async ({ page }) => {
    await mockAuthAndNavigate(page, `${BASE}/login`)
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL) })
    })
    await page.route('**/api/v1/templates', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.goto(`${BASE}/playlists/1`)
    // Ligne vidéo : durée native affichée (avant ce correctif : « — »).
    const videoRow = page.locator('li, div').filter({ hasText: 'clip.mp4' }).filter({ hasText: 'video' }).first()
    await expect(videoRow.getByText('42s')).toBeVisible()
    // En-tête : « 3 items · 57s » (total serveur).
    await expect(page.getByText('3 items · 57s')).toBeVisible()
  })

  test('audio_basket_card_shows_total_duration', async ({ page }) => {
    await mockAuthAndNavigate(page, `${BASE}/login`)
    await page.route(/\/api\/v1\/audio-baskets$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify([{
          id_basket: 1, id_org: 1, id_node: null, basket_name: 'Pop Nationale',
          basket_type: 'music', basket_scope: 'local', description: null,
          is_mandatory: false, min_ratio: 0, max_ratio: 100, ducking_config: {},
          trigger_mode: 'tracks', trigger_value: 5, shuffle: false, is_active: true,
          item_count: 12, total_duration_ms: 2_160_000, created_by: 1,
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        }]),
      })
    })
    await page.route('**/api/v1/governance/nodes', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.goto(`${BASE}/audio-baskets`)
    await expect(page.getByText('Pop Nationale')).toBeVisible()
    // 12 pistes × 3 min = 36 minutes.
    await expect(page.getByText('12 items · 36m0s')).toBeVisible()
  })
})
