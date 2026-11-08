'use client'

import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { AlertTriangle, ListVideo, CalendarClock, Zap, Music, Loader2 } from 'lucide-react'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import type { BroadcastState, MediaDeletionImpact } from '@/types/api'

interface Props {
  /** Nom affiché en tête de la modale. */
  name: string
  /** Endpoint GET renvoyant l'arbre d'impact (média, feed ou page web). */
  impactUrl: string
  /** Clé de cache React Query pour l'impact. */
  queryKey: (string | number)[]
  isPending: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Pastille d'état de diffusion (icône + couleur + libellé — règle design : jamais d'icône seule). */
function BroadcastBadge({ state }: { state: BroadcastState }) {
  const t = useTranslations('media')
  const map: Record<BroadcastState, { cls: string; label: string }> = {
    active:    { cls: 'bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-300',       label: t('bcast_active') },
    scheduled: { cls: 'bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300',     label: t('bcast_scheduled') },
    expired:   { cls: 'bg-gray-100 text-gray-500',     label: t('bcast_expired') },
    inactive:  { cls: 'bg-gray-100 text-gray-500',     label: t('bcast_inactive') },
    none:      { cls: 'bg-gray-100 text-gray-400',     label: t('bcast_none') },
  }
  const { cls, label } = map[state]
  return <span className={`text-[11px] px-1.5 py-0.5 rounded-full font-medium ${cls}`}>{label}</span>
}

export default function DeleteMediaDialog({
  name, impactUrl, queryKey, isPending, onConfirm, onCancel,
}: Props) {
  const t = useTranslations('media')

  const { data, isLoading, isError } = useQuery<MediaDeletionImpact>({
    queryKey,
    queryFn: () => api.get<MediaDeletionImpact>(impactUrl).then((r) => r.data),
    staleTime: 0,
  })

  const nowhere =
    data &&
    data.playlists.length === 0 &&
    data.events.length === 0 &&
    data.baskets.length === 0

  return (
    <div className="space-y-4" data-write-perm="media:edit">
      <div className="text-sm text-gray-600 bg-gray-50 rounded-lg px-3 py-2 truncate" title={name}>
        {name}
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-500 py-6 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> {t('delete_loading')}
        </div>
      )}

      {isError && <p className="text-sm text-danger py-4">{t('delete_impact_error')}</p>}

      {data && (
        <>
          {data.summary.has_live_broadcast && (
            <div className="flex items-start gap-2 rounded-lg bg-red-500/10 dark:bg-red-500/15 border border-red-400/20 dark:border-red-500/30 px-3 py-2">
              <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-300 mt-0.5 shrink-0" />
              <p className="text-xs text-red-700 dark:text-red-300 font-medium">{t('delete_live_warning')}</p>
            </div>
          )}

          {nowhere ? (
            <p className="text-sm text-gray-600 py-2">{t('delete_nowhere')}</p>
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-gray-700">{t('delete_intro')}</p>

              {data.playlists.length > 0 && (
                <section className="space-y-1.5">
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
                    <ListVideo className="w-3.5 h-3.5" /> {t('delete_playlists', { count: data.playlists.length })}
                  </h4>
                  <ul className="space-y-1">
                    {data.playlists.map((p) => (
                      <li key={p.id_playlist} className="flex items-center justify-between gap-2 text-sm px-2 py-1.5 rounded bg-gray-50">
                        <span className="truncate text-gray-800" title={p.playlist_name}>{p.playlist_name}</span>
                        <span className="flex items-center gap-1.5 shrink-0">
                          <BroadcastBadge state={p.broadcast} />
                          {p.will_be_deleted ? (
                            <span className="text-[11px] px-1.5 py-0.5 rounded-full font-medium bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-300">
                              {t('delete_playlist_will_delete')}
                            </span>
                          ) : (
                            <span className="text-[11px] text-gray-400">
                              {t('delete_playlist_remaining', { count: p.remaining_items })}
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.schedules.length > 0 && (
                <section className="space-y-1.5">
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-red-700 dark:text-red-300">
                    <CalendarClock className="w-3.5 h-3.5" /> {t('delete_schedules', { count: data.schedules.length })}
                  </h4>
                  <ul className="space-y-1">
                    {data.schedules.map((s) => (
                      <li key={s.id_schedule} className="flex items-center justify-between gap-2 text-sm px-2 py-1.5 rounded bg-red-500/10 dark:bg-red-500/15">
                        <span className="truncate text-gray-800" title={s.schedule_name}>{s.schedule_name}</span>
                        <BroadcastBadge state={s.broadcast} />
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.events.length > 0 && (
                <section className="space-y-1.5">
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
                    <Zap className="w-3.5 h-3.5" /> {t('delete_events', { count: data.events.length })}
                  </h4>
                  <ul className="space-y-1">
                    {data.events.map((e) => (
                      <li key={e.id_event} className="flex items-center justify-between gap-2 text-sm px-2 py-1.5 rounded bg-gray-50">
                        <span className="truncate text-gray-800" title={e.event_name}>{e.event_name}</span>
                        {e.will_be_cancelled && (
                          <span className="text-[11px] px-1.5 py-0.5 rounded-full font-medium bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300">
                            {t('delete_event_cancel')}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.baskets.length > 0 && (
                <section className="space-y-1.5">
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
                    <Music className="w-3.5 h-3.5" /> {t('delete_baskets', { count: data.baskets.length })}
                  </h4>
                  <p className="text-[11px] text-gray-500">{t('delete_baskets_note')}</p>
                  <ul className="space-y-1">
                    {data.baskets.map((b) => (
                      <li key={b.id_basket} className="text-sm px-2 py-1.5 rounded bg-gray-50 truncate text-gray-800" title={b.basket_name}>
                        {b.basket_name}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <p className="text-xs text-gray-500 border-t border-gray-100 pt-3">{t('delete_cascade_note')}</p>
            </div>
          )}
        </>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" onClick={onCancel} disabled={isPending}>
          {t('delete_cancel')}
        </Button>
        <Button variant="danger" data-write-action onClick={onConfirm} disabled={isPending || isLoading}>
          {isPending ? t('delete_in_progress') : t('delete_confirm_btn')}
        </Button>
      </div>
    </div>
  )
}
