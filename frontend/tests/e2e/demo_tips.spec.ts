import { test, expect } from '@playwright/test'

// Mode démo (demandes Ed 2026-07-10) : bulles d'infos contextuelles pour un compte
// is_demo (CMS standard + portail annonceur) et case « compte démo » à l'invitation.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const DEMO_USER = { id_user: 5, id_org: 1, email: 'demo@retail-demo.demo', full_name: 'Demo', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, is_demo: true, last_login_at: null, created_at: new Date().toISOString() }
const DEMO_ADV_USER = { ...DEMO_USER, id_user: 6, email: 'advertiser@retail-demo.demo', id_advertiser: 1 }
const ADMIN_USER = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

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

async function mockCampaignLists(page: import('@playwright/test').Page) {
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
}

test.describe('Demo tips & demo advertiser (S7)', () => {
  test('demo_user_tip_cannot_be_dismissed', async ({ page }) => {
    // Règle v2 (retour Ed) : un compte DÉMO ne peut pas fermer les bulles — pas de croix.
    await mockAuth(page, DEMO_USER, ['CMS_ORG_ADMIN'])
    await mockCampaignLists(page)
    await page.goto(`${BASE}/campaigns`)

    await expect(page.locator('text=Demo account — read-only')).toBeVisible()
    await expect(page.locator('text=Retail Media campaigns')).toBeVisible()
    await expect(page.locator('text=share-of-voice')).toBeVisible()
    await expect(page.getByTitle('Got it')).toHaveCount(0)
    await page.reload()
    await expect(page.locator('text=Retail Media campaigns')).toBeVisible()
  })

  test('demo_user_profile_telegram_link_shows_toast_not_spinner', async ({ page }) => {
    // Retour Ed 10/07 : le bouton « Lier mon compte Telegram » d'un compte démo restait
    // en spinner infini → blocage CLIENT (fireDemoToast) sans appel réseau.
    await mockAuth(page, DEMO_USER, ['CMS_ORG_ADMIN'])
    await page.route('**/api/v1/messaging/status', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ configured: true, bot_username: 'SignflowJeanineBot', identities: [] }),
      })
    })
    let linkCalled = false
    await page.route('**/api/v1/messaging/link-code', async (route) => {
      linkCalled = true
      await route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'demo_blocked' }) })
    })
    await page.goto(`${BASE}/settings/profile`)

    // Bulle profil présente (nouvelle page couverte)
    await expect(page.locator('text=Your profile')).toBeVisible()
    const btn = page.getByRole('button', { name: /link my telegram/i })
    await btn.click()
    // Toast démo affiché, bouton PAS en spinner, aucun appel réseau parti
    await expect(page.locator('text=Demo account — this action is not available.')).toBeVisible()
    await expect(btn).toBeEnabled()
    expect(linkCalled).toBe(false)
  })

  test('demo_assistant_showcase_no_llm_call', async ({ page }) => {
    // Vitrine de l'assistant IA pour un compte démo : panneau statique (fausse
    // conversation + capacités + exemples → toast), AUCUN appel réseau assistant.
    await mockAuth(page, DEMO_USER, ['CMS_ORG_ADMIN'])
    await mockCampaignLists(page)
    let assistantCalled = false
    await page.route('**/api/v1/assistant/**', async (route) => {
      assistantCalled = true
      await route.fulfill({ status: 500, body: '' })
    })
    await page.goto(`${BASE}/campaigns`)

    await page.getByRole('button', { name: 'AI Assistant' }).click()
    await expect(page.locator('text=Which screens are offline right now?')).toBeVisible()
    await expect(page.locator('text=What the assistant can do on a real account')).toBeVisible()
    await expect(page.getByPlaceholder('Disabled on a demo account')).toBeDisabled()
    // Cliquer un exemple → toast compte démo, pas d'appel
    await page.locator('text=Broadcast the promo video').click()
    await expect(page.locator('text=Demo account — this action is not available.')).toBeVisible()
    expect(assistantCalled).toBe(false)
  })

  test('demo_tip_on_templates_page', async ({ page }) => {
    await mockAuth(page, DEMO_USER, ['CMS_ORG_ADMIN'])
    await page.route('**/api/v1/templates/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.goto(`${BASE}/templates`)
    await expect(page.locator('text=Layout templates').first()).toBeVisible()
  })

  test('demo_tips_on_sidebar_submenus', async ({ page }) => {
    // Retour Ed : sous-menus couverts — Studio, Promo, Pages web, Feeds, Provisioning.
    await mockAuth(page, DEMO_USER, ['CMS_ORG_ADMIN'])
    await page.route('**/api/v1/**', async (route) => {
      if (route.request().method() === 'GET' && route.request().url().includes('/api/v1/')
          && !route.request().url().includes('/users/me') && !route.request().url().includes('/auth/')) {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      } else {
        await route.continue()
      }
    })
    for (const [path, title] of [
      ['/studio', 'Campaign Studio'],
      ['/promo', 'Promo Generator'],
      ['/url-display', 'Web pages'],
      ['/feeds', 'News feeds'],
      ['/settings/players/provisioning', 'Player provisioning'],
      ['/media/tags', 'A shared taxonomy'],
    ] as const) {
      await page.goto(`${BASE}${path}`)
      await expect(page.locator(`text=${title}`).first()).toBeVisible()
    }
  })

  test('classic_user_can_dismiss_and_reactivate_tips', async ({ page }) => {
    // Compte CLASSIQUE : bulle visible, fermable (persiste entre sessions — localStorage)
    // et réactivable depuis Réglages → Profil.
    await mockAuth(page, ADMIN_USER, ['CMS_ORG_ADMIN'])
    await mockCampaignLists(page)
    await page.route('**/api/v1/messaging/status', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ configured: false, bot_username: null, identities: [] }),
      })
    })
    await page.goto(`${BASE}/campaigns`)

    await expect(page.locator('text=Retail Media campaigns')).toBeVisible()
    await page.getByTitle('Got it').click()
    await expect(page.locator('text=Retail Media campaigns')).toHaveCount(0)
    await page.reload()
    await expect(page.locator('text=New campaign').first()).toBeVisible()
    await expect(page.locator('text=Retail Media campaigns')).toHaveCount(0)

    // Réactivation depuis le profil → la bulle revient sur /campaigns
    await page.goto(`${BASE}/settings/profile`)
    await page.getByRole('button', { name: 'Show help bubbles again' }).click()
    await expect(page.locator('text=Help bubbles restored.')).toBeVisible()
    await page.goto(`${BASE}/campaigns`)
    await expect(page.locator('text=Retail Media campaigns')).toBeVisible()
  })

  test('demo_advertiser_portal_shows_banner_and_tip', async ({ page }) => {
    await mockAuth(page, DEMO_ADV_USER, ['CMS_ADVERTISER'])
    await page.route('**/api/v1/portal/branding', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ org_name: 'Acme Retail', advertiser_name: 'Marque Démo', primary_color: '#4875B4', report_title: null, logo_url: null }),
      })
    })
    await page.route('**/api/v1/campaigns/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await page.goto(`${BASE}/portal`)

    await expect(page.locator('text=Demo account — read-only')).toBeVisible()
    await expect(page.locator('text=Advertiser portal (demo)')).toBeVisible()
    await expect(page.locator('text=what YOUR advertisers see')).toBeVisible()
  })

  test('invite_form_posts_is_demo_flag', async ({ page }) => {
    await mockAuth(page, ADMIN_USER, ['CMS_ORG_ADMIN'])
    await page.route('**/api/v1/advertisers/', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify([{ id_advertiser: 1, advertiser_name: 'Dyson', contact_name: null, contact_email: null, notes: null, is_active: true, campaign_count: 0, created_at: new Date().toISOString() }]),
      })
    })
    let postBody: unknown = null
    await page.route('**/api/v1/advertisers/1/users', async (route) => {
      if (route.request().method() === 'POST') {
        postBody = route.request().postDataJSON()
        await route.fulfill({
          status: 201, contentType: 'application/json',
          body: JSON.stringify({
            user: { id_user: 9, email: 'prospect@demo.com', full_name: null, is_active: true, is_demo: true, last_login_at: null, created_at: new Date().toISOString() },
            initial_password: 'sf-Demo-1',
          }),
        })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      }
    })
    await page.goto(`${BASE}/campaigns/advertisers`)
    await page.locator('text=Dyson').first().click()
    const drawer = page.getByRole('dialog', { name: 'Dyson' })
    await drawer.getByPlaceholder('buyer@brand.com').fill('prospect@demo.com')
    // Cible la case DEMO par son libelle : le drawer annonceur en compte desormais trois
    // (les flags allow_visual/audio_campaigns sont arrives le 2026-07-18, migr 0095), et un
    // `getByRole('checkbox')` nu tombait en strict mode violation.
    await drawer.getByLabel('Demo account (read-only showcase)').check()
    await drawer.getByRole('button', { name: 'Invite' }).click()
    await expect.poll(() => postBody).toEqual({ email: 'prospect@demo.com', full_name: null, is_demo: true })
  })
})
