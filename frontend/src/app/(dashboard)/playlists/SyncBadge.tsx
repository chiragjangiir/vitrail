'use client'

import { Wifi, WifiOff, CalendarClock } from 'lucide-react'
import type { useTranslations } from 'next-intl'
import type { PlaylistRead } from '@/types/api'

/**
 * Badge de synchronisabilité LAN d'une playlist, à 3 états :
 *  - vert  « Sync ready »   : wall-clock, durées résolues, aucune règle.
 *  - teal  « Sync (fenêtres) » : sync_ready MAIS règles scope=default → jeu d'items
 *    player-uniforme, juste une re-sync graceful aux frontières (sync de groupe OK).
 *  - ambre « Non synchronisable » : loop, durée manquante, conformité, ou override par cible.
 */
export default function SyncBadge({
  pl, t,
}: {
  pl: Pick<PlaylistRead, 'sync_ready' | 'sync_windowed'>
  t: ReturnType<typeof useTranslations>
}) {
  if (pl.sync_windowed) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-teal-50 dark:bg-teal-500/15 text-teal-700 dark:text-teal-300"
        title={t('playlists.sync_windowed_hint')}
      >
        <CalendarClock className="w-3 h-3" />
        {t('playlists.sync_windowed')}
      </span>
    )
  }
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
        pl.sync_ready ? 'bg-green-50 dark:bg-green-500/15 text-green-700 dark:text-green-300' : 'bg-amber-500/10 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300'
      }`}
      title={t(pl.sync_ready ? 'playlists.sync_ready_hint' : 'playlists.sync_not_ready_hint')}
    >
      {pl.sync_ready ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
      {t(pl.sync_ready ? 'playlists.sync_ready' : 'playlists.sync_not_ready')}
    </span>
  )
}
