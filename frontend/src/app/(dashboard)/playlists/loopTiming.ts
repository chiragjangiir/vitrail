import type { PlaylistItemRead } from '@/types/api'

/**
 * Durées d'exposition de la boucle — **définition unique** partagée par les trois surfaces
 * d'aperçu : l'éditeur de playlist, le lecteur enchaîné (`PlaylistPlayer`) et la scène
 * multi-zones (`TemplateStage`).
 *
 * Extrait de `PlaylistPlayer.tsx` le 2026-08-13 : la scène a besoin des mêmes durées, et
 * l'importer depuis le lecteur aurait créé un cycle (le lecteur monte la scène). Trois
 * aperçus qui ne donnent pas le même déroulé seraient pires que pas d'aperçu du tout.
 */

/**
 * Pages réellement diffusées par un item DOCUMENT, dans l'ordre de la spec `"2-5,8"`.
 *
 * Miroir de `document_media.parse_page_selection()` côté serveur — mêmes règles, y compris
 * les deux qui ne sautent pas aux yeux : **l'ordre de saisie est respecté** (`"5,2"` = page 5
 * puis page 2, c'est écrit dans l'aide du champ) et **une sélection illisible retombe sur le
 * document entier** plutôt que sur rien. Vide / hors bornes = tout le document.
 */
export function selectedPages(spec: string | null | undefined, pageCount: number): number[] {
  const all = pageCount > 0 ? Array.from({ length: pageCount }, (_, i) => i + 1) : []
  if (!spec || !spec.trim() || pageCount <= 0) return all
  const out: number[] = []
  const seen = new Set<number>()
  const push = (n: number) => { if (!seen.has(n)) { seen.add(n); out.push(n) } }
  for (const raw of spec.split(',')) {
    const part = raw.trim()
    if (!part) continue
    const m = part.match(/^(\d+)\s*-\s*(\d+)$/)
    if (m) {
      let a = Number(m[1]); let b = Number(m[2])
      if (b < a) [a, b] = [b, a]
      for (let n = Math.max(1, a); n <= Math.min(pageCount, b); n++) push(n)
    } else if (/^\d+$/.test(part)) {
      const n = Number(part)
      if (n >= 1 && n <= pageCount) push(n)
    } else {
      return all   // sélection illisible → repli sûr : tout le document
    }
  }
  return out.length ? out : all
}

/** Nb de pages sélectionnées (pendant de `document_media.selection_count`). */
export function selectedPageCount(spec: string | null | undefined, pageCount: number): number {
  return selectedPages(spec, pageCount).length
}

/**
 * Durée d'exposition d'un item en lecture enchaînée = celle que le player appliquerait.
 * Un document occupe l'antenne `durée × nombre de pages sélectionnées` (le serveur le
 * déroule en autant d'items image, §3.2).
 */
export function itemHoldMs(it: PlaylistItemRead | undefined): number | undefined {
  if (!it) return undefined
  const per = it.duration_ms || 10000
  if (it.media_type === 'document' && (it.media_page_count ?? 0) > 0)
    return selectedPageCount(it.doc_pages, it.media_page_count ?? 0) * per
  return per
}
