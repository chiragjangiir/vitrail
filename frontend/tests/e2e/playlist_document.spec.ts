import { test, expect } from '@playwright/test'

// Documents multipages (§3.2) : ligne d'item document dans l'éditeur de playlist —
// durée PAR PAGE, champ de sélection de pages ("2-5,8"), total calculé.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const DOC_ITEM = {
  id_item: 3, id_playlist: 1, id_media: 20, item_type: 'media',
  id_child_playlist: null, sort_order: 0, duration_ms: null, zone_index: 0,
  transition_type: 'cut', created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(), media_name: 'menu.pdf',
  media_type: 'document', conformance_status: null, has_rules: false,
  doc_pages: null, media_page_count: 6,
}

const DETAIL = {
  id_playlist: 1, id_org: 1, playlist_name: 'Doc Loop', description: null,
  id_template: null, sync_mode: 'wall_clock', total_duration_ms: 60000,
  sync_ready: true, has_item_rules: false, sync_windowed: false,
  has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1,
  used_as_child: false,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  items: [DOC_ITEM],
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

test.describe('Playlist document item', () => {
  test('document_row_shows_per_page_pages_and_total', async ({ page }) => {
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL) })
    })
    await page.route('**/api/v1/templates', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await expect(page.getByText('menu.pdf')).toBeVisible()
    // Durée par page + total : 6 pages × 10 s par défaut.
    await expect(page.getByText('/page')).toBeVisible()
    await expect(page.getByText(/6 pages · 1m0s total/)).toBeVisible()
    // Champ de sélection de pages (placeholder « all ») + bulle d'aide au focus.
    const pagesField = page.getByPlaceholder('all')
    await expect(pagesField).toBeVisible()
    await pagesField.focus()
    await expect(page.getByText(/Pages to play — empty = whole document/)).toBeVisible()
    await pagesField.blur()
    await expect(page.getByText(/Pages to play — empty = whole document/)).toBeHidden()
  })

  test('set_doc_pages_patches_item', async ({ page }) => {
    let patchBody: Record<string, unknown> | null = null
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL) })
    })
    await page.route('**/api/v1/playlists/1/items/3', async (route) => {
      patchBody = route.request().postDataJSON()
      const updated = { ...DOC_ITEM, doc_pages: (patchBody as { doc_pages?: string }).doc_pages ?? null }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([updated]) })
    })
    await page.route('**/api/v1/templates', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    const field = page.getByPlaceholder('all')
    await field.fill('2-4')
    await field.press('Enter')
    await expect.poll(() => patchBody).toEqual({ doc_pages: '2-4' })
  })
})

// ── Navigation tactile des documents (migr 0129, décisions d'Ed 2026-08-14) ────
//
// Ce qui est affirmé ici, c'est le RÉSULTAT : ce que l'écran ENVOIE au serveur. Vérifier la
// présence d'une case ne dirait pas si elle est câblée sur le bon champ.

test.describe('Playlist document — touch navigation', () => {
  const VIDEO_ITEM = {
    ...DOC_ITEM, id_item: 4, id_media: 21, media_name: 'clip.mp4',
    media_type: 'video', doc_pages: null, media_page_count: null,
  }

  async function mount(page: import('@playwright/test').Page, item: object,
                       onPatch?: (b: Record<string, unknown>) => void) {
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ...DETAIL, items: [item] }),
      })
    })
    await page.route('**/api/v1/playlists/1/items/*', async (route) => {
      const body = route.request().postDataJSON()
      if (onPatch) onPatch(body)
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify([{ ...item, ...body }]),
      })
    })
    await page.route('**/api/v1/templates', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)
  }

  test('touch_nav_checkbox_patches_item', async ({ page }) => {
    let patchBody: Record<string, unknown> | null = null
    await mount(page, DOC_ITEM, (b) => { patchBody = b })

    const box = page.getByLabel('Touch navigation')
    await expect(box).toBeVisible()
    await expect(box).not.toBeChecked()   // inerte par défaut : le parc ne change pas
    // La mention doit être là : sans elle, un opérateur coche, ne voit rien sur une box TV
    // et conclut à une panne alors que l'écran n'est simplement pas tactile.
    await expect(page.getByText(/no effect on a non-touch screen/)).toBeVisible()

    // ⚠️ `click()` et non `check()` : la case est CONTRÔLÉE par la donnée serveur, que ce mock
    // ne fait volontairement pas avancer. `check()` échouerait sur l'état visuel alors que le
    // PATCH est bien parti — et c'est le PATCH qui est la vraie affirmation ici.
    await box.click()
    await expect.poll(() => patchBody).toEqual({ touch_navigation: true })
  })

  test('touch_nav_absent_on_a_non_document_item', async ({ page }) => {
    await mount(page, VIDEO_ITEM)
    await expect(page.getByText('clip.mp4')).toBeVisible()
    // L'option n'a de sens que sur un contenu qui a des pages.
    await expect(page.getByLabel('Touch navigation')).toHaveCount(0)
  })

  test('touch_nav_resume_delay_appears_only_when_enabled', async ({ page }) => {
    let patchBody: Record<string, unknown> | null = null
    await mount(page, { ...DOC_ITEM, touch_navigation: true }, (b) => { patchBody = b })

    // Le délai de reprise n'a de sens que si le feuilletage est autorisé.
    const delay = page.getByPlaceholder('60')
    await expect(delay).toBeVisible()
    await delay.fill('30')
    await delay.press('Enter')
    await expect.poll(() => patchBody).toEqual({ touch_resume_after_s: 30 })
  })

  test('touch_nav_resume_delay_hidden_when_disabled', async ({ page }) => {
    await mount(page, DOC_ITEM)   // touch_navigation absent = faux
    await expect(page.getByPlaceholder('60')).toHaveCount(0)
  })
})
