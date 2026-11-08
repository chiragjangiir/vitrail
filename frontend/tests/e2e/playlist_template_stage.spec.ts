import { test, expect } from '@playwright/test'

/**
 * Scène MULTI-ZONES du lecteur (constat d'Ed 2026-08-08 : une playlist posée sur un template
 * multi-zones ne montrait que la zone 0, donc autre chose que ce qui allait diffuser).
 *
 * Ces specs visent les deux façons dont un tel aperçu peut mentir **en ayant l'air de
 * marcher** — c'est pour ça qu'elles existent, et c'est ce qu'on met à l'épreuve par mutation :
 *   1. une zone au mauvais endroit (division par la mauvaise dimension du canevas) ;
 *   2. un minuteur GLOBAL au lieu d'un minuteur par zone (toutes les zones avancent ensemble).
 * Plus la frontière : un template MONO-zone doit garder le lecteur à plat, inchangé.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const PNG_DATA_URI = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

const CANVAS_W = 1920
const CANVAS_H = 1080

/** Deux zones volontairement ASYMÉTRIQUES sur les deux axes : une inversion x↔y ou un
 *  rapport pris sur la mauvaise dimension du canevas se voit, ce qui ne serait pas le cas
 *  d'un découpage en deux moitiés égales. */
const ZONES = [
  { index: 0, x: 0, y: 0, w: 1280, h: 1080, label: 'Main' },
  { index: 1, x: 1280, y: 540, w: 640, h: 540, label: 'Side' },
]

function playlistItem(idItem: number, idMedia: number, name: string, durationMs: number, zone = 0, type = 'image') {
  return {
    id_item: idItem, id_playlist: 1, id_media: idMedia, item_type: 'media',
    id_child_playlist: null, sort_order: idItem, duration_ms: durationMs, zone_index: zone,
    transition_type: 'cut', created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(), media_name: name,
    media_type: type, conformance_status: 'ready', has_rules: false,
  }
}

function detail(items: unknown[], idTemplate: number | null = 5) {
  return {
    id_playlist: 1, id_org: 1, playlist_name: 'Storefront', description: null,
    id_template: idTemplate, sync_mode: 'wall_clock', total_duration_ms: 1200,
    sync_ready: true, has_item_rules: false, sync_windowed: false,
    has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1, used_as_child: false,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(), items,
  }
}

function template(zones: unknown[]) {
  return {
    id_template: 5, id_org: 1, template_name: 'Shop layout', description: null,
    layout: { layout_type: 'custom', canvas_width: CANVAS_W, canvas_height: CANVAS_H, zones },
    preview_url: null, campaign_placement: 'fullscreen',
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  }
}

async function mockAuthAndNavigate(page: import('@playwright/test').Page, url: string) {
  const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
  await page.goto(`${BASE}/login`)
  await page.evaluate((tok) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: {
        user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
        accessToken: tok, refreshToken: 'mock_refresh', roles: ['CMS_ORG_ADMIN'],
      },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', tok)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, mockToken)
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER_ME) })
  })
  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: mockToken, refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }),
    })
  })
  await page.goto(url)
}

/**
 * ⚠️ Playwright résout les routes de la DERNIÈRE enregistrée à la première : les motifs
 * GÉNÉRIQUES se posent d'abord, les spécifiques ensuite — sinon le générique les avale
 * (piège payé le 11/08 sur `/feeds/7/items`).
 */
async function mockRoutes(
  page: import('@playwright/test').Page,
  opts: { items: unknown[]; zones?: unknown[]; idTemplate?: number | null; child?: unknown[] },
) {
  // Détails médias : URL signée = data: URI, aucun réseau réel.
  await page.route(/\/api\/v1\/media\/(\d+)$/, async (route) => {
    const id = Number(route.request().url().match(/\/media\/(\d+)$/)![1])
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        id_media: id, media_name: `media-${id}`, media_type: 'image', mime_type: 'image/png',
        file_size_bytes: 10, served_size_bytes: null, duration_ms: null, thumbnail_url: null,
        source: 'upload', attribution_text: null, transcode_status: 'done', encode_mode: 'auto',
        conformance_status: 'ready', not_before_utc: null, embargo_event_id: null,
        embargo_event_name: null, tags: [], id_folder: null, cdn_url_signed: PNG_DATA_URI,
      }),
    })
  })
  await page.route(/\/api\/v1\/playlists\/(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{
        id_playlist: 1, id_org: 1, playlist_name: 'Storefront', description: null,
        id_template: opts.idTemplate === undefined ? 5 : opts.idTemplate,
        sync_mode: 'wall_clock', total_duration_ms: 1200, sync_ready: true,
        has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1, used_as_child: false,
        created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      }]),
    })
  })
  await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(detail(opts.items, opts.idTemplate === undefined ? 5 : opts.idTemplate)),
    })
  })
  await page.route(/\/api\/v1\/playlists\/7(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ...detail(opts.child ?? [], null), id_playlist: 7, playlist_name: 'Promos' }),
    })
  })
  await page.route(/\/api\/v1\/templates\/5$/, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(template(opts.zones ?? ZONES)),
    })
  })
}

async function openStage(page: import('@playwright/test').Page) {
  await mockAuthAndNavigate(page, `${BASE}/playlists`)
  await page.getByTitle('Play playlist').first().click()
}

test.describe('Playlist template stage', () => {
  // 🔑 Le point que seule une mesure géométrique attrape : une zone posée au mauvais
  // endroit s'affiche parfaitement, et l'aperçu a l'air de marcher.
  test('zones_are_placed_at_the_template_coordinates', async ({ page }) => {
    await mockRoutes(page, {
      items: [
        playlistItem(1, 10, 'a1.png', 60000, 0),
        playlistItem(2, 12, 'b1.png', 60000, 1),
      ],
    })
    await openStage(page)

    const canvas = page.getByTestId('stage-canvas')
    await expect(canvas).toBeVisible()
    const cb = (await canvas.boundingBox())!

    // Le canevas garde le ratio du template (letterbox), il ne se déforme pas.
    expect(cb.width / cb.height).toBeCloseTo(CANVAS_W / CANVAS_H, 2)

    for (const z of ZONES) {
      const zb = (await page.getByTestId(`stage-zone-${z.index}`).boundingBox())!
      expect((zb.x - cb.x) / cb.width).toBeCloseTo(z.x / CANVAS_W, 2)
      expect((zb.y - cb.y) / cb.height).toBeCloseTo(z.y / CANVAS_H, 2)
      expect(zb.width / cb.width).toBeCloseTo(z.w / CANVAS_W, 2)
      expect(zb.height / cb.height).toBeCloseTo(z.h / CANVAS_H, 2)
    }
  })

  // 🔑 Chaque zone a SON minuteur (`_mzScheduleAdvance` côté player). Un minuteur global
  // ferait avancer les deux ensemble : la scène tournerait, et serait fausse.
  test('each_zone_advances_on_its_own_timer', async ({ page }) => {
    await mockRoutes(page, {
      items: [
        // Zone 0 : tourne vite. Zone 1 : ne doit PAS bouger de tout le test.
        playlistItem(1, 10, 'a1.png', 500, 0),
        playlistItem(2, 11, 'a2.png', 500, 0),
        playlistItem(3, 12, 'b1.png', 120000, 1),
        playlistItem(4, 13, 'b2.png', 120000, 1),
      ],
    })
    await openStage(page)

    await expect(page.getByTestId('stage-zone-0')).toHaveAttribute('data-item-name', 'a1.png')

    // ⚠️ Formulé en COMPTANT les valeurs prises sur une fenêtre, et pas avec un
    // `toHaveAttribute` : ces assertions-là RÉESSAIENT jusqu'à trouver la valeur attendue.
    // Une zone qui alterne b1→b2→b1 les satisfait donc à un moment ou à un autre — ma
    // première version était VERTE sous la mutation (prouvé), c'est-à-dire vacante.
    const seen = await page.evaluate(async () => {
      const vals: Record<string, Set<string>> = { z0: new Set(), z1: new Set() }
      for (let i = 0; i < 30; i++) {
        for (const [k, id] of [['z0', 'stage-zone-0'], ['z1', 'stage-zone-1']] as const) {
          const el = document.querySelector(`[data-testid="${id}"]`)
          if (el) vals[k].add(el.getAttribute('data-item-name') ?? '')
        }
        await new Promise((r) => setTimeout(r, 100))
      }
      return { z0: [...vals.z0].sort(), z1: [...vals.z1] }
    })

    // TÉMOIN : la scène tourne vraiment. Sans lui, une scène FIGÉE passerait le test —
    // « la zone 1 n'a pas bougé » est trivialement vrai quand plus rien ne bouge.
    expect(seen.z0).toEqual(['a1.png', 'a2.png'])
    // Et pendant ce temps la zone lente n'a pris qu'UNE valeur. C'est cette égalité-ci qui
    // tombe si l'avance est pilotée par une horloge partagée.
    expect(seen.z1).toEqual(['b1.png'])
  })

  // Une sous-playlist n'a pas de zone : ses contenus prennent celle du SLOT PARENT,
  // comme le fait le serveur (`zone_override=item.zone_index`, ws.py:2792).
  test('sub_playlist_items_inherit_the_parent_slot_zone', async ({ page }) => {
    await mockRoutes(page, {
      items: [
        playlistItem(1, 10, 'a1.png', 60000, 0),
        // Le slot est en zone 1 ; l'enfant, lui, porte zone_index 0 dans SA playlist.
        { ...playlistItem(9, 0, '', 0, 1), id_media: null, item_type: 'sub_playlist',
          id_child_playlist: 7, child_name: 'Promos', media_type: null },
      ],
      child: [playlistItem(20, 14, 'promo-a.png', 60000, 0)],
    })
    await openStage(page)

    await expect(page.getByTestId('stage-zone-0')).toHaveAttribute('data-item-name', 'a1.png')
    await expect(page.getByTestId('stage-zone-1')).toHaveAttribute('data-item-name', 'promo-a.png')
  })

  // Décision d'Ed : les feeds / pages web / HDMI sont PRODUITS sur l'écran. On montre
  // leur place et leur identité, on ne prétend pas rendre leur contenu.
  test('pointer_media_are_named_in_their_zone_not_faked', async ({ page }) => {
    await mockRoutes(page, {
      items: [
        playlistItem(1, 10, 'a1.png', 60000, 0),
        playlistItem(2, 12, 'news-band', 60000, 1, 'feed_display'),
      ],
    })
    await openStage(page)

    const zone1 = page.getByTestId('stage-zone-1')
    await expect(zone1.getByText('news-band')).toBeVisible()
    await expect(zone1.getByText(/produced on the screen/i)).toBeVisible()
    await expect(zone1.locator('img')).toHaveCount(0)
  })

  // FRONTIÈRE — ce qui ne doit PAS changer. Le serveur n'émet un bloc `template` qu'à
  // partir de DEUX zones (`_build_template_block`) ; en dessous le player reste sur son
  // chemin mono-zone, et le lecteur doit rester sur le sien.
  test('single_zone_template_keeps_the_flat_viewer', async ({ page }) => {
    await mockRoutes(page, {
      items: [playlistItem(1, 10, 'a1.png', 60000, 0)],
      zones: [{ index: 0, x: 0, y: 0, w: CANVAS_W, h: CANVAS_H, label: 'Full' }],
    })
    await openStage(page)

    await expect(page.getByTestId('media-viewer')).toBeVisible()
    await expect(page.getByTestId('template-stage')).toHaveCount(0)
  })

  // Retour d'Ed 2026-08-13 : la scène s'ouvrait à la taille de la fenêtre, alors que le
  // lecteur des autres playlists est un panneau posé au centre. Le plein écran est un
  // GESTE, pas le défaut.
  test('stage_opens_at_the_same_scale_as_the_flat_viewer', async ({ page }) => {
    // ⚠️ FHD explicitement, et pas le 1280×720 par défaut : c'est la LARGEUR du panneau
    // qui doit contraindre le canevas pour que l'assertion sur la bande morte veuille dire
    // quelque chose. En 720 de haut, la hauteur contraint la première et le défaut est
    // invisible — ma première version du test passait sous la mutation, donc ne prouvait
    // rien (le défaut, lui, a été vu sur une capture en 1920×1080).
    await page.setViewportSize({ width: 1920, height: 1080 })
    await mockRoutes(page, { items: [playlistItem(1, 10, 'a1.png', 60000, 0)] })
    await openStage(page)

    const vp = page.viewportSize()!
    const panel = (await page.getByTestId('template-stage').locator('> div').boundingBox())!
    const canvas = (await page.getByTestId('stage-canvas').boundingBox())!

    // Même largeur que la visionneuse (`max-w-5xl` = 1024 px), et du fond visible
    // au-dessus et en dessous : c'est un panneau, pas une feuille pleine hauteur.
    expect(panel.width).toBeLessThanOrEqual(1024)
    expect(panel.height).toBeLessThan(vp.height * 0.9)
    // Zone de rendu plafonnée comme celle de la visionneuse (65vh).
    expect(canvas.height).toBeLessThan(vp.height * 0.66)
    expect(canvas.height).toBeGreaterThan(150)   // témoin : elle est bien rendue

    // 🔑 Pas de BANDE MORTE : le cadre épouse le canevas. Avec un cadre à hauteur fixe,
    // un 16:9 contraint par la largeur laissait ~125 px de noir au-dessus et en dessous
    // — vu sur une capture, invisible aux tests précédents.
    const frame = (await page.getByTestId('stage-canvas').locator('..').boundingBox())!
    expect(frame.height - canvas.height).toBeLessThan(40)   // = le padding du cadre
  })

  test('fullscreen_tool_enlarges_and_reduces', async ({ page }) => {
    await mockRoutes(page, { items: [playlistItem(1, 10, 'a1.png', 60000, 0)] })
    await openStage(page)

    const stage = page.getByTestId('template-stage')
    const canvas = page.getByTestId('stage-canvas')
    const before = (await canvas.boundingBox())!
    await expect(stage).toHaveAttribute('data-expanded', '0')

    await page.getByTestId('stage-fullscreen').click()
    await expect(stage).toHaveAttribute('data-expanded', '1')
    // 🔑 L'agrandissement est porté par le CSS et pas par l'API navigateur : elle peut
    // échouer (iframe, absence de geste), et le bouton serait alors mort. On mesure donc
    // la TAILLE RENDUE, seule chose qui compte pour l'utilisateur.
    await expect.poll(async () => (await canvas.boundingBox())!.height)
      .toBeGreaterThan(before.height * 1.15)

    await page.getByTestId('stage-fullscreen').click()
    await expect(stage).toHaveAttribute('data-expanded', '0')
    await expect.poll(async () => (await canvas.boundingBox())!.height)
      .toBeLessThan(before.height * 1.05)
  })

  // 🔴 Constat d'Ed 2026-08-13 : depuis l'ÉDITEUR, « Lire la playlist » déroulait la liste
  // à plat et ignorait le template — alors que la MÊME playlist lue depuis /playlists
  // ouvrait la scène. Deux boutons « lire » pour un seul contenu, deux résultats. Cause :
  // l'éditeur monte sa propre visionneuse (il lui faut ses actions) et ne passait donc
  // jamais par `PlaylistPlayer`.
  test('editor_play_button_opens_the_stage_too', async ({ page }) => {
    await mockRoutes(page, {
      items: [
        playlistItem(1, 10, 'a1.png', 60000, 0),
        playlistItem(2, 12, 'b1.png', 60000, 1),
      ],
    })
    // L'éditeur résout ses zones via la LISTE des templates, la scène via le détail.
    await page.route('**/api/v1/templates', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify([template(ZONES)]),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await page.getByRole('button', { name: 'Play playlist' }).click()
    await expect(page.getByTestId('template-stage')).toBeVisible()
    await expect(page.getByTestId('stage-zone-1')).toHaveAttribute('data-item-name', 'b1.png')
    // …et surtout PAS la liste à plat, qui est ce qu'on voyait avant.
    await expect(page.getByTestId('media-viewer')).toHaveCount(0)
  })

  test('escape_closes_the_stage', async ({ page }) => {
    await mockRoutes(page, { items: [playlistItem(1, 10, 'a1.png', 60000, 0)] })
    await openStage(page)

    await expect(page.getByTestId('template-stage')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('template-stage')).toHaveCount(0)
  })
})
