'use client'

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Ban, ChevronDown, ChevronRight, Clock, Layers, Lock } from 'lucide-react'
import MarqueeText from '@/components/ui/MarqueeText'
import api from '@/lib/api'
import type { CompiledSchedule, PlayerRead, Site } from '@/types/api'

/**
 * Programme compilé — colonne de DROITE de la mise en page A (validée Ed 2026-07-26).
 *
 * Contraintes nées de la largeur (~400 px en FHD) et des retours d'Ed :
 * · tableau des taux réduit à 3 colonnes (contenu · intervalle · passages/jour), le
 *   pourcentage d'antenne passant en infobulle — c'est l'intervalle (« toutes les
 *   11 minutes ») avec lequel on raisonne réellement, pas le % ;
 * · **tours dépliables, le premier ouvert** : 12 à 20 tours affichés à plat étaient
 *   illisibles (« c'est complètement incompréhensible visuellement ») ;
 * · sélecteur d'écran groupé par SITE et cherchable — un parc de 500 écrans ne se
 *   parcourt pas dans un `<select>` à plat.
 */
export default function CompiledProgramPanel({ nodeId }: { nodeId: number }) {
  const t = useTranslations('governance')
  const [pid, setPid] = useState<number | null>(null)
  const [at, setAt] = useState('')          // instant simulé ; vide = maintenant
  const [q, setQ] = useState('')            // recherche écran / site
  const [openTurns, setOpenTurns] = useState<Set<number>>(new Set([0]))

  const { data: nodePlayerIds = [] } = useQuery<number[]>({
    queryKey: ['gov-node-players', nodeId],
    queryFn: () => api.get<number[]>(`/governance/nodes/${nodeId}/players`).then((r) => r.data),
  })
  const { data: players = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'], queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
  })
  const { data: sites = [] } = useQuery<Site[]>({
    queryKey: ['sites'], queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
  })

  const siteName = useMemo(
    () => new Map(sites.map((s) => [s.id_site, s.site_name])), [sites],
  )
  const nodePlayers = useMemo(
    () => players.filter((p) => nodePlayerIds.includes(p.id_player)),
    [players, nodePlayerIds],
  )
  // Groupé par site, filtré sur le nom de l'écran OU celui du site (demande Ed : « recherche
  // d'écran par site » — c'est le site qu'on a en tête quand on vérifie un magasin).
  const grouped = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const map = new Map<string, PlayerRead[]>()
    for (const p of nodePlayers) {
      const site = p.id_site != null ? (siteName.get(p.id_site) ?? '') : ''
      const label = site || t('no_site')
      if (needle
        && !p.player_name.toLowerCase().includes(needle)
        && !label.toLowerCase().includes(needle)) continue
      if (!map.has(label)) map.set(label, [])
      map.get(label)!.push(p)
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [nodePlayers, siteName, q, t])

  const { data: compiled, isFetching } = useQuery<CompiledSchedule>({
    queryKey: ['compiled-schedule', pid, at],
    enabled: pid != null,
    queryFn: () => api.get<CompiledSchedule>(
      `/players/${pid}/compiled-schedule${at ? `?at=${encodeURIComponent(at)}` : ''}`,
    ).then((r) => r.data),
  })

  const orderedLayers = useMemo(() => {
    if (!compiled) return []
    return [...compiled.layers].sort(
      (a, b) => a.node_level - b.node_level || b.priority - a.priority,
    )
  }, [compiled])
  const maxLevel = useMemo(
    () => orderedLayers.reduce((m, l) => Math.max(m, l.node_level), 0), [orderedLayers],
  )

  const fmtDur = (ms: number) => {
    const s = Math.round(ms / 1000)
    return s >= 60 ? `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}` : `${s}s`
  }

  const statusBadge = (status: string) => {
    if (status === 'preempted')
      return <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 dark:bg-red-500/15 text-red-600 dark:text-red-300"><Ban className="w-3 h-3" />{t('cs_status_preempted')}</span>
    if (status === 'outside_time_window')
      return <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500"><Clock className="w-3 h-3" />{t('cs_status_window')}</span>
    return <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-green-50 dark:bg-green-500/15 text-green-700 dark:text-green-300">{t('cs_status_active')}</span>
  }

  const turns = compiled?.turns ?? 1
  const toggleTurn = (i: number) =>
    setOpenTurns((s) => {
      const next = new Set(s)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })

  return (
    <div className="flex flex-col min-h-0 h-full">
      <div className="shrink-0 px-4 py-3 border-b border-gray-100 space-y-2">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
          <Layers className="w-3.5 h-3.5" />{t('cs_title')}
        </p>
        {/* R11 (revue du 2026-07-23) : le panneau ne disait ni son objet ni son périmètre.
            Ed demandait « est-ce une simulation ? pourquoi un seul écran ? ». Ce n'est pas
            un mock — mêmes fonctions que le vrai `player:sync` — mais l'évaluation s'arrête
            AVANT tags, campagnes et ancrage wall-clock : c'est le résultat de la
            GOUVERNANCE, pour CET écran, à CET instant. Le dire vaut mieux que de laisser
            deviner. */}
        <p className="text-[11px] leading-snug text-gray-400" data-testid="cs-scope-hint">
          {t('cs_scope_hint')}
        </p>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('cs_search_player')}
          className="w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-surface"
        />
        <select
          value={pid ?? ''}
          onChange={(e) => setPid(e.target.value ? Number(e.target.value) : null)}
          className="w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-surface"
          data-testid="gov-player-select"
        >
          <option value="">{t('cs_pick_player')}</option>
          {grouped.map(([label, list]) => (
            <optgroup key={label} label={label}>
              {list.map((p) => (
                <option key={p.id_player} value={p.id_player}>{p.player_name}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <div className="flex items-center gap-1.5">
          <label className="text-[11px] text-gray-500 shrink-0">{t('cs_at_label')}</label>
          <input
            type="datetime-local"
            value={at}
            onChange={(e) => setAt(e.target.value)}
            className="flex-1 min-w-0 border border-gray-300 rounded-md px-2 py-1 text-xs bg-surface"
          />
          {at && (
            <button onClick={() => setAt('')} className="text-[11px] text-accent hover:underline shrink-0">
              {t('cs_at_now')}
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-2">
        {pid == null ? (
          <p className="text-xs text-gray-400">
            {nodePlayers.length === 0 ? t('cs_no_players') : t('cs_hint')}
          </p>
        ) : isFetching && !compiled ? (
          <p className="text-xs text-gray-400">…</p>
        ) : !compiled || orderedLayers.length === 0 ? (
          // R10 : nommer la VRAIE cause — « aucune couche active » en recouvrait cinq.
          <div className="rounded-md border border-amber-300 dark:border-amber-500/40 bg-amber-500/10 px-3 py-2">
            <p className="text-xs text-amber-700 dark:text-amber-300">
              {compiled?.empty_reason
                ? t(`cs_why_${compiled.empty_reason}`, { name: compiled.empty_detail ?? '—' })
                : t('cs_empty')}
            </p>
            {compiled?.empty_reason === 'outside_window' && (
              <p className="text-[11px] text-amber-600/80 dark:text-amber-300/70 mt-1">
                {t('cs_why_outside_window_hint')}
              </p>
            )}
          </div>
        ) : (
          <>
            <p className="text-[11px] text-gray-500">
              {t('cs_cycle')} : <span className="font-medium text-gray-700">{fmtDur(compiled.cycle_duration_ms)}</span>
              {turns > 1 && <span className="text-gray-400"> · {t('cs_turns', { n: turns })}</span>}
            </p>

            {compiled.truncated && (
              <div className="rounded-md border border-amber-300 dark:border-amber-500/40 bg-amber-500/10 px-3 py-2">
                <p className="text-xs text-amber-700 dark:text-amber-300">{t('cs_truncated')}</p>
              </div>
            )}

            {/* Taux de passage — 3 colonnes en 400 px ; le % d'antenne passe en infobulle. */}
            {(compiled.contents ?? []).length > 0 && (
              <div className="rounded-md border border-gray-200 overflow-hidden">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-gray-500">
                      <th className="text-left px-2 py-1">{t('rate_content')}</th>
                      <th className="text-right px-2 py-1">{t('rate_interval')}</th>
                      <th className="text-right px-2 py-1">{t('rate_per_day')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {(compiled.contents ?? []).map((c) => (
                      <tr key={c.id_media}
                          title={`${c.node_name} · ${t('rate_per_cycle')} ${c.plays_per_cycle} · ${c.airtime_pct.toFixed(1)} %`}>
                        <td className="px-2 py-1 text-gray-700 max-w-[150px]">
                          <MarqueeText text={c.media_name} />
                        </td>
                        <td className="px-2 py-1 text-right text-gray-600">{fmtDur(c.interval_ms)}</td>
                        <td className="px-2 py-1 text-right text-gray-600">{c.plays_per_day}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-[10px] text-gray-400 px-2 py-1">
                  {t('rate_hours_note', { h: compiled.open_hours_per_day ?? 24 })}
                </p>
              </div>
            )}

            {/* Tours dépliables — le premier ouvert. */}
            {turns > 1 && compiled.items.length > 0 && (
              <div className="space-y-1">
                {Array.from({ length: turns }, (_, ti) => {
                  const per = Math.max(1, Math.round(compiled.items.length / turns))
                  const slice = compiled.items.slice(ti * per, (ti + 1) * per)
                  if (!slice.length) return null
                  const open = openTurns.has(ti)
                  return (
                    <div key={ti} className="rounded-md border border-gray-200 bg-canvas">
                      <button
                        onClick={() => toggleTurn(ti)}
                        className="w-full flex items-center gap-1 px-2 py-1.5 text-[10px] uppercase tracking-wide text-gray-400"
                      >
                        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                        {t('cs_turn', { n: ti + 1 })}
                        <span className="ml-auto normal-case text-gray-400">{slice.length}</span>
                      </button>
                      {open && (
                        <div className="flex flex-wrap gap-1 px-2 pb-2">
                          {slice.map((it, i) => (
                            <span key={`${it.id_media}-${i}`} className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded bg-surface border border-gray-200 text-gray-600 max-w-[200px]">
                              <MarqueeText text={it.media_name} className="min-w-0" />
                              <span className="text-gray-400 shrink-0">{fmtDur(it.duration_ms)}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {orderedLayers.map((l) => {
              const inherited = l.node_level < maxLevel
              const dimmed = l.status !== 'active'
              const items = compiled.items.filter((it) => it.id_schedule === l.id_schedule)
              return (
                <div
                  key={l.id_schedule}
                  className={`rounded-md border px-2.5 py-2 ${
                    dimmed ? 'border-gray-100 bg-gray-50/60 opacity-70'
                      : inherited ? 'border-gray-200 bg-gray-50' : 'border-accent/30 bg-accent/5'
                  }`}
                >
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-600 shrink-0">
                      {t('cs_level', { n: l.node_level })}
                    </span>
                    <MarqueeText text={l.node_name} className="text-sm font-medium text-gray-800 min-w-0 flex-1" />
                    {inherited && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-gray-400" title={t('cs_inherited')}>
                        <Lock className="w-3 h-3" />
                      </span>
                    )}
                    <span className="flex-1" />
                    {statusBadge(l.status)}
                    {l.budget_trimmed && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300">
                        {l.budget_overflow ? t('cs_overflow') : t('cs_budget_reached')}
                      </span>
                    )}
                  </div>
                  {l.dropped_too_long && l.dropped_too_long.length > 0 && (
                    <p className="text-[11px] text-amber-600 dark:text-amber-300 mt-1">
                      {t('cs_dropped_too_long', { names: l.dropped_too_long.join(', ') })}
                    </p>
                  )}
                  {turns > 1 ? null : items.length > 0 ? (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {items.map((it, i) => (
                        <span key={`${it.id_media}-${i}`} className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded bg-surface border border-gray-200 text-gray-600 max-w-[200px]">
                          <MarqueeText text={it.media_name} className="min-w-0" />
                          <span className="text-gray-400 shrink-0">{fmtDur(it.duration_ms)}</span>
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gray-400 mt-1">{t('cs_no_items')}</p>
                  )}
                </div>
              )
            })}
          </>
        )}
      </div>
    </div>
  )
}
