'use client'

import { useEffect } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { getQueryClient } from '@/lib/query-client'

/**
 * Le CMS n'enregistre AUCUN service worker. Mais un SW parasite peut contrôler l'origine
 * (reliquat d'une ancienne version, ou PWA player ChromeOS dont le scope a fui à la racine) :
 * il intercepte/cache alors le JS du CMS et sert un bundle périmé — immunisé même au
 * hard-refresh (il fallait F12 → Application → Unregister à la main). On désinscrit donc tout
 * SW qui couvre le CMS au chargement (en préservant celui scopé /player-chromeos/, qui ne
 * contrôle pas les pages CMS), puis un reload unique si un SW contrôlait encore la page.
 */
function useUnregisterStaleServiceWorkers() {
  useEffect(() => {
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
    navigator.serviceWorker
      .getRegistrations()
      .then((regs) => {
        let removed = false
        for (const reg of regs) {
          if (!reg.scope.includes('/player-chromeos')) {
            reg.unregister()
            removed = true
          }
        }
        if (
          removed &&
          navigator.serviceWorker.controller &&
          !sessionStorage.getItem('_sfSwPurged')
        ) {
          sessionStorage.setItem('_sfSwPurged', '1')
          window.location.reload()
        }
      })
      .catch(() => {})
  }, [])
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient()
  useUnregisterStaleServiceWorkers()
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
