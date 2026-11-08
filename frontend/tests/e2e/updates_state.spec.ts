import { test, expect } from '@playwright/test'

// L'inventaire du parc a TROIS états, pas deux (défaut trouvé sur une capture d'Ed, 2026-08-10).
//
// Sans version au catalogue pour la plateforme d'un écran, il n'existe AUCUNE référence : le
// serveur repliait ce cas sur « à jour » et l'en-tête annonçait « 0 en retard ». Sur une
// installation neuve, dont le catalogue est vide, l'écran certifiait donc un parc sain qu'il
// n'avait comparé à rien — et personne ne mettait jamais rien à jour. Ce que ces tests figent :
// l'absence de mesure s'affiche « Inconnu », se compte à part, et se filtre.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye',
  avatar_url: null, totp_enabled: false, locale: 'en', is_active: true,
  last_login_at: null, created_at: new Date().toISOString(),
}

const row = (name: string, cur: string, latest: string | null, state: string) => ({
  id_player: name.length + latest?.length! || Math.random(), player_name: name,
  player_os: 'linux-x64', status: 'online', current_version: cur, latest_version: latest,
  up_to_date: state === 'up_to_date', update_state: state, site: 'Site-01', groups: [],
})

const PARC = {
  players: [
    { ...row('A-jour', '2.0.0', '2.0.0', 'up_to_date'), id_player: 1 },
    { ...row('En-retard', '1.0.0', '2.0.0', 'outdated'), id_player: 2 },
    { ...row('Sans-reference', '1.5.0', null, 'unknown'), id_player: 3 },
  ],
  total: 3, outdated: 1, unknown: 1,
}

async function setup(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(({ u }) => {
    const b64url = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const tk = [
      b64url({ alg: 'HS256', typ: 'JWT' }),
      b64url({ sub: '1', org: 1, roles: ['CMS_ORG_ADMIN'], locale: 'en', type: 'access', exp: 9999999999 }),
      'signature',
    ].join('.')
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: 'mock_refresh', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, { u: USER })

  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  // ⚠️ Playwright résout les routes de la DERNIÈRE à la première : le glob générique en premier.
  await page.route('**/api/v1/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill(json({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' })))
  await page.route('**/api/v1/updates/parc**', (r) => r.fulfill(json(PARC)))
  await page.goto(`${BASE}/settings/updates`)
  await expect(page.getByText('Sans-reference')).toBeVisible()
}

test('un ecran sans version publiee est Inconnu, pas A jour', async ({ page }) => {
  await setup(page)
  const sans = page.locator('tr', { hasText: 'Sans-reference' })
  await expect(sans).toContainText('Unknown')
  // Ce qu'il ne doit SURTOUT pas dire — c'était le défaut.
  await expect(sans).not.toContainText('Up to date')
  // Les deux autres états restent inchangés (non-régression).
  await expect(page.locator('tr', { hasText: 'A-jour' })).toContainText('Up to date')
  await expect(page.locator('tr', { hasText: 'En-retard' })).toContainText('Behind')
})

test("l'en-tete compte les inconnus a part des en-retard", async ({ page }) => {
  await setup(page)
  const head = page.locator('div', { hasText: /outdated/ }).last()
  await expect(head).toContainText('1 outdated')
  await expect(head).toContainText('1 Unknown')
})

test('le filtre d etat distingue les trois', async ({ page }) => {
  await setup(page)
  const sel = page.locator('select').filter({ hasText: 'Up to date' })
  await sel.selectOption('unknown')
  await expect(page.getByText('Sans-reference')).toBeVisible()
  await expect(page.getByText('A-jour')).toHaveCount(0)
  await sel.selectOption('up_to_date')
  await expect(page.getByText('A-jour')).toBeVisible()
  await expect(page.getByText('Sans-reference')).toHaveCount(0)
})

// La liste des versions ne peut plus être écrasée par l'inventaire du parc.
//
// Le partage de hauteur était FIXE (parc `flex-1`, bloc du bas `flex-[1.15]`) : un parc de 2 lignes
// gardait ~350 px de vide pendant que la liste des versions, sous un formulaire incompressible,
// tombait à 74 px — une ligne pour 121 versions. Mesuré, pas supposé.
test('la liste des versions garde une hauteur utile quand le parc est court', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await setup(page)
  const liste = page.locator('ul.divide-y').first()
  const box = await liste.boundingBox()
  expect(box).not.toBeNull()
  expect(box!.height).toBeGreaterThan(120)
  // Et la page reste verrouillée au viewport : aucun défilement de fenêtre.
  const deborde = await page.evaluate(() =>
    document.documentElement.scrollHeight > document.documentElement.clientHeight + 1)
  expect(deborde).toBe(false)
})
