'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Film, Music, Zap, Calendar } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import type { PlayerRead, PlayerDaySimResult } from '@/types/api'

/**
 * Simulation de la programmation COMPLÈTE d'un player sur une journée.
 * 2 pistes : Vidéo (programme/event → playlist actif par créneau) + Audio (paniers mixés).
 * Rejoue la résolution réelle (event > programme par priorité, validité, règles horaires).
 */
export default function DaySimulationDrawer({
  open, onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const t = useTranslations()
  const today = new Date().toISOString().slice(0, 10)
  const [playerId, setPlayerId] = useState<number | ''>('')
  const [date, setDate] = useState(today)
  const [result, setResult] = useState<PlayerDaySimResult | null>(null)

  const { data: players = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'],
    queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
    enabled: open,
  })

  const runMutation = useMutation({
    mutationFn: () => api.post<PlayerDaySimResult>(`/players/${playerId}/simulate-day`, { date }).then((r) => r.data),
    onSuccess: (data) => setResult(data),
  })

  return (
    <Drawer open={open} onClose={onClose} title={t('schedules.daysim_title')} width="w-[640px]">
      <div className="space-y-4">
        <p className="text-sm text-gray-500">{t('schedules.daysim_intro')}</p>

        {/* Sélecteurs player + date */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-600">{t('schedules.daysim_player')}</label>
            <select
              value={playerId}
              onChange={(e) => { setPlayerId(e.target.value ? Number(e.target.value) : ''); setResult(null) }}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
            >
              <option value="">{t('schedules.daysim_pick_player')}</option>
              {players.map((p) => (
                <option key={p.id_player} value={p.id_player}>{p.player_name}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-600">{t('schedules.daysim_date')}</label>
            <input
              type="date" value={date}
              onChange={(e) => { setDate(e.target.value); setResult(null) }}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
            />
          </div>
        </div>

        <Button onClick={() => runMutation.mutate()} disabled={playerId === '' || runMutation.isPending}>
          {runMutation.isPending ? t('common.loading') : t('schedules.daysim_run')}
        </Button>

        {result && (
          <div className="space-y-5 pt-2">
            {/* Les horaires ci-dessous sont ceux de l'ÉCRAN (fuseau de son site) : sans
                le dire, « 12:00 » est ambigu dès qu'un parc traverse deux fuseaux. */}
            <p className="text-xs text-gray-400 inline-flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5" />
              {t('schedules.daysim_timezone', { tz: result.timezone })}
            </p>

            {/* Piste vidéo */}
            <section className="space-y-1.5">
              <h3 className="text-sm font-semibold text-gray-700 inline-flex items-center gap-1.5">
                <Film className="w-4 h-4 text-accent" />{t('schedules.daysim_video')}
              </h3>
              {result.video.length === 0 ? (
                <p className="text-xs text-gray-400 px-1">{t('schedules.daysim_empty_video')}</p>
              ) : (
                <div className="space-y-1">
                  {result.video.map((s, i) => (
                    <div key={i} className={`flex items-center gap-3 text-xs rounded border px-2.5 py-1.5 ${s.source === 'event' ? 'bg-amber-500/10 dark:bg-amber-500/15 border-amber-400/20 dark:border-amber-500/30' : 'bg-surface border-gray-200'}`}>
                      <span className="font-mono text-gray-500 shrink-0 w-24">{s.start}–{s.end}</span>
                      {s.source === 'event'
                        ? <Zap className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                        : <Film className="w-3.5 h-3.5 text-gray-300 shrink-0" />}
                      <span className="font-medium text-gray-800 truncate">{s.name}</span>
                      {s.playlist_name && <span className="text-gray-400 truncate">→ {s.playlist_name}</span>}
                      <span className="ml-auto text-[10px] text-gray-400 shrink-0">P{s.priority}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Piste audio */}
            <section className="space-y-1.5">
              <h3 className="text-sm font-semibold text-gray-700 inline-flex items-center gap-1.5">
                <Music className="w-4 h-4 text-accent" />{t('schedules.daysim_audio')}
              </h3>
              {result.audio.length === 0 ? (
                <p className="text-xs text-gray-400 px-1">{t('schedules.daysim_empty_audio')}</p>
              ) : (
                <div className="space-y-1">
                  {result.audio.map((s, i) => {
                    // Fond continu = music + ambiance (couches simultanées, %) ; jingles à part (cadence).
                    const fond = s.baskets.filter((b) => ['music', 'ambiance'].includes(b.basket_type))
                    const jingles = s.baskets.filter((b) => b.basket_type === 'jingle')
                    const jingleLabel = (b: typeof jingles[number]) =>
                      b.trigger_mode === 'minutes'
                        ? t('schedules.daysim_jingle_minutes', { n: b.trigger_value ?? 0 })
                        : t('schedules.daysim_jingle_tracks', { n: b.trigger_value ?? 0 })
                    return (
                      <div key={i} className="flex items-start gap-3 text-xs rounded border border-gray-200 bg-surface px-2.5 py-1.5">
                        <span className="font-mono text-gray-500 shrink-0 w-24">{s.start}–{s.end}</span>
                        <div className="min-w-0 space-y-1">
                          {fond.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1">
                              <span className="text-[10px] uppercase tracking-wide text-gray-400 mr-0.5">{t('schedules.daysim_continuous')}</span>
                              {fond.map((b) => (
                                <span key={b.id_basket} className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 ${b.source === 'event' ? 'bg-amber-100 dark:bg-amber-500/20 text-amber-800 dark:text-amber-200' : 'bg-accent/10 text-accent'}`}>
                                  {b.name} · {t(`ab.type_${b.basket_type}`)} · {b.ratio}%
                                </span>
                              ))}
                            </div>
                          )}
                          {jingles.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1">
                              <span className="text-[10px] uppercase tracking-wide text-gray-400 mr-0.5">{t('schedules.daysim_jingles')}</span>
                              {jingles.map((b) => (
                                <span key={b.id_basket} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300">
                                  {b.name} · {jingleLabel(b)}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
              <p className="text-[11px] text-amber-700 dark:text-amber-300 bg-amber-500/10 dark:bg-amber-500/15 border border-amber-400/20 dark:border-amber-500/30 rounded px-2 py-1.5">
                {t('schedules.daysim_audio_note')}
              </p>
            </section>

            <p className="text-[11px] text-gray-400 inline-flex items-center gap-1">
              <Calendar className="w-3 h-3" />{t('schedules.daysim_footnote')}
            </p>
          </div>
        )}
      </div>
    </Drawer>
  )
}
