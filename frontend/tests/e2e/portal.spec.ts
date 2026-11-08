import { test, expect } from '@playwright/test'

// S7 B2 — portail annonceur : layout white-label + liste de SES campagnes +
// rapport (CampaignReportView), redirect des comptes annonceur hors du CMS,
// section « Accès portail » du drawer annonceur (invite → mot de passe une fois).

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const ADV_USER = { id_user: 9, id_org: 1, email: 'buyer@brightwell.com', full_name: 'Jane Buyer', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, id_advertiser: 1, last_login_at: null, created_at: new Date().toISOString() }
const ADMIN_USER = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const BRANDING = { org_name: 'Acme Retail', advertiser_name: 'Brightwell', primary_color: '#4875B4', report_title: 'Acme Media Network', logo_url: null }

const CAMPAIGN = {
  id_campaign: 1, id_advertiser: 1, campaign_name: 'Brightwell Summer', status: 'live',
  starts_on: '2026-07-01', ends_on: '2026-07-31', daily_hours: null,
  sov_percent: 20, pricing_model: 'sov', price_amount: 1500, price_currency: 'EUR',
  cpm_rate: null, priority: 50, advertiser_name: 'Brightwell', creative_count: 2,
  target_player_count: 3, targets: [],
}

const AUDIO_CAMPAIGN = {
  ...{ id_campaign: 2, id_advertiser: 1, campaign_name: 'Brightwell Audio', status: 'live',
    starts_on: '2026-07-01', ends_on: '2026-07-31', daily_hours: null,
    sov_percent: 10, pricing_model: 'flat', price_amount: null, price_currency: 'EUR',
    cpm_rate: null, priority: 50, advertiser_name: 'Brightwell', creative_count: 1,
    target_player_count: 2, targets: [], campaign_kind: 'audio', spots_per_hour: 6 },
}

const OVERVIEW = {
  campaigns: { total: 2, active: 2, visual: 1, audio: 1 },
  players: { total: 5, online: 3, offline: 1, warning: 1, maintenance: 0 },
  proof_of_play_24h: 128,
  sites: [{ id_site: 1, site_name: 'Store A', country: 'FR', site_number: 'A1',
    latitude: 48.85, longitude: 2.35, players_total: 3, players_online: 3,
    players_warning: 0, players_offline: 0, players_maintenance: 0 }],
  activity: [{ id: 1, action: 'publish', resource_type: 'campaign', resource_id: '1',
    user_name: 'Jane Buyer', created_at: new Date().toISOString() }],
}

const REPORT = {
  campaign: { id_campaign: 1, campaign_name: 'Brightwell Summer', advertiser_name: 'Brightwell', status: 'live', starts_on: '2026-07-01', ends_on: '2026-07-31', sov_percent: 20 },
  period: { from: '2026-07-01', to: '2026-07-31' },
  totals: { plays: 232, signed_plays: 232, airtime_seconds: 6264, players: 6, days_active: 9 },
  sov: { sold_pct: 20, served_pct: 19.8 },
  amount: { model: 'sov', amount: 1500, currency: 'EUR', cpm_indicative: null },
  per_player: [], per_day: [], per_creative: [],
}

async function mockAuth(page: import('@playwright/test').Page, user: Record<string, unknown>, roles: string[]) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(([u, r]) => {
    const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: mockToken, refreshToken: 'mock_refresh', roles: r },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', mockToken)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, [user, roles] as const)
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user) })
  })
  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }),
    })
  })
}

test.describe('Advertiser portal (S7 B2)', () => {
  test('portal_lists_campaigns_and_opens_report', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 }) // portail conçu FHD minimum
    await mockAuth(page, ADV_USER, ['CMS_ADVERTISER'])
    await page.route('**/api/v1/portal/branding', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BRANDING) })
    })
    await page.route('**/api/v1/campaigns/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAMPAIGN]) })
    })
    await page.route('**/api/v1/portal/overview', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) })
    })
    await page.route('**/api/v1/campaigns/1/report', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(REPORT) })
    })
    await page.goto(`${BASE}/portal`)

    // Chrome white-label : titre = NOM DE L'ORG (retour Ed #1 — report_title est
    // réservé aux rapports §24.3, il ne titre plus le portail) + chip annonceur
    await expect(page.locator('text=Acme Retail')).toBeVisible()
    await expect(page.locator('text=Acme Media Network')).toHaveCount(0)
    await expect(page.locator('text=Brightwell').first()).toBeVisible()
    await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
    // Pas de sidebar CMS
    await expect(page.locator('text=Dashboard')).toHaveCount(0)

    // Campagne listée (colonne visuelle) → clic sur la carte ouvre le rapport
    await expect(page.locator('text=Brightwell Summer')).toBeVisible()
    await page.locator('text=Brightwell Summer').click()
    await expect(page).toHaveURL(/\/portal\/campaigns\/1/)
    await expect(page.locator('text=Brightwell Summer').first()).toBeVisible()
    await expect(page.getByRole('button', { name: /pdf/i })).toBeVisible()
    // Un chiffre du rapport (232 passages) rendu par CampaignReportView
    await expect(page.locator('text=232').first()).toBeVisible()
  })

  test('portal_home_shows_kpis_and_two_campaign_columns', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await mockAuth(page, ADV_USER, ['CMS_ADVERTISER'])
    await page.route('**/api/v1/portal/branding', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BRANDING) })
    })
    await page.route('**/api/v1/portal/overview', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) })
    })
    await page.route('**/api/v1/campaigns/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAMPAIGN, AUDIO_CAMPAIGN]) })
    })
    await page.goto(`${BASE}/portal`)

    // KPI orientés annonceur (compteurs de l'overview)
    await expect(page.locator('text=Campaigns').first()).toBeVisible()
    await expect(page.locator('text=128')).toBeVisible()             // Proof of Play 24 h
    await expect(page.locator('text=Fleet status')).toBeVisible()
    await expect(page.locator('text=Recent activity')).toBeVisible()

    // Campagnes en 2 colonnes : visuelle à gauche, audio à droite
    await expect(page.locator('text=Visual campaigns')).toBeVisible()
    await expect(page.locator('text=Audio campaigns')).toBeVisible()
    await expect(page.locator('text=Brightwell Summer')).toBeVisible()
    await expect(page.locator('text=Brightwell Audio')).toBeVisible()
    await expect(page.locator('text=6 spots/h')).toBeVisible()
  })

  test('portal_new_campaign_form_two_columns', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await mockAuth(page, ADV_USER, ['CMS_ADVERTISER'])
    await page.route('**/api/v1/portal/branding', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BRANDING) })
    })
    await page.route('**/api/v1/portal/sites**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(
        [{ id_site: 1, site_name: 'Store A', latitude: 48.85, longitude: 2.35, country: 'FR', site_number: 'A1', screen_count: 2, excluded: false, players: [] }]) })
    })
    await page.route('**/api/v1/portal/site-lists', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.route('**/api/v1/portal/limits', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(
        { max_creatives: 20, creative_max_mb: 512, creative_max_duration_s: null, player_selection: false, allowed_kinds: ['visual', 'audio'] }) })
    })
    await page.goto(`${BASE}/portal/campaigns/new`)

    // Formulaire présent avec le sélecteur de type (les 2 droits) + sites (colonne droite)
    await expect(page.getByRole('button', { name: 'Visual', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Audio (spots)' })).toBeVisible()
    await expect(page.getByRole('button', { name: /Store A/ })).toBeVisible()
  })

  test('portal_language_selector_patches_locale', async ({ page }) => {
    await mockAuth(page, ADV_USER, ['CMS_ADVERTISER'])
    await page.route('**/api/v1/portal/branding', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BRANDING) })
    })
    await page.route('**/api/v1/campaigns/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    let patched: unknown = null
    await page.route('**/api/v1/users/me', async (route) => {
      if (route.request().method() === 'PATCH') {
        patched = route.request().postDataJSON()
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...ADV_USER, locale: 'fr' }) })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ADV_USER) })
      }
    })
    await page.goto(`${BASE}/portal`)

    const select = page.getByLabel('Language')
    await expect(select).toBeVisible()
    // Les 5 locales proposées
    await expect(select.locator('option')).toHaveCount(5)
    await select.selectOption('fr')
    await expect.poll(() => patched).toEqual({ locale: 'fr' })
  })

  test('advertiser_user_is_redirected_out_of_cms', async ({ page }) => {
    await mockAuth(page, ADV_USER, ['CMS_ADVERTISER'])
    await page.route('**/api/v1/portal/branding', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BRANDING) })
    })
    await page.route('**/api/v1/campaigns/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.goto(`${BASE}/dashboard`)
    await expect(page).toHaveURL(/\/portal/)
  })

  test('advertiser_drawer_portal_access_invite_and_revoke', async ({ page }) => {
    await mockAuth(page, ADMIN_USER, ['CMS_ORG_ADMIN'])
    await page.route('**/api/v1/advertisers/', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Brightwell', contact_name: null, contact_email: null, notes: null, is_active: true, campaign_count: 1, created_at: new Date().toISOString() }]),
      })
    })
    let invited = false
    await page.route('**/api/v1/advertisers/1/users', async (route) => {
      if (route.request().method() === 'POST') {
        invited = true
        await route.fulfill({
          status: 201, contentType: 'application/json',
          body: JSON.stringify({
            user: { id_user: 9, email: 'buyer@brightwell.com', full_name: 'Jane', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
            initial_password: 'sf-Temp-123',
          }),
        })
      } else {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: invited
            ? JSON.stringify([{ id_user: 9, email: 'buyer@brightwell.com', full_name: 'Jane', is_active: true, last_login_at: null, created_at: new Date().toISOString() }])
            : '[]',
        })
      }
    })
    await page.goto(`${BASE}/campaigns/advertisers`)

    await page.locator('text=Brightwell').first().click()
    const drawer = page.getByRole('dialog', { name: 'Brightwell' })
    await expect(drawer.locator('text=Portal access')).toBeVisible()
    await expect(drawer.locator('text=No portal account yet.')).toBeVisible()

    // Invitation → mot de passe affiché UNE fois
    await drawer.getByPlaceholder('buyer@brand.com').fill('buyer@brightwell.com')
    await drawer.getByRole('button', { name: 'Invite' }).click()
    await expect(drawer.locator('text=sf-Temp-123')).toBeVisible()
    await expect(drawer.locator('text=buyer@brightwell.com · sf-Temp-123')).toBeVisible()

    // Compte listé + bouton de révocation → DELETE
    page.on('dialog', (d) => d.accept())
    const delReq = page.waitForRequest((r) => r.url().includes('/advertisers/1/users/9') && r.method() === 'DELETE')
    await page.route('**/api/v1/advertisers/1/users/9', async (route) => {
      await route.fulfill({ status: 204, body: '' })
    })
    await drawer.getByTitle('Revoke access').click()
    await delReq
  })

  // Suppression d'un brouillon par l'annonceur (demande d'Ed, 2026-07-31) — le portail
  // n'avait aucune route de suppression : un brouillon créé par erreur obligeait à
  // écrire au retailer.
  test('portal_deletes_own_draft_only', async ({ page }) => {
    const DRAFT = { ...CAMPAIGN, id_campaign: 3, campaign_name: 'Brouillon Été', status: 'draft' }
    const SUBMITTED = {
      ...CAMPAIGN, id_campaign: 4, campaign_name: 'Soumise', status: 'draft',
      approval_request: { id_request: 7, status: 'pending_review' },
    }
    await page.setViewportSize({ width: 1920, height: 1080 })
    await mockAuth(page, ADV_USER, ['CMS_ADVERTISER'])
    await page.route('**/api/v1/portal/branding', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BRANDING) }))
    await page.route('**/api/v1/portal/overview', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OVERVIEW) }))
    await page.route('**/api/v1/campaigns/', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify([CAMPAIGN, DRAFT, SUBMITTED]) }))
    await page.goto(`${BASE}/portal`)

    await expect(page.getByText('Brouillon Été')).toBeVisible()
    // Une campagne EN DIFFUSION et une campagne SOUMISE n'offrent pas la suppression
    // (le serveur la refuse de toute façon — l'écran ne la promet pas).
    await expect(page.getByTestId('portal-delete-1')).toHaveCount(0)
    await expect(page.getByTestId('portal-delete-4')).toHaveCount(0)

    page.on('dialog', (d) => d.accept())
    const del = page.waitForRequest(
      (r) => r.url().includes('/portal/campaigns/3') && r.method() === 'DELETE')
    await page.route('**/api/v1/portal/campaigns/3', (r) => r.fulfill({ status: 204, body: '' }))
    await page.getByTestId('portal-delete-3').click()
    await del
  })
})
