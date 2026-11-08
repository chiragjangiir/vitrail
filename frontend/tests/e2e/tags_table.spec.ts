import { test, expect } from '@playwright/test'

// /media/tags — passage des cartes au TABLEAU (retour Ed, audit du menu Média 2026-07-28).
// Le reproche mesuré : « suivant le nombre de tags des différents groupes, la dimension des
// vignettes de groupe de tags n'est pas la même ». Une carte prenait la hauteur de son
// contenu, donc un groupe à 2 valeurs et un groupe à 21 ne se ressemblaient pas — grille en
// escalier. Ce test vérifie la propriété qui doit tenir : des lignes de MÊME hauteur, quel
// que soit l'écart du nombre de valeurs.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye', avatar_url: null,
  totp_enabled: false, locale: 'en', is_active: true, last_login_at: null,
  created_at: new Date().toISOString(),
  permissions: ['media:read', 'media:edit'],
}

const val = (id: number, v: string) => ({
  id_tag: id, id_namespace: 1, tag_value: v, label: v, color: '#4875B4', sort_order: id,
})

// Écart volontairement extrême : 2 valeurs contre 21 — c'est ce qui déformait les cartes.
const NAMESPACES = [
  {
    id_namespace: 1, namespace_key: 'orientation', label: 'Orientation', match_mode: 'any',
    applies_to: ['image', 'video'], is_active: true, is_system: false,
    values: [val(1, 'landscape'), val(2, 'portrait')],
  },
  {
    id_namespace: 2, namespace_key: 'brand', label: 'Brand', match_mode: 'all',
    applies_to: ['image'], is_active: true, is_system: true,
    values: Array.from({ length: 21 }, (_, i) => val(100 + i, `brand-${i + 1}`)),
  },
]

async function setup(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  await page.evaluate((u) => {
    const b64 = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const tk = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${b64({
      sub: '1', org: 1, roles: ['CMS_ORG_ADMIN'], locale: 'en', type: 'access', exp: 9999999999,
    })}.sig`
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, USER)
  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill(json({ access_token: 'x', refresh_token: 'r', token_type: 'bearer', locale: 'en' })))
  await page.route('**/api/v1/tags/namespaces**', (r) => r.fulfill(json(NAMESPACES)))
}

test('tag groups render as rows of equal height', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await page.goto(`${BASE}/media/tags`)

  const rows = page.locator('tbody tr')
  await expect(rows).toHaveCount(2)

  // La propriété qui manquait : 2 valeurs vs 21 → même hauteur de ligne.
  const h1 = (await rows.nth(0).boundingBox())!.height
  const h2 = (await rows.nth(1).boundingBox())!.height
  expect(Math.abs(h1 - h2)).toBeLessThanOrEqual(2)

  // Le nombre de valeurs est une donnée lisible, plus une longueur de pastilles à estimer.
  await expect(rows.nth(0)).toContainText('2')
  await expect(rows.nth(1)).toContainText('21')
  // L'aperçu est borné : 4 pastilles + le reste compté, jamais les 21.
  await expect(rows.nth(1)).toContainText('+17')
})

test('clicking a group opens its full value list', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await page.goto(`${BASE}/media/tags`)

  await page.locator('tbody tr', { hasText: 'Brand' }).click()
  // Le tiroir porte le détail : les 21 valeurs y sont, alors que la ligne n'en montrait que 4.
  await expect(page.getByText('brand-21')).toBeVisible()
  await expect(page.getByText('brand-9')).toBeVisible()
})
