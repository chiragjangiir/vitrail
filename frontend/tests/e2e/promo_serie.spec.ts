import { test, expect, type Page } from '@playwright/test'

// Générateur promo → mode SÉRIE (planche E, 2026-08-10).
//
// Ce que ces tests verrouillent :
//   · le partage commun / variable — le parcours de gauche garde ce qui ne change pas, le
//     tableau ne porte que ce qui change (sinon on aurait deux endroits pour la même chose) ;
//   · une ligne sans prix est NOMMÉE et écartée, elle ne bloque PAS la série ;
//   · « Générer les N » lance exactement N appels, un par ligne complète, sur l'endpoint des
//     visuels isolés — donc avec les mêmes gardes (conformité, charte, plafonds de dépense) ;
//   · l'import CSV et la saisie directe coexistent, et un fichier sans en-tête le DIT.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye',
  avatar_url: null, totp_enabled: false, locale: 'fr', is_active: true,
  last_login_at: null, created_at: new Date().toISOString(),
}

const TEMPLATES = {
  templates: [{
    id: 'fresh', label: 'Frais', formats: ['16:9'],
    theme: { accent: '#3F8F4F', ink: '#1D2B3A', paper: '#F8F7F5', badge_bg: '#E4572E', badge_ink: '#FFFFFF', font: 'Inter' },
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

/** Corps des POST de génération reçus — c'est LA preuve : un appel par ligne complète. */
let generated: Record<string, unknown>[] = []

async function setup(page: Page) {
  generated = []
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
  await page.route('**/api/v1/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/promo/templates**', (r) => r.fulfill(json(TEMPLATES)))
  await page.route('**/api/v1/promo/fonts**', (r) => r.fulfill(json({ fonts: [] })))
  await page.route('**/api/v1/promo/brand-kits/resolved**', (r) => r.fulfill(json({})))
  await page.route('**/api/v1/campaigns/advertisers**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/promo/validate', (r) => r.fulfill(json({ valid: true, errors: [] })))
  let n = 0
  await page.route('**/api/v1/promo/image', (r) => {
    generated.push(r.request().postDataJSON() as Record<string, unknown>)
    n++
    return r.fulfill(json({ id_job: n, kind: 'promo_image', status: 'pending', id_media: null, error_detail: null }))
  })

  await page.goto(`${BASE}/promo`)
  await expect(page.getByTestId('step-who')).toBeVisible()
  await page.getByTestId('promo-mode-serie').click()
  await expect(page.getByTestId('promo-serie')).toBeVisible()
}

const rows = (page: Page) => page.getByTestId('serie-row')

test('le tableau ne porte que ce qui VARIE, le parcours garde ce qui est commun', async ({ page }) => {
  await setup(page)
  // L'étape « Le produit » disparaît : elle se définit ligne par ligne.
  await expect(page.getByTestId('step-product')).toHaveCount(0)
  // « Texte et prix » reste, mais annonce que slogan et prix sont passés dans le tableau…
  await page.getByTestId('step-content').getByRole('button').first().click()
  await expect(page.getByTestId('step-content-serie-note')).toBeVisible()
  // …et ce qui s'applique à TOUS les visuels y demeure : mentions et devise.
  await expect(page.locator('textarea').first()).toBeVisible()
  await expect(page.getByRole('combobox').filter({ hasText: 'EUR' }).first()).toBeVisible()
})

test('saisie directe : une ligne complète part, une ligne sans prix est nommée et écartée', async ({ page }) => {
  await setup(page)
  await page.getByTestId('serie-add-line').click()
  await page.getByTestId('serie-add-line').click()
  await expect(rows(page)).toHaveCount(2)

  await rows(page).nth(0).getByTestId('serie-slogan').fill('Brightwell V15')
  await rows(page).nth(0).getByTestId('serie-price').fill('499,00')
  await rows(page).nth(1).getByTestId('serie-slogan').fill('Breeze')   // pas de prix

  // ⛔ La ligne incomplète est NOMMÉE — c'est ce qui la distingue d'un silence.
  const warn = page.getByTestId('serie-incomplete')
  await expect(warn).toBeVisible()
  await expect(warn).toContainText('Breeze')
  await expect(page.getByTestId('serie-count')).toContainText('1')

  // …et la série part quand même, avec la seule ligne complète.
  await page.getByTestId('serie-generate').click()
  // ⚠️ On attend la FIN de la série avant de compter. `expect.poll(...).toBe(1)` réussissait dès
  // que le compteur passait TRANSITOIREMENT par 1 : la mutation « ne plus écarter les lignes
  // sans prix » (0 → 1 → 2) laissait donc le test VERT. Un test qu'un état de passage satisfait
  // ne mesure rien.
  await expect(page.getByTestId('serie-generate')).toBeEnabled()
  await expect(rows(page).nth(0)).toContainText('lancée')
  expect(generated).toHaveLength(1)
  const body = generated[0] as { inputs: Record<string, string>; name: string }
  expect(body.inputs.price).toBe('499,00')
  expect(body.inputs.slogan).toBe('Brightwell V15')
  // Nommé d'après le produit : sinon N visuels arrivent sous le même nom dans la médiathèque.
  expect(body.name).toBe('Brightwell V15')
})

test('import CSV : point-virgule, accents et en-têtes reconnus', async ({ page }) => {
  await setup(page)
  const csv = 'Produit;Prix;Prix barré\nBrightwell V15;499,00;599,00\nBreeze;399,00;449,00\n'
  await page.getByTestId('serie-paste-toggle').click()
  await page.getByTestId('serie-paste-area').fill(csv)
  await page.getByTestId('serie-paste-apply').click()

  await expect(rows(page)).toHaveCount(2)
  await expect(rows(page).nth(0).getByTestId('serie-price')).toHaveValue('499,00')
  await expect(rows(page).nth(1).getByTestId('serie-slogan')).toHaveValue('Breeze')
  await expect(page.getByTestId('serie-import-note')).toContainText('2')

  // Deux lignes complètes ⇒ exactement deux appels, sur l'endpoint des visuels isolés.
  await page.getByTestId('serie-generate').click()
  await expect(page.getByTestId('serie-generate')).toBeEnabled()
  await expect(rows(page).nth(1)).toContainText('lancée')
  expect(generated).toHaveLength(2)
  expect(generated.map((g) => (g.inputs as Record<string, string>).slogan)).toEqual(['Brightwell V15', 'Breeze'])
})

test('un CSV sans en-tête reconnu le DIT au lieu de deviner en silence', async ({ page }) => {
  await setup(page)
  await page.getByTestId('serie-paste-toggle').click()
  await page.getByTestId('serie-paste-area').fill('Brightwell V15;499,00;599,00')
  await page.getByTestId('serie-paste-apply').click()

  await expect(rows(page)).toHaveCount(1)
  // 🔑 Le pire défaut évité : lire par position SANS le dire produirait des prix dans le
  // mauvais champ, ce qui ne se voit qu'une fois le visuel à l'antenne.
  await expect(page.getByTestId('serie-import-note')).toContainText('Aucun en-tête reconnu')
  await expect(rows(page).nth(0).getByTestId('serie-price')).toHaveValue('499,00')
})

test('l import COMPLÈTE le tableau, il ne le remplace pas', async ({ page }) => {
  await setup(page)
  await page.getByTestId('serie-add-line').click()
  await rows(page).nth(0).getByTestId('serie-slogan').fill('Saisi à la main')

  await page.getByTestId('serie-paste-toggle').click()
  await page.getByTestId('serie-paste-area').fill('nom;prix\nImporté;10,00')
  await page.getByTestId('serie-paste-apply').click()

  await expect(rows(page)).toHaveCount(2)
  await expect(rows(page).nth(0).getByTestId('serie-slogan')).toHaveValue('Saisi à la main')
  await expect(rows(page).nth(1).getByTestId('serie-slogan')).toHaveValue('Importé')
})

test('sans aucune ligne complète, le bouton de série reste éteint', async ({ page }) => {
  await setup(page)
  await expect(page.getByTestId('serie-generate')).toBeDisabled()
  await page.getByTestId('serie-add-line').click()
  await expect(page.getByTestId('serie-generate')).toBeDisabled()   // ligne vide = pas de prix
  await rows(page).nth(0).getByTestId('serie-price').fill('9,99')
  await expect(page.getByTestId('serie-generate')).toBeEnabled()
})
