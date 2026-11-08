/**
 * Langues servies par l'interface + négociation `Accept-Language`.
 *
 * Ce module porte l'UNIQUE définition de la liste des langues : `request.ts` la
 * ré-exporte pour ne pas déplacer la surface publique, mais ne la redéfinit pas.
 * Deux listes divergeraient (cf. la leçon `app/core/timezones.py`, P3.13).
 *
 * La négociation ne sert que de REPLI : le cookie `locale` — choix explicite de
 * l'utilisateur — l'emporte toujours (cf. `request.ts`). Elle ne décide donc que
 * de la première impression, avant toute connexion.
 *
 * Trois règles, conformes au cadrage P3.7 :
 *  ① `Accept-Language` est une LISTE ORDONNÉE et pondérée (`q=`), pas une valeur
 *     unique : `de;q=0.7, fr;q=0.9` demande du français, bien que l'allemand soit
 *     écrit en premier.
 *  ② la RÉGION est écartée (`fr-BE` → `fr`, `pt-BR` → `pt`) : on ne multiplie pas
 *     les locales servies pour des variantes qu'on ne traduit pas.
 *  ③ rien ne correspond ⇒ `defaultLocale`. Cette fonction ne lève JAMAIS : elle
 *     lit une chaîne fournie par le client, sur le chemin de l'écran de connexion.
 */

export const locales = ['en', 'fr', 'es', 'pt', 'de'] as const
export type Locale = (typeof locales)[number]
export const defaultLocale: Locale = 'en'

/**
 * Une valeur venue de l'extérieur (cookie, en-tête) désigne-t-elle une langue
 * que l'on sert réellement ? Garde de type — indispensable avant de construire
 * le chemin d'import des messages : un `as Locale` non contrôlé faisait répondre
 * 500 à toutes les pages sur un cookie forgé ou périmé (mesuré le 2026-08-06).
 */
export function isSupportedLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (locales as readonly string[]).includes(value)
}

/**
 * L'en-tête vient du client : on borne le nombre d'entrées analysées. Au-delà,
 * ce n'est plus un navigateur, et le tri n'a pas à payer pour une entrée
 * pathologique.
 */
const MAX_ENTRIES = 50

export function negotiateLocale(header: string | null | undefined): Locale {
  if (!header) return defaultLocale

  const candidates: { lang: Locale; q: number; order: number }[] = []

  header
    .split(',')
    .slice(0, MAX_ENTRIES)
    .forEach((raw, order) => {
      const [tagPart, ...params] = raw.split(';')
      const tag = tagPart.trim().toLowerCase()
      // `*` ne désigne aucune langue en particulier : on laisse le repli trancher.
      if (!tag || tag === '*') return

      // Poids par défaut = 1 (RFC 9110). Un `q=` présent mais illisible, nul ou
      // hors bornes ⇒ entrée ÉCARTÉE plutôt que promue à 1 : on ne devine pas
      // l'intention derrière un en-tête malformé, et `q=0` signifie
      // explicitement « pas acceptable ».
      let q = 1
      const qParam = params.map((p) => p.trim().toLowerCase()).find((p) => p.startsWith('q='))
      if (qParam !== undefined) {
        q = Number(qParam.slice(2))
        if (!Number.isFinite(q) || q <= 0 || q > 1) return
      }

      // ② la région (et l'éventuel script) sautent : `fr-BE` → `fr`.
      const lang = tag.split('-')[0]
      if (!isSupportedLocale(lang)) return

      candidates.push({ lang, q, order })
    })

  if (candidates.length === 0) return defaultLocale

  // ① poids décroissant ; à poids ÉGAL, l'ordre d'écriture tranche — c'est ce qui
  // fait de l'en-tête une liste ordonnée et non un ensemble.
  candidates.sort((a, b) => b.q - a.q || a.order - b.order)
  return candidates[0].lang
}
