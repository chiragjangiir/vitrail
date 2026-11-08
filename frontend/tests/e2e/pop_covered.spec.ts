import { test, expect } from '@playwright/test'

// PROOF OF PLAY — motif « zone recouverte » (migr 0125).
//
// Une preuve émise par une zone masquée par un overlay plein écran (spot de campagne P3.6
// ou takeover VOD) n'est comptée dans aucun agrégat d'antenne. La vue forensique, elle, DOIT
// la montrer et NOMMER la cause : la masquer rendrait le phénomène indétectable, et confondre
// les deux causes empêcherait de savoir laquelle corriger (écran éteint ≠ zone masquée —
// dans le second cas l'écran est allumé et le reste du contenu est bien diffusé).
//
// Ces specs affirment le RÉSULTAT AFFICHÉ, jamais la structure du composant.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye', avatar_url: null,
  totp_enabled: false, locale: 'en', is_active: true, last_login_at: null,
  created_at: new Date().toISOString(), permissions: ['reports:read', 'reports:export'],
}

const row = (id: number, name: string, extra: Record<string, unknown>) => ({
  id_pop: id, id_player: 4, player_name: 'RPi Entree', id_media: 143, media_name: name,
  played_at: '2026-08-07T12:00:00Z', duration_ms: 10000, signed: true,
  merkle_hash: `h${id}`, is_document: false, screen_off: false, covered: false, ...extra,
})

const ROWS = [
  row(3, 'Spot bien vu', {}),                        // comptée
  row(2, 'Zone masquee', { covered: true }),          // non comptée — overlay plein écran
  row(1, 'Ecran eteint', { screen_off: true }),       // non comptée — autre cause
]

async function setup(page: import('@playwright/test').Page, rows = ROWS) {
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
  await page.route('**/api/v1/players/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/sites/**', (r) => r.fulfill(json([])))
  // ⚠️ Le glob doit tolérer la query string : `**/pop/plays` ne matcherait PAS
  // `/pop/plays?from=…` et la requête partirait sur le réseau réel, page vide sans erreur
  // (piège vécu le 21/07 sur les specs du portail).
  await page.route('**/api/v1/pop/plays**', (r) =>
    r.fulfill(json({ total: rows.length, limit: 50, offset: 0, rows })))
  await page.route('**/api/v1/pop/archives**', (r) => r.fulfill(json({ total: 0, rows: [] })))
}

test('une preuve de zone recouverte est affichee et NOMMEE', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await page.goto(`${BASE}/reports/proof-of-play`)
  // La requête n'est armée qu'au clic (`enabled: committed !== null`) : sans ce geste la
  // page reste vide et TOUTES les assertions passeraient/échoueraient pour la mauvaise
  // raison. On part donc du geste réel de l'utilisateur.
  await page.getByRole('button', { name: 'Generate' }).click()

  // La ligne existe : on n'a pas masqué la preuve, on a neutralisé son comptage.
  await expect(page.getByText('Zone masquee')).toBeVisible()
  await expect(page.getByText('Zone covered')).toBeVisible()
})

test('les deux causes de non-comptage sont DISTINGUABLES', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await page.goto(`${BASE}/reports/proof-of-play`)
  // La requête n'est armée qu'au clic (`enabled: committed !== null`) : sans ce geste la
  // page reste vide et TOUTES les assertions passeraient/échoueraient pour la mauvaise
  // raison. On part donc du geste réel de l'utilisateur.
  await page.getByRole('button', { name: 'Generate' }).click()

  // Écran coupé et zone recouverte ne se corrigent pas de la même façon : un libellé
  // commun (« non comptée ») laisserait l'exploitant sans piste.
  await expect(page.getByText('Zone covered')).toHaveCount(1)
  await expect(page.getByText('Screen off')).toHaveCount(1)
})

test('une preuve normale ne porte AUCUN motif de non-comptage', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, [ROWS[0]])
  await page.goto(`${BASE}/reports/proof-of-play`)
  // La requête n'est armée qu'au clic (`enabled: committed !== null`) : sans ce geste la
  // page reste vide et TOUTES les assertions passeraient/échoueraient pour la mauvaise
  // raison. On part donc du geste réel de l'utilisateur.
  await page.getByRole('button', { name: 'Generate' }).click()

  // Témoin : sans lui, un composant qui afficherait le motif sur TOUTES les lignes
  // passerait les deux specs ci-dessus.
  await expect(page.getByText('Spot bien vu')).toBeVisible()
  await expect(page.getByText('Zone covered')).toHaveCount(0)
  await expect(page.getByText('Screen off')).toHaveCount(0)
})
