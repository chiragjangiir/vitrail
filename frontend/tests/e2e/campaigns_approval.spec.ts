import { test, expect } from '@playwright/test'

// Retail Media S5 — approbation des créatifs (flag org) : toggle sur /campaigns,
// badge Pending/Rejected + boutons Approve/Reject dans le drawer campagne.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const CAMPAIGN = {
  id_campaign: 1, id_advertiser: 1, campaign_name: 'Brightwell Summer', status: 'live',
  starts_on: '2026-07-01', ends_on: '2026-07-31', daily_hours: null,
  sov_percent: 20, pricing_model: 'sov', price_amount: 1500, price_currency: 'EUR',
  cpm_rate: null, priority: 50, advertiser_name: 'Brightwell', creative_count: 2,
  target_player_count: 3,
  targets: [{ id_target: 1, target_type: 'org', target_id: null }],
}

const CREATIVES = [
  { id_creative: 10, id_media: 100, duration_ms: 15000, weight: 1, sort_order: 0, status: 'active', approval_status: 'approved', media_name: 'spot-ok', media_type: 'video', media_duration_ms: 15000 },
  { id_creative: 11, id_media: 101, duration_ms: 15000, weight: 1, sort_order: 1, status: 'active', approval_status: 'pending', media_name: 'spot-new', media_type: 'video', media_duration_ms: 15000 },
]

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

async function mockCampaignRoutes(page: import('@playwright/test').Page, creativeApproval: boolean) {
  await page.route('**/api/v1/campaigns/', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAMPAIGN]) })
  })
  await page.route('**/api/v1/advertisers/', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Brightwell', id_folder: null }]) })
  })
  await page.route('**/api/v1/sites', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route('**/api/v1/player-groups/', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route('**/api/v1/site-groups/', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route('**/api/v1/players/', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route('**/api/v1/campaigns/inventory**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route('**/api/v1/campaigns/1/creatives', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CREATIVES) })
  })
  await page.route('**/api/v1/campaigns/settings', async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: route.request().postData() ?? '{}' })
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ creative_approval: creativeApproval }) })
    }
  })
}

test.describe('Campaigns creative approval (S5)', () => {
  test('toggle_reflects_org_setting_and_saves', async ({ page }) => {
    await mockCampaignRoutes(page, false)
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    const toggle = page.getByRole('checkbox', { name: /creative approval required/i })
    await expect(toggle).toBeVisible()
    await expect(toggle).not.toBeChecked()

    const putReq = page.waitForRequest((r) => r.url().includes('/campaigns/settings') && r.method() === 'PUT')
    await toggle.click()
    const req = await putReq
    expect(req.postDataJSON()).toEqual({ creative_approval: true })
  })

  test('drawer_shows_pending_badge_and_review_buttons', async ({ page }) => {
    await mockCampaignRoutes(page, true)
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.locator('td', { hasText: 'Brightwell Summer' }).click()
    const drawer = page.getByRole('dialog')
    // Section Créatifs repliée par défaut (creative_count > 0) → l'ouvrir
    await drawer.getByRole('button', { name: /^creatives\b/i }).click()
    await expect(drawer.locator('text=spot-new')).toBeVisible()
    // Créatif pending → badge + boutons de revue ; l'approuvé n'a pas de badge
    await expect(drawer.locator('text=Pending')).toBeVisible()
    const approveBtn = drawer.getByTitle('Approve', { exact: true }).first()
    await expect(approveBtn).toBeVisible()
    await expect(drawer.getByTitle('Reject', { exact: true }).first()).toBeVisible()

    const approveReq = page.waitForRequest((r) => r.url().includes('/campaigns/creatives/11/approve') && r.method() === 'POST')
    await page.route('**/api/v1/campaigns/creatives/11/approve', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...CREATIVES[1], approval_status: 'approved' }) })
    })
    await approveBtn.click()
    await approveReq
  })

  test('creative_picker_search_and_batch_add', async ({ page }) => {
    await mockCampaignRoutes(page, false)
    // Annonceur AVEC dossier → pills scope visibles, défaut = médias de l'annonceur
    await page.route('**/api/v1/advertisers/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Brightwell', id_folder: 5 }]) })
    })
    const served: string[] = []
    await page.route('**/api/v1/media/**', async (route) => {
      const url = new URL(route.request().url())
      served.push(url.search)
      const mediaType = url.searchParams.get('media_type')
      const q = (url.searchParams.get('q') ?? '').toLowerCase()
      const all = [
        { id_media: 100, media_name: 'promo-brightwell-v12', media_type: 'video', duration_ms: 15000, thumbnail_url: null, transcode_status: 'done' },
        { id_media: 101, media_name: 'affiche-soldes', media_type: 'image', duration_ms: null, thumbnail_url: null, transcode_status: 'done' },
      ]
      const out = all.filter((m) => m.media_type === mediaType && (!q || m.media_name.includes(q)))
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(out) })
    })
    await page.route('**/api/v1/campaigns/1/creatives', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ ...CREATIVES[0], id_creative: 12 }) })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CREATIVES) })
      }
    })
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.locator('td', { hasText: 'Brightwell Summer' }).click()
    // Section Créatifs repliée par défaut → l'ouvrir avant d'atteindre le bouton d'ajout
    await page.getByRole('dialog').getByRole('button', { name: /^creatives\b/i }).click()
    await page.getByRole('button', { name: /add creatives/i }).click()

    const picker = page.getByRole('dialog', { name: 'Add creatives' })
    await expect(picker).toBeVisible()
    // Pills scope + sous-arbre annonceur interrogé (id_folder=5&subtree=true)
    await expect(picker.getByRole('button', { name: /advertiser's media/i })).toBeVisible()
    await expect(picker.locator('text=promo-brightwell-v12')).toBeVisible()
    expect(served.some((s) => s.includes('id_folder=5') && s.includes('subtree=true'))).toBe(true)

    // Recherche server-side (déboucée 300 ms) → param q, l'autre média disparaît
    await picker.getByPlaceholder(/search/i).fill('promo')
    await expect.poll(() => served.some((s) => s.includes('q=promo'))).toBe(true)
    await expect(picker.locator('text=promo-brightwell-v12')).toBeVisible()
    await expect(picker.locator('text=affiche-soldes')).toHaveCount(0)

    // Sélection + ajout groupé → POST créatif
    const postReq = page.waitForRequest((r) => r.url().includes('/campaigns/1/creatives') && r.method() === 'POST')
    await picker.locator('text=promo-brightwell-v12').click()
    await expect(picker.locator('text=1 selected')).toBeVisible()
    await picker.getByRole('button', { name: /add \(1\)/i }).click()
    const req = await postReq
    expect(req.postDataJSON()).toEqual({ id_media: 100, duration_ms: null, weight: 1 })
  })

  test('drawer_layout_and_collapsible_sections_with_pills', async ({ page }) => {
    // Lot UI Ed 10/07 : badge seul sur sa ligne · transitions sur une ligne · Rapport
    // sur sa ligne · sections Cible/Créatifs repliables avec pastilles de comptage.
    await mockCampaignRoutes(page, false)
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)
    await page.locator('td', { hasText: 'Brightwell Summer' }).click()
    const drawer = page.getByRole('dialog', { name: 'Brightwell Summer' })

    // Campagne live → Pause/Complete/Cancel visibles, Rapport SOUS la ligne d'actions
    const pauseBtn = drawer.getByRole('button', { name: 'Pause' })
    const reportBtn = drawer.getByRole('button', { name: 'Campaign report' })
    await expect(pauseBtn).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Complete' })).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
    await expect(reportBtn).toBeVisible()
    const pauseBox = await pauseBtn.boundingBox()
    const reportBox = await reportBtn.boundingBox()
    expect(reportBox!.y).toBeGreaterThan(pauseBox!.y + pauseBox!.height - 1)

    // Cible repliée par défaut + pastille = players ciblés résolus (count serveur)
    await expect(drawer.locator('text=3 players')).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Add a target' })).toHaveCount(0)
    await drawer.getByRole('button', { name: /broadcast target/i }).click()
    await expect(drawer.getByRole('button', { name: 'Add a target' })).toBeVisible()

    // Créatifs repliés (creative_count > 0) + pastille = nb de contenus
    const creativesToggle = drawer.getByRole('button', { name: /^creatives\b/i })
    await expect(creativesToggle).toBeVisible()
    await expect(drawer.locator('text=spot-ok')).toHaveCount(0)
    await creativesToggle.click()
    await expect(drawer.locator('text=spot-ok')).toBeVisible()
  })

  test('list_row_delete_icon_without_opening_drawer', async ({ page }) => {
    await mockCampaignRoutes(page, false)
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)
    page.on('dialog', (d) => d.accept())
    await page.route('**/api/v1/campaigns/1', async (route) => {
      if (route.request().method() === 'DELETE') {
        await route.fulfill({ status: 204, body: '' })
      } else {
        await route.continue()
      }
    })
    const delReq = page.waitForRequest((r) => /\/api\/v1\/campaigns\/1$/.test(r.url()) && r.method() === 'DELETE')
    await page.getByRole('row', { name: /Brightwell Summer/ }).getByTitle('Delete', { exact: true }).click()
    await delReq
    // stopPropagation : le clic poubelle n'ouvre pas le drawer (le composant Drawer reste
    // monté fermé dans le DOM → on vérifie qu'il n'a PAS pris le titre de la campagne)
    await expect(page.getByRole('dialog', { name: 'Brightwell Summer' })).toHaveCount(0)
  })
})
