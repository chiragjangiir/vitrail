import { test, expect } from '@playwright/test'

// Exclusion concurrentielle #10 (migr 0087) — catégories d'industrie :
// gestion de la liste + catégorie sur l'annonceur (page Annonceurs), et sites
// exclus grisés/non sélectionnables dans le self-service du portail.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const CATEGORIES = [
  { id_category: 1, category_name: 'Automotive', advertiser_count: 1, excluded_site_count: 1 },
  { id_category: 2, category_name: 'Beverages', advertiser_count: 0, excluded_site_count: 0 },
]
const ADVERTISERS = [
  { id_advertiser: 1, advertiser_name: 'Peugeot', contact_name: null, contact_email: null,
    notes: null, is_active: true, campaign_count: 2, created_at: '2026-07-01T00:00:00Z',
    industry_categories: [1], industry_category_names: ['Automotive'] },
]

async function mockAdminAuth(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => {
    const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
    const user = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user, accessToken: mockToken, refreshToken: 'mock_refresh', roles: ['CMS_ORG_ADMIN'] },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', mockToken)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  })
  await page.route('**/api/v1/users/me', (r) => r.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }),
  }))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }),
  }))
}

test.describe('Competitive exclusion (#10)', () => {
  test('advertisers_page_manages_categories_and_assigns_one', async ({ page }) => {
    await mockAdminAuth(page)
    await page.route('**/api/v1/advertisers/', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(ADVERTISERS) }))
    await page.route('**/api/v1/advertisers/1/users', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: '[]' }))
    const posted: unknown[] = []
    await page.route('**/api/v1/campaigns/industry-categories', (r) => {
      if (r.request().method() === 'POST') {
        posted.push(r.request().postDataJSON())
        return r.fulfill({ status: 201, contentType: 'application/json',
          body: JSON.stringify({ id_category: 3, category_name: 'Retail', advertiser_count: 0, excluded_site_count: 0 }) })
      }
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CATEGORIES) })
    })
    let putBody: Record<string, unknown> | null = null
    await page.route('**/api/v1/advertisers/1', (r) => {
      if (r.request().method() === 'PUT') {
        putBody = r.request().postDataJSON()
        return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ADVERTISERS[0]) })
      }
      return r.fulfill({ status: 404, body: '{}' })
    })

    await page.goto(`${BASE}/campaigns/advertisers`)
    // La carte annonceur montre la catégorie
    await expect(page.locator('text=Automotive').first()).toBeVisible()

    // Drawer de gestion : liste + compteurs + ajout (POST)
    await page.getByRole('button', { name: /industry categories/i }).click()
    const catDrawer = page.getByRole('dialog', { name: 'Industry categories' })
    await expect(catDrawer.locator('text=Automotive')).toBeVisible()
    await expect(catDrawer.locator('text=1 advertiser(s) - 1 site(s)')).toBeVisible()
    await catDrawer.getByLabel(/new category/i).fill('Retail')
    await catDrawer.getByRole('button', { name: /^add$/i }).click()
    await expect.poll(() => posted.length).toBe(1)
    expect(posted[0]).toEqual({ category_name: 'Retail' })
    await page.keyboard.press('Escape')

    // Drawer annonceur : chips MULTI-catégories (agence de pub, 0088), save → PUT liste
    await page.locator('text=Peugeot').first().click()
    const advDrawer = page.getByRole('dialog', { name: 'Peugeot' })
    const autoChip = advDrawer.getByRole('button', { name: 'Automotive' })
    await expect(autoChip).toHaveClass(/bg-accent/)  // catégorie existante active
    await advDrawer.getByRole('button', { name: 'Beverages' }).click()  // en ajoute une 2e
    await advDrawer.getByRole('button', { name: /^save$/i }).click()
    await expect.poll(() => putBody).not.toBeNull()
    expect(putBody).toMatchObject({ industry_categories: [1, 2] })
  })

  test('portal_excluded_site_is_disabled', async ({ page }) => {
    // Auth annonceur (utilisateur lié) — mêmes mocks que portal_self_service
    await page.goto(`${BASE}/login`)
    const advUser = { id_user: 9, id_org: 1, email: 'buyer@peugeot.com', full_name: 'Jane', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, id_advertiser: 1, last_login_at: null, created_at: new Date().toISOString() }
    await page.evaluate((u) => {
      const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI5Iiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfQURWRVJUSVNFUiJdLCJsb2NhbGUiOiJlbiIsInR5cGUiOiJhY2Nlc3MiLCJleHAiOjk5OTk5OTk5OTl9.signature'
      localStorage.setItem('sf-auth', JSON.stringify({
        state: { user: u, accessToken: mockToken, refreshToken: 'mock_refresh', roles: ['CMS_ADVERTISER'] }, version: 0 }))
      localStorage.setItem('sf_access_token', mockToken)
      localStorage.setItem('sf_refresh_token', 'mock_refresh')
    }, advUser)
    await page.route('**/api/v1/users/me', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(advUser) }))
    await page.route('**/api/v1/auth/refresh', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }) }))
    await page.route('**/api/v1/portal/branding', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ org_name: 'Acme Retail', advertiser_name: 'Peugeot', primary_color: '#4875B4', report_title: 'x', logo_url: null }) }))
    await page.route('**/api/v1/campaigns/', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await page.route('**/api/v1/portal/site-lists', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await page.route('**/api/v1/portal/limits', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ max_creatives: 20, creative_max_mb: 1024 }) }))
    // Site 1 = exclu pour cet annonceur (concession concurrente), site 2 = ouvert
    await page.route('**/api/v1/portal/sites**', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([
        { id_site: 1, site_name: 'Renault Store', latitude: null, longitude: null, screen_count: 0, excluded: true },
        { id_site: 2, site_name: 'Mall Plaza', latitude: null, longitude: null, screen_count: 3, excluded: false },
      ]),
    }))

    await page.goto(`${BASE}/portal/campaigns/new`)
    const excludedChip = page.getByRole('button', { name: 'Renault Store' })
    await expect(excludedChip).toBeDisabled()
    await expect(excludedChip).toHaveClass(/line-through/)
    const okChip = page.getByRole('button', { name: /Mall Plaza/ })
    await expect(okChip).toBeEnabled()
    await okChip.click()
    await expect(okChip).toHaveClass(/bg-accent/)
  })
})
