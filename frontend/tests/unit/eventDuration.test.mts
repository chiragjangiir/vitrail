/**
 * Durée d'un événement : la conversion ms → secondes ne doit JAMAIS allonger
 * l'événement au-delà de son contenu.
 *
 * Exécution : `node tests/unit/eventDuration.test.mts` depuis `frontend/`.
 * Node ≥ 23 retire les annotations de type nativement — aucun outillage à ajouter.
 *
 * Question d'Ed (2026-08-11), après le correctif de l'image figée : « pour cette
 * vidéo on a 58 ms qui seront coupés, mais qu'en est-il pour d'autres contenus ?
 * Comment est choisi l'arrondi ? »
 *
 * Mesuré : le serveur n'arrondit rien (`expires_at = activation + duration_ms`).
 * L'arrondi vient du champ de saisie, en SECONDES, que la valeur traverse à
 * chaque ouverture du tiroir d'édition puis à l'enregistrement. Il était en
 * `Math.round`, donc la direction de l'erreur dépendait des décimales du média :
 * un contenu de 369,6 s devenait un événement de 370 s ⇒ 400 ms d'image figée.
 */
import assert from 'node:assert/strict'
import { msToWholeSeconds } from '../../src/lib/eventDuration.ts'

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

console.log("L'événement ne dépasse JAMAIS la durée de son contenu")
// Le cas d'Ed : 369,058 s. `round` donnait déjà 369 — ce n'est pas lui qui piégeait.
check('369 058 ms (la vidéo d\'Ed) → 369 s', msToWholeSeconds(369058), 369)
// 🔑 LE CAS QUI PIÉGEAIT : au-delà de la demi-seconde, `round` montait à 370.
check('369 600 ms → 369 s (et NON 370)', msToWholeSeconds(369600), 369)
check('9 999 ms → 9 s (et NON 10)', msToWholeSeconds(9999), 9)
check('30 900 ms → 30 s (et NON 31)', msToWholeSeconds(30900), 30)

console.log('\nValeurs exactes : rien ne bouge')
check('10 000 ms → 10 s', msToWholeSeconds(10000), 10)
check('1 000 ms → 1 s', msToWholeSeconds(1000), 1)
check('369 000 ms → 369 s (aller-retour stable)', msToWholeSeconds(369000), 369)

console.log('\nPlancher : une durée nulle basculerait l\'événement en BOUCLE')
// ⚠️ Côté serveur, `duration_ms` NULL ou 0 signifie « pas de durée » = diffusion
// en boucle jusqu'à la fin de fenêtre. Un média de moins d'une seconde ne doit
// donc jamais retomber à 0 : ce serait l'inverse exact de ce qui est demandé.
check('900 ms → 1 s (jamais 0)', msToWholeSeconds(900), 1)
check('1 ms → 1 s (jamais 0)', msToWholeSeconds(1), 1)

console.log('\nStabilité de l\'aller-retour : ré-enregistrer ne dérive plus')
// Le champ traverse ms → s → ms à chaque édition. Avec `round`, la valeur pouvait
// MONTER à chaque passage ; ici elle se stabilise dès le premier.
let ms = 369600
const first = msToWholeSeconds(ms) * 1000
ms = first
const second = msToWholeSeconds(ms) * 1000
check('deux éditions successives donnent la même durée', second, first)
check('et cette durée reste sous le contenu', first <= 369600, true)

console.log(`\n${failures === 0 ? 'TOUT VERT' : failures + ' ECHEC(S)'}`)
process.exit(failures === 0 ? 0 : 1)
