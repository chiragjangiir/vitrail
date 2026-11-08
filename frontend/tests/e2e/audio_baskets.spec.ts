import { test, expect } from '@playwright/test'

// Paniers audio — lecteur + drawer de recherche (demandes Ed 2026-07-29) :
// « comme pour le média, avoir un lecteur pour écouter les paniers et morceaux à
// sélectionner ; le drawer de recherche des contenus audio à l'image de celui de Media ».
// Le menu n'avait AUCUNE spec Playwright avant cet audit.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

// WAV silencieux de ~0,6 s généré ici même : assez court pour que l'enchaînement du
// lecteur se prouve vite, assez long pour que chaque morceau soit observable (un WAV de
// 0 échantillon enchaînait plus vite que les assertions). Aucun réseau réel.
function silentWavDataUri(seconds: number): string {
  const rate = 8000
  const n = Math.floor(rate * seconds)
  const buf = Buffer.alloc(44 + n)
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + n, 4); buf.write('WAVE', 8)
  buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20)
  buf.writeUInt16LE(1, 22); buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate, 28)
  buf.writeUInt16LE(1, 32); buf.writeUInt16LE(8, 34)
  buf.write('data', 36); buf.writeUInt32LE(n, 40)
  buf.fill(0x80, 44)  // silence 8-bit
  return 'data:audio/wav;base64,' + buf.toString('base64')
}
const WAV_DATA_URI = silentWavDataUri(0.6)

function basket(id: number, name: string, itemCount: number) {
  return {
    id_basket: id, id_org: 1, id_node: null, basket_name: name, basket_type: 'music',
    basket_scope: 'local', description: null, is_mandatory: false, min_ratio: 0,
    max_ratio: 100, ducking_config: {}, trigger_mode: 'tracks', trigger_value: 5,
    shuffle: false, is_active: true, item_count: itemCount, created_by: 1,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  }
}

function basketItem(idItem: number, idMedia: number, name: string) {
  return {
    id_item: idItem, id_basket: 1, id_media: idMedia, media_name: name,
    media_type: 'audio', duration_ms: 180000, weight: 1, valid_from: null,
    valid_until: null, rule_days: null, rule_time_start: null, rule_time_end: null,
    is_active: true, sort_order: idItem,
  }
}

function audioMedia(id: number, name: string) {
  return {
    id_media: id, media_name: name, media_type: 'audio', mime_type: 'audio/mpeg',
    file_size_bytes: 1234, served_size_bytes: null, duration_ms: 120000,
    thumbnail_url: null, source: 'upload', attribution_text: null,
    transcode_status: 'done', encode_mode: 'auto', conformance_status: null,
    not_before_utc: null, embargo_event_id: null, embargo_event_name: null,
    tags: [], id_folder: null,
  }
}

async function mockAuthAndNavigate(page: import('@playwright/test').Page, url: string) {
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => {
    const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
    const store = {
      state: {
        user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
        accessToken: mockToken, refreshToken: 'mock_refresh', roles: ['CMS_ORG_ADMIN'],
      },
      version: 0,
    }
    localStorage.setItem('sf-auth', JSON.stringify(store))
    localStorage.setItem('sf_access_token', mockToken)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  })
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER_ME) })
  })
  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature', refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }),
    })
  })
  await page.goto(url)
}

async function mockBasketRoutes(page: import('@playwright/test').Page) {
  await page.route(/\/api\/v1\/audio-baskets$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([basket(1, 'Pop Nationale', 2)]) })
  })
  await page.route(/\/api\/v1\/audio-baskets\/1\/items$/, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([basketItem(1, 10, 'track-one.mp3'), basketItem(2, 11, 'track-two.mp3')]),
    })
  })
  await page.route('**/api/v1/governance/nodes', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  // Détails médias : l'URL signée pointe un WAV silencieux (fin immédiate → enchaînement).
  for (const id of [10, 11, 20, 21]) {
    await page.route(new RegExp(`/api/v1/media/${id}$`), async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ...audioMedia(id, `media-${id}`), cdn_url_signed: WAV_DATA_URI }),
      })
    })
  }
}

// Le drawer audio interroge /media/stats, /media/folders puis /media/ (audio only).
async function mockPickerRoutes(page: import('@playwright/test').Page, onMediaQuery?: (params: URLSearchParams) => void) {
  await page.route('**/api/v1/media/stats**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 9, by_type: { audio: 4, image: 5 } }) })
  })
  await page.route('**/api/v1/media/folders**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route(/\/api\/v1\/media\/(\?.*)?$/, async (route) => {
    const params = new URL(route.request().url()).searchParams
    onMediaQuery?.(params)
    const q = params.get('q')
    const items = q === 'two'
      ? [audioMedia(21, 'lib-two.mp3')]
      : [audioMedia(20, 'lib-one.mp3'), audioMedia(21, 'lib-two.mp3'), audioMedia(10, 'track-one.mp3')]
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items) })
  })
}

test.describe('Audio baskets player + picker', () => {
  // Le bouton lecture de la carte enchaîne les morceaux du panier — le WAV de 0 s
  // se termine tout seul : track-one → track-two → fermeture.
  test('card_play_button_chains_basket_tracks', async ({ page }) => {
    await mockBasketRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/audio-baskets`)

    await expect(page.getByText('Pop Nationale')).toBeVisible()
    await page.getByTestId('play-basket-1').click()

    const viewer = page.getByTestId('media-viewer')
    await expect(viewer.getByText('track-one.mp3')).toBeVisible()
    // L'audio est LE lecteur : il doit démarrer seul (autoplay), sinon l'enchaînement
    // attendrait un clic à chaque morceau.
    await expect(viewer.locator('audio')).toHaveAttribute('autoplay', '')
    // WAV vide → fin immédiate → le 2e morceau prend la main, puis la lecture se ferme.
    await expect(viewer.getByText('track-two.mp3')).toBeVisible({ timeout: 5000 })
    await expect(viewer).toHaveCount(0, { timeout: 5000 })
  })

  test('listen_track_from_items_drawer_escape_keeps_drawer', async ({ page }) => {
    await mockBasketRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/audio-baskets`)

    await page.getByTitle('Manage items').click()
    await expect(page.getByText('track-one.mp3')).toBeVisible()

    // Casque = écoute d'UN morceau, par-dessus le drawer.
    await page.getByTestId('listen-item-2').click()
    const viewer = page.getByTestId('media-viewer')
    await expect(viewer.getByText('track-two.mp3')).toBeVisible()
    await expect(viewer.getByText('2 / 2')).toBeVisible()

    // Échap ne ferme QUE la visionneuse — le drawer d'items reste ouvert derrière.
    await page.keyboard.press('Escape')
    await expect(viewer).toHaveCount(0)
    await expect(page.getByText('track-one.mp3')).toBeVisible()
  })

  test('picker_searches_server_side_and_adds_in_bulk', async ({ page }) => {
    await mockBasketRoutes(page)
    const queries: URLSearchParams[] = []
    await mockPickerRoutes(page, (p) => queries.push(p))
    let bulkBody: { id_medias: number[] } | null = null
    await page.route(/\/api\/v1\/audio-baskets\/1\/items\/bulk$/, async (route) => {
      bulkBody = route.request().postDataJSON()
      await route.fulfill({ status: 201, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/audio-baskets`)

    await page.getByTitle('Manage items').click()
    await page.getByTestId('open-audio-picker').click()
    const list = page.getByTestId('audio-picker-list')
    await expect(list.getByText('lib-one.mp3')).toBeVisible()

    // Toute requête du picker est filtrée AUDIO côté serveur — jamais un filtrage client.
    expect(queries.length).toBeGreaterThan(0)
    for (const p of queries) expect(p.get('media_type')).toBe('audio')

    // Un morceau déjà dans le panier est montré grisé, pas caché (il « existe »).
    await expect(list.getByText('already in basket')).toBeVisible()

    // La recherche est résolue PAR LE SERVEUR (paramètre q), pas dans le navigateur.
    await page.getByPlaceholder('Search audio content…').fill('two')
    await expect(list.getByText('lib-two.mp3')).toBeVisible()
    await expect.poll(() => queries.some((p) => p.get('q') === 'two')).toBe(true)
    await expect(list.getByText('lib-one.mp3')).toHaveCount(0)

    // Multi-sélection + ajout en LOT (un seul POST bulk).
    await page.getByPlaceholder('Search audio content…').fill('')
    await expect(list.getByText('lib-one.mp3')).toBeVisible()
    await list.getByText('lib-one.mp3').click()
    await list.getByText('lib-two.mp3').click()
    await page.getByRole('button', { name: 'Add (2)' }).click()
    await expect.poll(() => bulkBody).not.toBeNull()
    expect(bulkBody!.id_medias.sort()).toEqual([20, 21])
  })

  test('picker_preview_listens_before_adding_and_escape_layers', async ({ page }) => {
    await mockBasketRoutes(page)
    await mockPickerRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/audio-baskets`)

    await page.getByTitle('Manage items').click()
    await page.getByTestId('open-audio-picker').click()
    await expect(page.getByTestId('audio-picker-list').getByText('lib-one.mp3')).toBeVisible()

    // Pré-écoute d'un morceau AVANT de l'ajouter, par-dessus le drawer de recherche.
    await page.getByTestId('audio-preview-20').click()
    const viewer = page.getByTestId('media-viewer')
    await expect(viewer).toBeVisible()
    await expect(viewer.locator('audio')).toBeVisible()

    // Échap : 1er = la visionneuse seule · 2e = le picker seul · le drawer d'items RESTE.
    await page.keyboard.press('Escape')
    await expect(viewer).toHaveCount(0)
    await expect(page.getByTestId('audio-picker-list')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('audio-picker-list')).toHaveCount(0)
    await expect(page.getByTestId('items-play-basket')).toBeVisible()
  })
})
