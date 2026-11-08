import { test, expect } from '@playwright/test'

// Approval Workflow §XXI (S7 C1) — file /approvals (compteurs, filtre, drawer
// timeline + actions) et soumission depuis le drawer campagne.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const APPROVAL = {
  id_request: 1, resource_type: 'campaign', resource_id: 1, status: 'pending_review',
  submitted_by: 2, submitted_at: '2026-07-10T10:00:00Z', due_date: null,
  notes: 'Please review', reviewed_by: null, reviewed_at: null, published_at: null,
  created_at: '2026-07-10T10:00:00Z', updated_at: '2026-07-10T10:00:00Z',
  resource_name: 'Dyson Summer', submitted_by_name: 'Sales Sam', reviewed_by_name: null,
}

const DASHBOARD = { pending_review: 1, changes_requested: 0, approved: 0, rejected: 0, published: 0, urgent: 0 }

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

// Un seul handler pour tout /approvals* (dispatch par pathname+méthode) — évite les
// recouvrements de globs entre /approvals/, /approvals/dashboard et /approvals/{id}/action.
function mockApprovalRoutes(page: import('@playwright/test').Page, opts?: {
  detail?: Record<string, unknown>
  rows?: Record<string, unknown>[]
  onAction?: (action: string, body: unknown) => void
}) {
  const detail = opts?.detail ?? {
    ...APPROVAL,
    comments: [{ id_comment: 1, id_request: 1, id_user: 2, comment_text: 'Please review', action: 'submitted', created_at: '2026-07-10T10:00:00Z', user_name: 'Sales Sam' }],
    creatives: [{ id_creative: 10, media_name: 'spot-dyson', media_type: 'video', duration_ms: 27000, approval_status: 'pending', preview_url: 'http://127.0.0.1:9/spot.mp4', thumbnail_url: null }],
    campaign: {
      advertiser_name: 'Dyson', starts_on: '2026-07-11', ends_on: '2026-07-18',
      daily_hours: null, sov_percent: 25, priority: 50, pricing_model: 'sov',
      price_amount: 500, price_currency: 'EUR', cpm_rate: null,
      targets: [{ target_type: 'player', name: 'NUC' }],
      target_player_count: 1,
      occupancy: { warning: true, blocked: false, max_projected_pct: 85 },
    },
  }
  return page.route('**/api/v1/approvals**', async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    const path = url.pathname
    if (method === 'GET' && path.endsWith('/approvals/dashboard')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DASHBOARD) })
    }
    if (method === 'GET' && path.endsWith('/approvals/')) {
      const st = url.searchParams.get('status')
      const all = opts?.rows ?? [APPROVAL]
      const rows = !st ? all : all.filter((r) => r.status === st)
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rows) })
    }
    if (method === 'DELETE' && /\/approvals\/\d+$/.test(path)) {
      opts?.onAction?.('delete', path)
      return route.fulfill({ status: 204, body: '' })
    }
    if (method === 'GET' && /\/approvals\/1$/.test(path)) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) })
    }
    if (method === 'POST' && path.endsWith('/approvals/')) {
      opts?.onAction?.('submit', route.request().postDataJSON())
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(APPROVAL) })
    }
    const m = path.match(/\/approvals\/1\/([a-z-]+)$/)
    if (method === 'POST' && m) {
      const body = route.request().postDataJSON()
      opts?.onAction?.(m[1], body)
      const status = m[1] === 'approve' ? 'approved' : m[1] === 'reject' ? 'rejected' : APPROVAL.status
      // #9 : email annonceur — le backend renvoie email_sent_to quand demandé
      const email = (body as { notify_advertiser?: boolean })?.notify_advertiser ? { email_sent_to: 1 } : {}
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...APPROVAL, status, ...email }) })
    }
    return route.fulfill({ status: 404, body: '{}' })
  })
}

test.describe('Approvals queue (§21 C1)', () => {
  test('queue_lists_counters_and_status_filter', async ({ page }) => {
    await mockApprovalRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/approvals`)

    // Ligne de la demande + compteur du pill
    await expect(page.locator('td', { hasText: 'Dyson Summer' })).toBeVisible()
    await expect(page.locator('td', { hasText: 'Sales Sam' })).toBeVisible()
    const pendingPill = page.getByRole('button', { name: /pending review/i })
    await expect(pendingPill).toContainText('1')

    // Filtre par statut → requête ?status=
    const filtered = page.waitForRequest((r) => r.url().includes('/approvals/?status=pending_review'))
    await pendingPill.click()
    await filtered
    await expect(page.locator('td', { hasText: 'Dyson Summer' })).toBeVisible()
  })

  test('drawer_timeline_approve_and_reject_requires_comment', async ({ page }) => {
    const actions: [string, unknown][] = []
    await mockApprovalRoutes(page, { onAction: (a, b) => actions.push([a, b]) })
    await mockAuthAndNavigate(page, `${BASE}/approvals`)

    await page.locator('td', { hasText: 'Dyson Summer' }).click()
    const drawer = page.getByRole('dialog', { name: 'Dyson Summer' })
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('text=Please review')).toBeVisible()
    await expect(drawer.locator('text=Sales Sam').first()).toBeVisible()

    // Le reviewer VOIT ce qu'il approuve : lecteur vidéo inline + badge pending + hint
    await expect(drawer.locator('video')).toBeVisible()
    await expect(drawer.locator('text=spot-dyson')).toBeVisible()
    await expect(drawer.locator('text=Approving the request also approves pending creatives.')).toBeVisible()
    // ... et les paramètres commerciaux + cible nommée + occupation projetée
    await expect(drawer.locator('text=25 %')).toBeVisible()
    await expect(drawer.locator('text=500 EUR')).toBeVisible()
    await expect(drawer.locator('text=NUC')).toBeVisible()
    await expect(drawer.locator('text=1 players')).toBeVisible()
    await expect(drawer.locator('text=Max projected occupancy of targets: 85%')).toBeVisible()

    // Reject sans commentaire = erreur CLIENT, aucun POST
    await drawer.getByRole('button', { name: 'Reject' }).click()
    await expect(drawer.locator('text=A comment is required')).toBeVisible()
    expect(actions.filter(([a]) => a === 'reject')).toHaveLength(0)

    // #9 : case « Notifier l'annonceur par email » cochée par défaut (campagne)
    const notify = drawer.locator('input[type="checkbox"]')
    await expect(notify).toBeChecked()

    // Approve (commentaire optionnel) → POST approve avec notify_advertiser,
    // puis retour d'envoi affiché dans le drawer
    const approveReq = page.waitForRequest((r) => r.url().includes('/approvals/1/approve') && r.method() === 'POST')
    await drawer.getByRole('button', { name: 'Approve' }).click()
    const posted = await approveReq
    expect(posted.postDataJSON()).toMatchObject({ notify_advertiser: true })
    await expect(drawer.locator('text=Email sent to 1 recipient(s)')).toBeVisible()
  })

  test('search_filters_and_terminal_rows_are_deletable', async ({ page }) => {
    // Retour Ed 12/07 : recherche à droite des pastilles + poubelle de ménage
    // (statuts TERMINAUX seulement — une demande active n'a pas d'icône).
    const actions: [string, unknown][] = []
    const OLD = { ...APPROVAL, id_request: 2, status: 'rejected', resource_name: 'Old Promo' }
    await mockApprovalRoutes(page, { rows: [APPROVAL, OLD], onAction: (a, b) => actions.push([a, b]) })
    await mockAuthAndNavigate(page, `${BASE}/approvals`)

    await expect(page.locator('td', { hasText: 'Dyson Summer' })).toBeVisible()
    await expect(page.locator('td', { hasText: 'Old Promo' })).toBeVisible()

    // Recherche client-side sur le nom de ressource
    await page.getByPlaceholder('Search…').fill('old')
    await expect(page.locator('td', { hasText: 'Dyson Summer' })).toHaveCount(0)
    await expect(page.locator('td', { hasText: 'Old Promo' })).toBeVisible()
    await page.getByPlaceholder('Search…').fill('')

    // Poubelle : absente sur la ligne active, présente sur la terminée
    const activeRow = page.locator('tr', { hasText: 'Dyson Summer' })
    const oldRow = page.locator('tr', { hasText: 'Old Promo' })
    await expect(activeRow.getByTitle('Delete request')).toHaveCount(0)
    page.on('dialog', (d) => d.accept())
    const del = page.waitForRequest((r) => r.url().includes('/approvals/2') && r.method() === 'DELETE')
    await oldRow.getByTitle('Delete request').click()
    await del
  })

  test('campaign_drawer_submit_for_approval_then_badge', async ({ page }) => {
    const CAMPAIGN = {
      id_campaign: 1, id_advertiser: 1, campaign_name: 'Dyson Summer', status: 'draft',
      starts_on: '2026-07-01', ends_on: '2026-07-31', daily_hours: null,
      sov_percent: 20, pricing_model: 'sov', price_amount: null, price_currency: 'EUR',
      cpm_rate: null, priority: 50, advertiser_name: 'Dyson', creative_count: 0,
      target_player_count: 0, approval_request: null,
      targets: [{ id_target: 1, target_type: 'org', target_id: null }],
    }
    await mockApprovalRoutes(page)
    for (const [glob, body] of [
      ['**/api/v1/campaigns/', JSON.stringify([CAMPAIGN])],
      ['**/api/v1/advertisers/', JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Dyson', id_folder: null }])],
      ['**/api/v1/sites', '[]'], ['**/api/v1/player-groups/', '[]'],
      ['**/api/v1/site-groups/', '[]'], ['**/api/v1/players/', '[]'],
      ['**/api/v1/campaigns/inventory**', '[]'],
      ['**/api/v1/campaigns/1/creatives', '[]'],
      ['**/api/v1/campaigns/settings', JSON.stringify({ creative_approval: false })],
      ['**/api/v1/campaigns/occupancy-check', JSON.stringify({ blocked: false, warning: false, max_projected_pct: 20, players: [] })],
    ] as const) {
      await page.route(glob, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body })
      })
    }
    await mockAuthAndNavigate(page, `${BASE}/campaigns`)

    await page.locator('td', { hasText: 'Dyson Summer' }).click()
    const drawer = page.getByRole('dialog', { name: 'Dyson Summer' })
    await expect(drawer.getByRole('button', { name: 'Publish' })).toBeVisible()

    // Soumettre pour approbation → POST /approvals/ + badge « Pending review »,
    // Publier et Soumettre disparaissent (demande en revue)
    const submitReq = page.waitForRequest((r) => r.url().endsWith('/api/v1/approvals/') && r.method() === 'POST')
    await drawer.getByRole('button', { name: 'Submit for approval' }).click()
    const req = await submitReq
    expect(req.postDataJSON()).toEqual({ resource_type: 'campaign', resource_id: 1 })
    await expect(drawer.locator('text=Pending review')).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Publish' })).toHaveCount(0)
    await expect(drawer.getByRole('button', { name: 'Submit for approval' })).toHaveCount(0)
  })
})
