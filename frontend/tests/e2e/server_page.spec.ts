import { test, expect } from '@playwright/test'

// Page « Serveur » (2026-08-03). Specs de RÉSULTAT : ce que l'exploitant lit à l'écran.

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'
const USER = {
  id_user: 1, id_org: 1, email: 'admin@test.com', full_name: 'Olivia Rhye', avatar_url: null,
  totp_enabled: false, locale: 'en', is_active: true, last_login_at: null,
  created_at: new Date().toISOString(), permissions: [],
}

const WITH_GPU = {
  version: '1.0.24',
  workers: [{
    hostname: 'media-01', hw_encoders: ['h264_nvenc', 'hevc_nvenc'],
    encoder_h264: 'h264_nvenc', encoder_hevc: 'hevc_nvenc',
    cpu_count: 24, ffmpeg_threads: 7, ffmpeg_version: '7.1.4',
    work_dir: '/tmp', disk_total_bytes: 1_000_000_000_000, disk_free_bytes: 400_000_000_000,
    at: 1,
  }],
  queue: [
    { id_media: 1, media_name: 'Spot 4K', id_org: 1, transcode_status: 'processing',
      encode_progress: { phase: 'encode', pct: 61, eta_s: 240, speed: 1.2, at: 1 },
      encode_decision: null },
    { id_media: 2, media_name: 'Film long', id_org: 1, transcode_status: 'awaiting_decision',
      encode_progress: null,
      encode_decision: { band: 'confirm', estimate_s: 3600, downscale: [] } },
  ],
  throughput: [{ encoder: 'hevc_nvenc', samples: 12, avg_speed: 3.4 }],
  media: { count: 89, total_bytes: 12_000_000_000 },
  encode_bands: { auto_below_s: 1200, refuse_above_s: 14400 },
}

async function setup(page: import('@playwright/test').Page, body: unknown, status = 200) {
  await page.goto(`${BASE}/login`)
  await page.evaluate((u) => {
    const b64 = (o: unknown) =>
      btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    const tk = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.${b64({
      sub: '1', org: 1, roles: ['CMS_ORG_ADMIN'], locale: 'en', type: 'access', exp: 9999999999,
    })}.sig`
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: 'r', roles: ['CMS_ORG_ADMIN'] }, version: 0,
    }))
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', 'r')
  }, USER)
  const json = (b: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(b) })
  await page.route('**/api/v1/users/me', (r) => r.fulfill(json(USER)))
  await page.route('**/api/v1/auth/refresh', (r) => r.fulfill(json({ access_token: 'x', refresh_token: 'r', token_type: 'bearer', locale: 'en' })))
  await page.route('**/api/v1/meta/server', (r) =>
    r.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }))
  await page.goto(`${BASE}/settings/server`)
}

test('la page dit si l accélération matérielle est active', async ({ page }) => {
  // C'est LE chiffre qui explique un encodage lent — il n'était visible nulle part.
  await setup(page, WITH_GPU)
  await expect(page.getByText(/Hardware acceleration active/)).toBeVisible()
  await expect(page.getByText(/h264_nvenc/).first()).toBeVisible()
  await expect(page.getByText(/400.0 Go free of/)).toBeVisible()
})

test('sans accélération matérielle, la page le dit clairement', async ({ page }) => {
  await setup(page, {
    ...WITH_GPU,
    workers: [{ ...WITH_GPU.workers[0], hw_encoders: [], encoder_h264: 'libx264', encoder_hevc: 'libx265' }],
  })
  await expect(page.getByText(/No hardware acceleration/)).toBeVisible()
})

test('aucun worker qui répond est signalé, pas masqué', async ({ page }) => {
  // Sans ce message, la page afficherait un vide silencieux là où la vraie information
  // est « les encodages ne peuvent pas aboutir ».
  await setup(page, { ...WITH_GPU, workers: [] })
  await expect(page.getByText(/No media worker is responding/)).toBeVisible()
})

test('la file montre la progression et ce qui attend une décision', async ({ page }) => {
  await setup(page, WITH_GPU)
  await expect(page.getByText('Spot 4K')).toBeVisible()
  await expect(page.getByTestId('encode-progress').first()).toBeVisible()
  await expect(page.getByText('Film long')).toBeVisible()
  await expect(page.getByText(/Estimated at 60 min/)).toBeVisible()
})

test('les débits constatés viennent du serveur', async ({ page }) => {
  await setup(page, WITH_GPU)
  // Assertion portée par la LIGNE de l'encodeur : « 12 » seul apparaît ailleurs dans la
  // page (taille de la médiathèque), un `getByText` global ne prouverait rien.
  const row = page.getByRole('row').filter({ hasText: 'hevc_nvenc' })
  await expect(row).toContainText('3.4×')
  await expect(row).toContainText('12')
  // Les bandes affichées sont celles du serveur, jamais recopiées côté client.
  await expect(page.getByText(/20 min/)).toBeVisible()
  await expect(page.getByText(/4 h/)).toBeVisible()
})

test('un non-porteur voit un ETAT explique, pas une erreur', async ({ page }) => {
  // Retour d'Ed (03/08) : une phrase rouge accusait l'utilisateur alors qu'il n'a rien
  // fait de mal. Même traitement que la page Licence — un panneau qui explique.
  await setup(page, { detail: "Réservé à l'exploitant du serveur" }, 403)
  await expect(page.getByText(/operated by your provider/i)).toBeVisible()
  await expect(page.getByText(/keeps being processed normally/i)).toBeVisible()
  // Et surtout : pas de ton d'erreur sur un état légitime.
  await expect(page.getByText(/Could not read the server status/i)).toHaveCount(0)
})

test('une vraie panne garde un ton d erreur', async ({ page }) => {
  // Le pendant du test precedent : ne pas rendre TOUT calme, une panne reste une panne.
  await setup(page, { detail: 'boom' }, 500)
  await expect(page.getByText(/Could not read the server status/i)).toBeVisible()
  await expect(page.getByText(/operated by your provider/i)).toHaveCount(0)
})
