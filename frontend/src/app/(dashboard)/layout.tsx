'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/auth'
import DashboardShell from '@/components/layout/DashboardShell'
import api from '@/lib/api'
import type { UserRead } from '@/types/api'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { accessToken, user, _hasHydrated } = useAuthStore()
  const router = useRouter()

  // Un compte annonceur (portail S7 B2) n'a pas sa place dans le CMS : redirigé vers
  // /portal (l'API est de toute façon isolée côté serveur — cross-annonceur = 404).
  const isAdvertiser = !!user?.id_advertiser

  useEffect(() => {
    if (!_hasHydrated) return
    if (!accessToken) router.replace('/login')
    else if (isAdvertiser) router.replace('/portal')
  }, [accessToken, isAdvertiser, _hasHydrated, router])

  // Rafraîchit le profil (donc les DROITS) à l'entrée dans le CMS.
  //
  // Deux raisons : ① une session ouverte AVANT l'ajout de `permissions` à
  // /users/me a un profil persisté sans droits — sans ce rafraîchissement, sa
  // sidebar resterait vide jusqu'à une reconnexion ; ② un changement de rôle
  // décidé par l'admin est pris en compte au prochain chargement, sans
  // déconnexion. On ne touche PAS aux jetons (setAuth les réécrirait).
  useEffect(() => {
    if (!_hasHydrated || !accessToken) return
    let cancelled = false
    api
      .get<UserRead>('/users/me')
      .then(({ data }) => {
        if (!cancelled) useAuthStore.setState({ user: data })
      })
      .catch(() => {
        /* best-effort : l'intercepteur gère déjà 401/refresh */
      })
    return () => { cancelled = true }
  }, [_hasHydrated, accessToken])

  if (!_hasHydrated) return null
  if (!accessToken || isAdvertiser) return null

  return <DashboardShell>{children}</DashboardShell>
}
