import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000',
    // Locale FIGÉE (P3.7) : l'interface négocie désormais `Accept-Language` tant
    // qu'aucun cookie `locale` n'est posé. Sans ce réglage, Chrome enverrait la
    // langue de l'OS — 45 des 49 specs passent par /login SANS poser de cookie et
    // rendraient donc en français sur ce poste, en anglais sur le runner CI. Le
    // test qui vérifie la négociation, lui, surcharge cette valeur explicitement.
    locale: 'en-US',
    // CI : pas de trace — chaque trace pèse plusieurs Mo et gonflait le rapport
    // uploadé en artefact (quota Actions 0,5 Go saturé le 21/07). Les captures
    // d'écran on-failure suffisent ; en local, les retries sont à 0 de toute façon.
    trace: process.env.CI ? 'off' : 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],
  webServer: process.env.CI
    ? {
        command: 'npm run start',
        url: 'http://localhost:3000',
        reuseExistingServer: false,
      }
    : undefined,
})
