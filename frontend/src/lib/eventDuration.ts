/**
 * Conversion millisecondes → secondes entières pour la durée d'un événement.
 *
 * 🔑 POURQUOI `floor` ET PAS `round` — la direction de l'erreur n'est pas neutre.
 *
 * Le serveur ne fait AUCUN arrondi : il pose `expires_at = activation + duration_ms`,
 * à la milliseconde. L'arrondi vient d'ici, parce que le champ de saisie est en
 * SECONDES : la valeur repasse par lui à chaque ouverture du tiroir d'édition
 * (ms → s pour l'affichage) puis à l'enregistrement (s → ms).
 *
 * Les deux sens de l'erreur n'ont pas le même coût à l'écran :
 *
 *   · durée < contenu  →  la toute fin est coupée. Sur un média de 369,058 s
 *     enregistré à 369 s, ce sont 58 ms — personne ne peut le voir.
 *
 *   · durée > contenu  →  le contenu se termine AVANT que l'événement n'expire,
 *     et l'écran garde la DERNIÈRE IMAGE FIGÉE en attendant. C'est exactement ce
 *     qu'Ed a décrit le 2026-08-11 : « ça donne l'impression qu'un truc est en
 *     panne, pas agréable à voir. »
 *
 * `Math.round` choisit la direction selon les décimales, donc au hasard du média :
 * un contenu de 369,6 s devenait 370 s à la réenregistrement ⇒ 400 ms d'image
 * figée, gratuitement. Pire, la dérive est CUMULATIVE dans le mauvais sens : ré-ouvrir
 * puis ré-enregistrer un événement pouvait l'ALLONGER au-delà de son contenu.
 *
 * `floor` fait toujours tomber l'erreur du côté inoffensif, au prix d'au plus
 * 999 ms coupés en fin de lecture.
 *
 * ⚠️ Le plancher à 1 n'est pas cosmétique : `duration_ms` à 0 est FAUX au sens du
 * produit — le serveur lit une durée nulle comme « pas de durée », donc comme le
 * mode BOUCLE (`event_worker` : `duration_ms` NULL ⇒ diffusion jusqu'à la fin de
 * fenêtre). Un média de moins d'une seconde basculerait donc l'événement en
 * lecture en boucle, soit l'inverse exact de ce qui est demandé.
 */
export function msToWholeSeconds(ms: number): number {
  return Math.max(1, Math.floor(ms / 1000))
}
