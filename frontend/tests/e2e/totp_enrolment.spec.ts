import { test, expect } from '@playwright/test'

// Enrôlement 2FA depuis l'écran de connexion — la porte qui n'existait pas.
//
// Avant le 2026-08-04, un administrateur à qui le second facteur est OBLIGATOIRE et qui ne
// l'avait pas encore voyait un panneau orange « configurez la double authentification » et…
// un bouton Retour. Rien d'autre. Le serveur répondait 403 sans jeton, et `/auth/totp/setup`
// exigeait un jeton d'accès que ce 403 empêchait d'obtenir : la boucle était fermée.
//
// Pire, mesuré en écrivant ce test : `/auth/totp/setup` et `/auth/totp/verify` n'avaient
// AUCUN appelant dans tout le frontend. Les deux endpoints existaient depuis le sprint IAM
// sans qu'aucun écran ne puisse les atteindre.
//
// Ce parcours est donc la fonctionnalité elle-même, pas un vernis : il verrouille qu'un
// compte refusé peut aller jusqu'au bout et se connecter.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

// 1×1 PNG transparent — le QR réel vient du serveur, seul compte le fait qu'il soit rendu.
const PNG_1PX =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

const SETUP = {
  secret: 'JBSWY3DPEHPK3PXP',
  qr_b64: PNG_1PX,
  backup_codes: ['aaa-111', 'bbb-222', 'ccc-333', 'ddd-444', 'eee-555',
                 'fff-666', 'ggg-777', 'hhh-888', 'iii-999', 'jjj-000'],
}

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin',
  avatar_url: null, totp_enabled: true, locale: 'fr', is_active: true,
  last_login_at: null, created_at: new Date().toISOString(), permissions: [],
}

const json = (body: unknown, status = 200) => ({
  status, contentType: 'application/json', body: JSON.stringify(body),
})

/** Le serveur tel qu'il répond à un org-admin non enrôlé, étape par étape. */
async function mockServer(
  page: import('@playwright/test').Page,
  opts: { enrolmentToken?: string | null } = {},
) {
  const token = opts.enrolmentToken === undefined ? 'ENROL.TOKEN.XYZ' : opts.enrolmentToken
  let enrolled = false

  // ⚠️ Playwright fait gagner la DERNIÈRE route enregistrée : le fourre-tout doit venir en
  // PREMIER, sinon il avale /auth/login et l'écran affiche « une erreur est survenue » sans
  // que rien du parcours ne soit exercé.
  await page.route('**/api/v1/**', (route) => route.fulfill(json([])))
  await page.route('**/api/v1/users/me', (route) => route.fulfill(json(USER)))

  await page.route('**/api/v1/auth/login', (route) => {
    const body = JSON.parse(route.request().postData() || '{}')
    if (!enrolled) {
      const detail: Record<string, unknown> = { message: '2FA obligatoire', force_2fa_setup: true }
      if (token) detail.enrolment_token = token
      return route.fulfill(json({ detail }, 403))
    }
    if (!body.totp_code) return route.fulfill(json({ detail: 'Code TOTP requis' }, 401))
    return route.fulfill(json({
      access_token: fakeJwt(), refresh_token: 'r', token_type: 'bearer', locale: 'fr',
    }))
  })

  await page.route('**/api/v1/auth/totp/setup', (route) => {
    // ⚠️ Le jeton d'enrôlement DOIT être présenté ici : c'est tout l'objet du correctif.
    const auth = route.request().headers()['authorization']
    if (auth !== `Bearer ${token}`) return route.fulfill(json({ detail: 'Token invalide' }, 401))
    return route.fulfill(json(SETUP))
  })

  await page.route('**/api/v1/auth/totp/verify', (route) => {
    const body = JSON.parse(route.request().postData() || '{}')
    if (body.secret !== SETUP.secret) return route.fulfill(json({ detail: 'Secret incohérent' }, 400))
    if (body.code !== '123456') return route.fulfill(json({ detail: 'Code TOTP invalide' }, 400))
    enrolled = true
    return route.fulfill({ status: 204, body: '' })
  })
}

function fakeJwt() {
  const b64url = (o: unknown) =>
    Buffer.from(JSON.stringify(o)).toString('base64')
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return [
    b64url({ alg: 'HS256', typ: 'JWT' }),
    b64url({ sub: '1', org: 1, roles: ['CMS_ORG_ADMIN'], locale: 'fr', type: 'access', exp: 9999999999 }),
    'signature',
  ].join('.')
}

async function signIn(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => { document.cookie = 'locale=fr; path=/' })
  await page.goto(`${BASE}/login`)
  await page.getByLabel(/e-mail|email/i).fill('admin@test.com')
  await page.getByLabel(/mot de passe/i).fill('Password1!')
  await page.getByRole('button', { name: /^Connexion$|^Se connecter$/ }).click()
}

test("un administrateur non enrôlé peut s'enrôler et entrer", async ({ page }) => {
  await mockServer(page)
  await signIn(page)

  // ① Le refus tend la main au lieu de fermer la porte.
  await expect(page.getByRole('button', { name: 'Configurer maintenant' })).toBeVisible()
  await page.getByRole('button', { name: 'Configurer maintenant' }).click()

  // ② Le QR est RENDU (un <img> vide passerait un test qui ne regarde que l'attribut src)
  //    et la clé est lisible pour une saisie manuelle.
  const qr = page.locator('img[src^="data:image/png;base64,"]')
  await expect(qr).toBeVisible()
  expect(await qr.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0)
  await expect(page.getByText(SETUP.secret)).toBeVisible()

  // ③ Le code active la 2FA.
  await page.getByLabel(/code/i).fill('123456')
  await page.getByRole('button', { name: 'Activer' }).click()

  // ④ Les codes de secours sont montrés UNE fois, tous.
  await expect(page.getByText('Double authentification activée')).toBeVisible()
  for (const code of SETUP.backup_codes) {
    await expect(page.getByText(code, { exact: true })).toBeVisible()
  }

  // ⑤ On repasse par /auth/login avec un code : une seule façon d'entrer.
  await page.getByRole('button', { name: 'Se connecter' }).click()
  await page.getByLabel(/code/i).fill('654321')
  await page.getByRole('button', { name: /Confirmer/ }).click()
  await page.waitForURL(/\/(dashboard|media|players)/, { timeout: 10_000 })
})

test('un code refusé garde la personne sur son enrôlement', async ({ page }) => {
  await mockServer(page)
  await signIn(page)
  await page.getByRole('button', { name: 'Configurer maintenant' }).click()
  await page.getByLabel(/code/i).fill('000000')
  await page.getByRole('button', { name: 'Activer' }).click()

  await expect(page.getByText('Code TOTP invalide')).toBeVisible()
  await expect(page.getByText(SETUP.secret)).toBeVisible()   // le secret reste affiché
})

test("sans jeton d'enrôlement, l'écran ne promet rien qu'il ne puisse tenir", async ({ page }) => {
  // Serveur antérieur au correctif : pas de bouton, plutôt qu'un bouton qui échouerait.
  await mockServer(page, { enrolmentToken: null })
  await signIn(page)
  await expect(page.getByText(/double authentification|2FA/i).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Configurer maintenant' })).toHaveCount(0)
})
