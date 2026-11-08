/**
 * Tests de la négociation `Accept-Language` (P3.7).
 *
 * Exécution : `node tests/unit/negotiate.test.mts` depuis `frontend/`.
 * Node ≥ 23 retire les annotations de type nativement — aucun outillage à ajouter.
 *
 * Volontairement en `.mts` : le `include: ["**\/*.ts"]` de `tsconfig.json` ferait
 * type-checker un `.ts`, et l'import d'une extension `.ts` y est refusé.
 *
 * Ces tests portent sur la fonction PURE. Le chemin HTTP réel (en-tête reçu par
 * Next, cookie prioritaire, messages effectivement rendus) est prouvé à part par
 * `tests/e2e/locale_negotiation.spec.ts` — un parseur juste branché nulle part
 * ne servirait à rien.
 */
import assert from 'node:assert/strict'
import { negotiateLocale, isSupportedLocale, defaultLocale } from '../../src/i18n/negotiate.ts'

let failures = 0
function check(label: string, actual: unknown, expected: unknown) {
  try {
    assert.deepEqual(actual, expected)
    console.log(`  ok   ${label}`)
  } catch {
    failures++
    console.log(`  FAIL ${label} — attendu ${JSON.stringify(expected)}, obtenu ${JSON.stringify(actual)}`)
  }
}

console.log('negotiateLocale — absence et valeurs vides')
check('en-tête absent (null)', negotiateLocale(null), 'en')
check('en-tête absent (undefined)', negotiateLocale(undefined), 'en')
check('en-tête vide', negotiateLocale(''), 'en')
check('que des virgules', negotiateLocale(',,,'), 'en')

console.log('negotiateLocale — ② la région est écartée')
check('fr-BE -> fr', negotiateLocale('fr-BE'), 'fr')
check('pt-BR -> pt', negotiateLocale('pt-BR'), 'pt')
check('es-MX -> es', negotiateLocale('es-MX'), 'es')
check('casse ignorée (FR-be)', negotiateLocale('FR-be'), 'fr')
check('espaces tolérés', negotiateLocale('  de-AT  '), 'de')

console.log('negotiateLocale — ① liste ORDONNÉE et pondérée')
check('premier servi gagne', negotiateLocale('fr-FR,fr;q=0.9,en;q=0.8'), 'fr')
check('le q l ordre sur l ecriture', negotiateLocale('de;q=0.7, fr;q=0.9'), 'fr')
check('q egaux -> ordre d ecriture', negotiateLocale('de;q=0.8, fr;q=0.8'), 'de')
check('langue non servie sautee', negotiateLocale('zh-CN, ja;q=0.9, de;q=0.5'), 'de')
check('q par defaut = 1 bat un q explicite', negotiateLocale('es;q=0.9, pt'), 'pt')

console.log('negotiateLocale — ③ repli, jamais d exception')
check('aucune langue servie', negotiateLocale('zh-CN,ja;q=0.9'), 'en')
check('joker seul', negotiateLocale('*'), 'en')
check('joker + langue servie', negotiateLocale('*;q=0.5, de;q=0.4'), 'de')
check('q=0 = pas acceptable', negotiateLocale('fr;q=0'), 'en')
check('q=0 sur l un, l autre reste', negotiateLocale('fr;q=0, de;q=0.5'), 'de')
check('q illisible -> entree ecartee', negotiateLocale('fr;q=abc, de'), 'de')
check('q hors bornes -> entree ecartee', negotiateLocale('fr;q=9, de'), 'de')
check('q negatif -> entree ecartee', negotiateLocale('fr;q=-1, de'), 'de')
check('en-tete absurde', negotiateLocale(';;;q=;;'), 'en')
check('entree pathologique bornee', negotiateLocale('zz,'.repeat(5000) + 'fr'), 'en')

console.log('isSupportedLocale — garde de type (le cookie passe par là)')
check('fr servi', isSupportedLocale('fr'), true)
check('en servi', isSupportedLocale('en'), true)
check('xx non servi', isSupportedLocale('xx'), false)
check('vide non servi', isSupportedLocale(''), false)
check('null non servi', isSupportedLocale(null), false)
check('objet non servi', isSupportedLocale({}), false)
check('casse non toleree (FR)', isSupportedLocale('FR'), false)
check('defaultLocale est servi', isSupportedLocale(defaultLocale), true)

console.log(failures === 0 ? '\nTous verts.' : `\n${failures} ÉCHEC(S).`)
process.exit(failures === 0 ? 0 : 1)
