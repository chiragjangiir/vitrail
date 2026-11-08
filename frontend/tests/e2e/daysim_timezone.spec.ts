import { test, expect } from '@playwright/test'

// P2.2 — la simulation d'une journée affiche des horaires qui sont désormais ceux de
// l'ÉCRAN (fuseau de son site) et non plus ceux du serveur. Sans le dire, « 12:00 » est
// ambigu dès qu'un parc traverse deux fuseaux.
//
// Ce test vise le RENDU du libellé, pas seulement sa présence : une clé i18n manquante
// ou posée dans le mauvais namespace s'affiche en clé brute (« schedules.daysim_timezone »)
// sans que tsc ni la parité des locales ne le voient — le piège documenté au § Frontend.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const MOCK_USER_ME = { id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Admin', avatar_url: null, totp_enabled: false, locale: 'en', is_active: true, last_login_at: null, created_at: new Date().toISOString() }

const SIM_RESULT = {
  id_player: 9,
  date: new Date().toISOString().slice(0, 10),
  timezone: 'America/New_York',
  video: [{ start: '08:00', end: '12:00', source: 'schedule', name: 'Morning Loop', playlist_name: 'PL', priority: 10 }],
  audio: [],
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

test.describe('Day simulation timezone', () => {
  test('simulation_states_the_screen_timezone', async ({ page }) => {
    // ⚠️ Regex et non glob : ces endpoints peuvent porter une query string.
    for (const [pattern, body] of [
      [/\/api\/v1\/schedules(\?.*)?$/, '[]'],
      [/\/api\/v1\/events(\?.*)?$/, '[]'],
      [/\/api\/v1\/campaigns\/(\?.*)?$/, '[]'],
    ] as const) {
      await page.route(pattern, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body })
      })
    }
    for (const [pattern, body] of [
      ['**/api/v1/players/**', JSON.stringify([{ id_player: 9, player_name: 'Lobby Screen', status: 'online', player_os: 'linux' }])],
      ['**/api/v1/sites**', JSON.stringify([{ id_site: 3, site_name: 'Site A' }])],
      ['**/api/v1/site-groups/**', '[]'],
      ['**/api/v1/player-groups/**', '[]'],
      ['**/api/v1/governance/nodes**', '[]'],
    ] as const) {
      await page.route(pattern, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body })
      })
    }
    await page.route('**/api/v1/players/9/simulate-day', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SIM_RESULT) })
    })

    await mockAuthAndNavigate(page, `${BASE}/schedules`)
    await page.getByRole('button', { name: 'Simulate a day' }).click()

    // Repère STABLE : le tiroir lui-même (role=dialog + son titre), jamais une position
    // ni un libellé ambigu — « Player » désigne aussi un bouton de la barre latérale.
    const drawer = page.getByRole('dialog', { name: 'Player day simulation' })
    await expect(drawer).toBeVisible()
    await drawer.locator('select').selectOption('9')
    await drawer.getByRole('button', { name: 'Run simulation' }).click()

    // Le fuseau de l'écran est NOMMÉ, et le libellé est traduit (pas la clé brute).
    const line = drawer.getByText(/America\/New_York/)
    await expect(line).toBeVisible()
    await expect(drawer.getByText('schedules.daysim_timezone')).toHaveCount(0)
    await expect(line).toContainText(/local time/i)
  })
})
