'use client'

import { useEffect, useRef } from 'react'
import { usePathname, useRouter } from 'next/navigation'

/**
 * Ouverture directe du drawer d'une FICHE depuis la recherche globale (topbar).
 *
 * `useSearchPrefill` pré-remplit la barre locale (`?q=`) : utile pour une liste, mais quand on
 * cherche un player précis on veut sa fiche, pas une liste filtrée à un élément (retour Ed
 * 2026-07-19 : « les players sont couverts mais cela n'ouvre pas le drawer »).
 *
 * La globale navigue donc vers `/cible?open=<id>` et la page ouvre le drawer correspondant.
 * Même double chemin que `useSearchPrefill` / `useCreateShortcut` (et même raison d'éviter
 * `useSearchParams` : Suspense obligatoire au build) :
 *   1. Arrivée depuis une AUTRE page → on lit `?open=` au montage, on ouvre, on nettoie l'URL ;
 *   2. Déjà sur la page (pas de remontage) → événement `sf:open-shortcut`.
 *
 * L'URL est nettoyée après ouverture : un rafraîchissement ne doit pas ré-ouvrir un drawer que
 * l'utilisateur vient de fermer.
 */
export function useOpenShortcut(onOpen: (id: number) => void): void {
  const cb = useRef(onOpen)
  cb.current = onOpen
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const raw = new URLSearchParams(window.location.search).get('open')
      const id = raw ? Number(raw) : NaN
      if (Number.isFinite(id)) {
        cb.current(id)
        router.replace(pathname, { scroll: false })
      }
    }
    const onEvt = (e: Event) => {
      const detail = (e as CustomEvent<number>).detail
      if (Number.isFinite(detail)) cb.current(detail)
    }
    window.addEventListener('sf:open-shortcut', onEvt)
    return () => window.removeEventListener('sf:open-shortcut', onEvt)
  }, [pathname, router])
}

/** Ouvre la fiche sur la page DÉJÀ affichée (cas 2 ci-dessus). */
export function fireOpenShortcut(id: number): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('sf:open-shortcut', { detail: id }))
  }
}
