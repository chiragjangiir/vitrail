import { test, expect } from '@playwright/test'

// Écran de gouvernance — mise en page A (choix d'Ed, 2026-07-26) et modèle de la migr 0110.
// Ce que ces tests protègent, et pourquoi :
//  · la page est VERROUILLÉE AU VIEWPORT — l'ancienne version violait notre propre règle,
//    l'arbre partait vers le haut dès qu'on descendait dans la configuration ;
//  · le nœud vit dans l'URL — une configuration se partage et survit à un rechargement ;
//  · les restrictions sont COCHÉES PAR DÉFAUT et par famille ;
//  · un paramètre non délégué reste AFFICHÉ, en lecture seule, avec la mention de qui décide
//    (l'écran précédent le masquait : l'admin local ne voyait pas ce qui le contraignait).

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const NOW = new Date().toISOString()

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: NOW }

const NODES = [
  { id_node: 1, id_org: 1, parent_id: null, node_name: 'National', node_level: 0, node_type: 'national', path: '1', created_at: NOW, child_count: 1, requires_approval: true, can_edit: true },
  { id_node: 2, id_org: 1, parent_id: 1, node_name: 'Store Lyon', node_level: 1, node_type: 'store', path: '1.2', created_at: NOW, child_count: 0, requires_approval: true, can_edit: true },
]

// Le magasin : `item_count` délégué par le national, le reste verrouillé plus haut.
const NODE_2_DETAIL = {
  ...NODES[1],
  children: [], assignments: [], admins: [],
  rules: [{ id_rule: 9, id_node: 2, rule_type: 'item_count', params: { max_per_cycle: 2, mode: 'one_random' }, soft_cut: true, is_active: true, created_at: NOW }],
  can_disable_moderation: false,
  can_set_rules_delegation: false,
  rules_locked: { item_count: false },
  rules_locked_above: { item_count: false, time_budget: true, time_window: true, preemptive: true },
  rules_locked_effective: { item_count: false, time_budget: true, time_window: true, preemptive: true },
  can_edit_rule_types: { item_count: true, time_budget: false, time_window: false, preemptive: false },
  inherited_max_per_turn: 4,
  inherited_max_item_sec: null,
  max_for_children: null,
  max_item_sec: null,
}

// Deux sites places + un SANS coordonnees : c'est la faiblesse assumee de la Carte 1, le
// site invisible sur la carte doit rester visible ET compte dans le panier.
const SITES = [
  { id_site: 10, id_org: 1, site_name: 'Lyon Part-Dieu', address: null, country: null, site_number: null, latitude: 45.76, longitude: 4.86, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
  { id_site: 11, id_org: 1, site_name: 'Marseille Prado', address: null, country: null, site_number: null, latitude: 43.28, longitude: 5.39, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
  { id_site: 12, id_org: 1, site_name: 'Entrepot sans GPS', address: null, country: null, site_number: null, latitude: null, longitude: null, timezone: null, ntp_server: null, auto_power_enabled: false, power_lead_min: 0 },
]
const PLAYERS = [
  { id_player: 7, id_org: 1, id_site: 10, player_name: 'Ecran 1', player_os: 'linux', player_version: null, player_role: 'content', status: 'online', ip_address: null, wan_ip: null, mac_address: null, last_seen_at: null, cpu_usage: null, ram_usage: null, disk_usage: null, current_playlist_id: null, token_expires_at: null, created_at: NOW, updated_at: NOW },
  { id_player: 8, id_org: 1, id_site: 12, player_name: 'Ecran entrepot', player_os: 'linux', player_version: null, player_role: 'content', status: 'online', ip_address: null, wan_ip: null, mac_address: null, last_seen_at: null, cpu_usage: null, ram_usage: null, disk_usage: null, current_playlist_id: null, token_expires_at: null, created_at: NOW, updated_at: NOW },
]

async function mockAuthAndNavigate(page: import('@playwright/test').Page, url: string) {
  const mockToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwib3JnIjoxLCJyb2xlcyI6WyJDTVNfT1JHX0FETUlOIl0sImxvY2FsZSI6ImVuIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6OTk5OTk5OTk5OX0.signature'
  await page.goto(`${BASE}/login`)
  await page.evaluate((tok) => {
    const store = {
      state: {
        user: { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() },
        accessToken: tok, refreshToken: 'mock_refresh', roles: ['CMS_ORG_ADMIN'],
      },
      version: 0,
    }
    localStorage.setItem('sf-auth', JSON.stringify(store))
    localStorage.setItem('sf_access_token', tok)
    localStorage.setItem('sf_refresh_token', 'mock_refresh')
  }, mockToken)
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER_ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: mockToken, refresh_token: 'mock_refresh', token_type: 'bearer', locale: 'en' }) }))
  await page.goto(url)
}

async function mockGovernance(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/governance/nodes', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(NODES) }))
  await page.route('**/api/v1/governance/nodes/2', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(NODE_2_DETAIL) }))
  await page.route('**/api/v1/governance/nodes/1', (r) =>
    r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ...NODES[0], children: [NODES[1]], rules: [], assignments: [], admins: [] }),
    }))
  for (const u of ['**/api/v1/governance/nodes/*/players', '**/api/v1/player-groups/', '**/api/v1/users']) {
    await page.route(u, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  }
  await page.route('**/api/v1/sites', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SITES) }))
  await page.route('**/api/v1/players/', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) }))
  // R4 : la selection de cibles se fait cote SERVEUR (drawer de recherche), plus dans des
  // listes deroulantes qui chargeaient tout le parc. G2 : un ecran ORPHELIN est propose ET
  // etiquete, pour que l'oubli soit reparable.
  await page.route('**/api/v1/governance/targets/search**', (r) =>
    r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([
        { target_type: 'player', target_id: 7, name: 'Ecran 1', subtitle: 'Lyon Part-Dieu', player_count: 1, orphan: false },
        { target_type: 'player', target_id: 9, name: 'Ecran oublie', subtitle: null, player_count: 1, orphan: true },
        { target_type: 'site', target_id: 10, name: 'Lyon Part-Dieu', subtitle: null, player_count: 4, orphan: false },
      ]),
    }))
}

test.describe('Governance page — layout A (§XVIII)', () => {
  test('columns_scroll_on_their_own_not_the_page', async ({ page }) => {
    await mockGovernance(page)
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()
    await expect(page.getByTestId('gov-restrictions')).toBeVisible()

    // ⚠️ Assertion STRUCTURELLE, et pas « le document ne défile pas » : `DashboardShell`
    // impose déjà `h-screen overflow-hidden`, donc le document ne défile jamais — un tel
    // test passerait aussi sur l'ancienne page et ne prouverait rien.
    // Le défaut réel était que <main> était LE conteneur de défilement commun : l'arbre
    // (en `h-fit`) partait vers le haut dès qu'on descendait dans la configuration.
    const layout = await page.evaluate(() => {
      const main = document.querySelector('main')!
      const tree = main.querySelector('aside')!
      const config = main.querySelector('section')!
      const oy = (el: Element) => getComputedStyle(el).overflowY
      return { main: oy(main), tree: oy(tree), config: oy(config) }
    })
    expect(layout.main).not.toMatch(/auto|scroll/)   // <main> ne défile pas
    expect(layout.tree).toMatch(/auto|scroll/)       // chaque colonne défile pour son compte
    expect(layout.config).toMatch(/auto|scroll/)
  })

  test('selected_node_lives_in_the_url_and_survives_a_reload', async ({ page }) => {
    await mockGovernance(page)
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()
    await expect(page).toHaveURL(/[?&]node=2\b/)

    await page.reload()
    // Après rechargement, le nœud est toujours celui de l'URL — et sa configuration est là.
    await expect(page.getByTestId('gov-restrictions')).toBeVisible()
    await expect(page.getByRole('checkbox', { name: /Takeover reserved/ })).toBeVisible()
  })

  test('restrictions_are_per_family_and_say_who_decides', async ({ page }) => {
    await mockGovernance(page)
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()

    // item_count délégué → décoché ; les trois autres restreints par le niveau supérieur.
    await expect(page.getByRole('checkbox', { name: /Contents per turn set above/ })).not.toBeChecked()
    for (const label of [/Time budget set above/, /Time window set above/, /Takeover reserved/]) {
      const box = page.getByRole('checkbox', { name: label })
      await expect(box).toBeChecked()
      // Posée plus haut : la case locale serait sans effet, elle ne doit pas être cliquable.
      await expect(box).toBeDisabled()
    }
    await expect(page.getByText('Set at a higher level: cannot be changed here.').first()).toBeVisible()
  })

  test('non_delegated_parameters_stay_visible_and_read_only', async ({ page }) => {
    await mockGovernance(page)
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()

    const rules = page.getByTestId('gov-rules')
    // Les 4 familles sont AFFICHÉES, y compris celles que le nœud ne décide pas.
    await expect(rules.getByText('Time budget', { exact: true })).toBeVisible()
    await expect(rules.getByText('Time window', { exact: true })).toBeVisible()
    // …avec la mention de qui décide (3 familles non déléguées ici).
    await expect(rules.getByText('Set by the level above')).toHaveCount(3)
    // Le champ du budget existe mais n'est pas saisissable.
    await expect(rules.locator('input[type="number"]').nth(1)).toBeDisabled()
    // Le paramètre délégué, lui, reste modifiable et porte la valeur du serveur.
    await expect(rules.locator('input[type="number"]').first()).toBeEnabled()
    await expect(rules.locator('input[type="number"]').first()).toHaveValue('2')
  })

  // ── Carte 1 : selection du perimetre sur carte (choix d'Ed, 2026-07-26) ────────
  test('map_perimeter_counts_sites_without_coordinates', async ({ page }) => {
    await mockGovernance(page)
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()
    await page.getByText('Pick on the map').click()

    const modal = page.getByTestId('gov-perimeter')
    await expect(modal).toBeVisible()
    await expect(modal.getByTestId('site-map-selector')).toBeVisible()

    // ⚠️ Le point de vigilance de la Carte 1 : un site sans GPS n'est pas sur la carte.
    // Il doit rester VISIBLE et COMPTE, sinon on croit un magasin gouverne alors qu'il ne
    // l'est pas — la faiblesse connue de ce choix, a ne pas laisser filer.
    await expect(modal.getByText(/1 site\(s\) without coordinates do not appear/)).toBeVisible()
    await expect(modal.getByText('Entrepot sans GPS')).toBeVisible()

    // Le panier part vide (aucune assignation de site sur ce noeud dans le mock).
    await expect(modal.getByText('No site selected yet.')).toBeVisible()
  })

  // ── Espace de travail du nœud (demande Ed 2026-07-26, point 4) ─────────────────
  test('node_workspace_lists_content_and_separates_edit_from_broadcast', async ({ page }) => {
    await mockGovernance(page)
    await page.route('**/api/v1/playlists/**', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{ id_playlist: 5, id_org: 1, playlist_name: 'Boucle magasin', description: null, id_template: null, sync_mode: 'wall_clock', total_duration_ms: 60000, sync_ready: true, has_item_rules: false, sync_windowed: false, rotation_mode: 'all', items_per_turn: 1, used_as_child: false, has_draft_changes: false, created_at: NOW, updated_at: NOW }]),
    }))
    await page.route('**/api/v1/schedules**', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()

    const ws = page.getByTestId('gov-workspace')
    // Le nom apparaît deux fois : dans la liste ET dans le sélecteur de playlist du
    // bloc Programmes — on vise la ligne de la liste.
    await expect(ws.getByText('Boucle magasin').first()).toBeVisible()

    // 🔑 Le malentendu qui a coûté une recherche à l'aveugle le 25/07 doit être écrit ICI :
    // rattacher une playlist ne diffuse pas, c'est le PROGRAMME qui met à l'antenne.
    await expect(ws.getByText(/does not broadcast it/)).toBeVisible()
    await expect(ws.getByText('No schedule: this node broadcasts nothing yet.')).toBeVisible()

    // Retour Ed : l'ordre du geste suit le sien — « je crée un programme ; s'il n'y a qu'une
    // playlist on ne me pose pas la question ». Le sélecteur permanent demandait de
    // re-choisir une playlist déjà visible juste au-dessus.
    let created: Record<string, unknown> | null = null
    await page.route('**/api/v1/schedules', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      created = route.request().postDataJSON()
      await route.fulfill({ status: 201, contentType: 'application/json', body: '{}' })
    })
    await ws.getByRole('button', { name: 'Create a schedule here' }).click()
    await expect.poll(() => created).not.toBeNull()
    expect(created!.id_playlist).toBe(5)
    // Sans règle horaire un programme n'est JAMAIS actif : on en pose une d'office.
    expect(created!.rules).toEqual([{ rule_type: 'always' }])
  })

  // ── D-b : « qui reçoit quoi » dans ce nœud (2026-07-26) ───────────────────────
  test('workspace_shows_resolved_screens_and_flags_the_uncovered_ones', async ({ page }) => {
    await mockGovernance(page)
    await page.route('**/api/v1/playlists/**', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: '[]',
    }))
    await page.route('**/api/v1/schedules**', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([
        { id_schedule: 31, id_org: 1, schedule_name: 'Entrances', schedule_kind: 'content', id_playlist: 5, id_governance_node: 2, priority: 0, is_active: true, valid_from: null, valid_until: null, created_at: NOW, updated_at: NOW, rules: [] },
        { id_schedule: 32, id_org: 1, schedule_name: 'Whole store', schedule_kind: 'content', id_playlist: 6, id_governance_node: 2, priority: 0, is_active: true, valid_from: null, valid_until: null, created_at: NOW, updated_at: NOW, rules: [] },
      ]),
    }))
    await page.route('**/api/v1/governance/nodes/2/coverage', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        id_node: 2, perimeter_count: 5,
        schedules: [
          { id_schedule: 31, schedule_name: 'Entrances', is_active: true, target_count: 1, resolved_count: 2 },
          { id_schedule: 32, schedule_name: 'Whole store', is_active: true, target_count: 0, resolved_count: 5 },
        ],
        uncovered: [{ id_player: 8, player_name: 'Butcher screen' }],
      }),
    }))
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()

    const ws = page.getByTestId('gov-workspace')
    // Toujours le résultat RÉSOLU : « une partie » vs « tout le nœud ».
    await expect(ws.getByText('2/5 screens')).toBeVisible()
    await expect(ws.getByText('whole node (5)')).toBeVisible()

    // Contrepartie assumée de D1 : un écran oublié dans son groupe ne reçoit que
    // l'héritage — rien d'autre ne le signalerait.
    await expect(ws.getByTestId('gov-uncovered')).toContainText('Butcher screen')
  })

  // ── Confort de la revue : R2 (le niveau) et R8/R9 (le rôle d'un admin) ────────
  test('node_level_and_admin_role_verdict_are_shown', async ({ page }) => {
    await mockGovernance(page)
    await page.route('**/api/v1/governance/nodes/2', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        ...NODE_2_DETAIL,
        admins: [
          { id_user: 5, email: 'boss@test.com', full_name: 'Org Boss' },
          { id_user: 6, email: 'watcher@test.com', full_name: 'Read Only' },
        ],
      }),
    }))
    await page.route('**/api/v1/governance/admin-candidates', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([
        { id_user: 5, email: 'boss@test.com', full_name: 'Org Boss', roles: ['CMS_ORG_ADMIN'], can_program: true, bypasses_governance: true },
        { id_user: 6, email: 'watcher@test.com', full_name: 'Read Only', roles: ['CMS_VIEWER'], can_program: false, bypasses_governance: false },
        { id_user: 7, email: 'prog@test.com', full_name: 'Site Programmer', roles: ['CMS_SITE_PROGRAMMER'], can_program: true, bypasses_governance: false },
      ]),
    }))
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()

    // R2 : le niveau — la seule donnée qui fixe l'ordre national→local — est affiché.
    await expect(page.getByTestId('node-level'))
      .toContainText('Level 1 — in the compiled program, this level comes BEFORE lower levels.')

    // R8 : les deux nominations sans effet sont NOMMÉES, au lieu d'être silencieuses.
    const warnings = page.getByTestId('admin-warning')
    await expect(warnings).toHaveCount(2)
    await expect(warnings.first()).toContainText('Org Boss')
    await expect(warnings.first()).toContainText('already bypass governance')
    await expect(warnings.nth(1)).toContainText('will not be able to edit any schedule')

    // R9 : le rôle est visible AU MOMENT DU CHOIX, dans l'option elle-même.
    // Libellé recadré par la migr 0111 (« Governance — Programmer ») : les rôles de
    // gouvernance portent desormais leur perimetre dans leur nom (G4).
    await expect(page.locator('option', { hasText: 'Site Programmer — Governance — Programmer' }))
      .toHaveCount(1)
  })

  test('map_finds_and_shows_site_groups', async ({ page }) => {
    // Retour Ed : « je ne vois pas les groupes de sites pour les sélectionner et les
    // visualiser », et chercher « Governance - IDF » ne trouvait rien — la recherche ne
    // regardait que les noms de SITE.
    await mockGovernance(page)
    await page.route('**/api/v1/site-groups/**', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([{ id_site_group: 3, id_org: 1, group_name: 'Governance - IDF', description: null, created_at: NOW, updated_at: NOW, site_count: 2, player_count: 2, site_ids: [10, 11] }]),
    }))
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()
    await page.getByText('Pick on the map').click()

    const modal = page.getByTestId('gov-perimeter')
    // Le groupe est listé et cochable, même s'il n'est pas encore rattaché.
    await expect(modal.getByRole('checkbox', { name: /Governance - IDF/ })).toBeVisible()

    // …et il se TROUVE par la recherche de la carte.
    await modal.locator('input[type=search]').fill('Governance')
    await expect(modal.getByRole('button', { name: /Governance - IDF/ })).toBeVisible()
  })

  test('target_picker_searches_server_side_and_shows_resolved_screens', async ({ page }) => {
    // R4 (revue du 23/07) : les 4 listes deroulantes chargeaient TOUT le parc a chaque
    // ouverture d'un noeud et n'ajoutaient qu'une cible a la fois. Le drawer cherche cote
    // serveur, permet la multi-selection, et AFFICHE LE NOMBRE D'ECRANS RESOLUS — la seule
    // donnee qui dise ce qu'on vient de selectionner quand on mele les natures de cible.
    await mockGovernance(page)
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()
    await page.getByTestId('gov-add-targets').click()

    const hits = page.getByTestId('gov-target-hits')
    await expect(hits.getByText('Ecran oublie')).toBeVisible()
    // Un site annonce les 4 ecrans qu'il resout, pas seulement son nom.
    await expect(hits.getByText('4 screen(s)')).toBeVisible()

    // Multi-selection : le bouton compte les cibles ET les ecrans.
    await hits.getByText('Ecran oublie').click()
    await hits.getByText('Lyon Part-Dieu', { exact: true }).click()
    await expect(page.getByRole('button', { name: /Add 2 target\(s\) — 5 screen\(s\)/ })).toBeVisible()
  })

  test('node_creation_goes_through_a_form', async ({ page }) => {
    // R1 : le bouton creait le noeud IMMEDIATEMENT avec un nom par defaut, et pour une
    // racine ce nom etait « Nouvelle region » — alors qu'une racine est le niveau le PLUS
    // HAUT. Le premier clic poussait donc a modeliser a l'envers.
    await mockGovernance(page)
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    let posted: Record<string, unknown> | null = null
    await page.route('**/api/v1/governance/nodes', async (r) => {
      if (r.request().method() !== 'POST') return r.fallback()
      posted = r.request().postDataJSON()
      return r.fulfill({ status: 201, contentType: 'application/json',
        body: JSON.stringify({ id_node: 99, id_org: 1, parent_id: null, node_name: 'National FR', node_level: 0, node_type: 'national', path: '99', child_count: 0 }) })
    })

    await page.getByRole('button', { name: /New root node/i }).click()
    // Le nom est OBLIGATOIRE : plus de nom par defaut trompeur.
    const create = page.getByRole('button', { name: /^Create$/ })
    await expect(create).toBeDisabled()
    await page.locator('input').last().fill('National FR')
    await create.click()
    await expect.poll(() => posted).not.toBeNull()
    expect(posted!.node_name).toBe('National FR')
  })
})