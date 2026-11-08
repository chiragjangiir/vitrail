'use client'

import Image from 'next/image'
import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FileVideo, Music, FileImage, FileText, ExternalLink, Search, Check, XCircle, Minus, Trash2, ChevronDown, ChevronRight, ChevronLeft, X, Layers, Plus, RefreshCw, Upload, Download, MonitorPlay, Lock } from 'lucide-react'
import { clsx } from 'clsx'
import { useTranslations } from 'next-intl'
import Drawer from '@/components/ui/Drawer'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'
import type { MediaRead, IsrcLookupResult, TagNamespace, TagValue, RenditionRead, DocumentPagesResult } from '@/types/api'
import { indexTags, useTagNamespaces } from '@/components/tags/TagControls'
import NodeSelect, { useGovernanceNodes, useNodeName } from '@/components/governance/NodeSelect'
import { CHECK_KEYS, checkDetail, conformanceBadge, conformanceReport } from '@/lib/mediaConformance'
import { downloadMedia, isMediaDownloadable } from '@/lib/mediaDownload'
import QuarantineSection from './QuarantineSection'
import EncodeProgressBar from './EncodeProgressBar'
import EncodeDecisionPanel from './EncodeDecisionPanel'
import { useAuthStore } from '@/store/auth'

interface MediaDrawerProps {
  mediaId: number | null
  onClose: () => void
}

function formatSize(bytes: number | null) {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(ms: number | null) {
  if (!ms) return null
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`
}

// ── Section repliable (drawer compact) ────────────────────────────────────────
function CollapsibleSection({
  title, badge, defaultOpen = false, children,
}: {
  title: React.ReactNode
  badge?: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-t border-gray-100 pt-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between w-full gap-2"
      >
        <span className="flex items-center gap-1.5 text-xs font-medium text-gray-500 uppercase tracking-wide">
          {open ? <ChevronDown className="w-3.5 h-3.5 text-gray-400" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400" />}
          {title}
        </span>
        {badge}
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  )
}


// ── Où ce média est-il utilisé, et sur quels écrans passe-t-il ? ──────────────
//
// Demande d'Ed (audit du menu Média, 2026-07-28) : « il faudrait que quand on sélectionne
// ou survole un média, on sache dans quelle playlist, programme il est utilisé et SURTOUT
// actif sur un ou des écrans ». Le compte d'écrans vient du service de ciblage canonique
// côté serveur — une cible « site » ou « groupe » résout donc bien ses écrans.
interface MediaUsage {
  playlists: { id_playlist: number; playlist_name: string; items_using: number; broadcast: string }[]
  schedules: { id_schedule: number; schedule_name: string | null; broadcast: string | null }[]
  events: { id_event: number; event_name: string | null }[]
  screens: { id_player: number; player_name: string; site_name: string | null; status: string; via: string[] }[]
  summary: { playlists: number; schedules: number; events: number; screens: number; is_live: boolean }
}

function UsageSection({ idMedia, t }: { idMedia: number; t: ReturnType<typeof useTranslations> }) {
  const { data } = useQuery<MediaUsage>({
    queryKey: ['media-usage', idMedia],
    queryFn: () => api.get<MediaUsage>(`/media/${idMedia}/usage`).then((r) => r.data),
  })
  const s = data?.summary

  return (
    <CollapsibleSection
      title={t('usage_title')}
      defaultOpen
      badge={
        s ? (
          <span
            className={`text-[11px] font-medium px-1.5 py-0.5 rounded ${
              s.screens > 0
                ? 'text-success bg-green-500/10'
                : 'text-gray-500 bg-white/5'
            }`}
          >
            {s.screens > 0 ? t('usage_on_screens', { n: s.screens }) : t('usage_not_broadcast')}
          </span>
        ) : undefined
      }
    >
      {!data ? (
        <p className="text-xs text-gray-400">…</p>
      ) : s && s.playlists === 0 && s.events === 0 ? (
        <p className="text-xs text-gray-500">{t('usage_unused')}</p>
      ) : (
        <div className="space-y-3">
          {data.playlists.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('usage_playlists')}</p>
              <ul className="space-y-1">
                {data.playlists.map((p) => (
                  <li key={p.id_playlist} className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate text-gray-800">{p.playlist_name}</span>
                    <span className="shrink-0 text-gray-500">
                      {t('usage_times', { n: p.items_using })}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.schedules.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('usage_schedules')}</p>
              <ul className="space-y-1">
                {data.schedules.map((sc) => (
                  <li key={sc.id_schedule} className="truncate text-xs text-gray-800">
                    {sc.schedule_name ?? `#${sc.id_schedule}`}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.events.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('usage_events')}</p>
              <ul className="space-y-1">
                {data.events.map((e) => (
                  <li key={e.id_event} className="truncate text-xs text-gray-800">
                    {e.event_name ?? `#${e.id_event}`}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Le point qui compte : les écrans, NOMMÉS et avec leur statut réel — « actif
              sur 3 écrans » sans dire lesquels ne permet de corriger rien du tout. */}
          <div>
            <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('usage_screens')}</p>
            {data.screens.length === 0 ? (
              <p className="text-xs text-gray-500">{t('usage_no_screen')}</p>
            ) : (
              <ul className="space-y-1">
                {data.screens.map((sc) => (
                  <li key={sc.id_player} className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate text-gray-800">
                      {sc.player_name}
                      {sc.site_name && <span className="text-gray-500"> · {sc.site_name}</span>}
                    </span>
                    <span
                      className={`shrink-0 w-1.5 h-1.5 rounded-full ${
                        sc.status === 'online' ? 'bg-success'
                          : sc.status === 'warning' ? 'bg-warning' : 'bg-gray-500'
                      }`}
                      title={sc.status}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </CollapsibleSection>
  )
}

function tagBadgeStyle(color: string | null): React.CSSProperties {
  if (!color) return {}
  return { backgroundColor: `${color}1A`, color, borderColor: `${color}55` }
}

/** Un namespace s'applique au média si applies_to est vide (= tous) ou contient son type. */
function appliesToType(ns: TagNamespace, mediaType: string) {
  return !ns.applies_to || ns.applies_to.length === 0 || ns.applies_to.includes(mediaType)
}

// ── Tags & filtrage (§XVII) — dropdown + pastilles, filtré par type de média ──────
function TagsSection({ media, t }: { media: MediaRead; t: ReturnType<typeof useTranslations> }) {
  const qc = useQueryClient()
  const { data: namespaces = [] } = useTagNamespaces()
  const { data: current = [] } = useQuery<number[]>({
    queryKey: ['media-tags', media.id_media],
    queryFn: () => api.get<number[]>(`/media/${media.id_media}/tags`).then((r) => r.data),
  })
  const [sel, setSel] = useState<Set<number> | null>(null)
  const selected = sel ?? new Set(current)

  const save = useMutation({
    mutationFn: (ids: number[]) => api.put(`/media/${media.id_media}/tags`, { id_tags: ids }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['media-tags', media.id_media] })
      qc.invalidateQueries({ queryKey: ['media'] })
      setSel(null)
    },
  })

  const add = (id: number) => { const next = new Set(selected); next.add(id); setSel(next) }
  const remove = (id: number) => { const next = new Set(selected); next.delete(id); setSel(next) }
  const dirty = sel !== null && (sel.size !== current.length || Array.from(sel).some((id) => !current.includes(id)))

  const idx = indexTags(namespaces)
  // Namespaces applicables au type du média (alimente la liste déroulante filtrée).
  const applicable = namespaces.filter(
    (ns) => ns.is_active && ns.values.length > 0 && appliesToType(ns, media.media_type),
  )
  const selectedResolved = Array.from(selected)
    .map((id) => idx.get(id))
    .filter(Boolean) as { value: TagValue; ns: TagNamespace }[]

  return (
    <div className="space-y-3">
      {/* Pastilles des tags sélectionnés uniquement */}
      {selectedResolved.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {selectedResolved.map(({ value }) => (
            <span
              key={value.id_tag}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border bg-gray-100 text-gray-600 border-gray-200"
              style={tagBadgeStyle(value.color)}
            >
              {value.label ?? value.tag_value}
              <button
                type="button"
                data-write-action
                onClick={() => remove(value.id_tag)}
                className="hover:opacity-70"
                aria-label={t('tags_clear')}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-400">{t('tags_none_selected')}</p>
      )}

      {/* Liste déroulante : ajouter un tag existant (filtré par type) */}
      {applicable.length > 0 ? (
        <select
          value=""
          onChange={(e) => { const id = Number(e.target.value); if (id) add(id) }}
          className="w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
        >
          <option value="">{t('tags_add_placeholder')}</option>
          {applicable.map((ns) => {
            const opts = ns.values.filter((v) => !selected.has(v.id_tag))
            if (opts.length === 0) return null
            return (
              <optgroup key={ns.id_namespace} label={ns.label ?? ns.namespace_key}>
                {opts.map((v) => (
                  <option key={v.id_tag} value={v.id_tag}>{v.label ?? v.tag_value}</option>
                ))}
              </optgroup>
            )
          })}
        </select>
      ) : (
        <p className="text-xs text-gray-400">{t('tags_empty')}</p>
      )}

      {dirty && (
        <button
          data-write-action
          onClick={() => save.mutate(Array.from(selected))}
          disabled={save.isPending}
          className="w-full py-1.5 bg-accent text-white text-sm rounded-md hover:bg-accent/90 disabled:opacity-50"
        >
          {save.isPending ? t('tags_saving') : t('tags_save')}
        </button>
      )}
    </div>
  )
}

// ── Droits d'auteur SACEM (§XIX.6) — section éditable, audio uniquement ───────────
function RightsSection({ media, t }: { media: MediaRead; t: ReturnType<typeof useTranslations> }) {
  const qc = useQueryClient()
  const meta = (media.rights_metadata ?? {}) as Record<string, unknown>
  const [isrc, setIsrc] = useState(media.isrc ?? '')
  const [composer, setComposer] = useState((meta.composer as string) ?? '')
  const [publisher, setPublisher] = useState((meta.publisher as string) ?? '')
  const [rightsOrg, setRightsOrg] = useState((meta.rights_org as string) ?? '')
  const [album, setAlbum] = useState((meta.album as string) ?? '')
  const [year, setYear] = useState(meta.year != null ? String(meta.year) : '')
  const [cleared, setCleared] = useState(Boolean(meta.rights_cleared))
  const [error, setError] = useState<string | null>(null)
  const [lookupMsg, setLookupMsg] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/media/${media.id_media}/rights`, {
        isrc: isrc.trim() || null,
        rights_metadata: {
          ...(composer.trim() && { composer: composer.trim() }),
          ...(publisher.trim() && { publisher: publisher.trim() }),
          ...(rightsOrg.trim() && { rights_org: rightsOrg.trim() }),
          ...(album.trim() && { album: album.trim() }),
          ...(year.trim() && !isNaN(Number(year)) && { year: Number(year) }),
          ...(cleared && { rights_cleared: true }),
        },
      }),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['media', media.id_media] })
      qc.invalidateQueries({ queryKey: ['media'] })
    },
    onError: () => setError(t('rights_save_error')),
  })

  const lookup = useMutation({
    mutationFn: () =>
      api.get<IsrcLookupResult>('/media/isrc-lookup', { params: { isrc: isrc.trim() } }).then((r) => r.data),
    onSuccess: (res) => {
      if (!res.found) { setLookupMsg(t('rights_lookup_none')); return }
      if (res.composer) setComposer(res.composer)
      if (res.album) setAlbum(res.album)
      if (res.year) setYear(String(res.year))
      setLookupMsg(t('rights_lookup_ok'))
    },
    onError: () => setLookupMsg(t('rights_lookup_none')),
  })

  const field = 'w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40'

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-gray-400 mb-1">{t('rights_isrc')}</label>
        <div className="flex gap-2">
          <input value={isrc} onChange={(e) => setIsrc(e.target.value)} placeholder="FR-Z03-26-00001" className={field} />
          <button
            type="button"
            onClick={() => { setLookupMsg(null); lookup.mutate() }}
            disabled={!isrc.trim() || lookup.isPending}
            title={t('rights_lookup')}
            className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-md border border-accent/30 text-accent hover:bg-accent/5 disabled:opacity-40"
          >
            <Search className="w-3.5 h-3.5" />{t('rights_lookup')}
          </button>
        </div>
        {lookupMsg && <p className="text-xs text-gray-400 mt-1">{lookupMsg}</p>}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs text-gray-400 mb-1">{t('rights_composer')}</label>
          <input value={composer} onChange={(e) => setComposer(e.target.value)} className={field} />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">{t('rights_publisher')}</label>
          <input value={publisher} onChange={(e) => setPublisher(e.target.value)} className={field} />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">{t('rights_org')}</label>
          <select value={rightsOrg} onChange={(e) => setRightsOrg(e.target.value)} className={field}>
            <option value="">—</option>
            {['SACEM', 'SOCAN', 'ASCAP', 'BMI', 'PRS', 'GEMA', 'SIAE', 'other'].map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">{t('rights_year')}</label>
          <input value={year} onChange={(e) => setYear(e.target.value)} inputMode="numeric" className={field} />
        </div>
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1">{t('rights_album')}</label>
        <input value={album} onChange={(e) => setAlbum(e.target.value)} className={field} />
      </div>

      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={cleared} onChange={(e) => setCleared(e.target.checked)} className="accent-accent" />
        <span className="text-xs text-gray-700">{t('rights_cleared')}</span>
      </label>

      {error && <p className="text-xs text-danger">{error}</p>}
      <button
        data-write-action
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="w-full inline-flex items-center justify-center gap-1.5 py-1.5 bg-accent text-white text-sm rounded-md hover:bg-accent/90 disabled:opacity-50"
      >
        {save.isSuccess && !save.isPending ? <Check className="w-4 h-4" /> : null}
        {save.isPending ? t('rights_saving') : t('rights_save')}
      </button>
    </div>
  )
}

// ── Renommage du média (libellé, pas le fichier) ─────────────────────────────────
function RenameSection({ media, t }: { media: MediaRead; t: ReturnType<typeof useTranslations> }) {
  const qc = useQueryClient()
  const [name, setName] = useState(media.media_name)
  const save = useMutation({
    mutationFn: () => api.patch(`/media/${media.id_media}/rename`, { media_name: name.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['media', media.id_media] })
      qc.invalidateQueries({ queryKey: ['media'] })
    },
  })
  const dirty = !!name.trim() && name.trim() !== media.media_name
  return (
    <div>
      <label className="mb-1 block text-xs text-gray-400">{t('rename_label')}</label>
      <div className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && dirty) save.mutate() }}
          className="flex-1 rounded-lg border border-gray-200 bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
        />
        <button
          type="button"
          data-write-action
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate()}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-gray-200 text-xs font-medium text-gray-700 hover:border-accent hover:text-accent transition-sf disabled:opacity-50"
        >
          {save.isSuccess && !dirty ? <Check className="w-3.5 h-3.5" /> : null}{t('rename_save')}
        </button>
      </div>
    </div>
  )
}

// ── Gouvernance §XVIII contenu (D9) — nœud propriétaire du média ─────────────────
// Un média rattaché à un nœud n'est modifiable NI SUPPRIMABLE que par un administrateur
// de ce nœud ou d'un ancêtre : un responsable local ne touche pas un visuel national.
// Rien ne s'affiche si l'org n'a aucun nœud de gouvernance.
function GovernanceSection({ media }: { media: MediaRead }) {
  const qc = useQueryClient()
  const tg = useTranslations('governance')
  const { data: nodes = [] } = useGovernanceNodes()
  const nodeName = useNodeName(media.id_governance_node)
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: (id_governance_node: number | null) =>
      api.patch(`/media/${media.id_media}/governance-node`, { id_governance_node }),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['media', media.id_media] })
      qc.invalidateQueries({ queryKey: ['media'] })
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : tg('content_node_error'))
    },
  })

  if (nodes.length === 0) return null

  return (
    // Section titrée comme les autres blocs du drawer : posée « nue » elle semblait
    // appartenir à la section Tags qui la précède. Ouverte par défaut sur un contenu
    // gouverné (le bandeau lecture seule doit se voir sans avoir à déplier).
    <CollapsibleSection
      title={tg('content_card_title')}
      defaultOpen={media.id_governance_node != null}
      badge={media.governed_readonly
        ? <Lock className="w-3.5 h-3.5 text-gray-400" />
        : media.id_governance_node != null
          ? <span className="text-xs text-gray-400">{nodeName ?? ''}</span>
          : undefined}
    >
      <div className="space-y-2">
        {media.governed_readonly && (
          <p className="flex items-center gap-1.5 text-xs text-gray-500">
            <Lock className="w-3.5 h-3.5 shrink-0" />
            {tg('content_readonly_banner', { node: nodeName ?? '—' })}
          </p>
        )}
        <NodeSelect
          value={media.id_governance_node ?? null}
          onChange={(id) => save.mutate(id)}
          disabled={media.governed_readonly || save.isPending}
        />
        {error && <p className="text-xs text-danger">{error}</p>}
      </div>
    </CollapsibleSection>
  )
}

// ── Conformité & sync-readiness (§XVI.2) — section éditable, vidéo uniquement ─────
function ConformanceSection({ media, t }: { media: MediaRead; t: ReturnType<typeof useTranslations> }) {
  const qc = useQueryClient()
  const report = conformanceReport(media)
  const status = media.conformance_status
  const nonReady = status === 'playable' || status === 'nonconform'
  const [ack, setAck] = useState(false)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['media', media.id_media] })
    qc.invalidateQueries({ queryKey: ['media'] })
  }
  const setMode = useMutation({
    mutationFn: (mode: 'auto' | 'passthrough') =>
      api.patch(`/media/${media.id_media}/encode-mode`, { encode_mode: mode }),
    onSuccess: invalidate,
  })
  const reanalyze = useMutation({
    mutationFn: () => api.post(`/media/${media.id_media}/reanalyze`),
    onSuccess: invalidate,
  })
  const acknowledge = useMutation({
    mutationFn: () => api.post(`/media/${media.id_media}/passthrough-ack`, {}),
  })

  const statusLabel = status ? t(`conf_status_${status}`) : t('conf_status_unknown')

  return (
    <div className="space-y-3">
      {/* Mode d'encodage */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">{t('conf_mode')}</span>
        <div className="inline-flex rounded-md border border-gray-200 overflow-hidden text-xs">
          {(['auto', 'passthrough'] as const).map((mode) => (
            <button
              key={mode}
              data-write-action
              onClick={() => media.encode_mode !== mode && setMode.mutate(mode)}
              disabled={setMode.isPending}
              className={clsx(
                'px-2.5 py-1 disabled:opacity-50',
                media.encode_mode === mode ? 'bg-accent text-white' : 'text-gray-600 hover:bg-gray-50',
              )}
            >
              {t(`conf_mode_${mode}`)}
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs text-gray-400">
        {media.encode_mode === 'passthrough' ? t('conf_mode_passthrough_hint') : t('conf_mode_auto_hint')}
      </p>

      {/* Verdict + ré-analyse */}
      <div className="flex items-center justify-between">
        <StatusBadge status={conformanceBadge(status)} label={statusLabel} />
        <button
          data-write-action
          onClick={() => reanalyze.mutate()}
          disabled={reanalyze.isPending}
          className="text-xs text-accent hover:underline disabled:opacity-50"
        >
          {reanalyze.isPending ? t('conf_reanalyzing') : t('conf_reanalyze')}
        </button>
      </div>

      {/* Rapport des checks (localisé) */}
      {report?.checks && (
        <div className="rounded-md bg-gray-50 px-3 py-2 text-xs space-y-1">
          {CHECK_KEYS.map((k) => {
            const c = report.checks?.[k]
            if (!c) return null
            const detail = checkDetail(k, c)
            return (
              <div key={k} className="flex items-center gap-1.5">
                {c.ok === true ? (
                  <Check className="w-3 h-3 text-success shrink-0" />
                ) : c.ok === false ? (
                  <XCircle className="w-3 h-3 text-danger shrink-0" />
                ) : (
                  <Minus className="w-3 h-3 text-gray-300 shrink-0" />
                )}
                <span className="text-gray-600">{t(`conf_check_${k}`)}</span>
                {detail && <span className="text-gray-400">— {detail}</span>}
              </div>
            )
          })}
        </div>
      )}

      {/* Acquittement si non sync-ready */}
      {nonReady &&
        (acknowledge.isSuccess ? (
          <p className="text-xs text-success inline-flex items-center gap-1">
            <Check className="w-3.5 h-3.5" />
            {t('conf_ack_done')}
          </p>
        ) : (
          <div className="rounded-md border border-orange-200 dark:border-orange-500/30 bg-orange-500/15 dark:bg-orange-500/15 px-3 py-2 space-y-2">
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={ack}
                onChange={(e) => setAck(e.target.checked)}
                className="accent-accent mt-0.5"
              />
              <span className="text-xs text-gray-700">{t('conf_ack_label')}</span>
            </label>
            <button
              data-write-action
              onClick={() => acknowledge.mutate()}
              disabled={!ack || acknowledge.isPending}
              className="w-full py-1.5 bg-accent text-white text-xs rounded-md hover:bg-accent/90 disabled:opacity-40"
            >
              {t('conf_ack_confirm')}
            </button>
          </div>
        ))}
    </div>
  )
}

// ── Renditions adaptatives (« artefacts » vidéo) ──────────────────────────────
const RENDITION_PROFILES = [
  { key: 'fhd', label: 'FHD 1080p', box: 1920 },
  { key: 'hd720', label: 'HD 720p', box: 1280 },
]

function renditionBadge(status: RenditionRead['status']) {
  return ({ ready: 'done', failed: 'error', processing: 'processing', pending: 'pending' } as const)[status]
}

function RenditionsSection({ media, t }: { media: MediaRead; t: ReturnType<typeof useTranslations> }) {
  const qc = useQueryClient()
  const { data: rends = [] } = useQuery<RenditionRead[]>({
    queryKey: ['media-renditions', media.id_media],
    queryFn: () => api.get<RenditionRead[]>(`/media/${media.id_media}/renditions`).then((r) => r.data),
    // Rafraîchit pendant l'encodage (pending/processing → ready/failed).
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => r.status === 'pending' || r.status === 'processing') ? 4000 : false,
  })
  const gen = useMutation({
    mutationFn: (profile: string) => api.post(`/media/${media.id_media}/renditions`, { profile }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['media-renditions', media.id_media] })
      qc.invalidateQueries({ queryKey: ['media'] })
    },
  })
  const del = useMutation({
    mutationFn: (id: number) => api.delete(`/media/${media.id_media}/renditions/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['media-renditions', media.id_media] })
      qc.invalidateQueries({ queryKey: ['media'] })
    },
  })

  const srcMax = Math.max(media.width ?? 0, media.height ?? 0)
  const byProfile = new Map(rends.map((r) => [r.profile, r]))

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">{t('renditions_hint')}</p>
      {rends.length > 0 && (
        <div className="space-y-1.5">
          {rends.map((r) => (
            <div key={r.id_rendition} className="flex items-center justify-between gap-2 rounded-md bg-gray-50 px-3 py-2 text-xs">
              <span className="flex items-center gap-2">
                <Layers className="w-3.5 h-3.5 text-accent" />
                <span className="font-medium text-gray-700 uppercase">{r.profile}</span>
                <span className="text-gray-400">
                  {r.width && r.height ? `${r.width}×${r.height}` : '—'}
                  {r.codec ? ` · ${r.codec.toUpperCase()}` : ''}
                  {r.file_size_bytes ? ` · ${formatSize(r.file_size_bytes)}` : ''}
                </span>
              </span>
              <span className="flex items-center gap-2">
                <StatusBadge status={renditionBadge(r.status)} label={t(`renditions_status_${r.status}`)} />
                <button
                  data-write-action
                  onClick={() => del.mutate(r.id_rendition)}
                  disabled={del.isPending}
                  className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10"
                  title={t('renditions_delete')}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </span>
            </div>
          ))}
        </div>
      )}
      {rends.some((r) => r.status === 'failed' && r.error_detail) && (
        <p className="text-xs text-danger truncate" title={rends.find((r) => r.status === 'failed')?.error_detail ?? ''}>
          {rends.find((r) => r.status === 'failed')?.error_detail}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {RENDITION_PROFILES.map((p) => {
          const existing = byProfile.get(p.key)
          const tooSmall = srcMax > 0 && srcMax <= p.box
          const busy = gen.isPending || existing?.status === 'pending' || existing?.status === 'processing'
          return (
            <button
              key={p.key}
              data-write-action
              onClick={() => gen.mutate(p.key)}
              disabled={busy || tooSmall}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-gray-200 text-xs font-medium text-gray-600 hover:border-accent hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed"
              title={tooSmall ? t('renditions_too_small') : undefined}
            >
              {existing ? <RefreshCw className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
              {existing ? t('renditions_regenerate', { profile: p.label }) : t('renditions_generate', { profile: p.label })}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Remplacer le fichier (même id_media, garde les références playlists/programmes) ──
function ReplaceSection({ media, t }: { media: MediaRead; t: ReturnType<typeof useTranslations> }) {
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const replace = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.post<MediaRead>(`/media/${media.id_media}/replace`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: ({ loaded, total }) =>
          setProgress(total ? Math.round((loaded / total) * 100) : 0),
      })
    },
    onSuccess: () => {
      setProgress(null)
      setError(null)
      qc.invalidateQueries({ queryKey: ['media', media.id_media] })
      qc.invalidateQueries({ queryKey: ['media'] })
      qc.invalidateQueries({ queryKey: ['media-renditions', media.id_media] })
    },
    onError: (err: unknown) => {
      setProgress(null)
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? t('replace_error'))
    },
  })

  const busy = replace.isPending || progress !== null

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">{t('replace_hint')}</p>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) { setError(null); setProgress(0); replace.mutate(file) }
          e.target.value = ''
        }}
      />
      <button
        type="button"
        data-write-action
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="w-full inline-flex items-center justify-center gap-1.5 py-1.5 rounded-md border border-gray-200 text-sm text-gray-700 hover:border-accent hover:text-accent disabled:opacity-50 transition-sf"
      >
        <Upload className="w-4 h-4" />
        {busy ? t('replace_uploading', { pct: progress ?? 0 }) : t('replace_action')}
      </button>
      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  )
}

// ── Visionneuse de pages (documents multipages §3.2) ─────────────────────────────
function DocumentPagesViewer({ media, t }: { media: MediaRead; t: ReturnType<typeof useTranslations> }) {
  const [page, setPage] = useState(0)
  const { data } = useQuery<DocumentPagesResult>({
    queryKey: ['media-pages', media.id_media],
    queryFn: () => api.get<DocumentPagesResult>(`/media/${media.id_media}/pages`).then((r) => r.data),
    staleTime: 30_000,
  })
  const pages = data?.pages ?? []
  if (pages.length === 0) {
    return (
      <div className="aspect-video bg-gray-50 rounded-lg flex flex-col items-center justify-center gap-2 text-gray-400">
        <FileText className="w-10 h-10 text-gray-300" />
        {media.transcode_status !== 'done' && (
          <p className="text-xs">{t('doc_converting')}</p>
        )}
      </div>
    )
  }
  const current = pages[Math.min(page, pages.length - 1)]
  return (
    <div className="space-y-2">
      <div className="aspect-video bg-gray-50 rounded-lg overflow-hidden relative">
        <Image src={current.url} alt={`${media.media_name} — ${current.page}`} fill className="object-contain" unoptimized />
      </div>
      <div className="flex items-center justify-center gap-3 text-xs text-gray-500">
        <button
          type="button"
          onClick={() => setPage((p) => Math.max(0, p - 1))}
          disabled={page <= 0}
          className="p-1 rounded hover:bg-gray-100 disabled:opacity-30"
          aria-label={t('doc_prev_page')}
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span>{t('doc_page_of', { page: current.page, total: pages.length })}</span>
        <button
          type="button"
          onClick={() => setPage((p) => Math.min(pages.length - 1, p + 1))}
          disabled={page >= pages.length - 1}
          className="p-1 rounded hover:bg-gray-100 disabled:opacity-30"
          aria-label={t('doc_next_page')}
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
      {data?.truncated && <p className="text-xs text-orange-500 text-center">{t('doc_truncated')}</p>}
    </div>
  )
}

export default function MediaDrawer({ mediaId, onClose }: MediaDrawerProps) {
  const t = useTranslations('media')

  const { data } = useQuery<MediaRead>({
    queryKey: ['media', mediaId],
    queryFn: () => api.get<MediaRead>(`/media/${mediaId}`).then((r) => r.data),
    enabled: mediaId !== null,
    staleTime: 30_000,
    // 🔴 Le tiroir ne se rafraîchissait JAMAIS : il chargeait une fois à l'ouverture et
    // restait figé. Or il s'ouvre le plus souvent JUSTE APRÈS un upload — le média y
    // restait donc « en cours » avec une barre à 0 % pendant tout l'encodage, pendant que
    // la grille derrière lui, elle, avançait et passait à « prêt » (constat d'Ed,
    // 2026-08-03). Il fallait fermer puis rouvrir pour voir la vérité.
    // Cadence plus rapide que la liste (2 s contre 5) : on regarde UN média de près,
    // et le worker publie son avancement toutes les ~1,5 s.
    // ⛔ On ne sonde pas `awaiting_decision` : rien ne changera sans un geste humain,
    // interroger le serveur en boucle pour un état stable ne renseignerait personne.
    refetchInterval: (q) => {
      const st = (q.state.data as MediaRead | undefined)?.transcode_status
      return st === 'pending' || st === 'processing' ? 2000 : false
    },
  })

  // Bande haute (> 4 h) : seul un org-admin peut passer outre — engager la machine
  // aussi longtemps est une décision d'exploitation, pas une édition de média.
  const hasRole = useAuthStore((s) => s.hasRole)
  const isOrgAdmin = hasRole('CMS_ORG_ADMIN') || hasRole('CMS_SUPER_ADMIN')

  const transcodeStatus = data
    ? ({ pending: 'pending', processing: 'processing', done: 'done', error: 'error',
         awaiting_decision: 'warning' } as const)[data.transcode_status] ?? 'info'
    : 'pending'

  const statusLabel = data
    ? (({ pending: t('status_pending'), processing: t('status_processing'), done: t('status_done'),
          error: t('status_error'), awaiting_decision: t('status_awaiting_decision') } as const)[data.transcode_status] ?? data.transcode_status)
    : ''

  // Infos du fichier RÉELLEMENT SERVI (après ré-encodage) plutôt que de l'upload original : la
  // taille (metadata.size_bytes) et la résolution viennent du flux transcodé ; repli sur les
  // colonnes d'upload (file_size_bytes / width / height) si le probe n'a pas (encore) tourné.
  const mm = (data?.media_metadata ?? null) as
    | { size_bytes?: number; video?: { width?: number; height?: number } }
    | null
  const servedSize = mm?.size_bytes ?? data?.file_size_bytes ?? null
  const servedW = mm?.video?.width ?? data?.width
  const servedH = mm?.video?.height ?? data?.height

  return (
    <Drawer open={mediaId !== null} onClose={onClose} title={data?.media_name ?? '…'}>
      {data ? (
        // `data-write-locked` (gouvernance §XVIII D9) : média d'un nœud non administré —
        // la permission media:edit est là, mais le serveur refuse toute mutation.
        <div
          className="space-y-5"
          data-write-perm="media:edit"
          {...(data.governed_readonly ? { 'data-write-locked': '1' } : {})}
        >
          {/* Preview — document multipage : visionneuse de pages (le PDF brut ne se
              prévisualise pas en <img>) */}
          {data.media_type === 'document' ? (
            <DocumentPagesViewer media={data} t={t} />
          ) : (
          <div className="aspect-video bg-gray-50 rounded-lg overflow-hidden flex items-center justify-center relative">
            {data.transcode_status === 'done' && data.cdn_url_signed ? (
              data.media_type === 'video' ? (
                <video
                  src={data.cdn_url_signed}
                  controls
                  className="w-full h-full object-contain"
                />
              ) : data.media_type === 'audio' ? (
                <div className="flex flex-col items-center gap-3">
                  <Music className="w-10 h-10 text-gray-300" />
                  <audio src={data.cdn_url_signed} controls className="w-full" />
                </div>
              ) : (
                <Image
                  src={data.cdn_url_signed}
                  alt={data.media_name}
                  fill
                  className="object-contain"
                  unoptimized
                />
              )
            ) : data.thumbnail_url ? (
              <Image src={data.thumbnail_url} alt={data.media_name} fill className="object-contain" unoptimized />
            ) : data.media_type === 'video' ? (
              <FileVideo className="w-10 h-10 text-gray-300" />
            ) : data.media_type === 'audio' ? (
              <Music className="w-10 h-10 text-gray-300" />
            ) : data.media_type === 'hdmi_input' ? (
              <MonitorPlay className="w-10 h-10 text-accent/60" />
            ) : (
              <FileImage className="w-10 h-10 text-gray-300" />
            )}
          </div>
          )}

          {/* Metadata */}
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <StatusBadge status={transcodeStatus} label={statusLabel} />
              {isMediaDownloadable(data.media_type) && (
                <button
                  type="button"
                  onClick={() => void downloadMedia(data.id_media)}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-gray-200 text-xs font-medium text-gray-700 hover:border-accent hover:text-accent transition-sf"
                >
                  <Download className="w-3.5 h-3.5" />
                  {t('download')}
                </button>
              )}
            </div>

            {/* Étalonnage : l'encodage a été mesuré trop long, rien ne part sans un geste.
                Le panneau propose la sortie (définition inférieure) autant que le refus. */}
            {data.transcode_status === 'awaiting_decision' && data.encode_decision && (
              <EncodeDecisionPanel
                idMedia={data.id_media}
                decision={data.encode_decision}
                isOrgAdmin={isOrgAdmin}
              />
            )}

            {/* Vue la plus détaillée : barre + phase + temps restant + vitesse constatée.
                La vitesse a une vraie valeur de diagnostic — elle chute quand plusieurs
                encodages se disputent la machine, ce qui explique un temps qui s'allonge. */}
            {data.encode_progress && (
              <div className="rounded-lg border border-white/5 bg-surface-hover/40 p-3">
                <EncodeProgressBar progress={data.encode_progress} />
                {typeof data.encode_progress.speed === 'number' && (
                  <p className="mt-2 text-[11px] text-gray-500">
                    {t('enc_speed', { speed: data.encode_progress.speed.toFixed(2) })}
                  </p>
                )}
              </div>
            )}

            <RenameSection key={data.id_media} media={data} t={t} />

            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div>
                <dt className="text-xs text-gray-400">{t('meta_type')}</dt>
                <dd className="font-medium text-gray-800 capitalize">{data.media_type}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">{t('meta_size')}</dt>
                <dd className="font-medium text-gray-800">{formatSize(servedSize)}</dd>
              </div>
              {servedW && servedH && (
                <div>
                  <dt className="text-xs text-gray-400">{t('meta_resolution')}</dt>
                  <dd className="font-medium text-gray-800">{servedW}×{servedH}</dd>
                </div>
              )}
              {data.duration_ms && (
                <div>
                  <dt className="text-xs text-gray-400">{t('meta_duration')}</dt>
                  <dd className="font-medium text-gray-800">{formatDuration(data.duration_ms)}</dd>
                </div>
              )}
              {data.media_type === 'document' && (data.page_count ?? 0) > 0 && (
                <div>
                  <dt className="text-xs text-gray-400">{t('meta_pages')}</dt>
                  <dd className="font-medium text-gray-800">{data.page_count}</dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-gray-400">{t('meta_source')}</dt>
                <dd className="font-medium text-gray-800 capitalize">{data.source}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">{t('meta_added')}</dt>
                <dd className="font-medium text-gray-800">
                  {new Date(data.created_at).toLocaleDateString()}
                </dd>
              </div>
            </dl>

            {/* Infos techniques (§6) — état réellement diffusé (après ré-encodage).
                Masqué pour les médias pointeurs sans fichier (hdmi_input : metadata non technique). */}
            {data.media_type !== 'hdmi_input' && data.media_metadata && Object.keys(data.media_metadata).length > 0 && (
            <CollapsibleSection title={t('technical')}>
            {(() => {
              const m = data.media_metadata as {
                container?: string
                video?: { codec?: string; profile?: string; width?: number; height?: number; fps?: number; bitrate_kbps?: number; hdr?: boolean }
                audio?: { codec?: string; channels?: number; channel_layout?: string; sample_rate?: number; bitrate_kbps?: number; language?: string }
                subtitles?: { lang?: string; label?: string }[]
              }
              const join = (parts: (string | number | null | undefined | false)[]) => parts.filter(Boolean).join(' · ')
              return (
                <div className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-500 space-y-1">
                  {m.video && (
                    <p><span className="text-gray-400">{t('tech_video')}: </span>{join([
                      m.video.codec?.toUpperCase(), m.video.profile,
                      m.video.width && m.video.height ? `${m.video.width}×${m.video.height}` : null,
                      m.video.fps ? `${m.video.fps} fps` : null,
                      m.video.bitrate_kbps ? `${m.video.bitrate_kbps} kbps` : null,
                      m.video.hdr ? 'HDR' : 'SDR'])}</p>
                  )}
                  {m.audio && (
                    <p><span className="text-gray-400">{t('tech_audio')}: </span>{join([
                      m.audio.codec?.toUpperCase(),
                      m.audio.channel_layout || (m.audio.channels ? `${m.audio.channels}ch` : null),
                      m.audio.sample_rate ? `${Math.round(m.audio.sample_rate / 1000)} kHz` : null,
                      m.audio.bitrate_kbps ? `${m.audio.bitrate_kbps} kbps` : null,
                      m.audio.language])}</p>
                  )}
                  {m.subtitles && m.subtitles.length > 0 && (
                    <p><span className="text-gray-400">{t('tech_subtitles')}: </span>{m.subtitles.map((s) => s.label || s.lang || '?').join(', ')}</p>
                  )}
                  {m.container && (
                    <p><span className="text-gray-400">{t('tech_container')}: </span>{m.container}</p>
                  )}
                </div>
              )
            })()}
            </CollapsibleSection>
            )}

            {/* Conformité & sync-readiness (§XVI.2) — vidéo uniquement */}
            {data.media_type === 'video' && (
              <CollapsibleSection
                title={t('conf_title')}
                badge={<StatusBadge status={conformanceBadge(data.conformance_status)} label={data.conformance_status ? t(`conf_status_${data.conformance_status}`) : t('conf_status_unknown')} />}
              >
                <ConformanceSection media={data} t={t} />
              </CollapsibleSection>
            )}

            {/* Renditions adaptatives (« artefacts » vidéo) — vidéo uniquement */}
            {data.media_type === 'video' && (
              <CollapsibleSection
                title={
                  <span className="inline-flex items-center gap-1.5">
                    {t('renditions_title')}
                    {data.has_renditions && (
                      <span
                        className="w-2 h-2 rounded-full bg-accent"
                        title={t('renditions_badge_title')}
                        aria-label={t('renditions_badge_title')}
                      />
                    )}
                  </span>
                }
              >
                <RenditionsSection media={data} t={t} />
              </CollapsibleSection>
            )}

            {/* Tags & filtrage (§XVII) — tous types */}
            <CollapsibleSection
              title={t('tags_title')}
              badge={data.tags && data.tags.length > 0 ? <span className="text-xs text-gray-400">{data.tags.length}</span> : undefined}
            >
            <UsageSection idMedia={data.id_media} t={t} />
              <TagsSection media={data} t={t} />
            </CollapsibleSection>

            {/* Gouvernance §XVIII contenu (D9) — se masque d'elle-même sans nœuds */}
            <GovernanceSection media={data} />

            {/* Remplacer le fichier — types à fichier uniquement (pointeurs : rien à remplacer) */}
            {data.media_type !== 'hdmi_input' && (
              <CollapsibleSection title={t('replace_title')}>
                <ReplaceSection media={data} t={t} />
              </CollapsibleSection>
            )}

            {/* Quarantaine / kill-switch (§ Q5) — tous types, JAMAIS repliée */}
            <QuarantineSection idMedia={data.id_media} />

            {/* Droits d'auteur SACEM (§XIX.6) — assets audio uniquement, replié par défaut */}
            {data.media_type === 'audio' && (
              <CollapsibleSection title={t('rights_title')}>
                <RightsSection media={data} t={t} />
              </CollapsibleSection>
            )}

            {data.attribution_text && (
              <div className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-500">
                <span className="font-medium">Attribution :</span> {data.attribution_text}
                {data.source.startsWith('stock_') && (
                  <a
                    href={`https://${data.attribution_text.toLowerCase().includes('pexels') ? 'pexels.com' : 'unsplash.com'}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 ml-1 text-accent hover:underline"
                  >
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-center h-32">
          <span className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      )}
    </Drawer>
  )
}
