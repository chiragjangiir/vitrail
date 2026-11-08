import { test, expect } from '@playwright/test'

// Réglages → Clés IA : l'offre et le solde du fournisseur, lus en direct.
//
// Pourquoi ce test existe : l'écran des clés ne disait RIEN de ce que l'abonnement permet.
// Un client BYOK sur une offre gratuite découvrait la limite au moment de la génération —
// et, jusqu'au 2026-08-04, sous la forme d'une « erreur réseau », donc en accusant le
// mauvais coupable. Le panneau rend l'information visible AVANT d'écrire un texte.
//
// Deux règles sont verrouillées ici, parce qu'elles sont contre-intuitives :
//   · un fournisseur qui n'expose pas d'abonnement (`supported: false`) n'affiche RIEN —
//     on ne feint pas une abstraction sur un seul fournisseur ;
//   · une lecture impossible n'est PAS un solde à zéro : le serveur renvoie sa phrase,
//     et c'est elle qu'on montre, jamais une barre vide qui ferait croire au pire.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye',
  avatar_url: null, totp_enabled: false, locale: 'fr', is_active: true,
  last_login_at: null, created_at: new Date().toISOString(),
}

const KEYS = [
  { provider: 'fal', key_last4: '1234', status: 'unverified', validated_at: null, updated_at: new Date().toISOString() },
  { provider: 'elevenlabs', key_last4: '9876', status: 'valid', validated_at: new Date().toISOString(), updated_at: new Date().toISOString() },
]

type Plan = Record<string, unknown>

async function setup(page: import('@playwright/test').Page, elevenPlan: Plan) {
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
    // ⚠️ La langue est servie par next-intl DEPUIS LE COOKIE, lu côté serveur : la poser
    // dans localStorage ne rend rien en français, et les assertions échoueraient sur des
    // libellés anglais sans que la fonctionnalité soit en cause.
    document.cookie = 'locale=fr; path=/'
  }, USER)

  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route('**/api/v1/**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill(json({ access_token: 'x', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'fr' })))
  await page.route('**/api/v1/orgs/1/ai-keys', (r) => r.fulfill(json(KEYS)))
  // ⚠️ Le glob doit matcher l'URL AVEC sa query : `**` en fin de motif, sinon la requête
  // part sur le réseau réel et le panneau reste vide SANS erreur (piège documenté).
  await page.route('**/api/v1/orgs/1/ai-keys/elevenlabs/plan**', (r) => r.fulfill(json(elevenPlan)))
  await page.route('**/api/v1/orgs/1/ai-keys/fal/plan**', (r) => r.fulfill(json({
    provider: 'fal', supported: false, tier: null, used: null, limit: null,
    remaining: null, resets_at: null,
    detail: "Ce fournisseur n'expose pas d'abonnement interrogeable.",
  })))
  await page.goto(`${BASE}/settings/ai-keys`)
}

test('le solde du compte ElevenLabs est affiché avant toute génération', async ({ page }) => {
  await setup(page, {
    provider: 'elevenlabs', supported: true, tier: 'starter', used: 9000, limit: 30000,
    remaining: 21000, resets_at: '2026-09-01T00:00:00Z', detail: null,
  })

  await expect(page.getByText('Offre et solde')).toBeVisible()
  await expect(page.getByText('starter')).toBeVisible()
  // Le chiffre qui compte : ce qui RESTE, pas ce qui a été consommé.
  await expect(page.getByText(/21[\s  ,.]?000/)).toBeVisible()
})

test("un fournisseur sans abonnement interrogeable n'affiche pas de panneau", async ({ page }) => {
  await setup(page, {
    provider: 'elevenlabs', supported: true, tier: 'starter', used: 0, limit: 30000,
    remaining: 30000, resets_at: null, detail: null,
  })
  // fal a une clé enregistrée, donc sa carte est là — mais sans panneau d'offre.
  await expect(page.getByRole('heading', { name: /fal\.ai/ })).toBeVisible()
  await expect(page.getByText("n'expose pas d'abonnement")).toHaveCount(0)
  await expect(page.getByText('Offre et solde')).toHaveCount(1)   // celui d'ElevenLabs seul
})

test('un abonnement illisible affiche la raison, jamais un solde à zéro', async ({ page }) => {
  await setup(page, {
    provider: 'elevenlabs', supported: true, tier: null, used: null, limit: null,
    remaining: null, resets_at: null,
    detail: 'clé ElevenLabs refusée (401) : Invalid API key',
  })

  await expect(page.getByText('Invalid API key')).toBeVisible()
  await expect(page.getByText('Offre et solde')).toHaveCount(0)   // pas de barre trompeuse
})
