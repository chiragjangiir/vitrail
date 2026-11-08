'use client'

import { useEffect, useRef } from 'react'
import { usePathname, useRouter } from 'next/navigation'

/**
 * Pré-remplissage de la barre de recherche LOCALE depuis la recherche globale (topbar).
 *
 * La globale navigue vers `/cible?q=terme` : sans ce hook, l'utilisateur atterrissait sur une
 * liste nue et devait re-saisir sa recherche (constat audit 2026-07-18). Les deux barres restent
 * complémentaires — la globale navigue, la locale filtre en place — mais le terme est transmis.
 *
 * Même double chemin que `useCreateShortcut` (et même raison d'éviter `useSearchParams` :
 * Suspense obligatoire au build) :
 *   1. Arrivée depuis une AUTRE page → on lit `?q=` au montage, on applique, on nettoie l'URL.
 *   2. Déjà sur la page (pas de remontage) → événement `sf:search-prefill`.
 */
export function useSearchPrefill(onQuery: (q: string) => void): void {
  const cb = useRef(onQuery)
  cb.current = onQuery
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const q = new URLSearchParams(window.location.search).get('q')
      if (q) {
        cb.current(q)
        router.replace(pathname, { scroll: false }) // retire ?q= (un refresh ne re-filtre pas)
      }
    }
    const onEvt = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail
      if (detail) cb.current(detail)
    }
    window.addEventListener('sf:search-prefill', onEvt)
    return () => window.removeEventListener('sf:search-prefill', onEvt)
  }, [pathname, router])
}

/** Transmet le terme à la page DÉJÀ affichée (cas 2 ci-dessus). */
export function fireSearchPrefill(q: string): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('sf:search-prefill', { detail: q }))
  }
}
