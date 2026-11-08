import { test, expect } from '@playwright/test'

/**
 * Défaut signalé par Ed le 2026-08-11 sur le tiroir des feeds : « je sélectionne
 * colonnes, je tape 1 et cela écrit 6, quand j'efface cela écrit 3 ».
 *
 * Cause : le champ était CONTRÔLÉ et CLAMPÉ à chaque frappe —
 *   value={String(config.grid_columns)}
 *   onChange={(e) => setCfg('grid_columns', Math.min(6, Math.max(1, parseInt(e.target.value, 10) || 3)))}
 * Il n'existait donc AUCUN état intermédiaire de saisie :
 *   · champ à 3, on tape « 1 » → la chaîne devient « 31 » → Math.min(6, 31) = 6 ;
 *   · on efface            → parseInt('') = NaN → NaN || 3 = 3, le champ se remplit tout seul.
 * Conséquence : impossible de vider pour retaper, donc impossible d'atteindre
 * certaines valeurs autrement qu'en sélectionnant tout. 46 champs du produit
 * portaient cette écriture ; tous passent désormais par `NumberField`.
 *
 * ⚠️ Ce que ce test doit prouver n'est PAS « taper 1 donne 1 » pour le geste exact
 * d'Ed : « 31 » dépasse le plafond de 6, donc 6 reste la bonne valeur finale. Le
 * vrai acquis est qu'on peut VIDER le champ et retaper — c'est ce qui était
 * impossible, et c'est ce qu'on fige ici.
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

// Feed en mode `card_grid` : c'est le seul mode qui expose Colonnes / Lignes.
const FEED = {
  id_feed: 7, id_media: 70, feed_name: 'Flux test', feed_type: 'rss',
  url: 'https://example.com/rss', display_mode: 'card_grid',
  display_config: { grid_columns: 3, grid_rows: 2 },
  config: {}, polling_interval_s: 900, max_items: 10,
  moderation_enabled: false, ai_summary_enabled: false,
  status: 'ok', last_error: null, item_count: 0,
  last_fetch_at: null, created_at: new Date().toISOString(),
}

async function auth(page: import('@playwright/test').Page) {
  // ⚠️ Playwright résout les routes de la DERNIÈRE enregistrée à la première : le glob
  // générique doit donc venir EN PREMIER, les plus spécifiques ensuite. Inversé, le
  // `feeds**` avalait `/feeds/7/items` et lui servait la LISTE des flux — des <li> sans
  // `key`, un avertissement React, et l'overlay de dev masquait le tiroir.
  await page.route(/\/api\/v1\/(?!feeds|users\/me|auth)/, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route('**/api/v1/feeds**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([FEED]) }))
  await page.route('**/api/v1/feeds/7', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FEED) }))
  await page.route('**/api/v1/feeds/7/items**', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route('**/api/v1/users/me', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ME) }))
  await page.route('**/api/v1/auth/refresh', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: TOKEN, refresh_token: 'r', token_type: 'bearer', locale: 'en' }) }))

  await page.goto(`${BASE}/login`)
  await page.evaluate((tk) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: { id_user: 1, id_org: 1, email: 'a@t.com', roles: ['CMS_ORG_ADMIN'], permissions: [] },
        accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, TOKEN)
}

/** Ouvre le tiroir d'édition du flux 7 et rend le champ « Colonnes ». */
async function openColumns(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/feeds`)
  await page.getByText('Flux test').first().click()
  const field = page.locator('input[type="number"][max="6"]')
  await expect(field).toBeVisible({ timeout: 10_000 })
  return field
}

test('un champ numerique se laisse VIDER puis retaper', async ({ page }) => {
  await auth(page)
  const field = await openColumns(page)
  await expect(field).toHaveValue('3')

  await field.click()
  await field.press('End')
  // Le geste qui était impossible : effacer le contenu du champ.
  await field.press('Backspace')
  // AVANT le correctif : le champ se remplissait tout seul avec « 3 » (NaN || 3),
  // si bien que la frappe suivante s'ajoutait à un 3 fantôme.
  await expect(field).toHaveValue('')

  await field.type('1')
  await expect(field).toHaveValue('1')
  await field.blur()
  // La valeur retenue est celle qu'on a tapée, pas un repli ni un clamp.
  await expect(field).toHaveValue('1')
})

test('les bornes s appliquent au commit, pas a la frappe', async ({ page }) => {
  await auth(page)
  const field = await openColumns(page)

  await field.click()
  await field.press('End')
  await field.type('1')                       // « 3 » + « 1 » = « 31 »
  // Pendant la frappe, l'affichage suit la SAISIE : le champ ne se réécrit plus
  // sous les doigts (avant, il affichait déjà « 6 » à cet instant).
  await expect(field).toHaveValue('31')

  // Au commit seulement, la borne s'applique — 31 colonnes n'existent pas.
  await field.blur()
  await expect(field).toHaveValue('6')
})
