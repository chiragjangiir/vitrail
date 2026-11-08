'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import api from '@/lib/api'
import type { BasketItem } from '@/types/api'
import MediaViewer, { type ViewerMedia } from '../media/components/MediaViewer'

/**
 * Écoute d'un panier audio dans la visionneuse (demande Ed 2026-07-29) — pendant exact de
 * `PlaylistPlayer` : le composant charge les items lui-même (les cartes de la liste n'ont
 * que le compteur) et enchaîne les morceaux, l'audio ayant une durée native (pas de holdMs).
 *
 * ⚠️ L'aperçu joue la liste DANS L'ORDRE et ne simule ni les poids, ni le shuffle, ni les
 * fenêtres de validité/règles horaires : c'est le player qui tire au sort selon les poids —
 * ici on écoute CE QUE contient le panier, pas le tirage d'un instant donné (même contrat
 * que PlaylistPlayer vis-à-vis de la rotation serveur).
 */

function toViewer(it: BasketItem): ViewerMedia {
  return {
    id_media: it.id_media,
    media_name: it.media_name ?? `#${it.id_media}`,
    media_type: 'audio',
  }
}

interface Props {
  /** Panier à écouter (null = fermé). */
  basket: { id_basket: number; basket_name: string } | null
  onClose: () => void
  /** Empilement au-dessus d'un Drawer déjà ouvert (cf. MediaViewer). */
  elevated?: boolean
}

export default function BasketPlayer({ basket, onClose, elevated }: Props) {
  const t = useTranslations()
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)

  const { data, isLoading } = useQuery<BasketItem[]>({
    queryKey: ['basket-items', basket?.id_basket],
    queryFn: () => api.get<BasketItem[]>(`/audio-baskets/${basket!.id_basket}/items`).then((r) => r.data),
    enabled: basket !== null,
  })

  // Nouveau panier demandé → on repart de son premier morceau.
  useEffect(() => { setIndex(0); setPlaying(true) }, [basket?.id_basket])

  // Seuls les items ACTIFS s'écoutent (un item désactivé ne diffuse pas non plus).
  const items = (data ?? []).filter((it) => it.is_active && (it.media_type ?? 'audio') === 'audio')
  const current = items[index]

  const emptyMessage = basket !== null && !isLoading && data && items.length === 0

  if (basket === null) return null

  if (emptyMessage) {
    // Portail, même raison que la visionneuse : la bulle d'aide de DashboardShell est
    // montée hors du conteneur des pages et recouvrirait ce panneau.
    if (typeof document === 'undefined') return null
    return createPortal(
      <div
        className={`fixed inset-0 ${elevated ? 'z-[60]' : 'z-50'} bg-black/80 backdrop-blur-sm flex items-center justify-center p-6`}
        onClick={onClose}
        role="dialog"
        aria-modal="true"
        data-testid="basket-player-empty"
      >
        <div className="sf-panel px-6 py-5 max-w-md text-center" onClick={(e) => e.stopPropagation()}>
          <p className="text-sm text-gray-700">{t('ab.player_empty')}</p>
        </div>
      </div>,
      document.body,
    )
  }

  return (
    <MediaViewer
      item={current ? toViewer(current) : null}
      onClose={onClose}
      onPrev={index > 0 ? () => { setPlaying(false); setIndex((i) => i - 1) } : undefined}
      onNext={index < items.length - 1 ? () => { setPlaying(false); setIndex((i) => i + 1) } : undefined}
      onEnded={playing
        ? () => (index < items.length - 1 ? setIndex((i) => i + 1) : onClose())
        : undefined}
      position={items.length > 1 ? { index, total: items.length } : undefined}
      elevated={elevated}
    />
  )
}
