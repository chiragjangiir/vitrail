import { test, expect } from '@playwright/test'

// Médiathèque — badge de transcodage après upload + recherche/import stock.
// Réécrit 2026-07-12 : la page est passée en pagination server-side (`/media/?limit=`)
// + requêtes stats/folders/recent → mock consolidé par pathname (l'ancien mock
// `**/api/v1/media` exact ne matchait plus rien, spec rouge depuis).

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

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

// Un seul handler pour tout /media* : liste paginée, stats, folders, upload, stock.
function mockMediaRoutes(page: import('@playwright/test').Page, opts: {
  list: unknown[]
  stock?: unknown[]
}) {
  return page.route('**/api/v1/media**', async (route) => {
    const url = new URL(route.request().url())
    const p = url.pathname
    const method = route.request().method()
    const json = (body: unknown, status = 200) => route.fulfill({
      status, contentType: 'application/json', body: JSON.stringify(body) })
    if (p.endsWith('/media/stats')) {
      return json({ total: opts.list.length, by_type: { video: opts.list.length } })
    }
    if (p.endsWith('/media/folders')) return json([])
    if (p.endsWith('/media/stock/search')) return json(opts.stock ?? [])
    if (p.endsWith('/media/stock/import') && method === 'POST') {
      return json({ id_media: 99, media_name: 'Mountain', media_type: 'image', mime_type: 'image/jpeg', file_size_bytes: null, thumbnail_url: null, source: 'stock_unsplash', attribution_text: 'Photo by John Doe on Unsplash', transcode_status: 'done', created_at: new Date().toISOString() })
    }
    if (p.endsWith('/media/upload') && method === 'POST') {
      return json(opts.list[0] ?? {})
    }
    if (p.endsWith('/media/') && method === 'GET') return json(opts.list)
    return json([])
  })
}

test.describe('Media library', () => {
  test('media_upload_shows_transcoding_badge', async ({ page }) => {
    const uploadedMedia = {
      id_media: 42, media_name: 'test-video', media_type: 'video',
      mime_type: 'video/mp4', file_size_bytes: 5_000_000, thumbnail_url: null,
      source: 'upload', attribution_text: null, transcode_status: 'processing',
      created_at: new Date().toISOString(),
    }
    await mockMediaRoutes(page, { list: [uploadedMedia] })
    await mockAuthAndNavigate(page, `${BASE}/media`)

    // Le média « processing » de la liste porte le badge de transcodage
    await expect(page.locator('text=test-video').first()).toBeVisible()
    await expect(page.locator('text=Processing').first()).toBeVisible()
  })

  test('media_stock_search_and_import_flow', async ({ page }) => {
    const stockResults = [{
      provider: 'unsplash', provider_id: 'abc123', title: 'Mountain',
      description: null, preview_url: 'https://images.unsplash.com/photo-abc?w=400',
      full_url: 'https://images.unsplash.com/photo-abc', attribution_text: 'Photo by John Doe on Unsplash',
      photographer: 'John Doe', photographer_url: null, width: 3000, height: 2000,
    }]
    await mockMediaRoutes(page, { list: [], stock: stockResults })
    await mockAuthAndNavigate(page, `${BASE}/media`)

    await page.getByRole('button', { name: /free photos/i }).click()
    const searchInput = page.getByPlaceholder(/search photos/i)
    await searchInput.fill('mountain')
    await searchInput.press('Enter')

    await expect(page.locator('text=John Doe')).toBeVisible()
    await page.getByRole('button', { name: /import/i }).first().click()
    await expect(page).toHaveURL(/\/media/)
  })
})
