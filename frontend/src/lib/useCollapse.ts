'use client'

import { useEffect, useState } from 'react'

/**
 * État replié/déplié persisté dans localStorage — une section reste comme
 * l'utilisateur l'a laissée d'une visite à l'autre.
 *
 * Source unique : ce hook était copié-collé à l'identique dans le dashboard CMS
 * et l'accueil du portail annonceur. Toute nouvelle section repliable PERSISTÉE
 * doit passer par ici.
 *
 * ⚠️ À ne pas confondre avec `components/ui/Collapsible.tsx`, qui est un repli
 * NON persisté (état local, oublié à la fermeture) utilisé dans les drawers.
 *
 * @param key    clé localStorage — préfixer par la page (`sf.media.folders`)
 * @param defaultOpen état au tout premier affichage, avant toute préférence
 */
export function useCollapse(key: string, defaultOpen = true): [boolean, () => void] {
  const [open, setOpen] = useState(defaultOpen)

  // Lecture APRÈS montage : localStorage n'existe pas au rendu serveur, et lire
  // pendant le rendu provoquerait une divergence d'hydratation.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const v = window.localStorage.getItem(key)
    if (v === '0') setOpen(false)
    else if (v === '1') setOpen(true)
  }, [key])

  const toggle = () =>
    setOpen((o) => {
      const next = !o
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(key, next ? '1' : '0')
      }
      return next
    })

  return [open, toggle]
}

export default useCollapse
