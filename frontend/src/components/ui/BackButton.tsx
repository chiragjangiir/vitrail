'use client'

import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { ArrowLeft } from 'lucide-react'
import Button from '@/components/ui/Button'

/**
 * Retour à l'écran précédent, pour les pages où l'on ATTERRIT depuis une autre.
 *
 * Constat d'Ed (2026-07-28) : depuis le tableau de bord, « Voir tout » ouvre la carte du
 * parc en grand — et une fois dedans, le seul moyen de revenir est de rouvrir le menu.
 * Les pages de rapports sont dans la barre latérale, donc joignables ; mais quand on y
 * arrive depuis AILLEURS, l'absence de retour se sent tout de suite.
 *
 * ⚠️ `router.back()` seul ne suffit pas : ouvert par lien direct ou dans un nouvel onglet,
 * il n'y a pas d'historique à remonter et le bouton ferait sortir du site (ou rien).
 * D'où le repli sur `fallback`, qui garantit que le bouton mène TOUJOURS quelque part.
 *
 * On revient donc « d'où l'on vient » plutôt que vers un parent fixe : la même page est
 * atteignable par le menu ET par le tableau de bord, un retour codé en dur renverrait la
 * moitié des visiteurs au mauvais endroit.
 */
export default function BackButton({ fallback = '/dashboard' }: { fallback?: string }) {
  const router = useRouter()
  const t = useTranslations('common')

  return (
    <Button
      size="sm"
      variant="secondary"
      onClick={() => {
        if (typeof window !== 'undefined' && window.history.length > 1) router.back()
        else router.push(fallback)
      }}
    >
      <ArrowLeft className="w-3.5 h-3.5 mr-1" />
      {t('back')}
    </Button>
  )
}
