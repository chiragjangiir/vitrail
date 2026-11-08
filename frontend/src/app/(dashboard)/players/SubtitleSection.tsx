'use client'

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Captions, ChevronDown, ChevronRight } from 'lucide-react'

import api from '@/lib/api'
import type { DisplayConfig, PlayerRead } from '@/types/api'

/**
 * Section « Sous-titres » du drawer player (§7).
 * Le player affiche les sous-titres de son pays d'installation :
 *  - subtitle_lang         : langue préférée (ex. "fr")
 *  - subtitle_fallback     : 'none' (rien si absente) | 'default' (langue de repli)
 *  - subtitle_default_lang : langue de repli si fallback='default' (ex. "en")
 * Réglages stockés dans display_config (zéro migration).
 */
export default function SubtitleSection({
  player,
  t,
  onPlayerUpdate,
}: {
  player: PlayerRead
  t: (key: string, values?: Record<string, string | number>) => string
  onPlayerUpdate?: (p: PlayerRead) => void
}) {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)  // replié par défaut
  const dc: Partial<DisplayConfig> = player.display_config ?? {}
  const lang = dc.subtitle_lang ?? ''
  const fallback = dc.subtitle_fallback ?? 'none'
  const defaultLang = dc.subtitle_default_lang ?? ''
  const configured = !!lang || fallback !== 'none'

  const mut = useMutation({
    mutationFn: (patch: Partial<DisplayConfig>) =>
      api
        .put<PlayerRead>(`/players/${player.id_player}`, { display_config: { ...dc, ...patch } })
        .then((r) => r.data),
    onSuccess: (updated) => {
      onPlayerUpdate?.(updated)
      qc.invalidateQueries({ queryKey: ['players'] })
    },
  })

  return (
    <div className="space-y-2 pt-2 border-t border-gray-100">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5 hover:text-gray-700"
      >
        {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        <Captions className="w-3.5 h-3.5" />
        {t('players.subtitles.title')}
        {configured && <span className="w-2 h-2 rounded-full bg-accent ml-1" title={t('players.configured')} />}
      </button>

      {expanded && (<>
      <label className="flex items-center justify-between gap-2 text-xs text-gray-600">
        {t('players.subtitles.lang')}
        <input
          type="text"
          value={lang}
          placeholder="fr"
          maxLength={8}
          onChange={(e) => mut.mutate({ subtitle_lang: e.target.value.trim().toLowerCase() || undefined })}
          disabled={mut.isPending}
          className="w-24 rounded border border-gray-200 px-2 py-1 bg-surface"
        />
      </label>

      <label className="flex items-center justify-between gap-2 text-xs text-gray-600">
        {t('players.subtitles.fallback')}
        <select
          value={fallback}
          onChange={(e) => mut.mutate({ subtitle_fallback: e.target.value as DisplayConfig['subtitle_fallback'] })}
          disabled={mut.isPending}
          className="rounded border border-gray-200 px-2 py-1 bg-surface"
        >
          <option value="none">{t('players.subtitles.fallback_none')}</option>
          <option value="default">{t('players.subtitles.fallback_default')}</option>
        </select>
      </label>

      {fallback === 'default' && (
        <label className="flex items-center justify-between gap-2 text-xs text-gray-600">
          {t('players.subtitles.default_lang')}
          <input
            type="text"
            value={defaultLang}
            placeholder="en"
            maxLength={8}
            onChange={(e) => mut.mutate({ subtitle_default_lang: e.target.value.trim().toLowerCase() || undefined })}
            disabled={mut.isPending}
            className="w-24 rounded border border-gray-200 px-2 py-1 bg-surface"
          />
        </label>
      )}

      <p className="text-[11px] text-gray-400">{t('players.subtitles.hint')}</p>
      </>)}
    </div>
  )
}
