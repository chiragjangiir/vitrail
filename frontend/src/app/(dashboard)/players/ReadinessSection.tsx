'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CalendarClock, CheckCircle2, ChevronDown, ChevronRight, Wifi } from 'lucide-react'

import api from '@/lib/api'
import type { PlayerRead } from '@/types/api'

type T = (key: string, values?: Record<string, string | number>) => string

interface RdItem {
  id_media: number
  media_name: string | null
  size_bytes: number
  play_at: string | null
  ready_at: string | null
  on_time: boolean
  network_bound: boolean
}

interface Readiness {
  reported: boolean
  bandwidth_kbps: number | null
  measured_kbps: number | null
  throughput_kbps: number | null
  throughput_source: 'cap' | 'measured' | 'unlimited'
  windows: { start: string; end: string }[] | null
  summary: {
    missing: number
    missing_bytes: number
    late: number
    overall_ready_at: string | null
    network_bound: boolean
  }
  items: RdItem[]
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function fmtMB(b: number): string {
  return `${(b / 1048576).toFixed(0)} Mo`
}

function fmtKbps(kbps: number): string {
  if (kbps >= 1000) {
    const mbps = kbps / 1000
    return `${mbps >= 10 ? Math.round(mbps) : mbps.toFixed(1)} Mbps`
  }
  return `${Math.round(kbps)} kbps`
}

/**
 * Section « Disponibilité (sync-readiness) » du drawer player (look-ahead Phase 3) :
 * pour chaque média programmé à venir NON caché, date estimée de fin de téléchargement
 * (selon débit + fenêtres) et si elle arrive avant la diffusion. Fetch à l'ouverture.
 */
export default function ReadinessSection({ player, t }: { player: PlayerRead; t: T }) {
  const [expanded, setExpanded] = useState(false)

  const { data, isLoading, isError } = useQuery<Readiness>({
    queryKey: ['player-readiness', player.id_player],
    queryFn: () => api.get(`/players/${player.id_player}/readiness`).then((r) => r.data),
    enabled: expanded,
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
          <CalendarClock className="w-3.5 h-3.5 text-gray-400" />
          {t('players.readiness.title')}
        </span>
        {s && (
          <span className="flex items-center gap-1.5 text-xs font-medium">
            {s.late > 0 ? (
              <span className="text-red-700 dark:text-red-300 flex items-center gap-1"><AlertTriangle className="w-3 h-3" />{s.late}</span>
            ) : s.missing > 0 ? (
              <span className="text-amber-700 dark:text-amber-300">{s.missing}</span>
            ) : (
              <CheckCircle2 className="w-3.5 h-3.5 text-green-600 dark:text-green-300" />
            )}
          </span>
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5 text-xs">
          {isLoading && <p className="text-gray-400">{t('players.readiness.loading')}</p>}
          {isError && <p className="text-red-600 dark:text-red-300">{t('players.readiness.error')}</p>}
          {s && !data?.reported && <p className="text-amber-700 dark:text-amber-300">{t('players.readiness.not_reported')}</p>}
          {s && data?.reported && (
            <p className="text-gray-500">
              {s.missing === 0
                ? t('players.readiness.all_ready')
                : s.network_bound
                  ? t('players.readiness.network_bound', { count: s.missing, mb: fmtMB(s.missing_bytes) })
                  : t('players.readiness.summary', { count: s.missing, mb: fmtMB(s.missing_bytes), date: fmtDate(s.overall_ready_at) })}
              {s.late > 0 && ` · ${t('players.readiness.late', { count: s.late })}`}
            </p>
          )}
          {data?.throughput_source === 'measured' && (
            <p className="text-[11px] text-gray-400">
              {t('players.readiness.measured', { value: fmtKbps(data.throughput_kbps ?? 0) })}
            </p>
          )}
          {data && data.items.length > 0 && (
            <ul className="space-y-1 max-h-64 overflow-auto pr-1">
              {data.items.map((it) => {
                const ok = it.on_time && it.ready_at !== null
                const cls = it.network_bound
                  ? 'bg-gray-50 text-gray-600 border-gray-200'
                  : ok
                    ? 'bg-green-50 dark:bg-green-500/15 text-green-700 dark:text-green-300 border-green-200 dark:border-green-500/30'
                    : 'bg-red-500/10 dark:bg-red-500/15 text-red-700 dark:text-red-300 border-red-400/20 dark:border-red-500/30'
                const label = it.network_bound
                  ? t('players.readiness.net')
                  : it.ready_at === null
                    ? t('players.readiness.unreachable')
                    : fmtDate(it.ready_at)
                const Icon = it.network_bound ? Wifi : ok ? CheckCircle2 : AlertTriangle
                return (
                  <li key={it.id_media} className="flex items-center gap-2">
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[11px] shrink-0 ${cls}`}>
                      <Icon className="w-3 h-3" />
                      {label}
                    </span>
                    <span
                      className="truncate text-gray-700"
                      title={it.play_at ? t('players.readiness.airs', { date: fmtDate(it.play_at) }) : ''}
                    >
                      {it.media_name ?? `#${it.id_media}`}
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
