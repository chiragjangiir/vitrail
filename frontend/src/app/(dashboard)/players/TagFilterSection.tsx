'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Filter, ChevronDown, ChevronRight } from 'lucide-react'
import api from '@/lib/api'
import type { PlayerRead, MediaListItem } from '@/types/api'
import { TagPicker, useTagNamespaces } from '@/components/tags/TagControls'

/**
 * Section « Diffusion » du drawer player (§XVII) :
 *  - Filtres de contenu par namespace (profil de réception)
 *  - Fallback : message vidéo + piste audio de secours
 */
export default function TagFilterSection({
  player,
  t,
}: {
  player: PlayerRead
  t: (key: string, values?: Record<string, string | number>) => string
}) {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)  // replié par défaut
  const { data: namespaces = [] } = useTagNamespaces()

  const { data: filters = [] } = useQuery<number[]>({
    queryKey: ['player-tag-filters', player.id_player],
    queryFn: () => api.get<number[]>(`/players/${player.id_player}/tag-filters`).then((r) => r.data),
  })
  const [sel, setSel] = useState<Set<number> | null>(null)
  const selected = sel ?? new Set(filters)

  const saveFilters = useMutation({
    mutationFn: () => api.put(`/players/${player.id_player}/tag-filters`, { id_tags: Array.from(selected) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['player-tag-filters', player.id_player] }); setSel(null) },
  })

  const toggle = (id: number) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSel(next)
  }
  const dirty = sel !== null && (sel.size !== filters.length || Array.from(sel).some((id) => !filters.includes(id)))

  // ── Fallback ──────────────────────────────────────────────────────────────
  const { data: fallback } = useQuery<{ fallback_audio_id: number | null; fallback_video_message: string | null }>({
    queryKey: ['player-fallback', player.id_player],
    queryFn: () => api.get(`/players/${player.id_player}/fallback-config`).then((r) => r.data),
  })
  const { data: audioMedia = [] } = useQuery<MediaListItem[]>({
    queryKey: ['media', 'audio'],
    queryFn: () => api.get<MediaListItem[]>('/media/?media_type=audio&limit=200').then((r) => r.data),
  })
  const [msg, setMsg] = useState<string | null>(null)
  const [audioId, setAudioId] = useState<string | null>(null)
  const fbMsg = msg ?? fallback?.fallback_video_message ?? ''
  const fbAudio = audioId ?? (fallback?.fallback_audio_id != null ? String(fallback.fallback_audio_id) : '')

  const saveFallback = useMutation({
    mutationFn: () => api.put(`/players/${player.id_player}/fallback-config`, {
      fallback_video_message: fbMsg || null,
      fallback_audio_id: fbAudio ? Number(fbAudio) : null,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['player-fallback', player.id_player] }); setMsg(null); setAudioId(null) },
  })
  const fbDirty = msg !== null || audioId !== null

  const configured = filters.length > 0
    || !!(fallback?.fallback_video_message)
    || (fallback?.fallback_audio_id != null)

  return (
    <div className="pt-2 border-t border-gray-100">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-xs font-medium text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1.5 hover:text-gray-700"
      >
        {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        <Filter className="w-3.5 h-3.5" />{t('players.tag_filters_title')}
        {configured && <span className="w-2 h-2 rounded-full bg-accent ml-1" title={t('players.configured')} />}
      </button>
      {expanded && (
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-3">
        <p className="text-[11px] text-gray-400">{t('players.tag_filters_hint')}</p>
        <TagPicker namespaces={namespaces} selected={selected} onToggle={toggle} emptyLabel={t('players.tag_filters_empty')} />
        {dirty && (
          <button onClick={() => saveFilters.mutate()} disabled={saveFilters.isPending}
            className="w-full py-1.5 bg-accent text-white text-sm rounded-md hover:bg-accent/90 disabled:opacity-50">
            {saveFilters.isPending ? t('common.loading') : t('players.tag_filters_save')}
          </button>
        )}

        <div className="pt-2 border-t border-gray-200 space-y-2">
          <p className="text-[11px] font-medium text-gray-500">{t('players.fallback_title')}</p>
          <div>
            <label className="block text-xs text-gray-400 mb-1">{t('players.fallback_message')}</label>
            <input value={fbMsg} onChange={(e) => setMsg(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">{t('players.fallback_audio')}</label>
            <select value={fbAudio} onChange={(e) => setAudioId(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface">
              <option value="">—</option>
              {audioMedia.map((m) => <option key={m.id_media} value={m.id_media}>{m.media_name}</option>)}
            </select>
          </div>
          {fbDirty && (
            <button onClick={() => saveFallback.mutate()} disabled={saveFallback.isPending}
              className="w-full py-1.5 bg-accent text-white text-sm rounded-md hover:bg-accent/90 disabled:opacity-50">
              {saveFallback.isPending ? t('common.loading') : t('players.fallback_save')}
            </button>
          )}
        </div>
      </div>
      )}
    </div>
  )
}
