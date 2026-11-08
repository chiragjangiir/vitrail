'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ShieldCheck, Download, FileText, Check, X, Trash2, Archive, MonitorOff, Layers } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import BackButton from '@/components/ui/BackButton'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import type { PlayerRead, PlayerGroupRead, Site, SiteGroupRead } from '@/types/api'

interface PopPlayRow {
  id_pop: number
  id_player: number
  player_name: string | null
  id_media: number | null
  media_name: string | null
  played_at: string
  duration_ms: number
  signed: boolean
  merkle_hash: string
  is_document?: boolean
  /** Joué alors que la sortie vidéo était coupée (auto-power) : la preuve existe et reste
   *  dans la chaîne, mais n'est comptée dans AUCUN agrégat d'antenne. Affichée ici car
   *  c'est la vue forensique — la masquer rendrait le phénomène invisible. */
  screen_off?: boolean
  /** Joué dans une zone RECOUVERTE par un overlay plein écran (spot de campagne P3.6 ou
   *  takeover VOD). Même statut que `screen_off` : la preuve existe, reste dans la chaîne,
   *  et n'est comptée dans aucun agrégat. Motif DISTINCT parce que la cause l'est — ici
   *  l'écran était allumé, c'est la zone qui était masquée. */
  covered?: boolean
}
/** Ligne affichée : pages > 1 = preuves consécutives d'un même document regroupées. */
interface DisplayRow extends PopPlayRow {
  pages: number
}

/**
 * Regroupe les preuves CONSÉCUTIVES d'un même document sur un même player (le serveur
 * déroule un PDF/PPT en N items image → N preuves, ex. 3 × 10 s) en UNE ligne : durée
 * cumulée + nombre de pages diffusées (retour Ed 17/07). Affichage seulement — les
 * preuves stockées (chaîne Merkle, signatures) restent individuelles. Deux passages
 * séparés du document (2 tours de boucle) ne fusionnent pas : la contiguïté temporelle
 * (fin de page N ≈ début de page N+1, tolérance 3 s) borne le groupe.
 */
function aggregateDocRows(rows: PopPlayRow[]): DisplayRow[] {
  const out: DisplayRow[] = []
  const open = new Map<string, DisplayRow>()   // "player|media" → groupe document ouvert
  for (const r of rows) {                       // rows triées played_at DESC
    if (!r.is_document || r.id_media == null) {
      out.push({ ...r, pages: 1 })
      continue
    }
    const key = `${r.id_player}|${r.id_media}`
    const g = open.get(key)
    if (g) {
      // DESC : la ligne courante précède le groupe — contiguë si sa fin ≈ le début du groupe.
      const gap = new Date(g.played_at).getTime() - (new Date(r.played_at).getTime() + r.duration_ms)
      // Ne jamais fusionner des pages de statut d'écran DIFFÉRENT : un document à cheval
      // sur l'extinction — ou sur le début d'un spot plein écran — produirait une ligne
      // mi-comptée mi-non comptée, illisible.
      if (Math.abs(gap) <= 3000
          && !!g.screen_off === !!r.screen_off
          && !!g.covered === !!r.covered) {
        g.played_at = r.played_at
        g.duration_ms += r.duration_ms
        g.signed = g.signed && r.signed
        g.pages += 1
        continue
      }
    }
    const fresh: DisplayRow = { ...r, pages: 1 }
    open.set(key, fresh)
    out.push(fresh)   // la ligne garde la position de sa page la plus récente
  }
  return out
}
interface PopPlaysResponse {
  total: number
  limit: number
  offset: number
  rows: PopPlayRow[]
}

type ScopeMode = 'all' | 'players' | 'group' | 'site' | 'site_group'
type MediaKind = 'all' | 'visual' | 'audio' | 'audio_standard' | 'audio_ambiance'
interface Committed {
  from: string
  until: string
  mode: ScopeMode
  players: number[]
  group: number | null
  site: number | null
  siteGroup: number | null
  kind: MediaKind
}

const LIMIT = 100

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}
function firstOfMonthISO(): string {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10)
}
function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`
}
function fmtDateTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

/** Params de périmètre selon le mode. id_players = tableau (sérialisé en clés répétées). */
function scopeParams(c: Committed): Record<string, unknown> {
  // Famille de média (S1 PoP audio) : 'all' = pas de filtre serveur.
  const kind = c.kind !== 'all' ? { media_type: c.kind } : {}
  if (c.mode === 'group' && c.group) return { id_group: c.group, ...kind }
  if (c.mode === 'site' && c.site) return { id_site: c.site, ...kind }
  if (c.mode === 'site_group' && c.siteGroup) return { id_site_group: c.siteGroup, ...kind }
  if (c.mode === 'players' && c.players.length) return { id_players: c.players, ...kind }
  return kind
}

export default function ProofOfPlayPage() {
  const t = useTranslations('reports')
  const isDemo = useAuthStore((s) => s.user?.is_demo)  // pas d'export CSV/PDF pour un compte démo
  const [from, setFrom] = useState(firstOfMonthISO())
  const [until, setUntil] = useState(todayISO())
  const [mode, setMode] = useState<ScopeMode>('all')
  const [players, setPlayers] = useState<number[]>([])
  const [group, setGroup] = useState<number | null>(null)
  const [site, setSite] = useState<number | null>(null)
  const [siteGroup, setSiteGroup] = useState<number | null>(null)
  const [kind, setKind] = useState<MediaKind>('all')

  const [committed, setCommitted] = useState<Committed | null>(null)
  const [offset, setOffset] = useState(0)
  const [downloading, setDownloading] = useState<'csv' | 'pdf' | null>(null)

  const { data: playerList = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'],
    queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
  })
  const { data: groupList = [] } = useQuery<PlayerGroupRead[]>({
    queryKey: ['player-groups'],
    queryFn: () => api.get<PlayerGroupRead[]>('/player-groups/').then((r) => r.data),
  })
  const { data: siteList = [] } = useQuery<Site[]>({
    queryKey: ['sites'],
    queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
  })
  const { data: siteGroupList = [] } = useQuery<SiteGroupRead[]>({
    queryKey: ['site-groups'],
    queryFn: () => api.get<SiteGroupRead[]>('/site-groups/').then((r) => r.data),
  })

  const plays = useQuery<PopPlaysResponse>({
    queryKey: ['pop-plays', committed, offset],
    enabled: committed !== null,
    queryFn: () =>
      api
        .get<PopPlaysResponse>('/pop/plays', {
          params: {
            from: committed!.from,
            until: committed!.until,
            limit: LIMIT,
            offset,
            ...scopeParams(committed!),
          },
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data),
  })

  const generate = () => {
    const next: Committed = { from, until, mode, players, group, site, siteGroup, kind }
    // Re-génération à sélection IDENTIQUE : la queryKey ne change pas → React Query ne
    // refetch pas et le bouton semble mort (retour Ed 17/07). Dans ce cas, refetch explicite.
    if (committed && offset === 0 && JSON.stringify(next) === JSON.stringify(committed)) {
      plays.refetch()
      return
    }
    setOffset(0)
    setCommitted(next)
  }

  const download = async (kind: 'csv' | 'pdf') => {
    if (!committed) return
    setDownloading(kind)
    try {
      const path = kind === 'csv' ? '/pop/plays.csv' : '/pop/report.pdf'
      const res = await api.get(path, {
        params: {
          from: committed.from,
          until: committed.until,
          ...scopeParams(committed),
        },
        paramsSerializer: { indexes: null },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `proof_of_play_${committed.from}_${committed.until}.${kind}`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setDownloading(null)
    }
  }

  // Purge des preuves d'UN player (périmètre = un seul player sélectionné). Destructif, org-admin.
  const [purgeMsg, setPurgeMsg] = useState<string | null>(null)
  const purge = useMutation({
    mutationFn: (idPlayer: number) =>
      api.delete<{ deleted: number }>(`/pop/players/${idPlayer}`).then((r) => r.data),
    onSuccess: (d) => { setPurgeMsg(t('pop_purge_done', { count: d.deleted })); plays.refetch() },
  })
  const onPurge = () => {
    const id = players[0]
    const name = playerList.find((p) => p.id_player === id)?.player_name ?? ''
    if (!confirm(t('pop_purge_confirm', { name }))) return
    setPurgeMsg(null)
    purge.mutate(id)
  }

  const togglePlayer = (id: number) =>
    setPlayers((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  const data = plays.data
  const inputCls =
    'border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface'
  const totalPages = data ? Math.max(1, Math.ceil(data.total / LIMIT)) : 1
  const page = Math.floor(offset / LIMIT) + 1

  return (
    <>
      <Topbar title={t('pop_title')}>
        <BackButton />
      </Topbar>
      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-8 space-y-6">
          <div className="bg-surface rounded-lg border border-gray-200 p-5 space-y-4 shadow-sf-card">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-accent" />
              <h2 className="text-sm font-semibold text-gray-900">{t('pop_title')}</h2>
            </div>
            <p className="text-xs text-gray-400">{t('pop_hint')}</p>

            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('from')}</label>
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inputCls} />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('until')}</label>
                <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className={inputCls} />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('pop_scope')}</label>
                <select value={mode} onChange={(e) => setMode(e.target.value as ScopeMode)} className={inputCls}>
                  <option value="all">{t('pop_scope_all')}</option>
                  <option value="players">{t('pop_scope_players')}</option>
                  <option value="group">{t('pop_scope_group')}</option>
                  <option value="site">{t('pop_scope_site')}</option>
                  <option value="site_group">{t('pop_scope_site_group')}</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('pop_media_kind')}</label>
                <select value={kind} onChange={(e) => setKind(e.target.value as MediaKind)} className={inputCls}>
                  <option value="all">{t('pop_media_all')}</option>
                  <option value="visual">{t('pop_media_visual')}</option>
                  <option value="audio">{t('pop_media_audio')}</option>
                  <option value="audio_standard">{t('pop_media_audio_standard')}</option>
                  <option value="audio_ambiance">{t('pop_media_audio_ambiance')}</option>
                </select>
              </div>

              {mode === 'group' && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('pop_scope_group')}</label>
                  <select
                    value={group ?? ''}
                    onChange={(e) => setGroup(e.target.value ? Number(e.target.value) : null)}
                    className={inputCls}
                  >
                    <option value="">—</option>
                    {groupList.map((g) => (
                      <option key={g.id_group} value={g.id_group}>{g.group_name}</option>
                    ))}
                  </select>
                </div>
              )}
              {mode === 'site' && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('pop_scope_site')}</label>
                  <select
                    value={site ?? ''}
                    onChange={(e) => setSite(e.target.value ? Number(e.target.value) : null)}
                    className={inputCls}
                  >
                    <option value="">—</option>
                    {siteList.map((s) => (
                      <option key={s.id_site} value={s.id_site}>{s.site_name}</option>
                    ))}
                  </select>
                </div>
              )}

              {mode === 'site_group' && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('pop_scope_site_group')}</label>
                  <select
                    value={siteGroup ?? ''}
                    onChange={(e) => setSiteGroup(e.target.value ? Number(e.target.value) : null)}
                    className={inputCls}
                  >
                    <option value="">—</option>
                    {siteGroupList.map((g) => (
                      <option key={g.id_site_group} value={g.id_site_group}>{g.group_name}</option>
                    ))}
                  </select>
                </div>
              )}

              <Button size="sm" onClick={generate} loading={plays.isFetching && committed !== null}>
                {t('generate')}
              </Button>
              {/* Exports = reports:export (backend require_admin_or_permission) */}
              {committed && !isDemo && (
                <Can perm="reports:export">
                  <Button size="sm" variant="secondary" onClick={() => download('csv')} loading={downloading === 'csv'}>
                    <Download className="w-3.5 h-3.5 mr-1.5" />
                    {t('export_csv')}
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => download('pdf')} loading={downloading === 'pdf'}>
                    <FileText className="w-3.5 h-3.5 mr-1.5" />
                    {t('pop_export_pdf')}
                  </Button>
                </Can>
              )}
              {/* Purge = destructif → org-admin uniquement */}
              {mode === 'players' && players.length === 1 && (
                <Can admin>
                  <Button size="sm" variant="danger" onClick={onPurge} loading={purge.isPending}>
                    <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                    {t('pop_purge')}
                  </Button>
                </Can>
              )}
              {purgeMsg && <span className="text-xs text-gray-500 self-center">{purgeMsg}</span>}
            </div>

            {mode === 'players' && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs text-gray-500">{t('pop_scope_players')}</label>
                  <div className="flex gap-3 text-xs">
                    <button type="button" className="text-accent hover:underline"
                      onClick={() => setPlayers(playerList.map((p) => p.id_player))}>
                      {t('pop_select_all')}
                    </button>
                    <button type="button" className="text-gray-400 hover:underline" onClick={() => setPlayers([])}>
                      {t('pop_select_none')}
                    </button>
                  </div>
                </div>
                <div className="max-h-40 overflow-y-auto border border-gray-200 rounded-md p-2 grid grid-cols-2 sm:grid-cols-3 gap-1">
                  {playerList.map((p) => (
                    <label key={p.id_player} className="flex items-center gap-2 text-sm text-gray-700 px-1 py-0.5 rounded hover:bg-gray-50 cursor-pointer">
                      <input type="checkbox" checked={players.includes(p.id_player)} onChange={() => togglePlayer(p.id_player)} />
                      <span className="truncate">{p.player_name}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>

          {committed && (
            <div className="bg-surface rounded-lg border border-gray-200 overflow-hidden shadow-sf-card">
              <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50 text-xs text-gray-500">
                <span>{t('pop_total', { count: data?.total ?? 0 })}</span>
                {data && data.total > LIMIT && (
                  <div className="flex items-center gap-3">
                    <button disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
                      className="px-2 py-1 rounded border border-gray-200 disabled:opacity-40 hover:bg-gray-100">←</button>
                    <span>{t('pop_page', { page, pages: totalPages })}</span>
                    <button disabled={page >= totalPages} onClick={() => setOffset((o) => o + LIMIT)}
                      className="px-2 py-1 rounded border border-gray-200 disabled:opacity-40 hover:bg-gray-100">→</button>
                  </div>
                )}
              </div>
              {!data || data.rows.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400">
                  <ShieldCheck className="w-10 h-10" />
                  <p className="text-sm">{t('no_data')}</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr>
                        {['pop_col_player', 'pop_col_media', 'pop_col_played_at', 'pop_col_duration', 'pop_col_signed'].map((k) => (
                          <th key={k} className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
                            {t(k)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {aggregateDocRows(data.rows).map((r) => (
                        <tr key={r.id_pop} className="hover:bg-gray-50">
                          <td className="px-4 py-2.5 font-medium text-gray-800">{r.player_name ?? `#${r.id_player}`}</td>
                          <td className="px-4 py-2.5 text-gray-600">
                            {r.media_name ?? (r.id_media ? `#${r.id_media}` : '—')}
                            {r.pages > 1 && (
                              <span className="ml-2 inline-flex items-center rounded-md bg-accent/10 px-1.5 py-0.5 text-[11px] font-medium text-accent">
                                {t('pop_doc_pages', { count: r.pages })}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-gray-600">
                            {fmtDateTime(r.played_at)}
                            {r.screen_off && (
                              <span
                                title={t('pop_screen_off_hint')}
                                /* Valeurs de la branche sombre de `.badge-warning` (le CMS
                                   est dark only) : la rampe de gris est inversée, un
                                   `bg-orange-50` y serait un fond CLAIR illisible. */
                                className="ml-2 inline-flex items-center gap-1 rounded-md bg-orange-500/15 px-1.5 py-0.5 text-[11px] font-medium text-orange-300"
                              >
                                <MonitorOff className="w-3 h-3" /> {t('pop_screen_off')}
                              </span>
                            )}
                            {r.covered && (
                              <span
                                title={t('pop_covered_hint')}
                                /* Même traitement visuel que « écran coupé » — les deux
                                   disent « non comptée » — mais un libellé et une icône
                                   distincts : l'exploitant doit pouvoir dire LAQUELLE des
                                   deux causes s'applique, elles ne se corrigent pas pareil. */
                                className="ml-2 inline-flex items-center gap-1 rounded-md bg-orange-500/15 px-1.5 py-0.5 text-[11px] font-medium text-orange-300"
                              >
                                <Layers className="w-3 h-3" /> {t('pop_covered')}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-gray-600">{fmtDuration(Math.round(r.duration_ms / 1000))}</td>
                          <td className="px-4 py-2.5">
                            {r.signed ? (
                              <span className="inline-flex items-center gap-1 text-green-600 text-xs font-medium">
                                <Check className="w-3.5 h-3.5" /> {t('pop_signed_yes')}
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-red-500 text-xs font-medium">
                                <X className="w-3.5 h-3.5" /> {t('pop_signed_no')}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <ArchivesSection />
        </div>
      </main>
    </>
  )
}

interface PopArchiveRow {
  id_archive: number
  period_start: string
  period_end: string
  row_count: number
  merkle_root: string | null
  has_pdf: boolean
  bytes_csv: number | null
  players: unknown[]
  created_at: string
}
interface PopArchivesResponse {
  total: number
  rows: PopArchiveRow[]
}

function ArchivesSection() {
  const t = useTranslations('reports')
  const { data } = useQuery<PopArchivesResponse>({
    queryKey: ['pop-archives'],
    queryFn: () => api.get<PopArchivesResponse>('/pop/archives').then((r) => r.data),
  })
  const [verifyResult, setVerifyResult] = useState<Record<number, boolean>>({})
  const [busy, setBusy] = useState<number | null>(null)

  const download = async (id: number, kind: 'csv' | 'pdf') => {
    const { url } = (await api.get<{ url: string }>(`/pop/archives/${id}/download`, {
      params: { kind },
    })).data
    const a = document.createElement('a')
    a.href = url
    a.click()
  }
  const verify = async (id: number) => {
    setBusy(id)
    try {
      const res = (await api.post<{ ok: boolean }>(`/pop/archives/${id}/verify`)).data
      setVerifyResult((m) => ({ ...m, [id]: res.ok }))
    } finally {
      setBusy(null)
    }
  }

  const rows = data?.rows ?? []

  return (
    <div className="bg-surface rounded-lg border border-gray-200 p-5 space-y-4 shadow-sf-card">
      <div className="flex items-center gap-2">
        <Archive className="w-4 h-4 text-accent" />
        <h2 className="text-sm font-semibold text-gray-900">{t('pop_archives_title')}</h2>
      </div>
      <p className="text-xs text-gray-400">{t('pop_archives_hint')}</p>

      {rows.length === 0 ? (
        <p className="text-sm text-gray-400 py-6 text-center">{t('pop_arc_none')}</p>
      ) : (
        <div className="overflow-x-auto -mx-5">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {['pop_arc_period', 'pop_arc_rows', 'pop_arc_merkle', 'pop_arc_actions'].map((k) => (
                  <th key={k} className="px-5 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
                    {t(k)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {rows.map((a) => (
                <tr key={a.id_archive} className="hover:bg-gray-50">
                  <td className="px-5 py-2.5 font-medium text-gray-800 whitespace-nowrap">{a.period_start}</td>
                  <td className="px-5 py-2.5 text-gray-600">{a.row_count}</td>
                  <td className="px-5 py-2.5">
                    <code className="text-xs text-gray-400">{a.merkle_root ? `${a.merkle_root.slice(0, 16)}…` : '—'}</code>
                  </td>
                  <td className="px-5 py-2.5">
                    <div className="flex items-center gap-2">
                      <Can perm="reports:export">
                        <Button size="sm" variant="secondary" onClick={() => download(a.id_archive, 'csv')}>
                          <Download className="w-3.5 h-3.5 mr-1" />
                          {t('pop_arc_csv')}
                        </Button>
                        {a.has_pdf && (
                          <Button size="sm" variant="secondary" onClick={() => download(a.id_archive, 'pdf')}>
                            <FileText className="w-3.5 h-3.5 mr-1" />
                            {t('pop_arc_pdf')}
                          </Button>
                        )}
                      </Can>
                      <Button size="sm" variant="ghost" onClick={() => verify(a.id_archive)} loading={busy === a.id_archive}>
                        <ShieldCheck className="w-3.5 h-3.5 mr-1" />
                        {t('pop_arc_verify')}
                      </Button>
                      {a.id_archive in verifyResult && (
                        verifyResult[a.id_archive] ? (
                          <span className="inline-flex items-center gap-1 text-green-600 text-xs font-medium">
                            <Check className="w-3.5 h-3.5" /> {t('pop_arc_verified_ok')}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-red-500 text-xs font-medium">
                            <X className="w-3.5 h-3.5" /> {t('pop_arc_verified_ko')}
                          </span>
                        )
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
