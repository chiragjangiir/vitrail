import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent, KeyboardEvent } from 'react'

/**
 * Champ de saisie qui **se commite tout seul** (débounce), sans jamais dépendre du `blur`.
 *
 * Pourquoi ce hook existe (retour Ed 2026-07-25) : un champ qui n'enregistre qu'`onBlur`
 * perd la saisie **en silence** dès qu'aucun blur ne survient. Cas vécu : on pousse les
 * FLÈCHES du spinner d'un `<input type="number">` **sans avoir cliqué dans le champ** —
 * la valeur affichée change, aucun appel serveur ne part, et la page suivante réaffiche
 * l'ancienne valeur. Le serveur était irréprochable : c'était la saisie qui ne partait pas.
 *
 * Garanties :
 *  · commit après `delay` ms sans frappe, au blur, à Entrée, et **au démontage** (on ne
 *    perd pas une valeur saisie juste avant de quitter la page) ;
 *  · aucun commit si la valeur est inchangée (`equals`) ou illisible (`parse` → undefined) ;
 *  · tant que le champ a le focus, une valeur venue du serveur **n'écrase pas** la saisie
 *    en cours — sinon le rafraîchissement qui suit le commit mange les frappes suivantes ;
 *  · au blur, l'affichage est normalisé (saisie illisible → retour à la valeur serveur).
 *
 * `parse` renvoie `undefined` pour « saisie pas (encore) exploitable » — à distinguer de
 * `null`, qui est une valeur à part entière (champ vidé = « hérite » / « pas de limite »).
 */
export interface CommitFieldOptions<T> {
  /** Valeur de référence (celle du serveur). */
  external: T
  /** Valeur → texte affiché. */
  toText: (v: T) => string
  /** Texte saisi → valeur à envoyer ; `undefined` = ne rien envoyer. */
  parse: (raw: string) => T | undefined
  /** Envoi effectif (mutation). Appelé seulement si la valeur a réellement changé. */
  commit: (v: T) => void
  /** Comparaison métier (défaut : `===`). */
  equals?: (a: T, b: T) => boolean
  /** Silence avant commit automatique, en ms. */
  delay?: number
}

export interface CommitFieldBinding {
  value: string
  onChange: (e: ChangeEvent<HTMLInputElement>) => void
  onFocus: () => void
  onBlur: () => void
  onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void
}

export function useCommitField<T>({
  external, toText, parse, commit, equals, delay = 700,
}: CommitFieldOptions<T>): CommitFieldBinding {
  const [raw, setRaw] = useState(() => toText(external))
  const focused = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Le flush au démontage s'exécute APRÈS le dernier rendu : il doit lire l'état courant,
  // pas celui capturé à la création du callback.
  const live = useRef({ external, toText, parse, commit, equals, raw })
  live.current = { external, toText, parse, commit, equals, raw }

  /** Envoie si nécessaire. Renvoie false si la saisie est illisible. */
  const flush = useCallback((): boolean => {
    const { external: ext, parse: p, commit: c, equals: eq, raw: r } = live.current
    const parsed = p(r)
    if (parsed === undefined) return false
    if (eq ? eq(parsed, ext) : parsed === ext) return true
    c(parsed)
    return true
  }, [])

  // Resynchronisation depuis le serveur — jamais pendant la frappe.
  const extText = toText(external)
  useEffect(() => {
    if (!focused.current) setRaw(extText)
  }, [extText])

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
    flush()
  }, [flush])

  return {
    value: raw,
    onChange: (e) => {
      setRaw(e.target.value)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => { timer.current = null; flush() }, delay)
    },
    onFocus: () => { focused.current = true },
    onBlur: () => {
      focused.current = false
      if (timer.current) { clearTimeout(timer.current); timer.current = null }
      const ok = flush()
      const { parse: p, toText: fmt, external: ext, raw: r } = live.current
      const parsed = ok ? p(r) : undefined
      // Normalisation d'affichage : « 007 » → « 7 » ; saisie illisible → valeur serveur.
      setRaw(fmt(parsed === undefined ? ext : parsed))
    },
    onKeyDown: (e) => { if (e.key === 'Enter') e.currentTarget.blur() },
  }
}
