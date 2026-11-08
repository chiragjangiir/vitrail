import { test, expect } from '@playwright/test'

// S6 Retail Media — import de campagne par fichier JSON : upload → dry-run
// (aperçu annonceur/cibles/créatifs) → confirmation → POST /campaigns/import.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const ORDER = {
  version: 1,
  advertiser: { name: 'ImportCo' },
  campaign: { name: 'Import Été', starts_on: '2026-08-01', ends_on: '2026-08-31', sov_percent: 10 },
  targets: [{ type: 'site_group', name: 'Sud-Ouest' }],
  creatives: [{ url: 'https://cdn.importco.com/spot-15s.mp4', weight: 2 }],
}

const DRY_OK = {
  ok: true, errors: [],
  advertiser_name: 'ImportCo', advertiser_matched: false,
  targets: [{ type: 'site_group', name: 'Sud-Ouest', target_id: 1, error: null }],
  target_player_count: 4,
  creatives: [{ url: ORDER.creatives[0].url, media_name: 'spot-15s.mp4', media_type: 'video', error: null }],
  occupancy: { blocked: false, warning: true, max_projected_pct: 85, players: [] },
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

test.describe('Campaign import (S6)', () => {
  test('upload_dry_run_preview_then_import', async ({ page }) => {
    for (const [pattern, body] of [
      ['**/api/v1/campaigns/', '[]'],
      ['**/api/v1/advertisers/', '[]'],
      ['**/api/v1/sites', '[]'],
      ['**/api/v1/player-groups/', '[]'],
      ['**/api/v1/site-groups/', '[]'],
      ['**/api/v1/players/', '[]'],
      ['**/api/v1/campaigns/inventory**', '[]'],
      ['**/api/v1/campaigns/settings', JSON.stringify({ creative_approval: false })],
    ] as const) {
      await page.route(pattern, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body })
      })
    }
    let dryBody: unknown = null
    await page.route('**/api/v1/campaigns/import/dry-run', async (route) => {
      dryBody = route.request().postDataJSON()
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DRY_OK) })
    })
    let importBody: unknown = null
    await page.route('**/api/v1/campaigns/import', async (route) => {
      importBody = route.request().postDataJSON()
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id_campaign: 42 }) })
    })
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.getByRole('button', { name: 'Import (JSON)' }).click()
    const drawer = page.getByRole('dialog', { name: 'Import (JSON)' })
    await expect(drawer).toBeVisible()

    await drawer.locator('input[type="file"]').setInputFiles({
      name: 'order.json', mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(ORDER)),
    })

    // Le dry-run reçoit l'ordre tel quel + aperçu rendu
    await expect(drawer.getByText('ImportCo')).toBeVisible()
    expect(dryBody).toEqual(ORDER)
    await expect(drawer.getByText('will be created')).toBeVisible()
    await expect(drawer.getByText('Sud-Ouest')).toBeVisible()
    await expect(drawer.getByText('spot-15s.mp4')).toBeVisible()
    await expect(drawer.getByText('4 players')).toBeVisible()
    // Warning occupation 85 % affiché, import non bloqué
    await expect(drawer.getByText(/85%/)).toBeVisible()

    await drawer.getByRole('button', { name: 'Import', exact: true }).click()
    await expect.poll(() => importBody).toEqual(ORDER)
    // Le Drawer fermé reste monté dans le DOM (translate-x-full) → on vérifie que
    // son état a été RESET (aperçu démonté), pas sa « visibilité ».
    await expect(drawer.getByText('ImportCo')).toHaveCount(0)
  })

  test('invalid_target_disables_import', async ({ page }) => {
    for (const [pattern, body] of [
      ['**/api/v1/campaigns/', '[]'],
      ['**/api/v1/advertisers/', '[]'],
      ['**/api/v1/sites', '[]'],
      ['**/api/v1/player-groups/', '[]'],
      ['**/api/v1/site-groups/', '[]'],
      ['**/api/v1/players/', '[]'],
      ['**/api/v1/campaigns/inventory**', '[]'],
      ['**/api/v1/campaigns/settings', JSON.stringify({ creative_approval: false })],
    ] as const) {
      await page.route(pattern, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body })
      })
    }
    await page.route('**/api/v1/campaigns/import/dry-run', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...DRY_OK, ok: false, errors: ['site_group « Nulle-Part » introuvable'],
          targets: [{ type: 'site_group', name: 'Nulle-Part', target_id: null, error: 'site_group « Nulle-Part » introuvable' }],
          occupancy: null, target_player_count: 0,
        }),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.getByRole('button', { name: 'Import (JSON)' }).click()
    const drawer = page.getByRole('dialog', { name: 'Import (JSON)' })
    await drawer.locator('input[type="file"]').setInputFiles({
      name: 'order.json', mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(ORDER)),
    })
    await expect(drawer.getByText('introuvable').first()).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Import', exact: true })).toBeDisabled()
  })
})
