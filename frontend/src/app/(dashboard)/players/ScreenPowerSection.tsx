'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Power } from 'lucide-react'

import api from '@/lib/api'
import type { DisplayConfig, PlayerRead } from '@/types/api'

/**
 * Section « Alimentation écran » du drawer player (auto-power §heures d'ouverture).
 * Définit comment l'écran de CE player est piloté par la tâche d'auto-power :
 *  - follow_site : suit les heures d'ouverture du site (défaut)
 *  - always_on   : toujours allumé (24/7)
 *  - manual      : jamais piloté automatiquement
 *  - custom      : fenêtre propre on_time→off_time (vitrine, ex. allumé toute la nuit)
 *
 * Stocké dans display_config.power_schedule. N'a d'effet que si l'écran est piloté
 * physiquement (display_config.type = rs232 | ip | cec) OU en repli « couper la sortie
 * vidéo » (display_config.output_power_fallback, écran non pilotable), et que le site
 * a l'auto-power actif.
 */
export default function ScreenPowerSection({
  player,
  t,
  onPlayerUpdate,
}: {
  player: PlayerRead
  t: (key: string, values?: Record<string, string | number>) => string
  onPlayerUpdate?: (p: PlayerRead) => void
}) {
  const qc = useQueryClient()
  const dc: Partial<DisplayConfig> = player.display_config ?? {}
  const ps = dc.power_schedule ?? { mode: 'follow_site' as const }
  const mode = ps.mode ?? 'follow_site'
  const displayPiloted =
    dc.type === 'rs232' || dc.type === 'ip' || dc.type === 'cec' || !!dc.output_power_fallback

  const mut = useMutation({
    mutationFn: (patch: NonNullable<DisplayConfig['power_schedule']>) =>
      api
        .put<PlayerRead>(`/players/${player.id_player}`, {
          display_config: { ...dc, power_schedule: patch },
        })
        .then((r) => r.data),
    onSuccess: (updated) => {
      onPlayerUpdate?.(updated)
      qc.invalidateQueries({ queryKey: ['players'] })
    },
  })

  return (
    <div className="space-y-2 pt-2 border-t border-gray-100">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
        <Power className="w-3.5 h-3.5" />
        {t('players.power.title')}
      </p>

      <label className="flex items-center justify-between gap-2 text-xs text-gray-600">
        {t('players.power.mode')}
        <select
          value={mode}
          onChange={(e) => {
            const m = e.target.value as NonNullable<DisplayConfig['power_schedule']>['mode']
            mut.mutate({ ...ps, mode: m, on_time: ps.on_time ?? '07:00', off_time: ps.off_time ?? '23:00' })
          }}
          disabled={mut.isPending}
          className="rounded border border-gray-200 px-2 py-1 bg-surface"
        >
          <option value="follow_site">{t('players.power.mode_follow_site')}</option>
          <option value="always_on">{t('players.power.mode_always_on')}</option>
          <option value="manual">{t('players.power.mode_manual')}</option>
          <option value="custom">{t('players.power.mode_custom')}</option>
        </select>
      </label>

      {mode === 'custom' && (
        <div className="grid grid-cols-2 gap-2">
          <label className="text-[11px] text-gray-500 space-y-0.5">
            <span>{t('players.power.on_time')}</span>
            <input
              type="time"
              value={ps.on_time ?? '07:00'}
              onChange={(e) => mut.mutate({ ...ps, mode: 'custom', on_time: e.target.value })}
              className="w-full rounded border border-gray-200 px-2 py-1"
            />
          </label>
          <label className="text-[11px] text-gray-500 space-y-0.5">
            <span>{t('players.power.off_time')}</span>
            <input
              type="time"
              value={ps.off_time ?? '23:00'}
              onChange={(e) => mut.mutate({ ...ps, mode: 'custom', off_time: e.target.value })}
              className="w-full rounded border border-gray-200 px-2 py-1"
            />
          </label>
        </div>
      )}

      <p className="text-[11px] text-gray-400">
        {!displayPiloted ? t('players.power.hint_no_display') : t('players.power.hint')}
      </p>
    </div>
  )
}
