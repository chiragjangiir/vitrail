import { test, expect } from '@playwright/test'

// « Est-ce que ça rentre ? » — avertissement de stockage AU MOMENT DE L'AFFECTATION.
//
// Le 2026-08-06, une playlist de 1,85 Go affectée à un écran de 4 Go a rempli son disque à
// 100 % et cassé Android : l'appareil n'a pu être récupéré qu'en désinstallant l'app. Le
// frein embarqué empêche désormais la casse — mais sans cet avertissement, l'écran
// diffuserait une playlist tronquée sans que personne ne sache pourquoi.
//
// Ces specs affirment un RÉSULTAT : ce que l'exploitant VOIT, et ce que le tiroir ENVOIE.
// Le point de conception qu'elles figent : on transmet les **cibles canoniques et la
// playlist**, pas des listes résolues — c'est le serveur qui déplie le ciblage et les
// sous-playlists. Résoudre côté écran ferait porter le contrôle sur autre chose que ce qui
// sera réellement diffusé.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }
const SITES = [{ id_site: 2, site_name: 'Store Lyon', latitude: 45.76, longitude: 4.83 }]
const PLAYERS = [
  { id_player: 9, player_name: 'Lyon Entrance', status: 'online', player_os: 'linux', id_site: 2 },
  { id_player: 10, player_name: 'Lyon Butcher', status: 'online', player_os: 'linux', id_site: 2 },
]

async function auth(page: import('@playwright/test').Page, url: string) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => {
    const tk = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.sig'
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }, accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
  })
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER_ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'x', refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))
  await page.goto(url)
}

// ⚠️ Regex et non glob : un glob ne matche pas la query string (piège § Frontend).
async function mockPage(
  page: import('@playwright/test').Page,
  fit: Record<string, unknown>,
  onCheck?: (b: Record<string, unknown>) => void,
) {
  await page.route(/\/api\/v1\/players\/storage-check$/, async (route) => {
    onCheck?.(route.request().postDataJSON())
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fit) })
  })
  await page.route(/\/api\/v1\/schedules(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/events(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/campaigns\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(/\/api\/v1\/playlists\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id_playlist: 10, playlist_name: 'PL', sync_mode: 'wall_clock', sync_ready: true }]) }))
  await page.route(/\/api\/v1\/sites(\/)?(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) }))
  await page.route(/\/api\/v1\/players\/(\?.*)?$/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) }))
  for (const re of [/\/api\/v1\/player-groups\/(\?.*)?$/, /\/api\/v1\/site-groups\/(\?.*)?$/,
                    /\/api\/v1\/audio-baskets(\?.*)?$/, /\/api\/v1\/governance\/nodes(\?.*)?$/]) {
    await page.route(re, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  }
  await page.route(/\/api\/v1\/schedules\/hdmi-check/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ has_hdmi_item: false, incompatible_players: [] }) }))
  await page.route(/tile\.|openstreetmap|basemaps/, (r) => r.abort())
}

/** Ouvre le tiroir, choisit la playlist et coche un écran — le geste réel d'affectation. */
async function assignContentToAScreen(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'New schedule' }).click()
  const drawer = page.getByRole('dialog', { name: 'New schedule' })
  await drawer.getByRole('textbox').first().fill('Prog stockage')
  await drawer.getByTestId('schedule-playlist-select').click()
  await page.getByTestId('content-playlist-10').click()
  await drawer.getByRole('button', { name: /Target players/ }).click()
  await drawer.getByText('Lyon Entrance').click()
  return drawer
}

const INSUFFICIENT = {
  worst: 'insufficient',
  required_bytes: 1_940_000_000,
  players: [{
    id_player: 9, player_name: 'Lyon Entrance', verdict: 'insufficient',
    reason: 'trop gros', required_bytes: 1_940_000_000, missing_count: 6,
    free_bytes: 1_280_000_000, disk_total_bytes: 4_000_000_000,
  }],
}

test.describe('Stockage — avertissement à l’affectation', () => {
  test('storage_banner_names_the_screen_that_cannot_hold_the_content', async ({ page }) => {
    await mockPage(page, INSUFFICIENT)
    await auth(page, `${BASE}/schedules`)
    const drawer = await assignContentToAScreen(page)

    const banner = drawer.getByTestId('storage-fit-banner')
    await expect(banner).toBeVisible()
    await expect(banner).toHaveAttribute('data-verdict', 'insufficient')
    // On NOMME l'écran : « un écran est plein » sans dire lequel oblige à chercher.
    await expect(banner).toContainText('Lyon Entrance')
    // Et on dit la conséquence, pas seulement « pas de place ».
    await expect(banner).toContainText(/only play part/i)
  })

  test('storage_banner_is_silent_when_everything_fits', async ({ page }) => {
    // Témoin indispensable : sans lui, une bannière affichée EN PERMANENCE passerait le
    // test précédent — et un bandeau toujours là finit par ne plus être lu.
    await mockPage(page, { worst: 'ok', required_bytes: 10, players: [] })
    await auth(page, `${BASE}/schedules`)
    const drawer = await assignContentToAScreen(page)
    await expect(drawer.getByTestId('storage-fit-banner')).toHaveCount(0)
  })

  test('a_park_with_brightsign_does_not_get_a_permanent_banner', async ({ page }) => {
    // Cas MESURÉ sur la prod le 2026-08-06 : les 2 BrightSign rendent `unknown` parce
    // qu'ils ne PEUVENT pas remonter l'espace de leur carte SD — et c'est définitif. Si
    // `unknown` levait la bannière, elle serait affichée à CHAQUE affectation touchant un
    // BrightSign, et plus personne ne la lirait le jour où elle dit « insuffisant ».
    await mockPage(page, {
      worst: 'unknown', required_bytes: 1_940_000_000,
      players: [
        { id_player: 9, player_name: 'Lyon Entrance', verdict: 'ok', reason: '', required_bytes: 0, missing_count: 0, free_bytes: 90_000_000_000, disk_total_bytes: 120_000_000_000 },
        { id_player: 12, player_name: 'BrightSign XT1144', verdict: 'unknown', reason: '', required_bytes: 0, missing_count: 0, free_bytes: null, disk_total_bytes: null },
      ],
    })
    await auth(page, `${BASE}/schedules`)
    const drawer = await assignContentToAScreen(page)
    await expect(drawer.getByTestId('storage-fit-banner')).toHaveCount(0)
  })

  test('unverifiable_screens_are_named_when_the_banner_IS_shown', async ({ page }) => {
    // Ne pas crier ne veut pas dire cacher : quand la bannière est là pour une VRAIE
    // raison, on dit aussi ce qui n'a pas pu être contrôlé — sinon on laisse croire que
    // tous les autres écrans sont verts.
    await mockPage(page, {
      worst: 'insufficient', required_bytes: 1_940_000_000,
      players: [
        ...INSUFFICIENT.players,
        { id_player: 12, player_name: 'BrightSign XT1144', verdict: 'unknown', reason: '', required_bytes: 0, missing_count: 0, free_bytes: null, disk_total_bytes: null },
      ],
    })
    await auth(page, `${BASE}/schedules`)
    const drawer = await assignContentToAScreen(page)
    await expect(drawer.getByTestId('storage-fit-banner')).toBeVisible()
    await expect(drawer.getByTestId('storage-fit-unverifiable')).toContainText(/could not be checked/i)
  })

  test('storage_check_sends_targets_and_playlist_for_the_SERVER_to_resolve', async ({ page }) => {
    // Le point de conception : l'écran n'envoie NI liste d'écrans résolue NI liste de
    // médias. Résoudre ici dupliquerait le ciblage et le dépliage des sous-playlists, et
    // le contrôle porterait sur autre chose que ce qui sera diffusé.
    let body: Record<string, unknown> | null = null
    await mockPage(page, INSUFFICIENT, (b) => { body = b })
    await auth(page, `${BASE}/schedules`)
    await assignContentToAScreen(page)

    await expect.poll(() => body).toMatchObject({
      id_playlist: 10,
      targets: [{ target_type: 'player', target_id: 9 }],
    })
    expect((body as unknown as { id_medias?: number[] })?.id_medias ?? []).toEqual([])
  })
})
