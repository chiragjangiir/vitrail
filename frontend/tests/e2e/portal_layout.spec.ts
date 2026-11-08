import { test, expect } from '@playwright/test'

/**
 * Deux défauts d'empilement/hauteur du portail annonceur, trouvés le 2026-07-20
 * en cherchant pourquoi deux specs échouaient. Les deux rendaient des éléments
 * CLIQUABLES inatteignables pour un annonceur — surface client.
 *
 *  ① La cloche des décisions est un menu `absolute z-50` rendu DANS le
 *    `<header relative z-10>`. Son z-50 ne vaut qu'à l'intérieur de ce contexte
 *    d'empilement : le `<main>`, lui aussi `z-10` mais PLUS BAS dans le DOM,
 *    peignait par-dessus. Cliquer une décision touchait la page en dessous.
 *    → en-tête passé en `z-30`.
 *
 *  ② Les sections « Indicateurs » et « État du parc » sont `shrink-0`. Sur un
 *    écran court (1280×720, portable courant) elles consommaient toute la
 *    hauteur et le bloc campagnes — la surface PRINCIPALE du portail — tombait à
 *    0 px. Ses cartes continuaient de peindre par-dessus le pied de page, qui
 *    interceptait les clics. → plancher `min-h-[320px]` + garde-fou de
 *    défilement sur le conteneur racine.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfQURWRVJUSVNFUiJdLCJsb2NhbGUiOiJlbiIsInR5cGUiOiJhY2Nlc3MiLCJleHAiOjk5OTk5OTk5OTl9.sig'

const ME = {
  id_user: 2, id_org: 1, email: 'adv@t.com', full_name: 'Adv', avatar_url: null,
  totp_enabled: false, locale: 'en', theme: 'dark', is_active: true, is_demo: false,
  id_advertiser: 3, last_login_at: null, created_at: new Date().toISOString(),
  org_name: 'Org', roles: ['CMS_ADVERTISER'], permissions: ['campaigns:read'],
}

const CAMPAIGNS = Array.from({ length: 6 }, (_, i) => ({
  id_campaign: i + 1, campaign_name: `Campagne ${i + 1}`, status: 'live',
  starts_on: '2026-07-01', ends_on: '2026-08-01', sov_percent: 20,
  campaign_kind: i % 2 ? 'audio' : 'visual', pricing_model: 'flat',
}))

async function openPortal(page: import('@playwright/test').Page, height: number) {
  await page.setViewportSize({ width: 1280, height })
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: TOKEN, refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  await page.route('**/api/v1/portal/branding', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ org_name: 'Acme', advertiser_name: 'Brightwell', primary_color: '#4875B4', report_title: null, logo_url: null }) }))
  await page.route('**/api/v1/portal/overview', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      campaigns: { total: 6, active: 3, visual: 3, audio: 3 },
      players: { total: 4, online: 3, offline: 1, warning: 0, maintenance: 0 },
      proof_of_play_24h: 12, sites: [], activity: [],
    }) }))
  await page.route(/\/api\/v1\/campaigns\//, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CAMPAIGNS) }))
  await page.route(/\/api\/v1\/(?!users\/me|auth|portal|campaigns)/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

  await page.goto(`${BASE}/login`)
  await page.evaluate((tk) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 2, id_org: 1, email: 'adv@t.com', id_advertiser: 3, roles: ['CMS_ADVERTISER'] },
        accessToken: tk, refreshToken: 'r', roles: ['CMS_ADVERTISER'] }, version: 0 }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, TOKEN)
  await page.goto(`${BASE}/portal`)
  await page.waitForTimeout(1200)
}

test.describe('Mise en page du portail annonceur', () => {
  test('campaigns_block_never_collapses_on_a_laptop_screen', async ({ page }) => {
    await openPortal(page, 720)

    // Le bloc campagnes garde une hauteur utilisable (il valait 0 px avant).
    const h = await page.evaluate(() => {
      const root = document.querySelector('.sf-stagger') as HTMLElement
      const last = root.children[root.children.length - 1] as HTMLElement
      return Math.round(last.getBoundingClientRect().height)
    })
    expect(h).toBeGreaterThanOrEqual(300)

    // Et une carte de campagne est réellement cliquable : l'élément au premier
    // plan à son centre doit être la carte elle-même, pas le pied de page.
    // (On la fait défiler dans le viewport d'abord : `elementFromPoint` ne voit
    // que la zone visible, et le conteneur défile désormais sur écran court.)
    await page.locator('a[href*="/portal/campaigns/"]:not([href$="/new"])').first()
      .scrollIntoViewIfNeeded()
    const top = await page.evaluate(() => {
      const card = [...document.querySelectorAll('a[href*="/portal/campaigns/"]')]
        .find((a) => !(a as HTMLAnchorElement).href.endsWith('/new')) as HTMLElement
      if (!card) return 'AUCUNE_CARTE'
      const r = card.getBoundingClientRect()
      const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
      return el?.closest('a') === card ? 'CARTE' : (el?.tagName ?? 'RIEN')
    })
    expect(top).toBe('CARTE')
  })

  test('header_dropdowns_paint_above_the_page', async ({ page }) => {
    await openPortal(page, 900)
    // L'en-tête doit créer un contexte d'empilement AU-DESSUS du <main>, sinon
    // aucun de ses menus déroulants n'est cliquable.
    const z = await page.evaluate(() => ({
      header: Number(getComputedStyle(document.querySelector('header')!).zIndex),
      main: Number(getComputedStyle(document.querySelector('main')!).zIndex),
    }))
    expect(z.header).toBeGreaterThan(z.main)
  })
})
