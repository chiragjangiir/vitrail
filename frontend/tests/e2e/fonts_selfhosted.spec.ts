import { test, expect } from '@playwright/test'

/**
 * Deux propriétés de la typographie de l'interface, décidées le 2026-08-11 après
 * rendu comparé (`scripts/compare-fonts.mjs`) :
 *
 *  ① AUCUN APPEL À UN CDN DE POLICES. `globals.css` chargeait Inter depuis
 *     `fonts.googleapis.com` — mesuré présent dans le CSS SERVI en production.
 *     Le produit s'installe SUR SITE et doit fonctionner sans Internet ; l'appel
 *     envoyait de surcroît l'IP de chaque visiteur à un tiers. Il était en plus
 *     redondant : `next/font` auto-héberge déjà Inter.
 *
 *  ② LA CHASSE FIXE EST FIRA MONO, EMBARQUÉE. Tailwind ne personnalisait que
 *     `sans` : les 35 surfaces `font-mono` (IP, MAC, versions, schémas) rendaient
 *     dans une police différente selon l'OS — SF Mono, Consolas, Liberation Mono —
 *     et en Courier New là où aucune n'existe. Ce sont précisément les chaînes où
 *     confondre `0` et `O` coûte.
 *
 * ⚠️ Ces deux tests portent sur des propriétés que rien d'autre ne surveille : une
 * régression y serait invisible à l'écran sur nos postes (qui ont tous Consolas et
 * un accès Internet) et ne se verrait que chez un client hors ligne.
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const CDN = /fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit|fonts\.bunny\.net/

/**
 * ⚠️ CE TEST A DEUX ASSERTIONS, ET LA PREMIÈRE NE SUFFIT PAS — leçon du 2026-08-11.
 *
 * Le contrôle « aucune requête réseau » est VACANT sur le banc de dev : `next dev`
 * concatène `globals.css` derrière d'autres contenus, si bien qu'un `@import` s'y
 * retrouve à ~9900 octets du début. Or un `@import` n'est valide QU'EN TÊTE de
 * feuille de style : ailleurs, le navigateur l'ignore. Le défaut ne se manifeste
 * donc que dans le BUILD DE PRODUCTION, où l'import revient en tête — et c'est
 * bien ce qui a été mesuré sur la prod : 2 requêtes, la CSS chez googleapis ET le
 * woff2 chez gstatic.
 *
 * D'où la seconde assertion, qui porte sur la RÈGLE dans le CSS servi et vaut donc
 * dans les deux modes. Elle cherche un `@import` de CDN, pas la chaîne
 * « googleapis » : celle-ci figure légitimement dans le commentaire d'en-tête de
 * `globals.css`, et un contrôle naïf échouerait sur un produit parfaitement sain.
 */
test('aucun chargement de police depuis un CDN', async ({ page }) => {
  const external: string[] = []
  page.on('request', (r) => { if (CDN.test(r.url())) external.push(r.url()) })

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })

  // Témoin : la page a bien chargé (sinon « 0 requête externe » ne prouverait rien —
  // une page blanche n'en fait aucune).
  await expect(page.locator('form, input[type="password"], h1').first()).toBeVisible()
  expect(external, `requetes CDN : ${external.join(', ')}`).toHaveLength(0)

  // La règle elle-même, dans chaque feuille servie — vrai en dev comme en prod.
  const hrefs = await page.evaluate(() =>
    [...document.querySelectorAll('link[rel="stylesheet"]')].map((l) => (l as HTMLLinkElement).href))
  expect(hrefs.length, 'aucune feuille de style servie ?').toBeGreaterThan(0)

  const offending: string[] = []
  for (const href of hrefs) {
    const css = await (await page.request.get(href)).text()
    const m = css.match(/@import\s+url\(\s*['"]?https?:\/\/[^)]*(?:googleapis|gstatic|typekit|bunny)[^)]*\)/gi)
    if (m) offending.push(`${href} -> ${m.join(' ; ')}`)
  }
  expect(offending, `@import de CDN dans le CSS servi : ${offending.join(' | ')}`).toHaveLength(0)
})

test('la chasse fixe est Fira Mono, servie depuis notre origine', async ({ page }) => {
  await page.goto(`${BASE}/login`)

  // On mesure ce que le NAVIGATEUR calcule pour une classe `font-mono`, pas ce que
  // dit la config : c'est la pile effective qui décide de ce que l'opérateur lit.
  const stack = await page.evaluate(() => {
    const el = document.createElement('span')
    el.className = 'font-mono'
    el.textContent = '192.168.1.10'
    document.body.appendChild(el)
    const f = getComputedStyle(el).fontFamily
    el.remove()
    return f
  })
  expect(stack.toLowerCase()).toContain('fira mono')

  // Et la face doit être RÉELLEMENT chargée depuis notre origine.
  const loaded = await page.evaluate(async () => {
    await document.fonts.ready
    return document.fonts.check('12px "Fira Mono"')
  })
  expect(loaded, 'la face Fira Mono doit etre chargee').toBe(true)
})
