import { test, expect, type Page } from '@playwright/test'

// Générateur promo → chartes de marque (P3.4).
//
// Ce que ces tests verrouillent, et pourquoi :
//   · l'aperçu montre les couleurs de la CHARTE, pas celles du modèle — sinon l'écran promet un
//     visuel et le serveur en rend un autre ;
//   · les mentions légales sont pré-remplies CÔTÉ ÉCRAN et une seule fois : un opérateur qui les
//     efface volontairement ne doit pas les voir revenir ;
//   · sans charte, la page est strictement celle d'avant (déploiement neutre) ;
//   · changer d'annonceur change la charte appliquée (c'est la règle « l'annonceur l'emporte »).

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye',
  avatar_url: null, totp_enabled: false, locale: 'fr', is_active: true,
  last_login_at: null, created_at: new Date().toISOString(),
}

const TEMPLATES = {
  templates: [{
    id: 'fresh',
    label: 'Frais',
    formats: ['16:9'],
    theme: {
      accent: '#3F8F4F', ink: '#1D2B3A', paper: '#F8F7F5',
      badge_bg: '#E4572E', badge_ink: '#FFFFFF', font: 'Inter',
    },
    layouts: {
      '16:9': {
        product: { left: 55, top: 12, width: 40, height: 76 },
        slogan: { left: 6, top: 12, width: 46, height: 32, align: 'left', font_vh: 8.5, min_vh: 4.5, color: 'ink', weight: 800, max_chars: 42 },
        price: { left: 6, top: 52, width: 40, align: 'left', font_vh: 16, min_vh: 9, color: 'accent', weight: 900, max_chars: 10 },
        mentions: { left: 6, top: 90, width: 88, height: 7, align: 'left', font_vh: 2.4, min_vh: 2, color: 'ink', weight: 500, max_chars: 220 },
      },
    },
  }],
  resolutions: { '16:9': ['fhd', '4k'] },
}

const ADVERTISERS = [{ id_advertiser: 7, advertiser_name: 'Brightwell' }]

const ORG_KIT = {
  id_brand_kit: 1, id_advertiser: null, kit_name: 'Enseigne',
  accent: '#E4002B', ink: null, paper: null, badge_bg: null, badge_ink: null,
  font_family: null, brand_name: 'Enseigne', id_logo_media: null,
  legal_mentions: 'Offre valable jusqu au 31/12.', tone: 'chaleureux',
}
const ADV_KIT = { ...ORG_KIT, id_brand_kit: 2, id_advertiser: 7, kit_name: 'Brightwell', accent: '#0055FF', legal_mentions: null }

async function setup(
  page: import('@playwright/test').Page,
  kits: { org: unknown; advertiser?: unknown },
) {
  await page.goto(`${BASE}/login`)
  await page.evaluate((u) => {
    const b64url = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const roles = ['CMS_ORG_ADMIN']
    const tk = [
      b64url({ alg: 'HS256', typ: 'JWT' }),
      b64url({ sub: '1', org: 1, roles, locale: 'fr', type: 'access', exp: 9999999999 }),
      'signature',
    ].join('.')
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: 'mock_refresh', roles }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
    document.cookie = 'locale=fr; path=/'
  }, USER)

  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  // ⚠️ Playwright résout les routes de la DERNIÈRE enregistrée à la première : le glob
  // générique se pose EN PREMIER, sinon il avale toutes les routes spécifiques.
  await page.route('**/api/v1/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/promo/templates**', (r) => r.fulfill(json(TEMPLATES)))
  await page.route('**/api/v1/promo/fonts**', (r) => r.fulfill(json({ fonts: [] })))
  await page.route('**/api/v1/campaigns/advertisers**', (r) => r.fulfill(json(ADVERTISERS)))
  // La charte RÉSOLUE dépend de l'annonceur demandé — c'est le serveur qui tranche, on le simule.
  await page.route('**/api/v1/promo/brand-kits/resolved**', (r) => {
    const url = new URL(r.request().url())
    const adv = url.searchParams.get('advertiser_id')
    return r.fulfill(json(adv ? (kits.advertiser ?? kits.org) : kits.org))
  })
  await page.route('**/api/v1/promo/brand-kits', (r) => r.fulfill(json([])))

  await page.goto(`${BASE}/promo`)
  await expect(page.getByTestId('promo-brand-state')).toBeVisible()
}

/**
 * Déplie l'étape « Texte et prix » — c'est elle qui porte les mentions légales.
 *
 * ⚠️ GESTE, pas assertion. Depuis le parcours en étapes (2026-08-10), le rail s'ouvre sur la
 * seule étape « Pour qui ? » : les mentions ne sont plus dans le DOM au chargement. Les
 * assertions de ce fichier n'ont PAS changé — seule la façon d'atteindre le champ change.
 * Les étapes s'ouvrent indépendamment, donc « Pour qui ? » reste dépliée pendant ce temps :
 * les deux tests qui alternent annonceur et mentions continuent de fonctionner.
 */
async function openStep(page: Page, key: string) {
  const step = page.getByTestId(`step-${key}`)
  if ((await step.getAttribute('data-open')) !== 'true') await step.getByRole('button').first().click()
  await expect(step).toHaveAttribute('data-open', 'true')
}
/** Déplie « Texte et prix ». ⚠️ Le parcours est un ACCORDÉON depuis le 2026-08-10 : ouvrir une
 *  étape referme les autres, donc il faut rouvrir celle dont on a besoin avant chaque geste. */
async function openContentStep(page: Page) {
  await openStep(page, 'content')
  await expect(page.locator('textarea').first()).toBeVisible()
}
async function openWhoStep(page: Page) {
  await openStep(page, 'who')
  await expect(page.getByTestId('promo-advertiser')).toBeVisible()
}

// ⚠️ Les couleurs se lisent en CSS CALCULÉ, jamais dans le HTML sérialisé : le navigateur
// normalise `#E4002B` en `rgb(228, 0, 43)`, et une assertion sur la chaîne hexadécimale
// échouerait sur un produit parfaitement juste.
const PAPER_TEMPLATE = 'rgb(248, 247, 245)'   // #F8F7F5, fond du modèle
const PAPER_KIT = 'rgb(255, 240, 240)'        // #FFF0F0, fond déclaré par la charte

test('l aperçu porte le fond de la charte, pas celui du modèle', async ({ page }) => {
  await setup(page, { org: { ...ORG_KIT, paper: '#FFF0F0' } })
  await expect(page.getByTestId('promo-preview').first()).toHaveCSS('background-color', PAPER_KIT)
})

test('une couleur non déclarée garde celle du modèle', async ({ page }) => {
  // La charte ne déclare QUE `accent` : le fond du modèle doit survivre — c'est la règle
  // « une charte ne remplace que ce qu'elle déclare », vue depuis l'écran.
  await setup(page, { org: ORG_KIT })
  await expect(page.getByTestId('promo-preview').first())
    .toHaveCSS('background-color', PAPER_TEMPLATE)
})

test('les mentions légales de la charte sont pré-remplies', async ({ page }) => {
  await setup(page, { org: ORG_KIT })
  await openContentStep(page)
  await expect(page.locator('textarea').first()).toHaveValue(/Offre valable/)
})

test('des mentions effacées ne reviennent pas, même en revenant sur la portée', async ({ page }) => {
  // ⚠️ Le scénario doit franchir le garde-fou, sinon le test est VACANT : il faut que les DEUX
  // chartes portent des mentions, sans quoi le passage par l'annonceur ne change rien à l'état
  // interne et le défaut (« ne retenir que la dernière portée ») ne se manifeste jamais.
  await setup(page, {
    org: ORG_KIT,
    advertiser: { ...ADV_KIT, legal_mentions: 'Mentions Brightwell.' },
  })
  // ⚠️ Accordéon : chaque aller-retour annonceur ↔ mentions rouvre l'étape concernée. GESTES
  // seulement — les assertions ci-dessous sont exactement celles d'avant.
  await openContentStep(page)
  await expect(page.locator('textarea').first()).toHaveValue(/Offre valable/)
  await page.locator('textarea').first().fill('')

  await openWhoStep(page)
  await page.getByTestId('promo-advertiser').selectOption('7')
  await openContentStep(page)
  await expect(page.locator('textarea').first()).toHaveValue(/Mentions Brightwell/)   // portée neuve → légitime
  await page.locator('textarea').first().fill('')

  await openWhoStep(page)
  await page.getByTestId('promo-advertiser').selectOption('')
  await expect(page.getByTestId('promo-brand-state')).toContainText('Enseigne')
  await openContentStep(page)
  await expect(page.locator('textarea').first()).toHaveValue('')                 // …jamais une 2e fois
})

test('changer d annonceur change la charte appliquée', async ({ page }) => {
  await setup(page, {
    org: { ...ORG_KIT, paper: '#FFF0F0' },
    advertiser: { ...ADV_KIT, paper: '#F0F5FF' },
  })
  const preview = page.getByTestId('promo-preview').first()
  await expect(page.getByTestId('promo-brand-state')).toContainText('Enseigne')
  await expect(preview).toHaveCSS('background-color', PAPER_KIT)

  await page.getByTestId('promo-advertiser').selectOption('7')
  await expect(page.getByTestId('promo-brand-state')).toContainText('Brightwell')
  await expect(preview).toHaveCSS('background-color', 'rgb(240, 245, 255)')
})

test('sans charte, la page reste exactement celle d avant', async ({ page }) => {
  await setup(page, { org: {} })
  await expect(page.getByTestId('promo-brand-state')).toContainText(/Aucune charte/)
  await expect(page.getByTestId('promo-preview').first())
    .toHaveCSS('background-color', PAPER_TEMPLATE)
  await openContentStep(page)
  await expect(page.locator('textarea').first()).toHaveValue('')
})
