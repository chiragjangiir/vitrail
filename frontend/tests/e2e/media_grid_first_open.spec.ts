import { test, expect } from '@playwright/test'

/**
 * Régression vue par Ed le 2026-07-20 : à la PREMIÈRE ouverture de /media, la
 * vue d'accueil n'affichait que 5 vignettes par ligne quelle que soit la largeur
 * de l'écran ; en quittant la page et en y revenant, le nombre devenait correct.
 *
 * Cause : `useRef` + `useEffect([])` pour mesurer la zone de défilement. Au
 * premier rendu la page affiche un écran de chargement, donc `ref.current` vaut
 * `null` quand l'effet se joue — il sort et ne se rejoue jamais, laissant
 * `perRow` à sa valeur initiale de 5. Au retour, React Query sert le cache : la
 * grille est montée dès le premier rendu, la mesure a lieu. D'où « juste
 * seulement à partir de la 2e visite ». Corrigé par une CALLBACK REF.
 *
 * Le test compare la 1re ouverture (cache vide) à la 2e (cache chaud) : les deux
 * doivent demander le même nombre d'éléments par type.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'

const ME = {
  id_user: 1, id_org: 1, email: 'a@t.com', full_name: 'A', avatar_url: null,
  totp_enabled: false, locale: 'en', theme: 'dark', is_active: true, is_demo: false,
  id_advertiser: null, last_login_at: null, created_at: new Date().toISOString(),
  org_name: 'Org', roles: ['CMS_ORG_ADMIN'], permissions: [],
}

function item(i: number) {
  return {
    id_media: i, media_name: `m${i}`, media_type: 'image', mime_type: 'image/png',
    file_size_bytes: 1, duration_ms: null, thumbnail_url: null, source: 'upload',
    attribution_text: null, transcode_status: 'done', encode_mode: 'auto',
    conformance_status: 'ready', not_before_utc: null, embargo_event_id: null,
    embargo_event_name: null, tags: [], id_folder: null, created_at: new Date().toISOString(),
  }
}

test('landing_grid_measures_width_on_first_open', async ({ page }) => {
  // Large viewport : à 180px + 16px de gouttière, bien plus de 5 vignettes tiennent.
  await page.setViewportSize({ width: 1920, height: 1080 })

  const limits: number[] = []
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: TOKEN, refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  await page.route('**/api/v1/media/stats*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ total: 40, by_type: { image: 40 } }) }))
  await page.route('**/api/v1/media/folders*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/media\/\?/, (r) => {
    const u = new URL(r.request().url())
    // Requête de la vue d'accueil : `limit` = nb de vignettes tenant sur UNE ligne.
    if (u.searchParams.get('media_type')) limits.push(Number(u.searchParams.get('limit')))
    return r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(Array.from({ length: 20 }, (_, i) => item(i))) })
  })
  await page.route(/\/api\/v1\/(?!media|users\/me|auth)/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

  await page.goto(`${BASE}/login`)
  await page.evaluate((tk) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'a@t.com', roles: ['CMS_ORG_ADMIN'], permissions: [] },
        accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, TOKEN)

  // 1re ouverture, cache React Query vide.
  await page.goto(`${BASE}/media`)
  await expect.poll(() => limits.length, { timeout: 10_000 }).toBeGreaterThan(0)
  const firstOpen = Math.max(...limits)

  // La mesure doit refléter la largeur réelle, pas le repli initial de 5.
  expect(firstOpen).toBeGreaterThan(5)

  // 2e visite (cache chaud) : le nombre demandé doit être IDENTIQUE.
  limits.length = 0
  await page.goto(`${BASE}/templates`)
  await page.goto(`${BASE}/media`)
  await expect.poll(() => limits.length, { timeout: 10_000 }).toBeGreaterThan(0)
  expect(Math.max(...limits)).toBe(firstOpen)
})
