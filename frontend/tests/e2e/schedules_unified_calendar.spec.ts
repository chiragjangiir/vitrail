import { test, expect } from '@playwright/test'

// Calendrier unifié /schedules (retours beta testeurs 2026-07) : pills de filtre
// de type (Tout/Visuels/Audio/Events/Campagnes), campagnes superposées au
// calendrier, filtre par cible (groupe de sites / site / player) propagé aux
// 3 requêtes, sélecteur de type de programme dans le drawer.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

// Format LOCAL (pas toISOString : minuit local convertit en UTC = jour précédent)
function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const today = new Date()
const weekAgo = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 7)
const weekAhead = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 7)

const SCHEDULE = {
  id_schedule: 1, id_org: 1, schedule_name: 'Morning Loop', schedule_kind: 'content',
  id_playlist: 10, id_governance_node: null, priority: 10, is_active: true,
  valid_from: null, valid_until: null, is_deleted: false,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  rules: [{ id_rule: 1, rule_type: 'weekly', days_of_week: [0, 1, 2, 3, 4, 5, 6], time_start: '08:00:00', time_end: '12:00:00', date_from: null, date_to: null }],
}

const EVENT = {
  id_event: 5, event_name: 'Flash Promo', event_type: 'manual', event_kind: 'content',
  status: 'inactive', priority: 80, id_playlist: 10, id_media: null, id_basket: null,
  mix_ratio: null, playlist_name: 'PL', media_name: null, basket_name: null,
  valid_from: weekAgo.toISOString(), valid_until: weekAhead.toISOString(),
  is_recurring: false, trigger_config: {}, target_config: { target_type: 'org' },
  created_at: new Date().toISOString(),
}

const CAMPAIGN = {
  id_campaign: 7, campaign_name: 'Dyson Push', status: 'live',
  starts_on: iso(weekAgo), ends_on: iso(weekAhead),
  advertiser_name: 'Dyson', sov_percent: 20,
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

async function mockData(page: import('@playwright/test').Page, captured: { schedules: string[]; events: string[]; campaigns: string[] }) {
  await page.route(/\/api\/v1\/schedules(\?.*)?$/, async (route) => {
    captured.schedules.push(new URL(route.request().url()).search)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([SCHEDULE]) })
  })
  await page.route(/\/api\/v1\/events(\?.*)?$/, async (route) => {
    captured.events.push(new URL(route.request().url()).search)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([EVENT]) })
  })
  await page.route(/\/api\/v1\/campaigns\/(\?.*)?$/, async (route) => {
    captured.campaigns.push(new URL(route.request().url()).search)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([CAMPAIGN]) })
  })
  // ⚠️ Regex et non glob : le tiroir de recherche de playlist appelle /playlists/ AVEC
  // une query string (limit, q) — un glob sans `**` final ne la matcherait pas (piège
  // documenté au § Frontend).
  await page.route(/\/api\/v1\/playlists\/(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{ id_playlist: 10, playlist_name: 'PL', sync_mode: 'wall_clock', sync_ready: true }]),
    })
  })
  for (const [pattern, body] of [
    ['**/api/v1/sites', JSON.stringify([{ id_site: 3, site_name: 'Site A' }])],
    ['**/api/v1/site-groups/', JSON.stringify([{ id_site_group: 4, group_name: 'Region North', description: null, site_count: 1, player_count: 2 }])],
    ['**/api/v1/players/', JSON.stringify([{ id_player: 9, player_name: 'Lobby Screen', status: 'online', player_os: 'linux' }])],
    ['**/api/v1/player-groups/', '[]'],
    ['**/api/v1/audio-baskets', '[]'],
    ['**/api/v1/governance/nodes', '[]'],
  ] as const) {
    await page.route(pattern, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body })
    })
  }
}

test.describe('Unified schedules calendar', () => {
  test('type_filter_pills_toggle_families', async ({ page }) => {
    const captured = { schedules: [], events: [], campaigns: [] }
    await mockData(page, captured)
    await mockAuthAndNavigate(page, `${BASE}/schedules`)

    // Vue « All » : les 3 familles sont visibles (programme + event + campagne).
    await expect(page.getByText('Morning Loop').first()).toBeVisible()
    await expect(page.getByText('Flash Promo').first()).toBeVisible()
    await expect(page.getByText('Dyson Push').first()).toBeVisible()

    // Filtre « Campaigns » : seule la campagne reste sur le calendrier.
    // (scope <main> : la sidebar a aussi un bouton replié « Campaigns »)
    const main = page.getByRole('main')
    await main.getByRole('button', { name: 'Campaigns', exact: true }).click()
    await expect(page.getByText('Dyson Push').first()).toBeVisible()
    // (la vignette latérale garde la liste des programmes — on vérifie le calendrier)
    await expect(page.getByTitle(/Flash Promo/).first()).not.toBeVisible()

    // Filtre « Events » : l'event revient, la campagne disparaît.
    await main.getByRole('button', { name: 'Events', exact: true }).click()
    await expect(page.getByText('Flash Promo').first()).toBeVisible()
    await expect(page.getByTitle(/Dyson Push/).first()).not.toBeVisible()
  })

  test('target_filter_propagates_to_all_queries', async ({ page }) => {
    const captured = { schedules: [] as string[], events: [] as string[], campaigns: [] as string[] }
    await mockData(page, captured)
    await mockAuthAndNavigate(page, `${BASE}/schedules`)
    await expect(page.getByText('Morning Loop').first()).toBeVisible()

    // Popover cible : groupes de sites / sites / players listés, sélection d'un site.
    await page.getByRole('button', { name: 'All targets' }).click()
    await expect(page.getByRole('button', { name: 'Region North' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Lobby Screen' })).toBeVisible()
    await page.getByRole('button', { name: 'Site A', exact: true }).click()

    // Les 3 requêtes repartent avec la cible résolue côté serveur.
    await expect.poll(() => captured.schedules.some((q) => q.includes('target_type=site') && q.includes('target_id=3'))).toBe(true)
    await expect.poll(() => captured.events.some((q) => q.includes('target_type=site') && q.includes('target_id=3'))).toBe(true)
    await expect.poll(() => captured.campaigns.some((q) => q.includes('target_type=site') && q.includes('target_id=3'))).toBe(true)
  })

  test('drawer_has_program_type_selector', async ({ page }) => {
    const captured = { schedules: [], events: [], campaigns: [] }
    await mockData(page, captured)
    await mockAuthAndNavigate(page, `${BASE}/schedules`)

    await page.getByRole('button', { name: 'New schedule' }).click()
    const drawer = page.getByRole('dialog')
    await expect(drawer.getByText('Program type')).toBeVisible()
    // Bascule Visual → Audio : le champ playlist laisse place aux paniers audio.
    await expect(drawer.getByText('Playlist', { exact: true }).first()).toBeVisible()
    await drawer.getByRole('button', { name: 'Audio', exact: true }).click()
    await expect(drawer.getByText('Audio baskets', { exact: true })).toBeVisible()
  })

  // ── Lot « calendrier » 2026-07-20 ────────────────────────────────────────────

  test('calendar_click_opens_schedule_drawer', async ({ page }) => {
    const captured = { schedules: [], events: [], campaigns: [] }
    await mockData(page, captured)
    await page.route('**/api/v1/schedules/1', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ...SCHEDULE, targets: [{ target_type: 'player', target_id: 9 }], baskets: [] }),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/schedules`)

    // Vue semaine : la vignette du programme dans la grille ouvre son drawer.
    await page.getByTitle(/Morning Loop/).first().click()
    // Nommé : la page monte AUSSI le drawer de simulation de journée (fermé).
    const drawer = page.getByRole('dialog', { name: 'Edit schedule' })
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('input[value="Morning Loop"]')).toBeVisible()

    // La cible portée par le programme rouvre sa section et affiche la pastille.
    await expect(drawer.getByRole('button', { name: /Target players/ })).toContainText('1')
  })

  test('month_view_fits_viewport_and_scrolls_per_day', async ({ page }) => {
    const captured = { schedules: [], events: [], campaigns: [] }
    await mockData(page, captured)
    await mockAuthAndNavigate(page, `${BASE}/schedules`)

    await page.getByRole('button', { name: 'Month', exact: true }).click()
    await expect(page.getByText('Morning Loop').first()).toBeVisible()

    // La page elle-même ne défile pas : le calendrier tient dans la fenêtre.
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollHeight - document.documentElement.clientHeight)
    expect(overflow).toBeLessThanOrEqual(1)

    // Chaque case de jour est son propre conteneur de défilement (pas de troncature
    // « +N autres » : au-delà de la hauteur de case, on fait défiler la case).
    const dayScrollable = await page.evaluate(() => {
      const cells = Array.from(document.querySelectorAll('div'))
        .filter((el) => el.className.includes('overflow-y-auto') && el.className.includes('space-y-0.5'))
      return cells.length
    })
    expect(dayScrollable).toBeGreaterThan(0)
  })

  test('drawer_single_search_filters_all_target_families', async ({ page }) => {
    const captured = { schedules: [], events: [], campaigns: [] }
    await mockData(page, captured)
    await mockAuthAndNavigate(page, `${BASE}/schedules`)

    await page.getByRole('button', { name: 'New schedule' }).click()
    const drawer = page.getByRole('dialog', { name: 'New schedule' })

    // Sections repliées par défaut (aucune sélection) → on déplie players + sites.
    await drawer.getByRole('button', { name: /Target players/ }).click()
    await drawer.getByRole('button', { name: /Sites/ }).first().click()
    await expect(drawer.getByText('Lobby Screen')).toBeVisible()
    await expect(drawer.getByText('Site A')).toBeVisible()

    // Un seul champ filtre les 4 familles à la fois.
    await drawer.getByPlaceholder(/Search a player/).fill('Lobby')
    await expect(drawer.getByText('Lobby Screen')).toBeVisible()
    await expect(drawer.getByText('Site A')).not.toBeVisible()

    // Sélection → pastille accent sur l'en-tête de la famille.
    await drawer.getByPlaceholder(/Search a player/).fill('')
    await drawer.getByText('Lobby Screen').click()
    await expect(drawer.getByRole('button', { name: /Target players/ })).toContainText('1')
  })

  // ── D-b (2026-07-26) : sous gouvernance, les cibles RESTREIGNENT le nœud ──────
  // L'écran disait exactement l'inverse (« les cibles ci-dessous sont ignorées », D2) et
  // grisait le sélecteur. Ce test protège les deux moitiés du geste : le sélecteur est
  // utilisable, et le RÉSULTAT RÉSOLU est affiché — sinon on croit avoir ciblé un magasin
  // qui ne recevra rien.
  test('governed_targets_narrow_the_node_and_show_the_resolved_count', async ({ page }) => {
    const captured = { schedules: [], events: [], campaigns: [] }
    await mockData(page, captured)
    await page.unroute('**/api/v1/governance/nodes')
    await page.route('**/api/v1/governance/nodes', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{ id_node: 2, id_org: 1, parent_id: null, node_name: 'Store Lyon', node_level: 0, node_type: 'store', path: '2', created_at: new Date().toISOString(), child_count: 0, requires_approval: false, can_edit: true }]),
    }))
    let lastScope: Record<string, unknown> | null = null
    await page.route('**/api/v1/schedules/governance-scope', async (route) => {
      lastScope = route.request().postDataJSON()
      const targets = (lastScope!.targets ?? []) as unknown[]
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          node_name: 'Store Lyon', perimeter_count: 5, target_count: targets.length,
          resolved_count: targets.length ? 2 : 5, players: [], out_of_scope: [],
          // D4 : cibler une partie du magasin coupe son groupe de synchro LAN.
          lan_sync_split: targets.length
            ? [{ group: 'Store LAN', kept: ['Entrance 1'], excluded: ['Butcher', 'Backroom'] }]
            : [],
        }),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/schedules`)
    await page.getByRole('button', { name: 'New schedule' }).click()
    const drawer = page.getByRole('dialog', { name: 'New schedule' })

    await drawer.locator('select').filter({ hasText: 'Store Lyon' }).selectOption('2')
    // Sans cible : tout le nœud (D0) — c'est le parc existant, aucune régression.
    await expect(drawer.getByTestId('gov-scope-count')).toContainText('whole node “Store Lyon” (5')

    // Le sélecteur de cibles reste UTILISABLE (il était grisé quand elles étaient ignorées).
    await drawer.getByRole('button', { name: /Target players/ }).click()
    await drawer.getByText('Lobby Screen').click()
    await expect(drawer.getByTestId('gov-scope-count')).toContainText('2 screen(s) kept out of 5')
    await expect.poll(() => (lastScope?.targets as unknown[])?.length).toBe(1)

    // D4 : on AVERTIT que le groupe de synchro LAN est coupé — et on ne bloque rien
    // (c'est le cas entrée/boucherie d'un magasin déjà câblé en un seul groupe, la
    // situation la plus probable).
    await expect(drawer.getByTestId('gov-lan-split'))
      .toContainText('LAN sync group “Store LAN” is split')

    // Le formulaire complété reste soumettable MALGRÉ l'avertissement (le bouton n'est
    // gaté que par le nom + la playlist : l'avertissement n'y touche pas).
    await drawer.getByRole('textbox').first().fill('Entrances')
    // Geste phase C : le <select> de playlist est devenu un tiroir de recherche serveur
    // (l'assertion — le bouton Create s'active — n'a pas bougé).
    await drawer.getByTestId('schedule-playlist-select').click()
    await page.getByTestId('content-playlist-10').click()
    await expect(drawer.getByRole('button', { name: 'Create' })).toBeEnabled()
    await expect(drawer.getByTestId('gov-lan-split')).toBeVisible()
  })

})
