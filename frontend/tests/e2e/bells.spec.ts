import { test, expect } from '@playwright/test'

// Cloches de validation (retours Ed #7/#8) : badge + liste chronologique côté CMS
// (rôles valideurs), badge décisions + marquage vu côté portail annonceur.

// Même défaut que les autres specs (CI = webServer :3000 ; bench dev = env :3010)
const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const USER = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }
const ADV = { ...USER, id_user: 9, email: 'buyer@brightwell.com', id_advertiser: 1 }

async function auth(page: import('@playwright/test').Page, user: Record<string, unknown>, roles: string[]) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(([u, r]) => {
    const tk = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
    localStorage.setItem('sf-auth', JSON.stringify({ state: { user: u, accessToken: tk, refreshToken: 'mock_refresh', roles: r }, version: 0 }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, [user, roles] as const)
  await page.route('**/api/v1/users/me', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user) }))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }) }))
}

test('cms approvals bell', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await auth(page, USER, ['CMS_ORG_ADMIN'])
  await page.route('**/api/v1/approvals/dashboard', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ pending_review: 3, changes_requested: 0, approved: 1, rejected: 0, published: 2, urgent: 1, is_reviewer: true }) }))
  await page.route('**/api/v1/approvals/?status=pending_review', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
    { id_request: 5, resource_type: 'campaign', resource_id: 3, status: 'pending_review', submitted_by: 9, submitted_at: '2026-07-09T10:00:00Z', due_date: null, notes: null, reviewed_by: null, reviewed_at: null, published_at: null, resource_name: 'Brightwell Summer', submitted_by_name: 'Jane Buyer' },
    { id_request: 7, resource_type: 'campaign', resource_id: 4, status: 'pending_review', submitted_by: 9, submitted_at: '2026-07-11T08:00:00Z', due_date: null, notes: null, reviewed_by: null, reviewed_at: null, published_at: null, resource_name: 'Corvane Drive', submitted_by_name: 'Jane Buyer' },
    { id_request: 6, resource_type: 'campaign', resource_id: 5, status: 'pending_review', submitted_by: 9, submitted_at: '2026-07-10T09:00:00Z', due_date: null, notes: null, reviewed_by: null, reviewed_at: null, published_at: null, resource_name: 'Coca Promo', submitted_by_name: 'John Doe' },
  ]) }))
  await page.route('**/api/v1/dashboard/stats', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.goto(`${BASE}/dashboard`)
  const bell = page.getByRole('button', { name: /awaiting validation/i })
  await expect(bell).toBeVisible()
  await expect(bell.locator('span')).toHaveText('3')
  await bell.click()
  await expect(page.locator('text=3 awaiting validation')).toBeVisible()
  // ordre chronologique : Brightwell (09/07) avant Coca (10/07) avant Corvane (11/07)
  const items = page.locator('ul button')
  await expect(items.nth(0)).toContainText('Brightwell Summer')
  await expect(items.nth(1)).toContainText('Coca Promo')
  await expect(items.nth(2)).toContainText('Corvane Drive')
  // clic → /approvals?open=5
  await items.nth(0).click()
  await expect(page).toHaveURL(/\/approvals\?open=5/)
})

test('portal decisions bell', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await auth(page, ADV, ['CMS_ADVERTISER'])
  await page.route('**/api/v1/portal/branding', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ org_name: 'Acme Retail', advertiser_name: 'Brightwell', primary_color: '#4875B4', report_title: null, logo_url: null }) }))
  await page.route('**/api/v1/campaigns/', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  let seenCalled = false
  await page.route('**/api/v1/portal/decisions/seen', (r) => { seenCalled = true; return r.fulfill({ status: 204, body: '' }) })
  await page.route('**/api/v1/portal/decisions', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ unseen_count: 2, items: [
    { id_request: 5, id_campaign: 3, campaign_name: 'Brightwell Summer', status: 'approved', decided_at: '2026-07-11T09:00:00Z', unseen: true },
    { id_request: 4, id_campaign: 2, campaign_name: 'Brightwell Spring', status: 'changes_requested', decided_at: '2026-07-10T09:00:00Z', unseen: true },
  ] }) }))
  await page.goto(`${BASE}/portal`)
  const bell = page.getByRole('button', { name: /decisions on your campaigns/i })
  await expect(bell).toBeVisible()
  await expect(bell.locator('span')).toHaveText('2')
  await bell.click()
  await expect(page.locator('text=Campaign approved')).toBeVisible()
  await expect(page.locator('text=Changes requested')).toBeVisible()
  await expect.poll(() => seenCalled).toBe(true)
  // clic sur « modifications demandées » → formulaire d'édition
  await page.locator('text=Brightwell Spring').click()
  await expect(page).toHaveURL(/\/portal\/campaigns\/2\/edit/)
})
