import { test, expect } from '@playwright/test'

// Visionneuse dans l'éditeur de playlist (demande Ed 2026-07-28) : réutilisation du
// MediaViewer de /media pour lire un contenu unitaire ou la playlist construite, et
// aperçu depuis le drawer « Ajouter un média » — le tout SANS quitter la page.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

// 1×1 PNG — servie en data: URI par le mock du détail média (aucun réseau réel).
const PNG_DATA_URI = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

function mediaItem(id: number, name: string, type = 'image') {
  return {
    id_media: id, media_name: name, media_type: type, mime_type: 'image/png',
    file_size_bytes: 1234, served_size_bytes: null, duration_ms: null,
    thumbnail_url: null, source: 'upload', attribution_text: null,
    transcode_status: 'done', encode_mode: 'auto', conformance_status: 'ready',
    not_before_utc: null, embargo_event_id: null, embargo_event_name: null,
    tags: [], id_folder: null,
  }
}

function playlistItem(idItem: number, idMedia: number, name: string, durationMs: number) {
  return {
    id_item: idItem, id_playlist: 1, id_media: idMedia, item_type: 'media',
    id_child_playlist: null, sort_order: idItem, duration_ms: durationMs, zone_index: 0,
    transition_type: 'cut', created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(), media_name: name,
    media_type: 'image', conformance_status: 'ready', has_rules: false,
  }
}

const DETAIL = {
  id_playlist: 1, id_org: 1, playlist_name: 'Main Loop', description: null,
  id_template: null, sync_mode: 'wall_clock', total_duration_ms: 1200,
  sync_ready: true, has_item_rules: false, sync_windowed: false,
  has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1,
  used_as_child: false,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  items: [
    playlistItem(1, 10, 'img-one.png', 600),
    playlistItem(2, 11, 'img-two.png', 600),
    // Pointeur : rien à montrer → PAS cliquable, PAS dans la lecture.
    { ...playlistItem(3, 12, 'my-webpage', 5000), media_type: 'url_display' },
  ],
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

async function mockPlaylistRoutes(page: import('@playwright/test').Page) {
  await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DETAIL) })
  })
  await page.route('**/api/v1/templates', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  // Détails médias : l'URL signée pointe une data: URI (l'img se rend sans réseau).
  for (const id of [10, 11, 20, 21]) {
    await page.route(new RegExp(`/api/v1/media/${id}$`), async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ...mediaItem(id, `media-${id}`), cdn_url_signed: PNG_DATA_URI }),
      })
    })
  }
}

/** Liste des playlists (page /playlists) — une seule carte, « Main Loop » (id 1). */
async function mockPlaylistListRoute(page: import('@playwright/test').Page) {
  await page.route(/\/api\/v1\/playlists\/(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{
        id_playlist: 1, id_org: 1, playlist_name: 'Main Loop', description: null,
        id_template: null, sync_mode: 'wall_clock', total_duration_ms: 1200,
        sync_ready: true, has_draft_changes: false, rotation_mode: 'all',
        items_per_turn: 1, used_as_child: false,
        created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      }]),
    })
  })
}

// Le drawer « Ajouter un média » interroge /media/stats puis /media/ par type.
async function mockPickerRoutes(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/media/stats**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 2, by_type: { image: 2 } }) })
  })
  await page.route(/\/api\/v1\/media\/(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([mediaItem(20, 'lib-a.png'), mediaItem(21, 'lib-b.png')]),
    })
  })
}

test.describe('Playlist viewer', () => {
  test('item_click_opens_viewer_and_navigates', async ({ page }) => {
    await mockPlaylistRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await page.getByRole('button', { name: 'img-one.png' }).click()
    const viewer = page.getByTestId('media-viewer')
    await expect(viewer).toBeVisible()
    await expect(viewer.getByText('img-one.png')).toBeVisible()

    // Flèche droite → contenu suivant. ⚠️ Depuis le 2026-07-29 les médias POINTEURS
    // (ici `my-webpage`, une page web) font partie de la navigation : les sauter donnait
    // un aperçu qui ne correspondait pas à la boucle réelle (question d'Ed).
    await page.keyboard.press('ArrowRight')
    await expect(viewer.getByText('img-two.png')).toBeVisible()
    await page.keyboard.press('ArrowRight')
    await expect(viewer.getByText('my-webpage')).toBeVisible()
    await page.keyboard.press('ArrowRight')
    await expect(viewer.getByText('my-webpage')).toBeVisible() // dernier : on ne va pas plus loin

    await page.keyboard.press('Escape')
    await expect(viewer).toHaveCount(0)
  })

  test('play_button_runs_through_playlist_and_closes', async ({ page }) => {
    await mockPlaylistRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await page.getByRole('button', { name: 'Play playlist' }).click()
    const viewer = page.getByTestId('media-viewer')
    await expect(viewer.getByText('img-one.png')).toBeVisible()
    // duration_ms = 600 : l'enchaînement passe au 2e contenu…
    await expect(viewer.getByText('img-two.png')).toBeVisible({ timeout: 5000 })
    // …puis au pointeur (5 s de durée d'exposition), qui fait partie de la boucle…
    await expect(viewer.getByText('my-webpage')).toBeVisible({ timeout: 5000 })
    // …et au bout, la lecture se termine et la visionneuse se ferme.
    await expect(viewer).toHaveCount(0, { timeout: 10000 })
  })

  test('picker_preview_overlays_drawer_and_escape_keeps_drawer', async ({ page }) => {
    await mockPlaylistRoutes(page)
    await mockPickerRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await page.getByRole('button', { name: 'Add media', exact: true }).click()
    await expect(page.getByText('lib-a.png')).toBeVisible()

    // Œil = aperçu sans quitter le drawer.
    await page.getByTitle('Preview').first().click()
    const viewer = page.getByTestId('media-viewer')
    await expect(viewer).toBeVisible()
    await expect(viewer.getByText('lib-a.png')).toBeVisible()

    // Échap ne ferme QUE la visionneuse — le drawer reste ouvert derrière.
    await page.keyboard.press('Escape')
    await expect(viewer).toHaveCount(0)
    await expect(page.getByText('lib-b.png')).toBeVisible()
  })

  // Retour Ed 2026-07-29 : les flèches translucides sur les bords ne se voyaient pas.
  // Des boutons LIBELLÉS doivent exister à côté des autres actions, avec la position.
  test('viewer_has_labelled_prev_next_and_position', async ({ page }) => {
    await mockPlaylistRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await page.getByRole('button', { name: 'img-one.png' }).click()
    const viewer = page.getByTestId('media-viewer')
    // 3 contenus : 2 images + le pointeur page web (compté depuis le 2026-07-29).
    await expect(viewer.getByText('1 / 3')).toBeVisible()

    // Repères stables : la flèche latérale porte le même libellé que le bouton du pied,
    // et les deux coexistent volontairement (geste rapide vs geste visible).
    const next = viewer.getByTestId('viewer-next')
    const prev = viewer.getByTestId('viewer-prev')
    await expect(next).toBeEnabled()
    await expect(prev).toBeDisabled()   // premier contenu : rien avant

    await next.click()
    await expect(viewer.getByText('img-two.png')).toBeVisible()
    await expect(viewer.getByText('2 / 3')).toBeVisible()
    await next.click()
    await expect(viewer.getByText('3 / 3')).toBeVisible()
    await expect(next).toBeDisabled()   // dernier contenu : rien apres
    await prev.click()
    await expect(viewer.getByText('img-two.png')).toBeVisible()
  })

  // « Une visualisation d'une playlist » depuis la LISTE, sans ouvrir l'éditeur.
  test('play_button_on_card_previews_playlist_from_the_list', async ({ page }) => {
    await mockPlaylistRoutes(page)
    await mockPlaylistListRoute(page)
    await mockAuthAndNavigate(page, `${BASE}/playlists`)

    await expect(page.getByText('Main Loop')).toBeVisible()
    await page.getByTitle('Play playlist').first().click()

    // On reste sur /playlists : la lecture se fait par-dessus la liste.
    const viewer = page.getByTestId('media-viewer')
    await expect(viewer.getByText('img-one.png')).toBeVisible()
    expect(new URL(page.url()).pathname).toBe('/playlists')
  })

  // 🔴 Questions d'Ed 2026-07-29 : que fait le lecteur d'un PDF/PPTX, d'un flux, d'une
  // entrée HDMI, d'une sous-playlist ? Mesuré : le document affichait le FICHIER SOURCE
  // dans un <img> (carré vide), les pointeurs et les sous-playlists étaient sautés.
  test('document_shows_converted_pages_not_the_source_file', async ({ page }) => {
    await mockPlaylistRoutes(page)
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...DETAIL,
          items: [{ ...playlistItem(4, 30, 'presentation.pptx', 5000), media_type: 'document', media_page_count: 3 }],
        }),
      })
    })
    // Le détail sert le PPTX lui-même — c'est ce que l'ancien code mettait dans <img>.
    await page.route(/\/api\/v1\/media\/30$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ...mediaItem(30, 'presentation.pptx', 'document'), page_count: 3,
                               cdn_url_signed: 'https://example.invalid/presentation.pptx' }),
      })
    })
    await page.route(/\/api\/v1\/media\/30\/pages$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          id_media: 30, page_count: 3, truncated: false,
          pages: [1, 2, 3].map((n) => ({ page: n, url: PNG_DATA_URI, width: 1920, height: 1080 })),
        }),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await page.getByRole('button', { name: 'presentation.pptx' }).click()
    const viewer = page.getByTestId('media-viewer')
    const img = viewer.locator('img')
    await expect(img).toBeVisible()

    // L'image affichée est une PAGE convertie, jamais le .pptx (qui ne s'afficherait pas).
    await expect(img).not.toHaveAttribute('src', /\.pptx/)
    await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0)

    // On feuillette : les pages ont leur propre navigation, distincte des contenus.
    await expect(viewer.getByText('Page 1 / 3')).toBeVisible()
    await viewer.getByRole('button', { name: 'Next page' }).click()
    await expect(viewer.getByText('Page 2 / 3')).toBeVisible()
  })

  test('pointer_media_are_shown_not_skipped', async ({ page }) => {
    await mockPlaylistRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    // L'entrée HDMI de DETAIL (item 3) fait désormais partie de la lecture.
    await page.getByRole('button', { name: 'my-webpage' }).click()
    const viewer = page.getByTestId('media-viewer')
    await expect(viewer).toBeVisible()
    await expect(viewer.getByText('my-webpage')).toBeVisible()
    // Pas de fichier → pas d'<img> cassée, mais une fiche qui dit ce que c'est.
    await expect(viewer.getByText(/no file/i)).toBeVisible()
  })

  test('sub_playlist_is_unrolled_in_the_preview', async ({ page }) => {
    await mockPlaylistRoutes(page)
    // Parent : 1 média + 1 sous-playlist. Enfant : 2 médias.
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...DETAIL,
          items: [
            playlistItem(1, 10, 'img-one.png', 600),
            { ...playlistItem(9, 0, '', 0), id_media: null, item_type: 'sub_playlist',
              id_child_playlist: 7, child_name: 'Promos', media_type: null },
          ],
        }),
      })
    })
    await page.route(/\/api\/v1\/playlists\/7(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...DETAIL, id_playlist: 7, playlist_name: 'Promos',
          items: [playlistItem(20, 10, 'promo-a.png', 600), playlistItem(21, 11, 'promo-b.png', 600)],
        }),
      })
    })
    await mockPlaylistListRoute(page)
    await mockAuthAndNavigate(page, `${BASE}/playlists`)

    await page.getByTitle('Play playlist').first().click()
    const viewer = page.getByTestId('media-viewer')
    // 1 média du parent + les 2 de la sous-playlist = 3 contenus, pas 1.
    await expect(viewer.getByText('1 / 3')).toBeVisible()
    await viewer.getByTestId('viewer-next').click()
    await expect(viewer.getByText('promo-a.png')).toBeVisible()
    await viewer.getByTestId('viewer-next').click()
    await expect(viewer.getByText('promo-b.png')).toBeVisible()
  })

  test('viewer_can_open_media_drawer_without_leaving', async ({ page }) => {
    await mockPlaylistRoutes(page)
    await mockPickerRoutes(page)
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await page.getByRole('button', { name: 'img-one.png' }).click()
    const viewer = page.getByTestId('media-viewer')
    await expect(viewer).toBeVisible()

    // « Ajouter un média » depuis la visionneuse : le drawer s'ouvre PAR-DESSUS,
    // la visionneuse reste montée derrière.
    await viewer.getByRole('button', { name: 'Add media' }).click()
    await expect(page.getByText('lib-a.png')).toBeVisible()
    await expect(viewer).toBeVisible()
  })
})
