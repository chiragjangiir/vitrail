import { test, expect } from '@playwright/test'

/**
 * P3.7 — l'écran de connexion négocie `Accept-Language`.
 *
 * Ces specs affirment un RÉSULTAT : le texte réellement rendu par le serveur pour
 * un navigateur donné. Elles exercent la chaîne complète (en-tête reçu par Next →
 * `request.ts` → messages importés), là où `tests/unit/negotiate.test.mts` ne
 * couvre que la fonction pure.
 *
 * ⚠️ La locale est FIGÉE à `en-US` dans `playwright.config.ts` pour toute la
 * suite ; chaque bloc ci-dessous la surcharge explicitement, c'est tout l'objet
 * du test.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

// Libellé du titre de l'écran de connexion (`auth.login`) dans chaque langue.
const TITLE = {
  en: 'Sign in',
  fr: 'Connexion',
  de: 'Anmelden',
  pt: 'Entrar',
} as const

async function titleOfLoginPage(page: import('@playwright/test').Page) {
  await page.goto(`${BASE}/login`)
  return page.getByRole('heading', { level: 1 }).first()
}

test.describe('Négociation — la langue du navigateur est honorée', () => {
  test.use({ locale: 'fr-BE' })

  test('accept_language_fr_be_serves_french — la région est écartée', async ({ page }) => {
    // `fr-BE` : on ne sert pas de variante belge, on sert du français.
    await expect(await titleOfLoginPage(page)).toHaveText(TITLE.fr)
  })
})

test.describe('Négociation — allemand', () => {
  test.use({ locale: 'de-DE' })

  test('accept_language_de_serves_german', async ({ page }) => {
    await expect(await titleOfLoginPage(page)).toHaveText(TITLE.de)
  })
})

test.describe('Négociation — langue non servie', () => {
  test.use({ locale: 'zh-CN' })

  test('accept_language_unsupported_falls_back_to_english', async ({ page }) => {
    // Repli, jamais d'erreur : le prospect chinois voit l'anglais, pas un 500.
    await expect(await titleOfLoginPage(page)).toHaveText(TITLE.en)
  })
})

test.describe("Négociation — l'en-tête est une liste ORDONNÉE et pondérée", () => {
  test('accept_language_respects_q_weights_over_write_order', async ({ request }) => {
    // ⚠️ Ce cas passe par une requête HTTP directe et NON par le navigateur :
    // l'option `locale` de Playwright fixe `Accept-Language` au niveau du contexte
    // et écrase `extraHTTPHeaders`, si bien qu'un en-tête pondéré écrit ainsi
    // n'atteint jamais le serveur (mesuré — le test échouait en recevant `en-US`).
    // Envoyer l'en-tête brut est la seule façon de prouver la règle des `q`.
    //
    // Écrit en premier : l'allemand. Demandé le plus fort : le portugais.
    const res = await request.get(`${BASE}/login`, {
      headers: { 'Accept-Language': 'de;q=0.7, pt;q=0.9, en;q=0.5' },
    })
    expect(res.status()).toBe(200)

    // ⚠️ On compare le contenu du <h1>, PAS une sous-chaîne du HTML brut : la page
    // embarque tout le catalogue de messages, où « Sign in » apparaît à l'intérieur
    // de « BrightSign install » — un `toContain` y était vert quelle que soit la
    // langue servie (mesuré). Un témoin qui ne peut pas distinguer les deux cas ne
    // prouve rien.
    const h1 = (await res.text()).match(/<h1[^>]*>([^<]*)<\/h1>/)?.[1]
    expect(h1).toBe(TITLE.pt)
  })
})

test.describe('Le cookie explicite l’emporte TOUJOURS sur l’en-tête', () => {
  test.use({ locale: 'fr-FR' })

  test('cookie_wins_over_accept_language', async ({ page, context }) => {
    // Navigateur en français, mais l'utilisateur a choisi l'anglais dans son
    // profil : son choix ne doit pas être repris par la préférence du navigateur.
    await context.addCookies([
      { name: 'locale', value: 'en', url: BASE },
    ])
    await expect(await titleOfLoginPage(page)).toHaveText(TITLE.en)
  })

  test('cookie_wins_in_the_other_direction_too', async ({ page, context }) => {
    // Le symétrique : sans lui, un test vert ne prouverait que « l'anglais gagne ».
    await context.addCookies([
      { name: 'locale', value: 'pt', url: BASE },
    ])
    await expect(await titleOfLoginPage(page)).toHaveText(TITLE.pt)
  })
})

test.describe('Un cookie invalide ne casse plus la page', () => {
  test.use({ locale: 'de-DE' })

  test('bogus_locale_cookie_no_longer_500s', async ({ page, context }) => {
    // Régression mesurée le 2026-08-06 : `locale=xx` faisait répondre 500 à TOUTES
    // les pages (chemin d'import de messages construit sans validation).
    // On repart sur la négociation, donc l'allemand du navigateur.
    await context.addCookies([
      { name: 'locale', value: 'xx', url: BASE },
    ])
    const response = await page.goto(`${BASE}/login`)
    expect(response?.status()).toBe(200)
    await expect(page.getByRole('heading', { level: 1 }).first()).toHaveText(TITLE.de)
  })
})
