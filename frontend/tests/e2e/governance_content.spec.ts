import { test, expect } from '@playwright/test'

// Contenu gouverné §XVIII (D6/D7/D9) — surface UI de la tranche backend du 25/07 :
//  · éditeur de playlist sous modération → « Submit for approval » à la place de Publier ;
//  · playlist d'un nœud non éditable (ancêtre) → bandeau lecture seule, aucun bouton ;
//  · sélecteur de nœud propriétaire : un nœud non éditable n'est pas proposé ;
//  · page Gouvernance : case « Content requires approval » verrouillée hors ancêtre.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const NOW = new Date().toISOString()
const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: NOW }

// national (non éditable par cet utilisateur) → store (éditable, sous modération)
const NODES = [
  { id_node: 1, id_org: 1, parent_id: null, node_name: 'National', node_level: 0, node_type: 'national', path: '1', created_at: NOW, child_count: 1, requires_approval: true, can_edit: false },
  { id_node: 2, id_org: 1, parent_id: 1, node_name: 'Store Lyon', node_level: 1, node_type: 'store', path: '1.2', created_at: NOW, child_count: 0, requires_approval: true, can_edit: true },
]

const BASE_PL = {
  id_playlist: 1, id_org: 1, playlist_name: 'Store Loop', description: null,
  id_template: null, sync_mode: 'wall_clock', total_duration_ms: 30000,
  sync_ready: true, has_item_rules: false, sync_windowed: false,
  rotation_mode: 'all', items_per_turn: 1, used_as_child: false,
  created_at: NOW, updated_at: NOW, items: [],
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

async function mockCommon(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/governance/nodes', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(NODES) })
  })
  await page.route('**/api/v1/templates', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
}

test.describe('Governed content (§XVIII)', () => {
  test('moderated_playlist_offers_submit_not_publish', async ({ page }) => {
    let submitted = false
    await mockCommon(page)
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...BASE_PL, has_draft_changes: true,
          id_governance_node: 2, governed_readonly: false, requires_approval: true,
          approval_status: null, approval_request_id: null,
        }),
      })
    })
    await page.route('**/api/v1/playlists/1/submit-approval', async (route) => {
      submitted = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id_request: 9, status: 'pending_review' }) })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    // Publier n'est PAS proposé : le nœud exige une approbation (409 côté serveur).
    await expect(page.getByRole('button', { name: 'Publish', exact: true })).toHaveCount(0)
    const submit = page.getByRole('button', { name: 'Submit for approval' })
    await expect(submit).toBeVisible()
    await submit.click()
    await expect.poll(() => submitted).toBe(true)

    // Carte Gouvernance : nœud propriétaire + pastille « sous modération ».
    await expect(page.getByText('Moderated', { exact: true })).toBeVisible()
  })

  test('pending_review_blocks_resubmission', async ({ page }) => {
    await mockCommon(page)
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...BASE_PL, has_draft_changes: true,
          id_governance_node: 2, governed_readonly: false, requires_approval: true,
          approval_status: 'pending_review', approval_request_id: 9,
        }),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await expect(page.getByText('Changes submitted — awaiting approval.')).toBeVisible()
    // Re-soumettre repartirait en 409 « demande déjà active » → bouton désactivé.
    await expect(page.getByRole('button', { name: 'Submit for approval' })).toBeDisabled()
  })

  test('readonly_node_shows_banner_and_no_actions', async ({ page }) => {
    let mutated = false
    await mockCommon(page)
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      if (route.request().method() !== 'GET') mutated = true
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...BASE_PL, playlist_name: 'National Loop', has_draft_changes: true,
          id_governance_node: 1, governed_readonly: true, requires_approval: true,
          approval_status: null, approval_request_id: null,
        }),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    await expect(page.getByText(/Content of node .*National.*: visible, not editable/)).toBeVisible()
    // Ni publication ni soumission : tout finirait en 403.
    await expect(page.getByRole('button', { name: 'Submit for approval' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Publish', exact: true })).toHaveCount(0)
    // Le sélecteur de nœud reste visible (contexte) mais verrouillé.
    await expect(page.getByLabel('Owning node')).toBeDisabled()

    // Les réglages restent LISIBLES (comprendre ce qui passe au-dessus de soi) mais
    // toute saisie est interceptée : sans ça, l'utilisateur croirait avoir modifié
    // le contenu national et n'aurait qu'un 403 silencieux.
    await page.getByText('Unsynchronized (loop)').click()
    await expect(page.getByText(/Governed content/)).toBeVisible()
    expect(mutated).toBe(false)
  })

  test('node_select_excludes_non_editable_nodes', async ({ page }) => {
    await mockCommon(page)
    await page.route(/\/api\/v1\/playlists\/1(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...BASE_PL, id_governance_node: 2, governed_readonly: false,
          requires_approval: true, approval_status: null,
        }),
      })
    })
    await mockAuthAndNavigate(page, `${BASE}/playlists/1`)

    const select = page.getByLabel('Owning node')
    await expect(select).toBeVisible()
    // « National » est visible (lecture seule) mais NON sélectionnable : le choisir
    // partirait en 403 côté serveur.
    await expect(select.locator('option', { hasText: 'National' })).toBeDisabled()
    await expect(select.locator('option', { hasText: 'Store Lyon' })).toBeEnabled()
  })

  test('governance_page_moderation_checkbox_locked_without_ancestor_right', async ({ page }) => {
    await page.route('**/api/v1/governance/nodes', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(NODES) })
    })
    await page.route('**/api/v1/governance/nodes/2', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ...NODES[1], children: [], rules: [], assignments: [], admins: [],
          can_disable_moderation: false,
        }),
      })
    })
    await page.route('**/api/v1/players/', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })
    await mockAuthAndNavigate(page, `${BASE}/governance`)

    // Mise en page A : l'arbre est déplié par défaut, le magasin est directement visible.
    await page.getByText('Store Lyon').first().click()
    const box = page.getByRole('checkbox', { name: /Content requires approval/ })
    await expect(box).toBeChecked()
    // D7 : seul un admin d'un nœud PARENT peut retirer la modération.
    await expect(box).toBeDisabled()
    await expect(page.getByText('Only an administrator of a parent node can remove moderation.')).toBeVisible()
  })
})

// ── R10 : l'aperçu du programme compilé nomme la VRAIE cause ─────────────────
// Avant : « No active governance layer for this player right now » pour cinq
// situations différentes — dont « le programme n'est pas rattaché au nœud », qui a
// coûté une recherche à l'aveugle en production le 25/07.
test.describe('Compiled program — real cause (R10)', () => {
  async function mockNode(page: import('@playwright/test').Page, compiled: object) {
    await page.route('**/api/v1/governance/nodes', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(NODES) }))
    await page.route('**/api/v1/governance/nodes/2', (r) =>
      r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ...NODES[1], children: [], rules: [], assignments: [], admins: [], can_disable_moderation: true }),
      }))
    await page.route('**/api/v1/governance/nodes/2/players', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: '[7]' }))
    await page.route('**/api/v1/players/', (r) =>
      r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify([{ id_player: 7, player_name: 'Ecran test', id_org: 1, status: 'online', player_os: 'linux', created_at: NOW, updated_at: NOW }]),
      }))
    await page.route(/\/api\/v1\/players\/7\/compiled-schedule.*/, (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(compiled) }))
  }

  const EMPTY = { id_player: 7, resolved_at: NOW, cycle_duration_ms: 0, layers: [], items: [] }

  test('names_the_missing_schedule', async ({ page }) => {
    await mockNode(page, { ...EMPTY, empty_reason: 'no_schedule', empty_detail: null })
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()
    await page.getByTestId('gov-player-select').selectOption('7')

    await expect(page.getByText(/No schedule is attached to this node/)).toBeVisible()
    // Le message doit aussi lever le malentendu de fond.
    await expect(page.getByText(/Attaching a playlist to a node does not broadcast it/)).toBeVisible()
    await expect(page.getByText('No active governance layer for this player right now.')).toHaveCount(0)
  })

  test('names_the_window_and_offers_the_simulated_time', async ({ page }) => {
    await mockNode(page, { ...EMPTY, empty_reason: 'outside_window', empty_detail: 'SC Governance' })
    await mockAuthAndNavigate(page, `${BASE}/governance`)
    await page.getByText('Store Lyon').first().click()
    await page.getByTestId('gov-player-select').selectOption('7')

    await expect(page.getByText(/“SC Governance” is outside its broadcast window/)).toBeVisible()
    await expect(page.getByText(/simulated time/)).toBeVisible()
  })
})
