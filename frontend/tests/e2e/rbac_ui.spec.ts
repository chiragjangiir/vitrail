import { test, expect } from '@playwright/test'

/**
 * Masquage UI par permission (audit rôles 2026-07-20).
 *
 * Constat Ed : quel que soit le rôle, TOUS les menus étaient visibles et les
 * formulaires acceptaient la saisie — le backend refusait bien (403) mais sans
 * que l'utilisateur le sache. Le frontend n'avait aucune notion de permission
 * (`hasRole('CMS_SUPER_ADMIN')` était son seul test de droits).
 *
 * ⚠️ Ces specs vérifient un CONFORT D'AFFICHAGE, pas une sécurité : l'autorisation
 * réelle est côté serveur et couverte par `tests/test_users.py`.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

/** JWT non signé côté vérif front (le back n'est pas sollicité : /users/me est mocké). */
function tokenFor(roles: string[]): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: '1', org: 1, roles, locale: 'en', type: 'access', exp: 9999999999 })
  ).toString('base64url')
  return `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${payload}.sig`
}

function meFor(roles: string[], permissions: string[]) {
  return {
    id_user: 1, id_org: 1, email: 'u@test.com', full_name: 'U', avatar_url: null,
    totp_enabled: false, locale: 'en', theme: 'dark', is_active: true, is_demo: false,
    id_advertiser: null, last_login_at: null, created_at: new Date().toISOString(),
    org_name: 'Org', roles, permissions,
  }
}

async function loginAs(
  page: import('@playwright/test').Page, roles: string[], permissions: string[]
) {
  const token = tokenFor(roles)
  await page.route('**/api/v1/users/me', async (r) => {
    await r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(meFor(roles, permissions)) })
  })
  await page.route('**/api/v1/auth/refresh', async (r) => {
    await r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: token, refresh_token: 'r', token_type: 'bearer', locale: 'en' }),
    })
  })
  // Tout le reste : réponses vides, on ne teste que le rendu de la navigation.
  await page.route(/\/api\/v1\/(?!users\/me|auth\/refresh)/, async (r) => {
    await r.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.goto(`${BASE}/login`)
  await page.evaluate(([tk, me]) => {
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: me, accessToken: tk, refreshToken: 'r', roles: (me as { roles: string[] }).roles },
      version: 0,
    }))
    localStorage.setItem('sf_access_token', tk as string)
    localStorage.setItem('sf_refresh_token', 'r')
  }, [token, meFor(roles, permissions)] as const)
  await page.goto(`${BASE}/schedules`)
}

test.describe('Masquage UI par permission', () => {
  test('approver_ne_voit_que_ses_menus', async ({ page }) => {
    // Rôle CMS_APPROVER réel : approvals:review/approve/reject + 3 lectures.
    await loginAs(page, ['CMS_APPROVER'], [
      'approvals:review', 'approvals:approve', 'approvals:reject',
      'media:read', 'templates:read', 'playlists:read',
    ])
    const nav = page.getByRole('navigation', { name: 'Main navigation' })

    // Visible : ce qu'il peut réellement lire.
    await expect(nav.getByRole('link', { name: 'Media', exact: true })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Playlists', exact: true })).toBeVisible()

    // Masqué : tout ce qui renvoyait 403 (constat Ed — dont les Players, d'où
    // l'accès au bouton « seuils d'alerte »).
    for (const label of ['Players', 'Schedules', 'Events', 'Campaigns', 'Governance', 'Dashboard']) {
      await expect(nav.getByRole('link', { name: label, exact: true })).toHaveCount(0)
    }
    // Réglages réservés aux org-admins.
    for (const label of ['Users & Roles', 'Notifications', 'Updates', 'Security']) {
      await expect(nav.getByRole('link', { name: label, exact: true })).toHaveCount(0)
    }
    // Les enfants de « Rapports » ne doivent pas non plus remonter au premier
    // niveau : ils exigent `reports:read` comme leur parent (défaut vu à la
    // capture du 2026-07-20 — ils s'affichaient faute de `perm` déclaré).
    for (const label of ['Executive Dashboard', 'Network / NOC', 'Proof of Play', 'Music Rights']) {
      await expect(nav.getByRole('link', { name: label, exact: true })).toHaveCount(0)
    }
    // En revanche « Approvals », lui, remonte bien : c'est son seul accès.
    await expect(nav.getByRole('link', { name: 'Approvals', exact: true })).toBeVisible()

    // Toujours accessibles : profil et manuel.
    await expect(nav.getByRole('link', { name: 'Profile', exact: true })).toBeVisible()
  })

  test('approver_na_pas_le_bouton_creer', async ({ page }) => {
    await loginAs(page, ['CMS_APPROVER'], ['approvals:review', 'playlists:read'])
    // Le « + New » disparaît quand aucun raccourci de création n'est permis.
    await expect(page.getByRole('button', { name: /New$/ })).toHaveCount(0)
  })

  test('org_admin_voit_tout', async ({ page }) => {
    // Non-régression : l'org-admin passe par `isAdmin()`, sans dépendre de la
    // liste de permissions (il porte tout le catalogue).
    await loginAs(page, ['CMS_ORG_ADMIN'], [])
    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    for (const label of ['Dashboard', 'Media', 'Players', 'Schedules', 'Campaigns']) {
      await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible()
    }
  })

  test('scheduler_voit_la_programmation_pas_liam', async ({ page }) => {
    await loginAs(page, ['CMS_SCHEDULER'], [
      'schedules:read', 'schedules:create', 'events:read', 'events:create',
      'players:read', 'playlists:read', 'media:read', 'templates:read', 'vod:read',
    ])
    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    await expect(nav.getByRole('link', { name: 'Schedules', exact: true })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Players', exact: true })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Users & Roles', exact: true })).toHaveCount(0)
    // Il peut créer un programme : le bouton est là.
    await expect(page.getByRole('button', { name: 'New schedule' })).toBeVisible()
  })
})

