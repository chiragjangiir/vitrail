'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, ChevronDown, ChevronRight, Download, HardDrive, XCircle } from 'lucide-react'

import api from '@/lib/api'
import type { PlayerRead } from '@/types/api'

type T = (key: string, values?: Record<string, string | number>) => string

type InvStatus = 'cached' | 'downloading' | 'missing'

interface InvItem {
  id_media: number
  media_name: string
  media_type: string
  refs: string[]
  status: InvStatus
}

interface Inventory {
  id_player: number
  summary: {
    expected: number
    cached: number
    downloading: number
    missing: number
    disk_used_ratio: number | null
    storage_pressure: boolean
    reported: boolean
  }
  items: InvItem[]
}

// Badge statut = icône + couleur + libellé (design system : jamais d'icône seule).
const ST: Record<InvStatus, { cls: string; Icon: typeof CheckCircle2 }> = {
  cached: { cls: 'bg-green-50 dark:bg-green-500/15 text-green-700 dark:text-green-300 border-green-200 dark:border-green-500/30', Icon: CheckCircle2 },
  downloading: { cls: 'bg-amber-500/10 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-400/20 dark:border-amber-500/30', Icon: Download },
  missing: { cls: 'bg-red-500/10 dark:bg-red-500/15 text-red-700 dark:text-red-300 border-red-400/20 dark:border-red-500/30', Icon: XCircle },
}

/**
 * Section « Inventaire média » du drawer player : compare le programme planifié (toutes
 * playlists/events/gouvernance ciblant ce player) au cache réel remonté → cached /
 * downloading / missing. Fetch à l'ouverture + polling tant qu'il reste des téléchargements.
 */
export default function InventorySection({ player, t }: { player: PlayerRead; t: T }) {
  const [expanded, setExpanded] = useState(false)

  const { data, isLoading, isError } = useQuery<Inventory>({
    queryKey: ['player-inventory', player.id_player],
    queryFn: () => api.get(`/players/${player.id_player}/inventory`).then((r) => r.data),
    enabled: expanded,
    refetchInterval: (q) => ((q.state.data?.summary?.downloading ?? 0) > 0 ? 5000 : false),
  })
  const s = data?.summary

  return (
    <div className="pt-2 border-t border-gray-100">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          <HardDrive className="w-3.5 h-3.5 text-gray-400" />
          {t('players.inventory.title')}
        </span>
        {s && (
          <span className="flex items-center gap-2 text-xs font-medium">
            <span className="text-green-700 dark:text-green-300">{s.cached}</span>
            {s.downloading > 0 && <span className="text-amber-700 dark:text-amber-300">{s.downloading}</span>}
            {s.missing > 0 && <span className="text-red-700 dark:text-red-300">{s.missing}</span>}
          </span>
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5 text-xs">
          {isLoading && <p className="text-gray-400">{t('players.inventory.loading')}</p>}
          {isError && <p className="text-red-600 dark:text-red-300">{t('players.inventory.error')}</p>}
          {s && !s.reported && <p className="text-amber-700 dark:text-amber-300">{t('players.inventory.not_reported')}</p>}
          {s && (
            <p className="text-gray-500">
              {t('players.inventory.summary', {
                cached: s.cached, downloading: s.downloading, missing: s.missing, total: s.expected,
              })}
              {s.disk_used_ratio != null && ` · ${Math.round(s.disk_used_ratio * 100)}% ${t('players.inventory.disk')}`}
            </p>
          )}
          {data && data.items.length === 0 && !isLoading && (
            <p className="text-gray-400">{t('players.inventory.empty')}</p>
          )}
          {data && data.items.length > 0 && (
            <ul className="space-y-1 max-h-64 overflow-auto pr-1">
              {data.items.map((it) => {
                const { cls, Icon } = ST[it.status]
                return (
                  <li key={it.id_media} className="flex items-center gap-2">
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[11px] shrink-0 ${cls}`}>
                      <Icon className="w-3 h-3" />
                      {t(`players.inventory.${it.status}`)}
                    </span>
                    <span className="truncate text-gray-700" title={it.refs.join(', ')}>
                      {it.media_name}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
