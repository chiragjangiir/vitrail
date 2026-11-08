'use client'

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { MonitorPlay } from 'lucide-react'
import api from '@/lib/api'

/**
 * « Où passe ce contenu ? », au SURVOL (demande d'Ed, audit du menu Média 2026-07-28 :
 * « quand on sélectionne ou survole un média, on sache dans quelle playlist, programme il
 * est utilisé et surtout actif sur un ou des écrans »).
 *
 * ⚠️ La requête n'est PAS déclenchée au rendu. `GET /media/{id}/usage` résout les
 * playlists, les programmes ET le parc ciblé : la tirer pour chaque vignette affichée
 * lancerait 100 analyses de diffusion pour un écran que personne ne regarde. Elle part au
 * survol, après un court délai — assez pour qu'un simple passage de souris ne coûte rien,
 * assez court pour que l'info arrive avant qu'on ait bougé. React Query met ensuite le
 * résultat en cache : re-survoler ne recharge pas.
 */

interface Usage {
  summary: { playlists: number; schedules: number; events: number; screens: number; is_live: boolean }
  screens: { id_player: number; player_name: string; site_name: string | null }[]
}

const HOVER_DELAY_MS = 350

export default function MediaUsageHint({ idMedia, hovered, summary }: {
  idMedia: number
  /** Survol de la LIGNE / de la VIGNETTE : c'est elle qu'on survole, pas ce petit texte. */
  hovered: boolean
  /** Résumé chargé EN LOT pour toute la page (une requête) — affiché en permanence. */
  summary?: { playlists: number; screens: number }
}) {
  const t = useTranslations('media')
  const [armed, setArmed] = useState(false)

  const { data } = useQuery<Usage>({
    queryKey: ['media-usage', idMedia],
    queryFn: () => api.get<Usage>(`/media/${idMedia}/usage`).then((r) => r.data),
    enabled: armed,
    staleTime: 60_000,
  })

  // Le libellé vient du LOT (permanent, demande d'Ed). Le détail chargé au survol ne sert
  // qu'à nommer les écrans dans l'infobulle — il ne conditionne plus l'affichage.
  const n = summary?.screens ?? 0

  // Délai : un simple passage de souris sur 20 lignes ne doit rien coûter. Une fois armé,
  // on le reste — React Query garde la réponse en cache, re-survoler ne recharge pas.
  useEffect(() => {
    if (!hovered || armed || n === 0) return
    const id = setTimeout(() => setArmed(true), HOVER_DELAY_MS)
    return () => clearTimeout(id)
  }, [hovered, armed, n])

  const label = !summary
    ? null
    : n > 0
      ? t('usage_on_screens', { n })
      : summary.playlists > 0
        ? t('usage_not_broadcast')
        : t('usage_unused_short')

  return (
    <span
      className="block text-[11px] text-gray-500 min-h-[15px]"
      // ⚠️ `data` (le détail nommé) n'arrive qu'AU SURVOL, alors que `n` vient du résumé
      // chargé en lot dès l'affichage : les deux ne sont plus synchrones depuis que
      // l'information est permanente. Tester `n > 0` ne dit donc RIEN sur `data` — d'où
      // l'assertion non-nulle qui plantait toute la page au premier rendu.
      title={
        n > 0 && data
          ? data.screens.map((s) => s.site_name ? `${s.player_name} · ${s.site_name}` : s.player_name).join('\n')
          : undefined
      }
    >
      {label && (
        <span className={`inline-flex items-center gap-1 ${n > 0 ? 'text-success' : ''}`}>
          {n > 0 && <MonitorPlay className="w-3 h-3" />}
          {label}
        </span>
      )}
    </span>
  )
}
