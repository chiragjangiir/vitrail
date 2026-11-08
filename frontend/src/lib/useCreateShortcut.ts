'use client'

import { useEffect, useRef } from 'react'
import { usePathname, useRouter } from 'next/navigation'

/**
 * Raccourci « + New » de la topbar (NewMenu) : ouvre directement le drawer/formulaire de
 * création de la page cible.
 *
 * Deux chemins d'ouverture, sans `useSearchParams` (le projet l'évite — sinon Suspense requis
 * au build, cf. /approvals) :
 *   1. Arrivée depuis une AUTRE page → NewMenu navigue vers `/cible?new=1` → au montage on lit
 *      `?new=1` dans l'URL, on ouvre, puis on nettoie l'URL (un refresh ne rouvre pas).
 *   2. Clic +New alors qu'on est DÉJÀ sur la page (pas de remontage) → NewMenu émet l'événement
 *      `sf:new-shortcut` que la page montée capte pour rouvrir.
 */
export function useCreateShortcut(onOpen: () => void): void {
  const cb = useRef(onOpen)
  cb.current = onOpen
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (typeof window !== 'undefined'
        && new URLSearchParams(window.location.search).get('new') === '1') {
      cb.current()
      router.replace(pathname, { scroll: false }) // retire ?new=1
    }
    const onEvt = () => cb.current()
    window.addEventListener('sf:new-shortcut', onEvt)
    return () => window.removeEventListener('sf:new-shortcut', onEvt)
  }, [pathname, router])
}

/** Émet le raccourci de création pour la page déjà affichée (cas 2 ci-dessus). */
export function fireCreateShortcut(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('sf:new-shortcut'))
  }
}
