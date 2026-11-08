import { test, expect } from '@playwright/test'

// P3.6 — ou s'affiche un spot de campagne sur un ecran MULTI-ZONES.
//
// L'injection des creatifs etait coupee des qu'un template portait 2 zones ou plus, alors
// qu'aucun service ne connaissait cette notion : ces ecrans etaient comptes VENDABLES par
// l'occupancy-check et jamais servis. Decision d'Ed : le mode est choisi PAR TEMPLATE.
//
// Ces specs affirment un RESULTAT : ce que l'exploitant voit, et ce que l'editeur ENVOIE.
// Le point qui compte : le reglage n'a de sens qu'a partir de 2 zones — sur un template
// plein ecran, un spot a toujours occupe tout l'ecran, et l'afficher la ferait croire a un
// choix qui n'existe pas.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const ZONES_2 = [
  { index: 0, x: 0, y: 0, w: 1280, h: 1080, label: 'Main' },
  { index: 1, x: 1280, y: 0, w: 640, h: 1080, label: 'Side' },
]
const ZONES_1 = [{ index: 0, x: 0, y: 0, w: 1920, h: 1080, label: 'Full' }]

function tpl(zones: unknown[], placement = 'fullscreen') {
  return {
    id_template: 7, id_org: 1, template_name: 'T', description: null,
    layout: { layout_type: zones.length > 1 ? 'split_v' : 'full', canvas_width: 1920, canvas_height: 1080, zones },
    preview_url: null, campaign_placement: placement, id_governance_node: null,
    governed_readonly: false,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  }
}

async function open(page: import('@playwright/test').Page, zones: unknown[], placement = 'fullscreen',
                   onPut?: (b: Record<string, unknown>) => void) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => {
    const tk = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }, accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
  })
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER_ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'x', refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  await page.route(/\/api\/v1\/templates\/7(\?.*)?$/, async (route) => {
    if (route.request().method() === 'PUT') {
      onPut?.(route.request().postDataJSON())
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tpl(zones, placement)) })
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tpl(zones, placement)) })
  })
  await page.route(/\/api\/v1\/media(\/)?(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) }))
  await page.goto(`${BASE}/templates/7/edit`)
}

test.describe('Templates — placement des spots de campagne', () => {
  test('the_setting_appears_only_for_a_multizone_template', async ({ page }) => {
    await open(page, ZONES_2)
    await expect(page.getByTestId('campaign-placement')).toBeVisible()
  })

  test('a_single_zone_template_does_NOT_offer_the_choice', async ({ page }) => {
    // Temoin indispensable : sur un plein ecran, le spot a TOUJOURS occupe tout l'ecran.
    // Proposer le reglage la ferait croire a un choix qui n'existe pas — et sans ce test,
    // un reglage affiche en permanence passerait le test precedent.
    await open(page, ZONES_1)
    await expect(page.getByTestId('campaign-placement')).toHaveCount(0)
  })

  test('the_server_value_is_reflected_and_the_choice_is_SENT', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await open(page, ZONES_2, 'zone', (b) => { body = b })

    // Ce que le serveur a enregistre doit etre ce qu'on voit : sinon on croit modifier un
    // reglage qui vaut deja autre chose.
    await expect(page.getByTestId('campaign-placement-zone')).toBeChecked()

    await page.getByTestId('campaign-placement-fullscreen').check()
    await page.getByRole('button', { name: /save/i }).first().click()
    await expect.poll(() => body).toMatchObject({ campaign_placement: 'fullscreen' })
  })
})
