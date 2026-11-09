import { test, expect } from '@playwright/test'

// PLAFONDS DE DÉPENSE BYOK — surface de réglage (P3.2).
//
// Ce que ces specs figent, et c'est un piège précis : `PATCH /orgs/{id}` filtre les valeurs
// nulles (`exclude_none=True`). Un champ vidé qui partirait en `undefined` ne serait donc PAS
// transmis, et le plafond resterait en place — un réglage qui SEMBLE effacé et ne l'est pas
// est pire que pas de réglage du tout. On envoie **0**, qui traverse le filtre et vaut
// « aucun plafond » (même convention que le crédit assistant juste au-dessus).

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'root@test.com', full_name: 'Root', avatar_url: null,
  totp_enabled: false, locale: 'en', is_active: true, last_login_at: null,
  created_at: '2026-01-01T00:00:00Z', permissions: [],
}

const ORG = {
  id_org: 4, org_name: 'Acme', org_slug: 'acme',
  is_active: true, rendition_policy: 'off', ai_quota_unit: 'tokens', ai_quota_tokens: null,
  ai_quota_eur: null, ai_quota_period: 'monthly', ai_alert_threshold_pct: 80,
  ai_byok_mode: 'strict', ai_spend_cap_usd: 50, ai_user_spend_cap_usd: 10,
  ai_spend_cap_period: 'month', created_at: '2026-01-01T00:00:00Z',
}

async function setup(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  await page.evaluate((u) => {
    const b64 = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const tk = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${b64({
      sub: '1', org: 1, roles: ['CMS_SUPER_ADMIN'], locale: 'en', type: 'access', exp: 9999999999,
    })}.sig`
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: 'r', roles: ['CMS_SUPER_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, USER)

  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  // ⚠️ Ordre : Playwright résout de la DERNIÈRE route enregistrée à la première.
  await page.route('**/api/v1/orgs**', (r) => r.fulfill(json([ORG])))
  await page.route('**/api/v1/orgs/ai-usage**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill(json({ access_token: 'x', refresh_token: 'r', token_type: 'bearer', locale: 'en' })))
}

test('les plafonds enregistres sont affiches', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await page.goto(`${BASE}/settings/orgs`)
  // `Acme` apparaît deux fois (nom + slug) : on vise la CELLULE du nom, pas le premier
  // texte venu — un sélecteur ambigu casse au moindre ajout de colonne.
  await page.getByRole('cell', { name: 'Acme', exact: true }).click()

  await expect(page.getByTestId('spend-cap-org')).toHaveValue('50')
  await expect(page.getByTestId('spend-cap-user')).toHaveValue('10')
})

test('vider un plafond envoie 0, jamais un champ absent', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  let sent: Record<string, unknown> | null = null
  await page.route('**/api/v1/orgs/4', (r) => {
    if (r.request().method() === 'PATCH') {
      sent = r.request().postDataJSON()
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ORG) })
    }
    return r.continue()
  })
  await page.goto(`${BASE}/settings/orgs`)
  // `Acme` apparaît deux fois (nom + slug) : on vise la CELLULE du nom, pas le premier
  // texte venu — un sélecteur ambigu casse au moindre ajout de colonne.
  await page.getByRole('cell', { name: 'Acme', exact: true }).click()

  // Attendre la valeur ENREGISTRÉE avant de vider : le tiroir s'ouvre avec des champs vides,
  // puis un effet y pose les valeurs de l'org. Vider trop tôt (runner rapide) laissait l'effet
  // remettre 50 par-dessus — et le test prouvait alors qu'on vide un champ déjà vide.
  await expect(page.getByTestId('spend-cap-org')).toHaveValue('50')
  await page.getByTestId('spend-cap-org').fill('')
  await page.getByTestId('spend-cap-save').click()

  // C'est le CORPS ENVOYÉ qui compte : un `undefined` serait filtré par le serveur et le
  // plafond survivrait à son propre effacement.
  await expect.poll(() => sent).not.toBeNull()
  expect(sent!.ai_spend_cap_usd).toBe(0)
  // Témoin : l'autre plafond, lui, n'a pas été touché et part avec sa valeur.
  expect(sent!.ai_user_spend_cap_usd).toBe(10)
})
