'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldAlert, ShieldCheck, Trash2 } from 'lucide-react'
import { useTranslations } from 'next-intl'
import api from '@/lib/api'
import type { MediaRead } from '@/types/api'

// ── Quarantaine / kill-switch (§ Q5) ───────────────────────────────────────────
// Composant autonome : lit son propre état média via idMedia (cache partagé avec
// la clé ['media', idMedia]) → réutilisable dans MediaDrawer, FeedDrawer,
// UrlDisplayDrawer (feed_display/url_display sont des cms_media, l'endpoint
// /media/{id}/quarantine n'a aucune garde de type).
export default function QuarantineSection({ idMedia }: { idMedia: number }) {
  const t = useTranslations('media')
  const qc = useQueryClient()
  const [reason, setReason] = useState('')

  const { data: media } = useQuery<MediaRead>({
    queryKey: ['media', idMedia],
    queryFn: () => api.get<MediaRead>(`/media/${idMedia}`).then((r) => r.data),
    staleTime: 30_000,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['media', idMedia] })
    qc.invalidateQueries({ queryKey: ['media'] })
  }
  const quarantine = useMutation({
    mutationFn: () => api.post(`/media/${idMedia}/quarantine`, { reason: reason || null }),
    onSuccess: () => { setReason(''); invalidate() },
  })
  const unquarantine = useMutation({
    mutationFn: () => api.post(`/media/${idMedia}/unquarantine`),
    onSuccess: invalidate,
  })
  const purge = useMutation({
    mutationFn: () => api.post(`/media/${idMedia}/purge`),
  })

  const isBlocked = media?.is_blocked ?? false

  return (
    <div className="border-t border-gray-100 pt-4 space-y-3" data-write-perm="media:edit">
      <div className="flex items-center gap-2">
        {isBlocked
          ? <ShieldAlert className="w-4 h-4 text-danger" />
          : <ShieldCheck className="w-4 h-4 text-gray-400" />}
        <span className="text-sm font-medium text-gray-800">{t('quarantine_title')}</span>
      </div>

      {isBlocked ? (
        <div className="space-y-2">
          <div className="rounded-md bg-red-500/10 dark:bg-red-500/15 border border-red-400/20 dark:border-red-500/30 px-3 py-2 text-xs text-red-700 dark:text-red-300">
            <p className="font-medium">{t('quarantine_active')}</p>
            {media?.block_reason && <p className="mt-0.5">{t('quarantine_reason')}: {media.block_reason}</p>}
          </div>
          <button
            data-write-action
            onClick={() => unquarantine.mutate()}
            disabled={unquarantine.isPending}
            className="w-full px-3 py-2 rounded border border-gray-200 text-sm text-gray-700 hover:bg-gray-50 transition-sf"
          >
            {t('quarantine_lift')}
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-gray-400">{t('quarantine_hint')}</p>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('quarantine_reason_placeholder')}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
          <button
            data-write-action
            onClick={() => { if (confirm(t('quarantine_confirm'))) quarantine.mutate() }}
            disabled={quarantine.isPending}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded bg-danger text-white text-sm font-medium hover:opacity-90 transition-sf"
          >
            <ShieldAlert className="w-4 h-4" />
            {t('quarantine_action')}
          </button>
        </div>
      )}

      {/* Purge des caches players (best-effort) */}
      <button
        data-write-action
        onClick={() => { if (confirm(t('purge_confirm'))) purge.mutate() }}
        disabled={purge.isPending}
        className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 transition-sf"
      >
        <Trash2 className="w-3.5 h-3.5" />
        {purge.isSuccess ? t('purge_done') : t('purge_action')}
      </button>
    </div>
  )
}
