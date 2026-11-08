import { test, expect } from '@playwright/test'

// S7 C2 — self-service annonceur : création de brouillon (sites + SOV/Exclusif +
// devis agrégé), upload de créatifs, soumission §21 depuis /portal.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const ADV_USER = { id_user: 9, id_org: 1, email: 'buyer@brightwell.com', full_name: 'Jane Buyer', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, id_advertiser: 1, last_login_at: null, created_at: new Date().toISOString() }
const BRANDING = { org_name: 'Acme Retail', advertiser_name: 'Brightwell', primary_color: '#4875B4', report_title: 'Acme Media Network', logo_url: null }
const SITES = [
  { id_site: 1, site_name: 'Lille Centre', latitude: 50.63, longitude: 3.06 },
  { id_site: 2, site_name: 'Paris Sud', latitude: null, longitude: null },
]
const DRAFT = {
  id_campaign: 42, id_advertiser: 1, campaign_name: 'Promo V16', status: 'draft',
  starts_on: '2026-08-01', ends_on: '2026-08-15', daily_hours: null,
  sov_percent: 15, pricing_model: 'sov', price_amount: null, price_currency: 'EUR',
  cpm_rate: null, priority: 50, advertiser_name: 'Brightwell', creative_count: 0,
  target_player_count: 2, approval_request: null,
  targets: [{ id_target: 1, target_type: 'site', target_id: 1 }],
}

async function mockAuth(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  await page.evaluate((u) => {
    const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI5Iiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfQURWRVJUSVNFUiJdLCJsb2NhbGUiOiJlbiIsInR5cGUiOiJhY2Nlc3MiLCJleHAiOjk5OTk5OTk5OTl9.signature'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: mockToken, refreshToken: 'mock_refresh', roles: ['CMS_ADVERTISER'] },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', mockToken)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, ADV_USER)
  await page.route('**/api/v1/users/me', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ADV_USER) }))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }) }))
  await page.route('**/api/v1/portal/branding', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BRANDING) }))
}

test.describe('Portal self-service (S7 C2)', () => {
  test('create_draft_with_quote_then_upload_and_submit', async ({ page }) => {
    await mockAuth(page)
    await page.route('**/api/v1/campaigns/', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await page.route('**/api/v1/portal/sites**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) }))
    await page.route('**/api/v1/portal/occupancy-check', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ availability: 'ok', price: { estimated_price: 120, priced_players: 2, unpriced_players: 0, days: 15 } }),
    }))
    let creatives: unknown[] = []
    await page.route('**/api/v1/portal/campaigns', (r) => {
      if (r.request().method() === 'POST') {
        return r.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(DRAFT) })
      }
      return r.fulfill({ status: 404, body: '{}' })
    })
    await page.route('**/api/v1/portal/campaigns/42/creatives', (r) => {
      if (r.request().method() === 'POST') {
        creatives = [{ id_creative: 7, id_media: 70, media_name: 'v16.mp4', media_type: 'video', duration_ms: 20000, approval_status: 'pending' }]
        return r.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(creatives[0]) })
      }
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(creatives) })
    })
    const submitted = page.waitForRequest((r) => r.url().includes('/portal/campaigns/42/submit') && r.method() === 'POST')
    await page.route('**/api/v1/portal/campaigns/42/submit', (r) => r.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id_request: 5, status: 'pending_review' }) }))

    await page.goto(`${BASE}/portal`)
    await page.getByRole('button', { name: /new campaign/i }).click()
    await expect(page).toHaveURL(/\/portal\/campaigns\/new/)

    await page.getByLabel(/campaign name/i).fill('Promo V16')
    await page.getByLabel(/start date/i).fill('2026-08-01')
    await page.getByLabel(/end date/i).fill('2026-08-15')
    // Sélection d'un site via la LISTE (le site sans coords reste cochable)
    await page.getByRole('button', { name: 'Paris Sud' }).click()

    // Devis agrégé (déclenché automatiquement, réponse strippée)
    await expect(page.locator('text=Inventory available')).toBeVisible()
    await expect(page.locator('text=Indicative price: 120 € (15 d)')).toBeVisible()

    // Création du brouillon → section créatifs
    await page.getByRole('button', { name: /create draft/i }).click()
    await expect(page.locator('text=Your creatives')).toBeVisible()

    // Upload (input caché) → créatif listé pending
    const submitBtn = page.getByRole('button', { name: /submit for validation/i })
    await expect(submitBtn).toBeDisabled()
    await page.locator('input[type=file]').setInputFiles({
      name: 'v16.mp4', mimeType: 'video/mp4', buffer: Buffer.from('0000'),
    })
    await expect(page.locator('text=v16.mp4')).toBeVisible()
    await expect(page.locator('text=Pending').first()).toBeVisible()

    // Soumission → retour à l'accueil portail
    await submitBtn.click()
    await submitted
    await expect(page).toHaveURL(/\/portal$/)
  })

  test('per_screen_selection_builds_mixed_targets', async ({ page }) => {
    // Sélection PAR ÉCRAN (0089, réglage org ON) : déplier un site, cocher un écran
    // → cible player (site partiel, pastille n/total), POST avec player_ids.
    await mockAuth(page)
    await page.route('**/api/v1/campaigns/', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await page.route('**/api/v1/portal/site-lists', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await page.route('**/api/v1/portal/limits', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ max_creatives: 20, creative_max_mb: 1024, creative_max_duration_s: 30, player_selection: true }),
    }))
    await page.route('**/api/v1/portal/sites**', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{
        id_site: 1, site_name: 'Lille Centre', latitude: null, longitude: null,
        screen_count: 2, excluded: false,
        players: [{ id_player: 11, player_name: 'Entrance' }, { id_player: 12, player_name: 'Checkout' }],
      }]),
    }))
    await page.route('**/api/v1/portal/occupancy-check', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ availability: 'ok', price: { estimated_price: 42, priced_players: 1, unpriced_players: 0, days: 15 } }),
    }))
    let postBody: Record<string, unknown> | null = null
    await page.route('**/api/v1/portal/campaigns', (r) => {
      if (r.request().method() === 'POST') {
        postBody = r.request().postDataJSON()
        return r.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ ...DRAFT, targets: [{ id_target: 1, target_type: 'player', target_id: 11 }] }) })
      }
      return r.fulfill({ status: 404, body: '{}' })
    })
    await page.route('**/api/v1/portal/campaigns/42/creatives', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

    await page.goto(`${BASE}/portal/campaigns/new`)
    await page.getByLabel(/campaign name/i).fill('Entrance only')
    await page.getByLabel(/start date/i).fill('2026-08-01')
    await page.getByLabel(/end date/i).fill('2026-08-15')

    // Déplier le site → cocher UN écran → pastille 1/2 (site partiel)
    await page.getByTitle(/pick screens/i).click()
    await page.getByLabel('Entrance').check()
    await expect(page.getByRole('button', { name: /Lille Centre · 1\/2/ })).toBeVisible()
    // Devis déclenché sur la sélection par écran seule (aucun site entier)
    await expect(page.locator('text=Inventory available')).toBeVisible()

    await page.getByRole('button', { name: /create draft/i }).click()
    await expect.poll(() => postBody).not.toBeNull()
    expect(postBody).toMatchObject({ site_ids: [], player_ids: [11] })
  })

  test('sov_achievable_banner_and_suggestion', async ({ page }) => {
    // SOV réalisable (anti-martèlement) : l'agrégat strippé achievable_sov_pct
    // déclenche le bandeau quand la SOV demandée le dépasse ; « Use 6% » l'applique.
    await mockAuth(page)
    await page.route('**/api/v1/campaigns/', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await page.route('**/api/v1/portal/sites**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) }))
    await page.route('**/api/v1/portal/occupancy-check', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ availability: 'ok', price: null, achievable_sov_pct: 6.2 }),
    }))

    await page.goto(`${BASE}/portal/campaigns/new`)
    await page.getByLabel(/campaign name/i).fill('Trop gourmande')
    await page.getByLabel(/start date/i).fill('2026-08-01')
    await page.getByLabel(/end date/i).fill('2026-08-15')
    await page.getByRole('button', { name: 'Paris Sud' }).click()

    // SOV 10 (défaut) > 6.2 → bandeau + suggestion
    await expect(page.locator('text=exceeds what the targeted screens')).toBeVisible()
    await page.getByRole('button', { name: /use 6%/i }).click()
    await expect(page.getByLabel(/share of voice/i)).toHaveValue('6')
    // 6 ≤ 6.2 → le bandeau disparaît
    await expect(page.locator('text=exceeds what the targeted screens')).toBeHidden()
  })

  test('changes_requested_shows_feedback_and_resubmit', async ({ page }) => {
    await mockAuth(page)
    const campaignWithRequest = {
      ...DRAFT,
      approval_request: { id_request: 5, status: 'changes_requested' },
    }
    await page.route('**/api/v1/campaigns/', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([campaignWithRequest]) }))
    await page.route('**/api/v1/portal/sites**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) }))
    await page.route('**/api/v1/portal/occupancy-check', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ availability: 'ok', price: null }) }))
    await page.route('**/api/v1/portal/campaigns/42/creatives', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{ id_creative: 7, id_media: 70, media_name: 'v16.mp4', media_type: 'video', duration_ms: 20000, approval_status: 'pending' }]),
    }))
    await page.route('**/api/v1/approvals/5', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        id_request: 5, status: 'changes_requested',
        comments: [{ id_comment: 1, comment_text: 'Logo flou sur le visuel', action: 'changes_requested', created_at: '2026-07-11T10:00:00Z', user_name: 'Admin' }],
      }),
    }))
    const resubmitted = page.waitForRequest((r) => r.url().includes('/approvals/5/resubmit') && r.method() === 'POST')
    await page.route('**/api/v1/approvals/5/resubmit', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id_request: 5, status: 'pending_review' }) }))

    // La carte du brouillon porte le badge « Changes requested » et mène à l'édition
    await page.goto(`${BASE}/portal`)
    await expect(page.locator('text=Changes requested')).toBeVisible()
    await page.locator('text=Promo V16').click()
    await expect(page).toHaveURL(/\/portal\/campaigns\/42\/edit/)

    // Motif du retailer affiché + resoumission
    await expect(page.locator('text=Logo flou sur le visuel')).toBeVisible()
    await page.getByRole('button', { name: /resubmit/i }).click()
    await resubmitted
  })
})
