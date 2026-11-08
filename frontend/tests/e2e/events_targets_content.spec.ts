import { test, expect } from '@playwright/test'

/**
 * FILET DE REFACTOR — écran Événements (audit du 2026-07-29, phase B).
 *
 * `events/page.tsx` fait 1350 lignes et n'avait AUCUNE spec, alors que c'est le module qui
 * met du contenu à l'antenne. La phase C va remplacer le choix des cibles (par une carte) et
 * celui du contenu (par un tiroir de recherche à dossiers) : sans filet, on refactoriserait
 * à l'aveugle.
 *
 * 🔑 CE QUE CES SPECS AFFIRMENT : le RÉSULTAT — la requête réellement envoyée au serveur et
 * l'état affiché — jamais le widget. Un `<select>` remplacé par une carte doit laisser ces
 * tests VERTS ; s'ils tombent, c'est le comportement qui a changé, pas la présentation.
 * Les repères `data-testid` nomment donc le CONCEPT (« choisir le contenu ») et seront
 * reportés tels quels sur les nouveaux composants.
 *
 * ⚠️ Chaque test part de l'URL NUE, comme l'utilisateur : la leçon coûteuse du 28/07 est
 * que six specs pouvaient être vertes sur un produit cassé parce qu'elles passaient toutes
 * par un helper qui quittait l'écran d'accueil.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SITES = [
  { id_site: 1, id_org: 1, site_name: 'Store Paris', address: null, country: null, site_number: null, latitude: 48.85, longitude: 2.35, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
  { id_site: 2, id_org: 1, site_name: 'Store Lyon', address: null, country: null, site_number: null, latitude: 45.76, longitude: 4.83, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
]

const PLAYERS = [
  { id_player: 10, id_org: 1, player_name: 'Paris Window', player_os: 'linux', status: 'online', id_site: 1, ip_address: '192.168.1.10', capabilities: {} },
  { id_player: 11, id_org: 1, player_name: 'Paris Counter', player_os: 'linux', status: 'offline', id_site: 1, ip_address: '192.168.1.11', capabilities: {} },
  { id_player: 20, id_org: 1, player_name: 'Lyon Window', player_os: 'linux', status: 'online', id_site: 2, ip_address: '192.168.2.10', capabilities: {} },
]

const GROUPS = [{ id_group: 5, id_org: 1, group_name: 'Vitrines', player_ids: [10, 20] }]
const SITE_GROUPS = [{ id_site_group: 7, id_org: 1, group_name: 'Region Sud', site_ids: [2] }]

const PLAYLISTS = [
  { id_playlist: 100, id_org: 1, playlist_name: 'Boucle principale', description: null, id_template: null, sync_mode: 'wall_clock', total_duration_ms: 30000, sync_ready: true, has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1, used_as_child: false, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id_playlist: 101, id_org: 1, playlist_name: 'Promo ete', description: null, id_template: null, sync_mode: 'wall_clock', total_duration_ms: 15000, sync_ready: true, has_draft_changes: false, rotation_mode: 'all', items_per_turn: 1, used_as_child: false, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
]

const MEDIA = [
  { id_media: 200, media_name: 'alerte.mp4', media_type: 'video', mime_type: 'video/mp4', file_size_bytes: 1, duration_ms: 8000, thumbnail_url: null, source: 'upload', attribution_text: null, transcode_status: 'done', encode_mode: 'auto', conformance_status: 'ready', not_before_utc: null, embargo_event_id: null, embargo_event_name: null, tags: [], id_folder: null, created_at: new Date().toISOString() },
]

function evt(id: number, name: string, status: string, targetType = 'player', targetIds: number[] = [10]) {
  return {
    id_event: id, id_org: 1, event_name: name, event_type: 'manual', event_kind: 'content',
    id_playlist: 100, playlist_name: 'Boucle principale', id_media: null, media_name: null,
    id_basket: null, basket_name: null, mix_ratio: null, priority: 70, duration_ms: null,
    revert_on_end: true, status, trigger_config: null,
    target_config: { target_type: targetType, target_ids: targetIds },
    id_governance_node: null, valid_from: null, valid_until: null, is_recurring: false,
    is_preemptive: false, keep_screens_on: false, not_before_utc: null,
    timezone: 'Europe/Paris',
    activated_at: null, expires_at: null,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
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

/** Toutes les listes que l'écran consomme. `events` est paramétrable par test. */
async function mockEventsPage(
  page: import('@playwright/test').Page,
  opts: { events?: unknown[]; onPost?: (b: Record<string, unknown>) => void } = {},
) {
  // ⚠️ Le glob doit matcher l'URL AVEC sa query string (piège documenté au § Frontend).
  await page.route(/\/api\/v1\/events(\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      opts.onPost?.(route.request().postDataJSON())
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(evt(999, 'Cree', 'inactive')) })
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(opts.events ?? []) })
  })
  await page.route(/\/api\/v1\/playlists\/(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYLISTS) })
  })
  await page.route(/\/api\/v1\/media\/(\?.*)?$/, async (route) => {
    // Le double HONORE `media_type`, comme le serveur : le tiroir lance une requête par
    // type, et un double qui rend tout à chaque fois ferait apparaître le même média
    // plusieurs fois — un comportement qu'aucune vraie API n'a.
    const ty = new URL(route.request().url()).searchParams.get('media_type')
    const items = ty ? MEDIA.filter((m) => m.media_type === ty) : MEDIA
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items) })
  })
  await page.route(/\/api\/v1\/players\/(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) })
  })
  await page.route(/\/api\/v1\/player-groups\/(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GROUPS) })
  })
  await page.route(/\/api\/v1\/site-groups\/(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITE_GROUPS) })
  })
  await page.route(/\/api\/v1\/sites(\/)?(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) })
  })
  await page.route(/\/api\/v1\/audio-baskets(\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
}

/**
 * Gestes de choix du contenu — ILS ONT CHANGÉ en phase C (les deux menus déroulants sont
 * devenus un tiroir de recherche), les ASSERTIONS de ces specs n'ont pas bougé d'un octet.
 * C'est exactement ce qu'un filet de refactor doit permettre : constater que le RÉSULTAT
 * envoyé au serveur est identique, quel que soit le widget.
 */
async function pickPlaylist(page: import('@playwright/test').Page, id: number) {
  await page.getByTestId('event-content-select').click()
  await page.getByTestId(`content-playlist-${id}`).click()
}

async function pickMedia(page: import('@playwright/test').Page, id: number) {
  await page.getByTestId('event-content-select').click()
  await page.getByTestId(`content-media-${id}`).click()
}

test.describe('Événements — filet de refactor (cibles + contenu)', () => {
  test('list_renders_from_bare_url', async ({ page }) => {
    await mockEventsPage(page, { events: [evt(1, 'Alerte incendie', 'inactive')] })
    await mockAuthAndNavigate(page, `${BASE}/events`)
    await expect(page.getByText('Alerte incendie')).toBeVisible()
  })

  // Le cœur du filet : quelle CIBLE part au serveur pour chaque type ?
  test('target_player_sends_player_ids', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Ev players')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-target-type').selectOption('player')
    await page.getByText('Paris Window').click()
    await page.getByTestId('event-save').click()

    await expect.poll(() => body).toMatchObject({
      event_name: 'Ev players', id_playlist: 100,
      target_config: { target_type: 'player', target_ids: [10] },
    })
  })

  // 🔑 La cible SITE : c'est elle dont le résolveur de force_sync ne s'occupait pas
  // (phase A2). Le filet doit garantir qu'elle continue d'être envoyée telle quelle.
  test('target_site_sends_site_ids', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Ev site')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-target-type').selectOption('site')
    await page.getByText('Store Lyon').click()
    await page.getByTestId('event-save').click()

    await expect.poll(() => body).toMatchObject({
      target_config: { target_type: 'site', target_ids: [2] },
    })
  })

  test('target_group_and_site_group_send_their_ids', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Ev groupe')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-target-type').selectOption('group')
    await page.getByText('Vitrines').click()
    await page.getByTestId('event-save').click()
    await expect.poll(() => body).toMatchObject({
      target_config: { target_type: 'group', target_ids: [5] },
    })

    body = null
    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Ev groupe de sites')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-target-type').selectOption('site_group')
    await page.getByText('Region Sud').click()
    await page.getByTestId('event-save').click()
    await expect.poll(() => body).toMatchObject({
      target_config: { target_type: 'site_group', target_ids: [7] },
    })
  })

  test('target_org_sends_no_ids', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Ev org')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-target-type').selectOption('org')
    await page.getByTestId('event-save').click()

    await expect.poll(() => body).toMatchObject({
      target_config: { target_type: 'org', target_ids: [] },
    })
  })

  // Le CONTENU : playlist par défaut, média en bascule. C'est ce que le tiroir de recherche
  // de la phase C devra continuer d'envoyer à l'identique.
  test('content_media_mode_sends_id_media', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Ev media')
    await page.getByRole('button', { name: 'Single media' }).click()
    await pickMedia(page, 200)
    await page.getByTestId('event-target-type').selectOption('player')
    await page.getByText('Paris Window').click()
    await page.getByTestId('event-save').click()

    await expect.poll(() => body).toMatchObject({ id_media: 200 })
    // Choisir un média unique ne doit pas laisser traîner une playlist : les deux modes
    // sont exclusifs côté serveur. (`body` est capturé après le poll, d'où le cast.)
    const sent = body as unknown as Record<string, unknown>
    expect(sent.id_playlist).toBeFalsy()
  })

  // Les transitions : ce sont elles qui mettent à l'antenne. Elles doivent viser la bonne
  // route — c'est aussi ce que les gardes de nœud de la phase A1 protègent côté serveur.
  test('transitions_hit_the_right_endpoints', async ({ page }) => {
    const calls: string[] = []
    await mockEventsPage(page, { events: [evt(1, 'Ev transitions', 'inactive')] })
    for (const action of ['activate', 'deactivate', 'cancel']) {
      await page.route(new RegExp(`/api/v1/events/1/${action}$`), async (route) => {
        calls.push(action)
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(evt(1, 'Ev transitions', 'active')) })
      })
    }
    await mockAuthAndNavigate(page, `${BASE}/events`)
    await expect(page.getByText('Ev transitions')).toBeVisible()

    await page.getByTitle(/Activate|Activer/).first().click()
    await expect.poll(() => calls).toContain('activate')
  })
})

test.describe('Événements — choisir les écrans sur la carte (phase C)', () => {
  // Ed : « à 200, 500, 1000 écrans, la liste à cases à cocher ne suffira pas ». Au-delà de
  // quelques dizaines d'écrans on ne cherche plus par nom mais par EMPLACEMENT. Ce test
  // vérifie que la carte alimente la MÊME cible que la liste — donc le même corps envoyé.
  test('map_selection_feeds_the_same_target', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    // Les tuiles de la carte partent vers un service EXTERNE : sans ce blocage le test
    // attend un réseau qu'il n'aura pas. Les marqueurs et la recherche, eux, sont locaux.
    await page.route(/tile\.|openstreetmap|basemaps/, (r) => r.abort())
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Ev carte')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-target-type').selectOption('site')

    // La carte n'apparaît que pour les cibles qui ont un emplacement (site / écran).
    await page.getByTestId('event-target-map').click()
    await expect(page.getByTestId('target-map')).toBeVisible()

    // On désigne le site par la RECHERCHE de la carte, puis on le retient. C'est le seul
    // chemin qui marche aussi pour un site SANS coordonnées — celui-là n'a pas de marqueur.
    await page.getByPlaceholder('Search a site…').fill('Lyon')
    await page.getByRole('button', { name: 'Store Lyon' }).click()
    await page.getByTestId('target-map-toggle-focused').click()
    await page.getByTestId('target-map-apply').click()

    await page.getByTestId('event-save').click()
    await expect.poll(() => body).toMatchObject({
      target_config: { target_type: 'site', target_ids: [2] },
    })
  })

  test('mixed_site_plus_players_sends_the_hetero_form', async ({ page }) => {
    // La demande d'Ed validée le 29/07 : « ce site » + « ces écrans » dans UN SEUL
    // événement, comme les campagnes. Un seul type sélectionné continue d'envoyer la
    // forme héritée (les 4 specs ci-dessus le prouvent) ; le MÉLANGE envoie
    // {targets:[...]} — l'union des entrées.
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Ev mixte')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-target-type').selectOption('site')
    await page.getByText('Store Lyon').click()
    await page.getByTestId('event-target-type').selectOption('player')
    await page.getByText('Paris Window').click()

    // Le récapitulatif NOMME tout ce que l'événement emporte, tous types confondus.
    const recap = page.getByTestId('event-target-recap')
    await expect(recap.getByText('Store Lyon')).toBeVisible()
    await expect(recap.getByText('Paris Window')).toBeVisible()

    await page.getByTestId('event-save').click()
    await expect.poll(() => body).toMatchObject({
      target_config: { targets: [
        { target_type: 'player', target_ids: [10] },
        { target_type: 'site', target_ids: [2] },
      ] },
    })
  })

  test('editing_a_mixed_event_repopulates_and_resends_the_union', async ({ page }) => {
    let putBody: Record<string, unknown> | null = null
    const mixed = {
      ...evt(1, 'Ev mixte', 'inactive'),
      target_config: { targets: [
        { target_type: 'player', target_ids: [10] },
        { target_type: 'site', target_ids: [2] },
      ] },
    }
    await mockEventsPage(page, { events: [mixed] })
    await page.route(/\/api\/v1\/events\/1$/, async (route) => {
      if (route.request().method() === 'PUT') {
        putBody = route.request().postDataJSON()
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mixed) })
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mixed) })
    })
    await mockAuthAndNavigate(page, `${BASE}/events`)
    await expect(page.getByText('Ev mixte')).toBeVisible()

    await page.getByTitle(/Edit|Modifier/).first().click()
    // Le drawer re-remplit TOUTES les listes depuis la forme hétérogène…
    const recap = page.getByTestId('event-target-recap')
    await expect(recap.getByText('Paris Window')).toBeVisible()
    await expect(recap.getByText('Store Lyon')).toBeVisible()
    // …et sauvegarder sans rien changer renvoie la même union (pas de perte silencieuse).
    await page.getByTestId('event-save').click()
    await expect.poll(() => putBody).toMatchObject({
      target_config: { targets: [
        { target_type: 'player', target_ids: [10] },
        { target_type: 'site', target_ids: [2] },
      ] },
    })
  })


  // ── P3.13 : ce que « 18:00 » veut dire ────────────────────────────────────────
  // Un événement porte UNE ligne et UN `activated_at` : il ne peut pas s'activer à l'heure
  // locale de chaque écran. Il DÉCLARE son fuseau de référence — et l'écran doit à la fois
  // permettre de le choisir et ne jamais afficher une heure sans lui.

  test('scheduled_event_sends_its_reference_timezone', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Happy hour')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-type').selectOption('scheduled')
    await page.getByTestId('event-timezone').selectOption('America/New_York')
    await page.getByTestId('event-target-type').selectOption('org')
    await page.getByTestId('event-save').click()

    await expect.poll(() => body).toMatchObject({ timezone: 'America/New_York' })
  })

  test('no_timezone_chosen_sends_null_and_keeps_the_server_default', async ({ page }) => {
    let body: Record<string, unknown> | null = null
    await mockEventsPage(page, { onPost: (b) => { body = b } })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByPlaceholder('Event name').fill('Sans fuseau')
    await pickPlaylist(page, 100)
    await page.getByTestId('event-type').selectOption('scheduled')
    await page.getByTestId('event-target-type').selectOption('org')
    await page.getByTestId('event-save').click()

    // `null` et pas '' : c'est ce qui laisse la colonne NULL, donc le comportement historique.
    await expect.poll(() => body).toMatchObject({ timezone: null })
  })

  test('an_hour_is_never_shown_without_its_timezone', async ({ page }) => {
    const scheduled = {
      ...evt(3, 'Happy hour', 'inactive'),
      event_type: 'scheduled',
      timezone: 'America/New_York',
      trigger_config: {
        logic: 'AND',
        conditions: [{ source: 'schedule', days_of_week: [0, 1], time_start: '18:00', time_end: '19:00' }],
      },
    }
    await mockEventsPage(page, { events: [scheduled] })
    await mockAuthAndNavigate(page, `${BASE}/events`)

    const line = page.getByText(/18:00/)
    await expect(line).toBeVisible()
    await expect(line).toContainText('America/New_York')
  })

  test('map_button_is_absent_for_targets_without_a_place', async ({ page }) => {
    await mockEventsPage(page)
    await mockAuthAndNavigate(page, `${BASE}/events`)

    await page.getByTestId('event-new').click()
    await page.getByTestId('event-target-type').selectOption('org')
    await expect(page.getByTestId('event-target-map')).toHaveCount(0)
    await page.getByTestId('event-target-type').selectOption('group')
    await expect(page.getByTestId('event-target-map')).toHaveCount(0)
    // …mais présente dès qu'on cible des écrans.
    await page.getByTestId('event-target-type').selectOption('player')
    await expect(page.getByTestId('event-target-map')).toBeVisible()
  })
})
