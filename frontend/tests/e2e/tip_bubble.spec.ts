import { test, expect } from '@playwright/test'

// La bulle d'aide ne doit plus rendre d'action inatteignable (audit de toutes les pages, 2026-08-10).
//
// Son commentaire affirmait « la bulle ne doit jamais masquer une action » — vrai des TIROIRS
// (z-50), faux du contenu de page (z-10). Mesuré sur 38 pages × 2 hauteurs : 20 éléments
// interactifs renvoyaient la bulle sous `elementFromPoint`, donc étaient réellement incliquables —
// et sur une page verrouillée au viewport, aucun défilement ne permet de les dégager.
// Ce que ces tests figent : la bulle se RANGE (elle ne se ferme pas — le compte démo garde sa
// visite guidée), et une fois rangée elle libère la zone.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye',
  avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, is_demo: false,
  last_login_at: null, created_at: new Date().toISOString(),
}

async function setup(page: import('@playwright/test').Page, demo: boolean) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(({ u }) => {
    localStorage.clear()
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
  }, { u: { ...USER, is_demo: demo } })

  const json = (b: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(b) })
  await page.route('**/api/v1/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json({ ...USER, is_demo: demo })))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill(json({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' })))
  await page.goto(`${BASE}/players`)
  await expect(page.getByTestId('tip-bubble')).toBeVisible()
}

test('la bulle se range en pastille et libere la place', async ({ page }) => {
  await setup(page, false)
  const bulle = await page.getByTestId('tip-bubble').boundingBox()
  expect(bulle).not.toBeNull()

  await page.getByTestId('tip-collapse').click()
  await expect(page.getByTestId('tip-bubble')).toHaveCount(0)
  const pastille = page.getByTestId('tip-pill')
  await expect(pastille).toBeVisible()

  // La mesure qui compte : la surface occupée s'effondre. Une bulle « rangée » qui garderait
  // sa taille ne corrigerait rien — c'est la place reprise, pas le changement d'apparence.
  const box = (await pastille.boundingBox())!
  expect(box.width).toBeLessThan(56)
  expect(box.height).toBeLessThan(56)
  expect(box.width * box.height).toBeLessThan(bulle!.width * bulle!.height / 4)

  // Et le point qui était couvert est rendu : plus rien de la bulle n'y répond.
  const pointLibre = await page.evaluate(([x, y]) => {
    const e = document.elementFromPoint(x, y)
    return !!e && !e.closest('[data-testid="tip-pill"]')
  }, [Math.round(bulle!.x + 20), Math.round(bulle!.y + 20)])
  expect(pointLibre).toBe(true)
})

test('ranger n est pas fermer : la pastille redeploie la bulle', async ({ page }) => {
  await setup(page, false)
  await page.getByTestId('tip-collapse').click()
  await page.getByTestId('tip-pill').click()
  await expect(page.getByTestId('tip-bubble')).toBeVisible()
})

test('un compte demo peut ranger la bulle mais jamais la fermer', async ({ page }) => {
  await setup(page, true)
  const bulle = page.getByTestId('tip-bubble')
  // ⛔ Pas de croix en démo : la visite guidée ne se perd pas (décision Ed 2026-07-10).
  await expect(bulle.getByRole('button', { name: /dismiss/i })).toHaveCount(0)
  await expect(page.getByTestId('tip-collapse')).toBeVisible()
  await page.getByTestId('tip-collapse').click()
  await expect(page.getByTestId('tip-pill')).toBeVisible()
})

test('changer de page redeploie la bulle (rangee, pas oubliee)', async ({ page }) => {
  await setup(page, false)
  await page.getByTestId('tip-collapse').click()
  await expect(page.getByTestId('tip-pill')).toBeVisible()
  await page.goto(`${BASE}/media`)
  // Rangé n'est pas persisté : sinon un seul clic ferait disparaître l'aide de tout le produit.
  await expect(page.getByTestId('tip-bubble')).toBeVisible()
})

// Le point décisif, mesuré APRÈS un premier déploiement qui n'a rien corrigé : rendre la bulle
// repliable ne suffisait pas — elle s'ouvre dépliée, donc 22 éléments restaient incliquables tant
// que l'utilisateur n'avait pas deviné le bouton. Un clic doit TRAVERSER la bulle.
test('un clic traverse la bulle et atteint ce qui est dessous', async ({ page }) => {
  await setup(page, false)
  const b = (await page.getByTestId('tip-bubble').boundingBox())!
  // Point au cœur du texte de la bulle : ce qui répond doit être la PAGE, pas la bulle.
  const dessous = await page.evaluate(([x, y]) => {
    const e = document.elementFromPoint(x, y)
    return e ? !e.closest('[data-testid="tip-bubble"]') : false
  }, [Math.round(b.x + b.width / 2), Math.round(b.y + b.height - 12)])
  expect(dessous).toBe(true)

  // …mais ses propres boutons restent cliquables, sinon on ne pourrait plus la ranger.
  await page.getByTestId('tip-collapse').click()
  await expect(page.getByTestId('tip-pill')).toBeVisible()
})
