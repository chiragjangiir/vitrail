'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQueryClient } from '@tanstack/react-query'
import { Eye, Lock } from 'lucide-react'
import { useAuthStore } from '@/store/auth'

/**
 * Mode démo (§II) — bandeau permanent + toast. Le compte démo navigue en lecture ; toute écriture
 * est bloquée côté serveur (middleware `demo_blocked`) → l'intercepteur axios émet `sf-demo-blocked`
 * → on affiche UNIQUEMENT un toast localisé « compte démo, action impossible ».
 * L'intercepteur ne rejette pas l'erreur (sinon les onError locaux afficheraient des messages
 * rouges dans les drawers) : la mutation reste « pending » → on purge le MutationCache après un
 * court délai pour ramener tous les useMutation à idle (boutons/spinners rendus à la normale).
 */
export default function DemoMode() {
  const t = useTranslations()
  const qc = useQueryClient()
  const isDemo = useAuthStore((s) => s.user?.is_demo)
  const [toast, setToast] = useState(false)

  useEffect(() => {
    if (!isDemo) return
    const onBlocked = () => {
      setToast(true)
      // Laisse le temps au cycle de rendu, puis remet toutes les mutations à idle.
      setTimeout(() => qc.getMutationCache().clear(), 400)
    }
    window.addEventListener('sf-demo-blocked', onBlocked)
    return () => window.removeEventListener('sf-demo-blocked', onBlocked)
  }, [isDemo, qc])

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(false), 3500)
    return () => clearTimeout(id)
  }, [toast])

  if (!isDemo) return null
  return (
    <>
      <div className="flex items-center justify-center gap-2 bg-amber-500 px-4 py-1.5 text-xs font-medium text-white">
        <Eye className="h-3.5 w-3.5" /> {t('demo.banner')}
      </div>
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[100] flex -translate-x-1/2 items-center gap-2 rounded-lg border border-white/10 bg-[#1A1D2B] px-4 py-2.5 text-sm text-white shadow-lg ring-1 ring-black/40">
          <Lock className="h-4 w-4 text-amber-400" /> {t('demo.blocked')}
        </div>
      )}
    </>
  )
}
