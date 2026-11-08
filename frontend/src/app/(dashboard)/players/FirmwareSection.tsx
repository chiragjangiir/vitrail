'use client'

import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Cpu, Download, RefreshCw } from 'lucide-react'

import api from '@/lib/api'
import type { PlayerRead } from '@/types/api'

type T = (key: string, values?: Record<string, string | number>) => string

interface FirmwareState {
  current_version: string | null
  model_family: string | null
  pinned_version: string | null
  update_available: boolean
  last_status: string | null
}

/**
 * Section « Firmware » du drawer player (P1.1) — BrightSign uniquement. Affiche la version courante
 * (bs_bos) et, si une version validée est ÉPINGLÉE pour la famille et diffère, propose la MAJ. Le
 * garde-fou (seule la version épinglée est poussée) est appliqué côté serveur : l'UI ne choisit pas.
 */
export default function FirmwareSection({ player, t }: { player: PlayerRead; t: T }) {
  const [expanded, setExpanded] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const caps = player.capabilities
  const isBs = player.player_os === 'brightsign' || !!caps?.bs_model || caps?.platform === 'brightsign'

  const { data, isLoading, refetch } = useQuery<FirmwareState>({
    queryKey: ['firmware-state', player.id_player],
    queryFn: () => api.get<FirmwareState>(`/firmware/players/${player.id_player}/state`).then((r) => r.data),
    enabled: isBs && expanded,
  })

  const updateMutation = useMutation({
    mutationFn: () => api.post(`/firmware/players/${player.id_player}/update`),
    onSuccess: (r) => {
      setNotice(t('players.firmware.update_sent', { version: r.data?.version ?? '' }))
      refetch()
    },
    onError: (e: unknown) => {
      // FastAPI 422 renvoie detail = LISTE d'objets → ne garder qu'une string (sinon React error #31).
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setNotice(typeof d === 'string' ? d : t('players.firmware.update_error'))
    },
  })

  if (!isBs) return null

  return (
    <div className="pt-2 border-t border-gray-100">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          <Cpu className="w-3.5 h-3.5 text-gray-400" />
          {t('players.firmware.title')}
        </span>
        {caps?.bs_bos && <span className="text-xs text-gray-400">{caps.bs_bos}</span>}
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 text-xs">
          {isLoading && <p className="text-gray-400">{t('common.loading')}</p>}
          {data && (
            <>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-gray-600">
                <dt className="text-gray-400">{t('players.firmware.current')}</dt>
                <dd className="font-medium text-gray-700 dark:text-gray-300">{data.current_version || '—'}</dd>
                <dt className="text-gray-400">{t('players.firmware.pinned')}</dt>
                <dd className="font-medium text-gray-700 dark:text-gray-300">{data.pinned_version || t('players.firmware.none_pinned')}</dd>
              </dl>

              {data.update_available ? (
                <div className="space-y-1.5">
                  <button
                    type="button"
                    onClick={() => { if (confirm(t('players.firmware.confirm', { version: data.pinned_version ?? '' }))) updateMutation.mutate() }}
                    disabled={updateMutation.isPending}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-accent text-white hover:bg-accent/80 transition-sf disabled:opacity-50"
                  >
                    {updateMutation.isPending
                      ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      : <Download className="w-3.5 h-3.5" />}
                    {t('players.firmware.update_to', { version: data.pinned_version ?? '' })}
                  </button>
                  <p className="text-[11px] text-amber-700 dark:text-amber-300">{t('players.firmware.reboot_warning')}</p>
                </div>
              ) : (
                <p className="text-gray-500">{t('players.firmware.up_to_date')}</p>
              )}
              {notice && <p className="text-[11px] text-gray-500">{notice}</p>}
            </>
          )}
        </div>
      )}
    </div>
  )
}
