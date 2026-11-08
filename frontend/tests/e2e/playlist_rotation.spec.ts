import { test, expect } from '@playwright/test'

// Playlist rotation (retour beta 2026-07) : section Rotation de l'éditeur,
// ajout d'une sous-playlist (picker), rendu d'un item sub_playlist.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SUB_ITEM = {
  id_item: 2, id_playlist: 1, id_media: null, item_type: 'sub_playlist',
  id_child_playlist: 5, child_name: 'Promos Rotation', child_item_count: 3,
  child_rotation_mode: 'one_sequential', child_items_per_turn: 1,
  sort_order: 1, duration_ms: null, zone_index: 0, transition_type: 'cut',
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  media_name: null, media_type: null, conformance_status: null, has_rules: false,
}

const DETAIL = {
  id_playlist: 1, id_org: 1, playlist_name: 'Main Loop', description: null,
  id_template: null, sync_mode: 'wall_clock', total_duration_ms: 40000,
  sync_ready: true, has_item_rules: false, sync_windowed: false,
  has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1,
  used_as_child: false,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  items: [
    {
      id_item: 1, id_playlist: 1, id_media: 10, item_type: 'media',
      id_child_playlist: null, sort_order: 0, duration_ms: 30000, zone_index: 0,
      transition_type: 'cut', created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(), media_name: 'home.mp4',
      media_type: 'video', conformance_status: 'ready', has_rules: false,
    },
    SUB_ITEM,
  ],
}

const CANDIDATES = [
  { id_playlist: 5, id_org: 1, playlist_name: 'Promos Rotation', description: null, id_template: null, sync_mode: 'wall_clock', total_duration_ms: 30000, sync_ready: true, has_draft_changes: false, rotation_mode: 'one_sequential', items_per_turn: 1, used_as_child: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id_playlist: 7, id_org: 1, playlist_name: 'News Loop', description: null, id_template: null, sync_mode: 'wall_clock', total_duration_ms: 20000, sync_ready: true, has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1, used_as_child: false, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
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

test.describe('Playlist rotation editor', () => {
  test('rotation_section_and_sub_item_row', async ({ page }) => {
    let putBody: Record<string, unknown> | null = null
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      if (route.request().method() === 'PUT') {
        putBody = route.request().postDataJSON()
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...DETAIL, ...putBody }) })
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL) })
    })
    await page.route('**/api/v1/templates', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    // Item sub_playlist : nom de l'enfant + résumé rotation.
    await expect(page.getByText('Promos Rotation')).toBeVisible()
    await expect(page.getByText(/Sub-playlist · 3 items · 1 per loop/)).toBeVisible()

    // Section Rotation : passage en « N per loop — in order » → PUT rotation_mode.
    await expect(page.getByRole('heading', { name: 'Rotation' })).toBeVisible()
    await page.locator('select').filter({ hasText: 'All items (full playback)' }).selectOption('one_sequential')
    await expect.poll(() => putBody).toEqual({ rotation_mode: 'one_sequential' })
  })

  // ③ (retour Ed 2026-07-25) : « Items per loop » ne s'enregistrait qu'au blur. En
  // poussant les FLÈCHES du spinner sans avoir cliqué dans le champ, il n'y a ni focus
  // ni blur — donc aucun appel serveur, alors que la valeur affichée a changé.
  // Le test reproduit exactement ça : on change la valeur SANS focus (setter natif +
  // événement `input`, ce que fait le spinner), puis on attend le PUT débouncé.
  // ⚠️ `fill()` ne prouverait rien : il focus ET blur, donc l'ancien code passait.
  test('items_per_loop_saves_without_focus_or_blur', async ({ page }) => {
    let putBody: Record<string, unknown> | null = null
    const rotating = { ...DETAIL, rotation_mode: 'one_sequential', items_per_turn: 1 }
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      if (route.request().method() === 'PUT') {
        putBody = route.request().postDataJSON()
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rotating) })
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rotating) })
    })
    await page.route('**/api/v1/templates', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    const field = page.locator('label').filter({ hasText: 'Items per loop' }).locator('input[type=number]')
    await expect(field).toBeVisible()
    await field.evaluate((el: HTMLInputElement) => {
      // Le tracker de valeur de React ignore une écriture directe sur `.value` : passer
      // par le setter natif est la seule façon de simuler ce que fait le spinner.
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
      setter.call(el, '3')
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })
    // Aucun blur n'a eu lieu — et pourtant la valeur part.
    await expect.poll(() => putBody, { timeout: 5000 }).toEqual({ items_per_turn: 3 })
  })

  test('add_sub_playlist_via_picker', async ({ page }) => {
    let postBody: Record<string, unknown> | null = null
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL) })
    })
    await page.route(/\/api\/v1\/playlists\/(\?.*)?$/, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CANDIDATES) })
    })
    await page.route('**/api/v1/playlists/1/items', async (route) => {
      postBody = route.request().postDataJSON()
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(SUB_ITEM) })
    })
    await page.route('**/api/v1/templates', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await page.getByRole('button', { name: 'Add a playlist' }).click()
    await expect(page.getByRole('button', { name: /News Loop/ })).toBeVisible()
    await page.getByRole('button', { name: /News Loop/ }).click()
    await expect.poll(() => postBody).toEqual({ id_child_playlist: 7 })
  })
})
