import { test, expect } from '@playwright/test'

// Barre d'avancement des encodages (2026-08-03). Ces specs affirment le RÉSULTAT AFFICHÉ
// — la barre existe, elle porte la bonne valeur, elle disparaît quand l'encodage est fini —
// jamais la structure interne du composant.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye', avatar_url: null,
  totp_enabled: false, locale: 'en', is_active: true, last_login_at: null,
  created_at: new Date().toISOString(), permissions: ['media:read', 'media:edit', 'media:create'],
}
const FOLDERS = [
  { id_folder: 1, id_org: 1, parent_id: null, folder_name: 'Video', depth: 0, path: '1', child_count: 0, media_count: 3, full_path: 'Video', created_at: '2026-01-01T00:00:00Z' },
]

const mk = (id: number, name: string, status: string, progress: unknown) => ({
  id_media: id, media_name: name, media_type: 'video', mime_type: null,
  file_size_bytes: 5_000_000, served_size_bytes: null, duration_ms: null, thumbnail_url: null,
  source: 'upload', attribution_text: null, transcode_status: status, encode_mode: 'auto',
  conformance_status: null, not_before_utc: null, embargo_event_id: null,
  embargo_event_name: null, tags: [], id_folder: 1, created_at: '2026-08-03T10:00:00Z',
  encode_progress: progress,
})

const MEDIA = [
  // En cours, durée connue → barre déterminée + temps restant
  mk(1, 'En cours', 'processing', { phase: 'encode', pct: 42, eta_s: 310, speed: 1.8, at: 1 }),
  // En cours, durée INCONNUE → barre indéterminée, aucun pourcentage inventé
  mk(2, 'Sans duree', 'processing', { phase: 'encode', at: 1 }),
  // Terminé → aucune barre
  mk(3, 'Termine', 'done', null),
]

async function setup(page: import('@playwright/test').Page, media = MEDIA) {
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
  await page.route('**/api/v1/media/folders**', (r) => r.fulfill(json(FOLDERS)))
  await page.route('**/api/v1/media/stats**', (r) => r.fulfill(json({ total: 3, by_type: { video: 3 } })))
  await page.route('**/api/v1/media/usage-summary**', (r) => r.fulfill(json({})))
  await page.route('**/api/v1/media/*/usage', (r) => r.fulfill(json({ summary: {}, screens: [] })))
  await page.route('**/api/v1/media/?*', (r) => r.fulfill(json(media)))
  await page.route('**/api/v1/media/1', (r) =>
    r.fulfill(json({ ...media[0], id_org: 1, width: null, height: null, isrc: null,
                     rights_metadata: {}, media_metadata: {}, cdn_url_signed: null,
                     updated_at: '2026-08-03T10:00:00Z' })))
  await page.route('**/api/v1/tags/namespaces**', (r) => r.fulfill(json([])))
  await page.route('**/api/v1/generation/**', (r) => r.fulfill(json([])))
}

// La vue d'accueil « N derniers par type » a ses PROPRES grilles : partir de /media nu ne
// montrerait pas la liste. Piège vécu le 2026-07-28 — 6 specs vertes sur un produit cassé.
async function gotoFolder(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/media`)
  await page.getByTestId('folder-tree').getByRole('button', { name: 'Video' }).click()
}

test('la liste montre une barre determinee avec le pourcentage et le temps restant', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await gotoFolder(page)
  await page.getByRole('button', { name: /list/i }).click().catch(() => {})

  const bar = page.getByTestId('encode-progress').first()
  await expect(bar).toBeVisible()
  // La valeur affichée VIENT du serveur : c'est ce qui prouve le câblage bout en bout.
  await expect(bar.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '42')
  await expect(page.getByText('42 %')).toBeVisible()
  await expect(page.getByText(/5 min/)).toBeVisible()   // 310 s → « 5 min restant »
})

test('sans duree connue aucun pourcentage n est invente', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page)
  await gotoFolder(page)

  // Le média 2 a une progression SANS pct : la barre est là (il se passe quelque chose)
  // mais elle ne porte pas de valeur — annoncer « 0 % » serait un chiffre faux.
  const bars = page.getByTestId('encode-progress')
  await expect(bars.first()).toBeVisible()
  const indeterminate = bars.nth(1).getByRole('progressbar')
  await expect(indeterminate).not.toHaveAttribute('aria-valuenow', /.+/)
})

test('un media termine n affiche aucune barre', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, [MEDIA[2]])
  await gotoFolder(page)

  await expect(page.getByText('Termine')).toBeVisible()
  await expect(page.getByTestId('encode-progress')).toHaveCount(0)
})

// ── Décision d'encodage (étalonnage, bandes) ───────────────────────────────────

const DECISION = {
  band: 'confirm' as const,
  estimate_s: 2400,
  measured_speed: 0.39,
  width: 3840, height: 2160, encoder: 'libx265',
  resolved: false,
  downscale: [
    { profile: 'fhd', box: 1920, estimate_s: 600 },
    { profile: 'hd720', box: 1280, estimate_s: 260 },
  ],
}
const AWAITING = [{
  ...mk(9, 'Trop lourd', 'awaiting_decision', null),
  encode_decision: DECISION,
}]

test('un media en attente reste VISIBLE dans la mediatheque avec son badge', async ({ page }) => {
  // Décision d'Ed : rien ne se lance sans un geste, mais le média ne disparaît pas —
  // un média oublié doit rester réparable.
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, AWAITING)
  await gotoFolder(page)
  await expect(page.getByText('Trop lourd')).toBeVisible()
  await expect(page.getByText('Decision needed').first()).toBeVisible()
})

test('le tiroir propose la definition inferieure ET envoie le bon profil', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await setup(page, AWAITING)
  await page.route('**/api/v1/media/9', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      ...AWAITING[0], id_org: 1, width: 3840, height: 2160, isrc: null,
      rights_metadata: {}, media_metadata: {}, cdn_url_signed: null,
      updated_at: '2026-08-03T10:00:00Z',
    }) }))

  let posted: Record<string, unknown> | null = null
  await page.route('**/api/v1/media/9/encode-decision', async (r) => {
    posted = JSON.parse(r.request().postData() ?? '{}')
    await r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ id_media: 9, transcode_status: 'pending', downscale_box: 1920 }) })
  })

  await gotoFolder(page)
  await page.getByTitle('Edit').first().click()

  // Ce qui compte : l'utilisateur voit la DURÉE de chaque option — c'est ce qui
  // transforme un refus en choix.
  await expect(page.getByText('This encode will take a while')).toBeVisible()
  await expect(page.getByRole('button', { name: /Encode at 1080p \(10 min\)/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Run it anyway \(40 min\)/ })).toBeVisible()

  await page.getByRole('button', { name: /Encode at 1080p/ }).click()
  await expect.poll(() => posted).toEqual({ action: 'downscale', profile: 'fhd' })
})

test('le tiroir se met a jour TOUT SEUL pendant l encodage', async ({ page }) => {
  // 🔴 Constat d'Ed (03/08) : le tiroir s'ouvre juste apres un upload et restait fige sur
  // « en cours » + barre a 0 % pendant tout l'encodage, alors que la grille derriere
  // avancait. Il fallait fermer et rouvrir pour voir la verite.
  await page.setViewportSize({ width: 1600, height: 900 })
  const encoding = { ...mk(9, 'En encodage', 'processing', { phase: 'encode', pct: 12, eta_s: 300, speed: 1.1, at: 1 }) }
  await setup(page, [encoding])

  let appels = 0
  await page.route('**/api/v1/media/9', (r) => {
    appels += 1
    // A partir du 3e appel, le serveur repond « termine » : c'est ce que le tiroir doit
    // refleter sans qu'on touche a rien.
    const body = appels >= 3
      ? { ...encoding, transcode_status: 'done', encode_progress: null }
      : { ...encoding, encode_progress: { phase: 'encode', pct: 12 + appels * 20, eta_s: 200, speed: 1.1, at: 1 } }
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      ...body, id_org: 1, width: 1920, height: 1080, isrc: null, rights_metadata: {},
      media_metadata: {}, cdn_url_signed: null, updated_at: '2026-08-03T10:00:00Z',
    }) })
  })

  await gotoFolder(page)
  await page.getByTitle('Edit').first().click()

  // On raisonne DANS le tiroir : la grille derriere lui garde sa propre barre (sa
  // requete de liste n'a pas change), une assertion a l'echelle de la page mesurerait
  // les deux et ne dirait rien du tiroir.
  const tiroir = page.getByRole('dialog')
  await expect(tiroir.getByTestId('encode-progress')).toHaveCount(1)

  // ... et SANS AUCUNE interaction, le tiroir doit finir par montrer « pret ».
  await expect(tiroir.getByText('Ready')).toBeVisible({ timeout: 15_000 })
  await expect(tiroir.getByTestId('encode-progress')).toHaveCount(0)
  expect(appels).toBeGreaterThan(1)   // il a bien re-interroge le serveur
})
