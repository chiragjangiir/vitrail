'use client'

import { useCallback } from 'react'

export type Theme = 'light' | 'dark'

/**
 * Refonte « Mission Control » 2026-07-17 : le CMS est DARK ONLY.
 * La classe .dark est posée en dur sur <html> (layout.tsx) ; ce hook est conservé
 * pour compatibilité d'API (consommateurs historiques) mais ne bascule plus rien.
 */
export function useTheme() {
  const noop = useCallback(() => {}, [])
  return { theme: 'dark' as Theme, toggle: noop, setTheme: noop as (t: Theme) => void }
}

/** Conservé pour compatibilité (appelé après /users/me) — sans effet en dark only. */
export function syncThemeFromServer(_theme: string | null | undefined) {}
