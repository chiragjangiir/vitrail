/**
 * Tests du parseur CSV du mode série (générateur promo).
 *
 * Exécution : `node tests/unit/csv.test.mts` depuis `frontend/`.
 * Node ≥ 23 retire les annotations de type nativement — aucun outillage à ajouter.
 * ⚠️ Ces tests ne sont PAS dans la CI (comme `negotiate.test.mts`) : à relancer à la main
 * après toute retouche du parseur.
 *
 * Ce qu'ils verrouillent : les quatre choses qu'un fichier RÉEL apporte et qu'un parseur naïf
 * casse — le point-virgule d'Excel FR, la BOM, les guillemets, les CRLF — plus la règle qui
 * évite le pire défaut : ne jamais deviner les colonnes EN SILENCE.
 */
import assert from 'node:assert/strict'
import { parseCsv, parseSerieCsv, detectSeparator } from '../../src/lib/csv.ts'

let failures = 0
function check(label: string, actual: unknown, expected: unknown) {
  try {
    assert.deepEqual(actual, expected)
    console.log(`  ok   ${label}`)
  } catch {
    failures++
    console.log(`  FAIL ${label}\n         attendu ${JSON.stringify(expected)}\n         obtenu  ${JSON.stringify(actual)}`)
  }
}

// ── Séparateur ───────────────────────────────────────────────────────────────
check('Excel FR sépare avec ;', detectSeparator('nom;prix\na;1'), ';')
check('CSV standard sépare avec ,', detectSeparator('nom,prix\na,1'), ',')
check('tabulation reconnue', detectSeparator('nom\tprix\na\t1'), '\t')
// 🔑 Sans exclure les guillemets, ce slogan ferait détecter la virgule et rendrait 3 colonnes.
check('une virgule DANS un champ ne fait pas le séparateur',
  detectSeparator('"Frais, local et de saison";4,99'), ';')

// ── Robustesse du fichier ────────────────────────────────────────────────────
check('BOM UTF-8 retirée', parseCsv('﻿nom;prix\nDyson;499')[0], ['nom', 'prix'])
check('CRLF', parseCsv('a;b\r\nc;d'), [['a', 'b'], ['c', 'd']])
check('ligne vide finale ignorée', parseCsv('a;b\n\n'), [['a', 'b']])
check('guillemets : séparateur inclus', parseCsv('"a;b";c'), [['a;b', 'c']])
check('guillemets : "" = un guillemet', parseCsv('"il dit ""oui""";c'), [['il dit "oui"', 'c']])
check('guillemets : saut de ligne inclus', parseCsv('"deux\nlignes";c'), [['deux\nlignes', 'c']])
check('espaces autour des valeurs retirés', parseCsv(' a ; b '), [['a', 'b']])

// ── Reconnaissance des colonnes ──────────────────────────────────────────────
const accents = parseSerieCsv('Produit;Prix;Prix barré;Remise\nDyson V15;499,00;599,00;-17%')
// 🔑 Le test qui prouve la normalisation des accents : « Prix barré » doit tomber sur
// `original_price`. Si la classe de diacritiques était cassée, il resterait non reconnu.
check('en-têtes accentués reconnus', accents.mapped,
  ['slogan', 'price', 'original_price', 'discount_pct'])
check('en-tête détecté', accents.hasHeader, true)
check('ligne lue', accents.lines,
  [{ slogan: 'Dyson V15', price: '499,00', original_price: '599,00', discount_pct: '-17%' }])

check('en-têtes anglais reconnus',
  parseSerieCsv('name,price,was\nV15,499,599').lines,
  [{ slogan: 'V15', price: '499', original_price: '599' }])

// L'ordre du fichier fait foi, pas un ordre attendu.
check('colonnes dans le désordre',
  parseSerieCsv('Prix;Produit\n499;V15').lines, [{ price: '499', slogan: 'V15' }])

// Une colonne inconnue est ignorée sans faire tomber les autres.
check('colonne inconnue ignorée',
  parseSerieCsv('nom;reference;prix\nV15;REF-1;499').lines,
  [{ slogan: 'V15', price: '499' }])

// ⛔ La règle qui évite le pire : sans en-tête reconnu on lit par position, mais on le DIT.
const noHead = parseSerieCsv('Dyson V15;499;599\nAirwrap;399;449')
check('sans en-tête : hasHeader=false (l\'écran doit pouvoir le dire)', noHead.hasHeader, false)
check('sans en-tête : lecture par position, 1re ligne CONSERVÉE', noHead.lines, [
  { slogan: 'Dyson V15', price: '499', original_price: '599' },
  { slogan: 'Airwrap', price: '399', original_price: '449' },
])

// ── Cas limites ──────────────────────────────────────────────────────────────
check('fichier vide', parseSerieCsv('').lines, [])
check('en-têtes seuls, aucune donnée', parseSerieCsv('nom;prix').lines, [])
check('cellules vides ignorées',
  parseSerieCsv('nom;prix;prix barré\nV15;499;').lines, [{ slogan: 'V15', price: '499' }])
check('colonnes manquantes en fin de ligne',
  parseSerieCsv('nom;prix;prix barré\nV15;499').lines, [{ slogan: 'V15', price: '499' }])

// ── Aller-retour avec l'export du produit ────────────────────────────────────
// `downloadCsv` écrit avec `;`, une BOM et des guillemets doublés : ce que SignFlow exporte
// doit pouvoir être relu par SignFlow. Reproduit ici son format exact.
const exported = '﻿' + ['nom;prix', '"Frais, local";4,99'].join('\r\n')
check('un CSV exporté par SignFlow se relit', parseSerieCsv(exported).lines,
  [{ slogan: 'Frais, local', price: '4,99' }])

console.log(failures === 0 ? `\n${'✓'} tous les tests passent` : `\n✗ ${failures} échec(s)`)
process.exitCode = failures === 0 ? 0 : 1   // pas process.exit() : laisse stdout se vider
