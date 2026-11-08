'use client'

import { useRef, useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, GripVertical, Plus, Trash2, X, Tag, FlaskConical, Check, CalendarClock, ChevronDown, ChevronRight, FolderTree as FolderTreeIcon, Download, Layers, FilePenLine, Copy, ListVideo, Shuffle, ExternalLink, Lock, Network, Send, ShieldCheck, AlertTriangle, Play, Eye } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import NumberField from '@/components/ui/NumberField'
import SearchInput from '@/components/ui/SearchInput'
import api from '@/lib/api'
import { formatMs } from '@/lib/formatMs'
import { useCollapse } from '@/lib/useCollapse'
import { useCommitField } from '@/lib/useCommitField'
import type { ItemRuleRead, MediaListItem, PlaylistDetail, PlaylistItemRead, PlaylistItemTags, PlaylistRead, PlayerRead, PlayerGroupRead, SimulatePlayerResult, SimulateTimelineResult, TemplateRead } from '@/types/api'
import { TagPicker, useTagNamespaces } from '@/components/tags/TagControls'
import NodeSelect, { useGovernanceNodes, useNodeName } from '@/components/governance/NodeSelect'
import FolderTree, { type FolderFilter } from '../../media/components/FolderTree'
import MediaViewer, { isViewable, type ViewerMedia } from '../../media/components/MediaViewer'
import PlaylistPlayer, { itemHoldMs, toViewerMedia, viewableItems } from '../PlaylistPlayer'
import SyncBadge from '../SyncBadge'

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

/**
 * Picker de médias — vue d'accueil : les N derniers de CHAQUE type (décision Ed
 * 2026-07-20). L'audio est absent de la liste : une playlist standard porte du
 * contenu visuel, l'audio pur relevant des paniers audio §XIX.
 */
const PICKER_RECENT_PER_TYPE = 3
const PICKER_TYPE_ORDER = [
  'image', 'video', 'document', 'html_package', 'url_display', 'feed_display', 'hdmi_input',
] as const

/** Génère et télécharge un CSV (échappement RFC 4180) côté client. */
function downloadCsv(filename: string, rows: (string | number)[][]) {
  const esc = (v: string | number) => {
    const s = String(v ?? '')
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csv = rows.map((r) => r.map(esc).join(',')).join('\r\n')
  // BOM UTF-8 pour qu'Excel lise correctement les accents.
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}


/** Champ durée d'exposition (secondes) éditable inline — pour image/PDF sans durée native.
 *  Vide = repli sur la durée par défaut player (10 s). S'enregistre seul (débounce), sans
 *  dépendre du blur : les flèches du spinner ne donnent pas toujours le focus. */
function ItemDurationField({ initialMs, onSave }: { initialMs: number | null; onSave: (ms: number | null) => void }) {
  const t = useTranslations()
  return (
    // stopPropagation au niveau du conteneur : la saisie ne doit pas amorcer le drag de l'item.
    <span className="inline-flex items-center gap-1" onPointerDown={(e) => e.stopPropagation()}>
      <NumberField
        value={initialMs ? Math.round(initialMs / 1000) : null}
        onCommit={(s) => onSave(s === null ? null : s * 1000)}
        allowEmpty
        min={1}
        placeholder="10"
        title={t('playlists.duration_seconds')}
        className="w-12 border border-gray-200 rounded-lg px-1.5 py-0.5 text-xs text-gray-600 focus:outline-none focus:ring-1 focus:ring-accent/40 bg-surface"
      />
      <span>s</span>
    </span>
  )
}

/** Nb de pages sélectionnées par une spec "2-5,8" (pendant client du parseur serveur —
 *  lenient : spec vide/illisible = toutes les pages). */
function selectedPageCount(spec: string | null | undefined, pageCount: number): number {
  if (!spec || !spec.trim() || pageCount <= 0) return pageCount
  const seen = new Set<number>()
  for (const raw of spec.split(',')) {
    const part = raw.trim()
    if (!part) continue
    const m = part.match(/^(\d+)\s*-\s*(\d+)$/)
    if (m) {
      let a = Number(m[1]); let b = Number(m[2])
      if (b < a) [a, b] = [b, a]
      for (let n = Math.max(1, a); n <= Math.min(pageCount, b); n++) seen.add(n)
    } else if (/^\d+$/.test(part)) {
      const n = Number(part)
      if (n >= 1 && n <= pageCount) seen.add(n)
    } else {
      return pageCount // illisible → repli serveur = tout le document
    }
  }
  return seen.size || pageCount
}

/** Sélection de pages d'un document ("2-5,8", vide = toutes) — s'enregistre seul (débounce),
 *  sans dépendre du blur (cf. `useCommitField`).
 *  `onFocusChange` remonte le focus pour afficher la bulle d'aide au format sous la ligne. */
function DocPagesField({ initial, onSave, onFocusChange }: {
  initial: string | null
  onSave: (spec: string | null) => void
  onFocusChange?: (focused: boolean) => void
}) {
  const t = useTranslations()
  const bind = useCommitField<string | null>({
    external: initial ?? null,
    toText: (v) => v ?? '',
    parse: (raw) => raw.trim() || null,
    commit: onSave,
  })
  return (
    <input
      type="text"
      {...bind}
      onFocus={() => { bind.onFocus(); onFocusChange?.(true) }}
      onBlur={() => { bind.onBlur(); onFocusChange?.(false) }}
      onPointerDown={(e) => e.stopPropagation()}
      placeholder={t('playlists.doc_pages_all')}
      title={t('playlists.doc_pages_title')}
      className="w-20 border border-gray-200 rounded-lg px-1.5 py-0.5 text-xs text-gray-600 focus:outline-none focus:ring-1 focus:ring-accent/40 bg-surface"
    />
  )
}

export default function PlaylistDetailPage() {
  const t = useTranslations()
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const qc = useQueryClient()

  // Bloc de réglages replié/déplié, persisté — la préférence survit à la navigation.
  const [settingsOpen, toggleSettings] = useCollapse('sf.playlist.settings')
  const [mediaDrawerOpen, setMediaDrawerOpen] = useState(false)
  const [mediaSearch, setMediaSearch] = useState('')
  const [pickedMedia, setPickedMedia] = useState<Set<number>>(new Set())
  const [pickerFolder, setPickerFolder] = useState<FolderFilter>('all')
  const [tagItem, setTagItem] = useState<number | null>(null)  // id_item en cours d'édition de tags
  const [rulesItem, setRulesItem] = useState<number | null>(null)  // id_item en cours d'édition de règles
  // Rotation : picker de sous-playlist (item sub_playlist).
  const [plDrawerOpen, setPlDrawerOpen] = useState(false)
  const [plSearch, setPlSearch] = useState('')
  const [subError, setSubError] = useState<string | null>(null)
  const [simOpen, setSimOpen] = useState(false)
  // Documents multipages : id_item dont le champ « pages » a le focus (bulle d'aide au format).
  const [docHintItem, setDocHintItem] = useState<number | null>(null)
  // Visionneuse (réutilisée de /media — demande Ed 2026-07-28) : lecture d'un contenu
  // unitaire ou de la playlist construite, SANS quitter la page. `source` distingue la
  // liste des items ('items') de l'aperçu depuis le drawer « Ajouter un média » ('picker'),
  // qui n'empilent pas pareil vis-à-vis du drawer. `playing` = enchaînement automatique.
  const [viewer, setViewer] = useState<{ source: 'items' | 'picker'; index: number; playing: boolean } | null>(null)
  // Lecture d'une SOUS-playlist imbriquée, sur place (retour Ed 2026-07-29) : il fallait
  // jusqu'ici ouvrir la playlist enfant dans une autre page pour voir ce qu'elle contient.
  const [subPlaying, setSubPlaying] = useState<number | null>(null)
  // Lecture de CETTE playlist par la scène multi-zones (constat d'Ed 2026-08-13 : depuis
  // l'éditeur, « Lire la playlist » ne tenait pas compte du template). L'éditeur monte sa
  // PROPRE visionneuse — il lui faut ses actions (« Ajouter un média », navigation dans le
  // picker) — donc il ne passait pas par `PlaylistPlayer`, et n'a jamais vu la scène.
  const [selfPlaying, setSelfPlaying] = useState(false)
  const [renditionAdvisory, setRenditionAdvisory] = useState<Array<{ media_height: number; target_height: number; action: string }>>([])
  const dragItem = useRef<number | null>(null)
  const dragOver = useRef<number | null>(null)

  const { data: pl, isLoading } = useQuery<PlaylistDetail>({
    queryKey: ['playlist', params.id],
    queryFn: () => api.get<PlaylistDetail>(`/playlists/${params.id}`).then((r) => r.data),
  })

  // Contenu gouverné §XVIII (D6/D7) — hooks AVANT tout retour anticipé.
  const govNodeName = useNodeName(pl?.id_governance_node)
  const govReadonly = !!pl?.governed_readonly          // nœud visible mais non éditable
  const govModerated = !!pl?.requires_approval          // publication via approbation §XXI
  const [approvalError, setApprovalError] = useState<string | null>(null)

  // ── Picker de médias ────────────────────────────────────────────────────────
  // Recherche débouncée et RÉSOLUE PAR LE SERVEUR (comme /media). L'ancien picker
  // chargeait `limit: 200` puis filtrait dans le navigateur : au-delà de 200 médias,
  // une recherche ne pouvait tout simplement PAS trouver les suivants — le média
  // existait, le drawer répondait « aucun résultat ».
  const [debouncedMediaSearch, setDebouncedMediaSearch] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedMediaSearch(mediaSearch.trim()), 300)
    return () => clearTimeout(timer)
  }, [mediaSearch])

  function pickerFolderParams(): Record<string, string | number | boolean> {
    if (pickerFolder === 'unfiled') return { unfiled: true }
    if (pickerFolder !== 'all') return { id_folder: pickerFolder }
    return {}
  }

  // Vue d'accueil du drawer : ni recherche, ni dossier choisi → on ne déverse pas
  // toute la médiathèque, on montre les 3 derniers de chaque type (décision Ed).
  const isPickerLanding = !debouncedMediaSearch && pickerFolder === 'all'

  const { data: pickerStats } = useQuery<{ total: number; by_type: Record<string, number> }>({
    queryKey: ['media', 'stats', 'picker'],
    queryFn: () => api.get('/media/stats').then((r) => r.data),
    enabled: mediaDrawerOpen,
  })
  const pickerTypes = PICKER_TYPE_ORDER.filter((ty) => pickerStats?.by_type?.[ty])

  // Une petite requête PAR TYPE (même patron que la page /media) : les 3 derniers
  // d'un type ne sont pas dérivables d'une liste globale tronquée.
  const recentPickerQueries = useQueries({
    queries: pickerTypes.map((ty) => ({
      queryKey: ['media', 'picker-recent', ty],
      queryFn: () =>
        api.get<MediaListItem[]>('/media/', { params: { media_type: ty, limit: PICKER_RECENT_PER_TYPE } })
          .then((r) => r.data),
      enabled: mediaDrawerOpen && isPickerLanding,
    })),
  })

  // Recherche ou dossier choisi → liste complète correspondante, SANS plafond à 3.
  const { data: pickerResults = [] } = useQuery<MediaListItem[]>({
    queryKey: ['media', 'picker-list', pickerFolder, debouncedMediaSearch],
    queryFn: () => {
      const params: Record<string, string | number | boolean> = { ...pickerFolderParams(), limit: 200 }
      if (debouncedMediaSearch) params.q = debouncedMediaSearch
      return api.get<MediaListItem[]>('/media/', { params }).then((r) => r.data)
    },
    enabled: mediaDrawerOpen && !isPickerLanding,
  })

  // Templates (§25.4) : le modèle de la playlist + ses zones (pour l'affectation item→zone).
  const { data: templates = [] } = useQuery<TemplateRead[]>({
    queryKey: ['templates'],
    queryFn: () => api.get<TemplateRead[]>('/templates').then((r) => r.data),
  })

  // Rotation : playlists candidates au picker de sous-playlist.
  const { data: allPlaylists = [] } = useQuery<PlaylistRead[]>({
    queryKey: ['playlists'],
    queryFn: () => api.get<PlaylistRead[]>('/playlists/?limit=200').then((r) => r.data),
    enabled: plDrawerOpen,
  })

  const addSubMutation = useMutation({
    mutationFn: (id_child_playlist: number) =>
      api.post(`/playlists/${params.id}/items`, { id_child_playlist }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playlist', params.id] })
      setPlDrawerOpen(false)
      setSubError(null)
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSubError(typeof detail === 'string' ? detail : t('common.error'))
    },
  })

  // Rotation : réglages de CETTE playlist (utilisée comme sous-playlist).
  const rotationMutation = useMutation({
    mutationFn: (patch: { rotation_mode?: string; items_per_turn?: number; no_ads_inside?: boolean }) =>
      api.put(`/playlists/${params.id}`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  // Ajout multi-sélection : on accumule les contenus cochés puis on les ajoute d'un coup.
  const addItemsMutation = useMutation({
    mutationFn: (id_medias: number[]) =>
      api.post(`/playlists/${params.id}/items/bulk`, { id_medias }),
    onSuccess: () => {
      // Staging : l'ajout va au brouillon (pas de push). L'advisory de conformité
      // remonte à la publication.
      qc.invalidateQueries({ queryKey: ['playlist', params.id] })
      setMediaDrawerOpen(false)
      setPickedMedia(new Set())
    },
  })

  function togglePick(id: number) {
    setPickedMedia((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function openMediaPicker() {
    setPickedMedia(new Set())
    setMediaSearch('')
    setMediaDrawerOpen(true)
  }

  const publishMutation = useMutation({
    mutationFn: () => api.post(`/playlists/${params.id}/publish`),
    onSuccess: (res) => {
      // Conformité §XVI.2 : la publication peut avoir lancé des renditions FHD.
      const raw = res.headers?.['x-rendition-advisory']
      if (raw) {
        try { setRenditionAdvisory(JSON.parse(raw)) } catch { /* ignore */ }
      }
      qc.invalidateQueries({ queryKey: ['playlist', params.id] })
    },
    // Gouvernance : nœud sous modération → 409, la publication passe par l'approbation.
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setApprovalError(typeof detail === 'string' ? detail : t('common.error'))
    },
  })

  // Modération §XVIII/§XXI : soumet le BROUILLON — c'est l'approbation qui publiera.
  const submitApprovalMutation = useMutation({
    mutationFn: () => api.post(`/playlists/${params.id}/submit-approval`),
    onSuccess: () => {
      setApprovalError(null)
      qc.invalidateQueries({ queryKey: ['playlist', params.id] })
      qc.invalidateQueries({ queryKey: ['approvals'] })
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setApprovalError(typeof detail === 'string' ? detail : t('common.error'))
    },
  })

  // Rattacher / détacher la playlist d'un nœud de gouvernance (D6).
  const govNodeMutation = useMutation({
    mutationFn: (id_governance_node: number | null) =>
      api.put(`/playlists/${params.id}`, { id_governance_node }),
    onSuccess: () => {
      setApprovalError(null)
      qc.invalidateQueries({ queryKey: ['playlist', params.id] })
      qc.invalidateQueries({ queryKey: ['playlists'] })
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setApprovalError(typeof detail === 'string' ? detail : t('common.error'))
    },
  })

  const discardMutation = useMutation({
    mutationFn: () => api.post(`/playlists/${params.id}/discard`),
    onSuccess: () => {
      setRenditionAdvisory([])
      qc.invalidateQueries({ queryKey: ['playlist', params.id] })
    },
  })

  const removeItemMutation = useMutation({
    mutationFn: (id_item: number) =>
      api.delete(`/playlists/${params.id}/items/${id_item}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  const updateItemMutation = useMutation({
    mutationFn: ({ id_item, duration_ms }: { id_item: number; duration_ms: number | null }) =>
      api.patch(`/playlists/${params.id}/items/${id_item}`, { duration_ms }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  // Documents multipages : sélection de pages de l'item ("2-5,8", null = toutes).
  const docPagesMutation = useMutation({
    mutationFn: ({ id_item, doc_pages }: { id_item: number; doc_pages: string | null }) =>
      api.patch(`/playlists/${params.id}/items/${id_item}`, { doc_pages }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  // Documents multipages : feuilletage au doigt + délai de reprise (migr 0129).
  const touchNavMutation = useMutation({
    mutationFn: ({ id_item, ...body }: { id_item: number; touch_navigation?: boolean; touch_resume_after_s?: number | null }) =>
      api.patch(`/playlists/${params.id}/items/${id_item}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  const duplicateItemMutation = useMutation({
    mutationFn: (id_item: number) =>
      api.post(`/playlists/${params.id}/items/${id_item}/duplicate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  const reorderMutation = useMutation({
    mutationFn: (items: { id_item: number; sort_order: number }[]) =>
      api.put(`/playlists/${params.id}/items/reorder`, { items }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  const syncModeMutation = useMutation({
    mutationFn: (sync_mode: string) =>
      api.put(`/playlists/${params.id}`, { sync_mode }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  // §25.4 : assigner un template de mise en page à la playlist.
  const templateMutation = useMutation({
    mutationFn: (id_template: number | null) =>
      api.put(`/playlists/${params.id}`, { id_template }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  // §25.4 : affecter un item à une zone du template.
  const zoneMutation = useMutation({
    mutationFn: ({ id_item, zone_index }: { id_item: number; zone_index: number }) =>
      api.patch(`/playlists/${params.id}/items/${id_item}`, { zone_index }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlist', params.id] }),
  })

  function handleDragStart(index: number) {
    dragItem.current = index
  }

  function handleDragEnter(index: number) {
    dragOver.current = index
  }

  function handleDrop() {
    if (dragItem.current === null || dragOver.current === null) return
    if (!pl) return
    const items = [...pl.items]
    const dragged = items.splice(dragItem.current, 1)[0]
    items.splice(dragOver.current, 0, dragged)
    dragItem.current = null
    dragOver.current = null
    reorderMutation.mutate(
      items.map((item, i) => ({ id_item: item.id_item, sort_order: i }))
    )
  }

  // Playlist standard = contenu visuel : l'audio pur reste réservé aux paniers audio.
  const pickable = (m: MediaListItem) => m.transcode_status === 'done' && m.media_type !== 'audio'

  // Sections affichées dans le picker : par type en vue d'accueil, une seule liste
  // à plat dès qu'une recherche ou un dossier restreint le champ.
  const pickerSections: Array<{ type: string | null; items: MediaListItem[] }> = isPickerLanding
    ? pickerTypes
        .map((ty, i) => ({ type: ty as string, items: (recentPickerQueries[i]?.data ?? []).filter(pickable) }))
        .filter((s) => s.items.length > 0)
    : [{ type: null, items: pickerResults.filter(pickable) }]

  const pickerCount = pickerSections.reduce((n, s) => n + s.items.length, 0)

  // ── Visionneuse ─────────────────────────────────────────────────────────────
  // Les deux listes navigables : items de la playlist (médias VISUELS seulement — les
  // pointeurs page web/flux/HDMI n'ont rien à montrer, cf. isViewable ; une sous-playlist
  // se lit en l'ouvrant) et contenus du picker.
  // `viewableItems` / `toViewerMedia` / `itemHoldMs` sont partagés avec `PlaylistPlayer` :
  // la lecture depuis la LISTE et celle depuis l'ÉDITEUR doivent dérouler exactement pareil.
  // ⚠️ Cette visionneuse-ci ne sert plus qu'au MONO-zone et au clic sur un contenu isolé ;
  // « Lire la playlist » sur un template multi-zones passe par `PlaylistPlayer` (scène).
  const playableItems = viewableItems(pl?.items ?? [])
  const pickerViewable = pickerSections.flatMap((s) => s.items).filter((m) => isViewable(m.media_type))

  const viewerList: ViewerMedia[] = viewer?.source === 'picker'
    ? pickerViewable
    : playableItems.map(toViewerMedia)
  const viewerMedia = viewer ? viewerList[viewer.index] ?? null : null

  const viewerHoldMs = viewer?.playing && viewer.source === 'items'
    ? itemHoldMs(playableItems[viewer.index])
    : undefined

  // La liste sous-jacente a changé (recherche du picker, item supprimé…) et l'index ne
  // résout plus : on ferme proprement plutôt que de laisser un état sans UI.
  useEffect(() => {
    if (viewer && !viewerMedia) setViewer(null)
  }, [viewer, viewerMedia])

  function openItemViewer(id_item: number) {
    const idx = playableItems.findIndex((it) => it.id_item === id_item)
    if (idx >= 0) setViewer({ source: 'items', index: idx, playing: false })
  }

  // Fin du contenu courant en lecture : item suivant, ou fin de la lecture au bout.
  const onViewerEnded = viewer?.playing
    ? () => setViewer((v) => (v && v.index < playableItems.length - 1 ? { ...v, index: v.index + 1 } : null))
    : undefined

  if (isLoading) {
    return (
      <>
        <Topbar title="…" />
        <main className="flex-1 flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </main>
      </>
    )
  }

  if (!pl) return null

  // §25.4 : zones du template actif (pour l'affectation item→zone et le hint multi-zones).
  const activeTemplate = templates.find((x) => x.id_template === pl.id_template) ?? null
  const templateZones = activeTemplate?.layout?.zones ?? []
  const multiZone = templateZones.length > 1
  const zoneName = (idx: number) => {
    const z = templateZones.find((zz) => zz.index === idx)
    return z ? `${t('templates.zone')} ${z.index + 1}${z.label ? ` — ${z.label}` : ''}` : `${t('templates.zone')} ${idx + 1}`
  }

  return (
    <>
      <Topbar title={pl.playlist_name}>
        {/* Lecture de la playlist construite — lecture seule : disponible aussi aux rôles
            sans playlists:edit.
            🔑 Template MULTI-zones ⇒ on passe la main à `PlaylistPlayer`, qui compose la
            SCÈNE. Sans ça l'éditeur déroulait sa liste à plat et montrait autre chose que
            l'écran, alors que la même playlist lue depuis /playlists était juste : deux
            boutons « lire » pour un seul contenu, deux résultats. Mono-zone : la
            visionneuse de l'éditeur, inchangée (elle porte ses propres actions). */}
        {playableItems.length > 0 && (
          <Button
            size="sm"
            onClick={() => (multiZone
              ? setSelfPlaying(true)
              : setViewer({ source: 'items', index: 0, playing: true }))}
          >
            <Play className="w-3.5 h-3.5 mr-1" />
            {t('playlists.play_preview')}
          </Button>
        )}
        {pl.items.length > 0 && (
          <Button size="sm" onClick={() => setSimOpen(true)}>
            <FlaskConical className="w-3.5 h-3.5 mr-1" />
            {t('tags.simulate')}
          </Button>
        )}
        <Button size="sm" variant="secondary" onClick={() => router.push('/playlists')}>
          <ArrowLeft className="w-3.5 h-3.5 mr-1" />
          {t('common.back')}
        </Button>
      </Topbar>

      {/*
        Page verrouillée au viewport en deux parties : un bloc haut REPLIABLE
        (réglages : diffusion, template/zones, rotation) et la liste des contenus
        qui occupe toute la hauteur restante et défile pour elle seule.

        ⚠️ La ligne de titre « Items » reste TOUJOURS visible, même replié : elle
        porte « Ajouter un média » et « Ajouter une sous-playlist ». Replier la
        section entière, titre compris, aurait rendu l'action principale de la
        page inatteignable.
      */}
      {/* Édition de playlist = playlists:edit. Un rôle en lecture (Approbateur…)
          consulte les réglages et les items mais toute saisie déclenche le nudge
          « lecture seule » (ReadOnlyNudge). Les boutons d'action sont en plus
          masqués via <Can> — ce qui suit couvre les CHAMPS qui restent visibles. */}
      {/* `data-write-locked` (gouvernance §XVIII D6) : l'utilisateur A la permission
          playlists:edit, mais pas sur CE nœud — sans ce verrou, tous les champs et
          réglages resteraient manipulables pour finir en 403 côté serveur. */}
      <main
        className="flex-1 flex flex-col min-h-0"
        data-write-perm="playlists:edit"
        {...(govReadonly ? { 'data-write-locked': '1' } : {})}
      >
        <div className="max-w-3xl w-full mx-auto px-6 pt-8 flex-1 flex flex-col min-h-0">
          <div className="shrink-0 space-y-6">

          {/* Gouvernance §XVIII (D6) : playlist d'un nœud que l'utilisateur n'administre pas
              → visible pour comprendre ce qui passe au-dessus de lui, mais intouchable.
              Le serveur refuse déjà toute mutation ; ici on le DIT au lieu de laisser
              l'utilisateur découvrir une suite de 403. */}
          {govReadonly && (
            <div className="flex items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
              <Lock className="w-4 h-4 text-gray-400 shrink-0" />
              <div className="flex-1 text-sm text-gray-600">
                {t('governance.content_readonly_banner', { node: govNodeName ?? '—' })}
              </div>
            </div>
          )}

          {/* Durée maximale par contenu (gouvernance §XVIII) : AVERTIR au chargement, et pas
              seulement à l'aperçu du programme compilé — décision Ed 2026-07-26. Un contenu
              au-dessus du plafond sera écarté à la diffusion ; le découvrir une fois la
              playlist construite arrive trop tard.
              ⚠️ Avertissement NON BLOQUANT et volontairement prudent : seule la compilation
              connaît le contexte réel (quel nœud diffuse, à quel instant). On nomme les
              contenus concernés — jamais « certains contenus » : c'est exactement la classe
              de message qui envoie chercher au mauvais endroit. */}
          {(pl.governance_too_long ?? []).length > 0 && (
            <div className="flex items-start gap-3 rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-500/10 px-4 py-3">
              <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
              <div className="flex-1 text-sm text-amber-700 dark:text-amber-300">
                {t('governance.item_too_long_warning', {
                  sec: pl.governance_max_item_sec ?? 0,
                  names: (pl.governance_too_long ?? []).join(', '),
                })}
              </div>
            </div>
          )}

          {/* Staging (#1) : bandeau « modifications non publiées » + Publier / Annuler.
              Sous modération (D7), le bouton Publier laisse place à « Soumettre à
              l'approbation » : la publication se fera à l'approbation (§XXI). */}
          {pl.has_draft_changes && !govReadonly && (
            <div className="flex items-center gap-3 rounded-lg border border-accent/40 bg-accent/5 px-4 py-3">
              <FilePenLine className="w-4 h-4 text-accent shrink-0" />
              <div className="flex-1 text-sm text-gray-700">
                {pl.approval_status === 'pending_review'
                  ? t('governance.content_pending_review')
                  : pl.approval_status === 'changes_requested'
                    ? t('governance.content_changes_requested')
                    : t('playlists.unpublished_changes')}
              </div>
              <button
                onClick={() => discardMutation.mutate()}
                disabled={discardMutation.isPending || publishMutation.isPending
                  || pl.approval_status === 'pending_review'}
                className="text-sm text-gray-500 hover:text-gray-700 px-2 transition-sf disabled:opacity-50"
              >
                {t('playlists.discard')}
              </button>
              {govModerated ? (
                <Button
                  size="sm"
                  onClick={() => submitApprovalMutation.mutate()}
                  loading={submitApprovalMutation.isPending}
                  // Une demande déjà en revue ne se re-soumet pas (le serveur renverrait 409).
                  disabled={pl.approval_status === 'pending_review' || discardMutation.isPending}
                >
                  <Send className="w-3.5 h-3.5 mr-1" />
                  {t('governance.content_submit_approval')}
                </Button>
              ) : (
                <Button size="sm" onClick={() => publishMutation.mutate()}
                  disabled={publishMutation.isPending || discardMutation.isPending}>
                  {publishMutation.isPending ? t('playlists.publishing') : t('playlists.publish')}
                </Button>
              )}
            </div>
          )}
          {approvalError && (
            <div className="flex items-start gap-2 rounded-lg border border-red-300 dark:border-red-500/40 bg-red-500/10 px-4 py-2 -mt-3">
              <p className="flex-1 text-sm text-danger">{approvalError}</p>
              <button onClick={() => setApprovalError(null)} className="text-danger" aria-label={t('common.close')}>
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* Advisory de conformité §XVI.2 : contenu trop lourd pour les players cibles */}
          {renditionAdvisory.length > 0 && (
            <div className="flex items-start gap-3 rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-500/10 dark:bg-amber-500/15 px-4 py-3">
              <Layers className="w-4 h-4 text-amber-600 dark:text-amber-300 mt-0.5 shrink-0" />
              <div className="flex-1 text-sm text-amber-900 dark:text-amber-200 space-y-1">
                {renditionAdvisory.map((a, i) => (
                  <div key={i}>
                    {t(
                      a.action === 'generating'
                        ? 'playlists.conformance_generating'
                        : 'playlists.conformance_exists',
                      { src: a.media_height, target: a.target_height },
                    )}
                  </div>
                ))}
              </div>
              <button
                onClick={() => setRenditionAdvisory([])}
                className="text-amber-600 dark:text-amber-300 hover:text-amber-800 transition-sf"
                aria-label={t('common.close')}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Header actions — toujours visible ; son chevron replie les réglages */}
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={toggleSettings}
              aria-expanded={settingsOpen}
              title={settingsOpen ? t('playlists.settings_collapse') : t('playlists.settings_expand')}
              className="group flex items-center gap-2 text-left"
            >
              <ChevronDown
                className={`w-4 h-4 text-gray-500 group-hover:text-gray-800 transition-sf ${settingsOpen ? '' : '-rotate-90'}`}
              />
              <h2 className="text-sm font-semibold text-gray-900">{t('playlists.items_title')}</h2>
              {/* Total vivant : recalculé serveur à chaque mutation d'item (le GET détail
                  est réinvalidé) — même formule que le wall-clock du player. */}
              {pl.items.length > 0 && (
                <span className="text-xs text-gray-400">
                  {t('playlists.items_summary', { count: pl.items.length })}
                  {pl.total_duration_ms != null && <> · {formatMs(pl.total_duration_ms)}</>}
                </span>
              )}
            </button>
            {/* Gouvernance D6 : sur un contenu d'un nœud non administré, ces actions
                n'aboutiraient jamais — on ne les propose pas. */}
            <Can perm="playlists:edit">
              <div className={`flex items-center gap-2 ${govReadonly ? 'hidden' : ''}`}>
                <Button size="sm" variant="secondary" onClick={() => { setPlSearch(''); setSubError(null); setPlDrawerOpen(true) }}>
                  <ListVideo className="w-3.5 h-3.5 mr-1" />
                  {t('playlists.add_sub_playlist')}
                </Button>
                <Button size="sm" onClick={openMediaPicker}>
                  <Plus className="w-3.5 h-3.5 mr-1" />
                  {t('playlists.add_media')}
                </Button>
              </div>
            </Can>
          </div>

          {/* Bloc repliable : diffusion, template/zones, rotation */}
          {settingsOpen && (
          <div className="space-y-6">

          {/* Sync mode */}
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={pl.sync_mode === 'loop'}
                onChange={(e) =>
                  syncModeMutation.mutate(e.target.checked ? 'loop' : 'wall_clock')
                }
                className="w-4 h-4 rounded border-gray-300"
              />
              <span className="text-sm text-gray-700">{t('playlists.unsynchronized')}</span>
            </label>
            {pl.sync_mode === 'wall_clock' && (
              <span className="text-xs text-gray-400">{t('playlists.sync_hint')}</span>
            )}
            <SyncBadge pl={pl} t={t} />
          </div>
          {pl.sync_windowed && (
            <p className="text-xs text-teal-600 dark:text-teal-300 -mt-3">{t('playlists.sync_windowed_hint')}</p>
          )}
          {!pl.sync_ready && (
            <p className="text-xs text-amber-600 dark:text-amber-300 -mt-3">{t('playlists.sync_not_ready_hint')}</p>
          )}

          {/* Modèle de mise en page (§25.4 zones de template) */}
          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-700 shrink-0">{t('playlists.template_label')}</label>
            <select
              value={pl.id_template ?? ''}
              onChange={(e) => templateMutation.mutate(e.target.value ? Number(e.target.value) : null)}
              className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
            >
              <option value="">{t('playlists.template_none')}</option>
              {templates.map((tp) => (
                <option key={tp.id_template} value={tp.id_template}>{tp.template_name}</option>
              ))}
            </select>
          </div>
          {multiZone && (
            <p className="text-xs text-accent -mt-3">{t('playlists.template_hint')}</p>
          )}

          {/* Rotation (« N items par tour » quand la playlist est imbriquée comme
              sous-playlist d'un programme — retour beta 2026-07) */}
          <div className="bg-surface border border-gray-200 rounded-lg p-4 space-y-3 shadow-sf-card">
            <div className="flex items-center gap-2">
              <Shuffle className="w-4 h-4 text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900">{t('playlists.rotation_title')}</h3>
              {pl.used_as_child && (
                <span className="text-[10px] font-medium text-accent bg-accent/10 px-1.5 py-0.5 rounded">
                  {t('playlists.rotation_in_use')}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-400">{t('playlists.rotation_hint')}</p>
            {/* Décision Ed 2026-07-25 ④ : la rotation suit le brouillon comme les items —
                deux réglages voisins ne peuvent pas avoir deux comportements. */}
            <p className="text-xs text-gray-400">{t('playlists.rotation_draft_hint')}</p>
            <div className="flex flex-wrap items-center gap-3">
              <select
                value={pl.rotation_mode ?? 'all'}
                onChange={(e) => rotationMutation.mutate({ rotation_mode: e.target.value })}
                className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
              >
                <option value="all">{t('playlists.rotation_all')}</option>
                <option value="one_sequential">{t('playlists.rotation_sequential')}</option>
                <option value="one_random">{t('playlists.rotation_random')}</option>
              </select>
              {(pl.rotation_mode === 'one_sequential' || pl.rotation_mode === 'one_random') && (
                <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                  {t('playlists.rotation_per_turn')}
                  <NumberField
                    value={pl.items_per_turn ?? 1}
                    onCommit={(v) => rotationMutation.mutate({ items_per_turn: v ?? 1 })}
                    min={1}
                    max={50}
                    className="w-16 border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                  />
                </label>
              )}
            </div>
            {/* « Pas de pub entre les contenus » — effet quand cette playlist est imbriquée
                comme sous-playlist : son bloc passe d'une traite (retour Ed 2026-07-16). */}
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={pl.no_ads_inside ?? false}
                onChange={(e) => rotationMutation.mutate({ no_ads_inside: e.target.checked })}
                className="accent-accent mt-0.5"
              />
              <span className="text-sm text-gray-700">
                {t('playlists.no_ads_toggle')}
                <span className="block text-xs text-gray-400">{t('playlists.no_ads_hint')}</span>
              </span>
            </label>
          </div>

          {/* Gouvernance §XVIII (contenu gouverné D6/D7) — masquée si l'org n'a aucun nœud
              (NodeSelect renvoie null) : la carte n'existe que là où elle a du sens. */}
          <GovernanceCard
            idNode={pl.id_governance_node ?? null}
            readonly={govReadonly}
            moderated={govModerated}
            onChange={(id) => govNodeMutation.mutate(id)}
            t={t}
          />

          </div>
          )}
          {/* fin du bloc repliable */}
          </div>

          {/* Liste des contenus : occupe la hauteur restante, défile seule */}
          <div className="flex-1 min-h-0 overflow-y-auto mt-6 pb-8">
          {pl.items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400 bg-surface rounded-lg border border-gray-200 border-dashed shadow-sf-card">
              <p className="text-sm">{t('playlists.no_items')}</p>
            </div>
          ) : (
            <div className="bg-surface rounded-lg border border-gray-200 overflow-hidden shadow-sf-card">
              {pl.items.map((item, i) => (
                <div
                  key={item.id_item}
                  draggable
                  onDragStart={() => handleDragStart(i)}
                  onDragEnter={() => handleDragEnter(i)}
                  onDragEnd={handleDrop}
                  onDragOver={(e) => e.preventDefault()}
                  className={`flex items-center gap-3 px-4 py-3 transition-sf ${
                    i > 0 ? 'border-t border-gray-100' : ''
                  } hover:bg-gray-50`}
                >
                  <GripVertical className="w-4 h-4 text-gray-300 cursor-grab shrink-0" />
                  <span className="w-6 text-xs text-gray-400 text-center shrink-0">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    {item.item_type === 'sub_playlist' ? (
                      <>
                        <p className="text-sm font-medium text-gray-800 truncate inline-flex items-center gap-1.5">
                          <ListVideo className="w-3.5 h-3.5 text-accent shrink-0" />
                          <span className="truncate">{item.child_name ?? `#${item.id_child_playlist}`}</span>
                          {/* Voir ce que contient la sous-playlist SANS quitter la page :
                              c'était le seul contenu de l'éditeur qui obligeait à naviguer
                              ailleurs pour être regardé (retour Ed 2026-07-29). */}
                          <button
                            onClick={() => setSubPlaying(item.id_child_playlist ?? null)}
                            onPointerDown={(e) => e.stopPropagation()}
                            className="text-gray-300 hover:text-accent transition-sf shrink-0"
                            title={t('playlists.play_preview')}
                          >
                            <Play className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => router.push(`/playlists/${item.id_child_playlist}`)}
                            onPointerDown={(e) => e.stopPropagation()}
                            className="text-gray-300 hover:text-accent transition-sf shrink-0"
                            title={t('playlists.open_sub')}
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </button>
                        </p>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {t('playlists.sub_badge')} · {t('playlists.sub_items_count', { count: item.child_item_count ?? 0 })} ·{' '}
                          {item.child_rotation_mode === 'one_sequential'
                            ? t('playlists.sub_rotation_seq', { k: item.child_items_per_turn ?? 1 })
                            : item.child_rotation_mode === 'one_random'
                              ? t('playlists.sub_rotation_rand', { k: item.child_items_per_turn ?? 1 })
                              : t('playlists.sub_rotation_all')}
                        </p>
                      </>
                    ) : (
                      <>
                        {/* Contenu VISUEL → clic = visionneuse (les pointeurs page web /
                            flux / HDMI n'ont pas de fichier à montrer). */}
                        {item.media_type && isViewable(item.media_type) ? (
                          <p
                            role="button"
                            tabIndex={0}
                            onClick={() => openItemViewer(item.id_item)}
                            onKeyDown={(e) => { if (e.key === 'Enter') openItemViewer(item.id_item) }}
                            title={t('playlists.view_item')}
                            className="text-sm font-medium text-gray-800 truncate cursor-pointer hover:text-accent transition-sf"
                          >
                            {item.media_name ?? `#${item.id_media}`}
                          </p>
                        ) : (
                          <p className="text-sm font-medium text-gray-800 truncate">
                            {item.media_name ?? `#${item.id_media}`}
                          </p>
                        )}
                        <p className="text-xs text-gray-400 mt-0.5">
                          {item.media_type ?? '—'} ·{' '}
                          {(item.media_type === 'image' || item.media_type === 'document' || item.media_type === 'url_display' || item.media_type === 'feed_display' || item.media_type === 'hdmi_input') ? (
                            <ItemDurationField
                              initialMs={item.duration_ms}
                              onSave={(ms) => updateItemMutation.mutate({ id_item: item.id_item, duration_ms: ms })}
                            />
                          ) : (
                            // Vidéo/audio : override manuel sinon durée NATIVE du média
                            // (même repli que le player — ws.py : item || media || 10 s).
                            formatMs(item.duration_ms ?? item.media_duration_ms ?? null)
                          )}
                          {/* Document multipage : durée = PAR PAGE + sélection de pages + total */}
                          {item.media_type === 'document' && (item.media_page_count ?? 0) > 0 && (
                            <>
                              <span className="text-gray-400">{t('playlists.doc_per_page')}</span>
                              {' · '}
                              <span className="inline-flex items-center gap-1">
                                {t('playlists.doc_pages_label')}
                                <DocPagesField
                                  initial={item.doc_pages ?? null}
                                  onSave={(spec) => docPagesMutation.mutate({ id_item: item.id_item, doc_pages: spec })}
                                  onFocusChange={(f) => setDocHintItem(f ? item.id_item : null)}
                                />
                              </span>
                              {' · '}
                              {t('playlists.doc_total', {
                                pages: selectedPageCount(item.doc_pages, item.media_page_count ?? 0),
                                total: formatMs(
                                  selectedPageCount(item.doc_pages, item.media_page_count ?? 0) *
                                    (item.duration_ms || 10000)
                                ),
                              })}
                            </>
                          )}
                          {item.media_type === 'document' && !item.media_page_count && (
                            <> · <span className="text-warning">{t('playlists.doc_not_converted')}</span></>
                          )}
                        </p>
                        {/* Feuilletage au doigt (migr 0129). Deux propriétés DISTINCTES : la dalle
                            tactile appartient au PLAYER, l'autorisation au CONTENU. La mention le
                            dit explicitement — sans elle, un opérateur coche, ne voit rien bouger
                            sur une box TV et conclut à une panne. */}
                        {item.media_type === 'document' && (item.media_page_count ?? 0) > 0 && (
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                            <label
                              className="inline-flex items-center gap-1.5 cursor-pointer text-gray-600"
                              onPointerDown={(e) => e.stopPropagation()}
                              data-write-action
                            >
                              <input
                                type="checkbox"
                                className="accent-accent"
                                checked={item.touch_navigation ?? false}
                                onChange={(e) =>
                                  touchNavMutation.mutate({ id_item: item.id_item, touch_navigation: e.target.checked })
                                }
                              />
                              <span>{t('playlists.touch_nav_label')}</span>
                            </label>
                            {item.touch_navigation && (
                              <span
                                className="inline-flex items-center gap-1 text-gray-400"
                                onPointerDown={(e) => e.stopPropagation()}
                              >
                                {t('playlists.touch_nav_resume')}
                                <NumberField
                                  value={item.touch_resume_after_s ?? null}
                                  onCommit={(v) =>
                                    touchNavMutation.mutate({ id_item: item.id_item, touch_resume_after_s: v })
                                  }
                                  allowEmpty
                                  min={5}
                                  max={3600}
                                  placeholder={t('playlists.touch_nav_resume_default')}
                                  title={t('playlists.touch_nav_resume_title')}
                                  className="w-16 text-xs border border-gray-200 rounded-lg px-1.5 py-0.5 bg-surface text-gray-600 focus:outline-none focus:ring-1 focus:ring-accent/40"
                                />
                              </span>
                            )}
                            <span className="text-gray-500">{t('playlists.touch_nav_hint')}</span>
                          </div>
                        )}
                        {/* Bulle d'aide au format de sélection — visible tant que le champ a le focus */}
                        {docHintItem === item.id_item && (
                          <div className="mt-1.5 rounded-lg border border-accent/30 bg-accent/5 px-2.5 py-1.5 text-[11px] leading-relaxed text-gray-600 max-w-xl">
                            {t('playlists.doc_pages_hint')}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                  {multiZone && (
                    <select
                      value={item.zone_index}
                      onChange={(e) => zoneMutation.mutate({ id_item: item.id_item, zone_index: Number(e.target.value) })}
                      onPointerDown={(e) => e.stopPropagation()}
                      title={t('playlists.item_zone')}
                      className="text-xs border border-gray-200 rounded-lg px-1.5 py-1 bg-surface text-gray-600 shrink-0 focus:outline-none focus:ring-1 focus:ring-accent/40 max-w-[10rem]"
                    >
                      {templateZones.map((z) => (
                        <option key={z.index} value={z.index}>{zoneName(z.index)}</option>
                      ))}
                    </select>
                  )}
                  {item.has_rules && item.item_type !== 'sub_playlist' && (
                    <span className="text-[10px] font-medium text-accent bg-accent/10 px-1.5 py-0.5 rounded shrink-0">
                      {t('playlists.rule_badge')}
                    </span>
                  )}
                  {/* Règles/tags par item : portés par les items DE la sous-playlist
                      (les ids enfants sont ceux servis au player) — masqués ici. */}
                  {item.item_type !== 'sub_playlist' && (
                    <>
                      <button
                        onClick={() => setRulesItem(item.id_item)}
                        className={`transition-sf shrink-0 ${item.has_rules ? 'text-accent' : 'text-gray-300 hover:text-accent'}`}
                        title={t('playlists.rules_title')}
                      >
                        <CalendarClock className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setTagItem(item.id_item)}
                        className="text-gray-300 hover:text-accent transition-sf shrink-0"
                        title={t('tags.item_tags')}
                      >
                        <Tag className="w-4 h-4" />
                      </button>
                    </>
                  )}
                  <button
                    data-write-action
                    onClick={() => duplicateItemMutation.mutate(item.id_item)}
                    disabled={duplicateItemMutation.isPending}
                    className="text-gray-300 hover:text-accent transition-sf shrink-0 disabled:opacity-50"
                    title={t('playlists.duplicate_title')}
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                  <button
                    data-write-action
                    onClick={() => {
                      if (confirm(t('playlists.delete_confirm'))) {
                        removeItemMutation.mutate(item.id_item)
                      }
                    }}
                    className="text-gray-300 hover:text-danger transition-sf shrink-0"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
          </div>
        </div>
      </main>

      {/* Visionneuse (réutilisée de /media). Rendue AVANT les drawers : à z égal (50),
          l'ordre DOM fait passer un drawer ouvert DEPUIS la visionneuse par-dessus elle ;
          `elevated` inverse l'empilement pour l'aperçu ouvert DEPUIS le picker. */}
      <MediaViewer
        item={viewerMedia}
        onClose={() => setViewer(null)}
        onPrev={viewer && viewer.index > 0
          ? () => setViewer((v) => v && { ...v, index: v.index - 1, playing: false })
          : undefined}
        onNext={viewer && viewer.index < viewerList.length - 1
          ? () => setViewer((v) => v && { ...v, index: v.index + 1, playing: false })
          : undefined}
        onEnded={onViewerEnded}
        holdMs={viewerHoldMs}
        position={viewerList.length > 1 ? { index: viewer?.index ?? 0, total: viewerList.length } : undefined}
        elevated={viewer?.source === 'picker'}
        keysDisabled={mediaDrawerOpen && viewer?.source === 'items'}
        actions={
          viewer?.source === 'items' && !govReadonly ? (
            <Can perm="playlists:edit">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  // Le drawer passe devant : on suspend l'enchaînement automatique.
                  setViewer((v) => v && { ...v, playing: false })
                  openMediaPicker()
                }}
              >
                <Plus className="w-3.5 h-3.5" />
                {t('playlists.add_media')}
              </Button>
            </Can>
          ) : undefined
        }
      />

      {/* Lecture d'une SOUS-playlist imbriquée (charge son détail elle-même). */}
      <PlaylistPlayer idPlaylist={subPlaying} onClose={() => setSubPlaying(null)} />
      {/* Cette playlist-ci, jouée par la scène (template multi-zones). */}
      <PlaylistPlayer
        idPlaylist={selfPlaying ? Number(params.id) : null}
        onClose={() => setSelfPlaying(false)}
      />

      {/* Media picker drawer */}
      <Drawer
        open={mediaDrawerOpen}
        onClose={() => setMediaDrawerOpen(false)}
        title={t('playlists.add_media')}
      >
        {/*
          Drawer en 3 bandes : recherche FIXE, dossiers FIXES (≈38 % de la hauteur
          disponible, arbre défilant à l'intérieur), puis la liste des contenus qui
          prend le reste et défile seule.
        */}
        <div className="flex flex-col h-full min-h-0 gap-4">
          <div className="shrink-0">
            <SearchInput
              placeholder={t('media.search_placeholder')}
              value={mediaSearch}
              onChange={(e) => setMediaSearch(e.target.value)}
              wrapperClassName="max-w-none"
            />
          </div>

          {/* Arbre de dossiers — dimensionné en proportion du drawer (basis 38 %) */}
          <div className="shrink-0 basis-[38%] min-h-[8rem] flex flex-col border border-gray-200 rounded overflow-hidden">
            <div className="flex items-center justify-between w-full px-3 py-2 text-sm text-gray-600 shrink-0">
              <span className="flex items-center gap-2">
                <FolderTreeIcon className="w-4 h-4 text-gray-400" />
                {t('media.folders')}
              </span>
              {pickerFolder !== 'all' && (
                <button
                  type="button"
                  onClick={() => setPickerFolder('all')}
                  className="text-xs text-accent hover:underline"
                >
                  {pickerFolder === 'unfiled' ? t('media.folder_unfiled') : t('media.folder_filtered')}
                </button>
              )}
            </div>
            <div className="border-t border-gray-100 p-2 flex-1 min-h-0">
              <FolderTree selected={pickerFolder} onSelect={setPickerFolder} fill />
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto space-y-1">
            {pickerSections.map((section) => (
              <div key={section.type ?? '_flat'} className="space-y-1">
                {/* Titre de type : uniquement en vue d'accueil « 3 derniers par type » */}
                {section.type && (
                  <div className="flex items-center gap-2 px-1 pt-2">
                    <span className="text-[11px] uppercase tracking-wide text-gray-400 font-semibold">
                      {t(`media.type_${section.type}`)}
                    </span>
                    <span className="flex-1 h-px bg-white/5" />
                    <span className="text-[10px] text-gray-500">
                      {pickerStats?.by_type?.[section.type] ?? section.items.length}
                    </span>
                  </div>
                )}
                {section.items.map((m) => {
                  const checked = pickedMedia.has(m.id_media)
                  return (
                    <button
                      key={m.id_media}
                      type="button"
                      onClick={() => togglePick(m.id_media)}
                      aria-pressed={checked}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded text-left transition-sf border ${
                        checked ? 'border-accent bg-accent/5' : 'border-transparent hover:bg-gray-50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        readOnly
                        tabIndex={-1}
                        className="accent-accent w-4 h-4 shrink-0 pointer-events-none"
                      />
                      <div className="w-8 h-8 rounded bg-gray-100 shrink-0 overflow-hidden">
                        {m.thumbnail_url ? (
                          <img src={m.thumbnail_url} alt="" className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full bg-gray-200" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-800 truncate">{m.media_name}</p>
                        <p className="text-xs text-gray-400">{m.media_type}</p>
                      </div>
                      {/* Aperçu SANS quitter le drawer : la visionneuse passe au-dessus
                          (elevated) et Échap ne referme qu'elle. Pas un <button> — la
                          ligne entière en est déjà un. */}
                      {isViewable(m.media_type) && (
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => {
                            e.stopPropagation()
                            const idx = pickerViewable.findIndex((x) => x.id_media === m.id_media)
                            if (idx >= 0) setViewer({ source: 'picker', index: idx, playing: false })
                          }}
                          onKeyDown={(e) => {
                            if (e.key !== 'Enter') return
                            e.stopPropagation()
                            const idx = pickerViewable.findIndex((x) => x.id_media === m.id_media)
                            if (idx >= 0) setViewer({ source: 'picker', index: idx, playing: false })
                          }}
                          title={t('playlists.picker_preview')}
                          className="text-gray-300 hover:text-accent transition-sf shrink-0 p-1"
                        >
                          <Eye className="w-4 h-4" />
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            ))}
            {pickerCount === 0 && (
              <p className="text-sm text-gray-400 text-center py-8">{t('media.no_results')}</p>
            )}
            {/* Rappel : en accueil on ne montre volontairement qu'un échantillon. */}
            {isPickerLanding && pickerCount > 0 && (
              <p className="text-xs text-gray-500 text-center pt-3">
                {t('playlists.picker_landing_hint')}
              </p>
            )}
          </div>

          {/* Pied : ajout en lot de tous les contenus cochés */}
          <div className="shrink-0 flex items-center justify-between gap-3 border-t border-gray-100 pt-3">
            <span className="text-xs text-gray-500">
              {t('playlists.picker_selected', { count: pickedMedia.size })}
            </span>
            <Button
              size="sm"
              onClick={() => addItemsMutation.mutate(Array.from(pickedMedia))}
              disabled={pickedMedia.size === 0 || addItemsMutation.isPending}
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              {t('playlists.picker_add', { count: pickedMedia.size })}
            </Button>
          </div>
        </div>
      </Drawer>

      {/* Picker de sous-playlist (rotation) */}
      <Drawer
        open={plDrawerOpen}
        onClose={() => setPlDrawerOpen(false)}
        title={t('playlists.add_sub_playlist')}
      >
        <div className="space-y-4">
          <p className="text-xs text-gray-400">{t('playlists.sub_picker_hint')}</p>
          <input
            type="text"
            placeholder={t('common.search')}
            value={plSearch}
            onChange={(e) => setPlSearch(e.target.value)}
            className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
          {subError && <p className="text-sm text-danger">{subError}</p>}
          <div className="space-y-1 max-h-[60vh] overflow-y-auto">
            {allPlaylists
              .filter((p) => p.id_playlist !== Number(params.id))
              .filter((p) => !plSearch || p.playlist_name.toLowerCase().includes(plSearch.toLowerCase()))
              .map((p) => (
                <button
                  key={p.id_playlist}
                  type="button"
                  onClick={() => addSubMutation.mutate(p.id_playlist)}
                  disabled={addSubMutation.isPending}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded text-left transition-sf border border-transparent hover:bg-gray-50 hover:border-accent/30 disabled:opacity-50"
                >
                  <ListVideo className="w-4 h-4 text-gray-300 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-800 truncate">{p.playlist_name}</p>
                    <p className="text-xs text-gray-400">
                      {p.rotation_mode === 'one_sequential'
                        ? t('playlists.sub_rotation_seq', { k: p.items_per_turn ?? 1 })
                        : p.rotation_mode === 'one_random'
                          ? t('playlists.sub_rotation_rand', { k: p.items_per_turn ?? 1 })
                          : t('playlists.sub_rotation_all')}
                    </p>
                  </div>
                  <Plus className="w-4 h-4 text-gray-300 shrink-0" />
                </button>
              ))}
            {allPlaylists.length === 0 && (
              <p className="text-sm text-gray-400 text-center py-8">{t('common.no_results')}</p>
            )}
          </div>
        </div>
      </Drawer>

      {/* Tags d'un item (additif / override) §XVII */}
      <Drawer open={tagItem !== null} onClose={() => setTagItem(null)} title={t('tags.item_tags')}>
        {tagItem !== null && (
          <div data-write-perm="playlists:edit">
            <ItemTagsEditor idItem={tagItem} idPlaylist={params.id} onClose={() => setTagItem(null)} t={t} />
          </div>
        )}
      </Drawer>

      {/* Règles de diffusion d'un item (heure locale) § retours clients item 4.
          data-write-perm : le drawer étant rendu hors de <main>, il porte son
          propre marqueur pour que le nudge « lecture seule » couvre ses champs. */}
      <Drawer open={rulesItem !== null} onClose={() => setRulesItem(null)} title={t('playlists.rules_title')}>
        {rulesItem !== null && (
          <div data-write-perm="playlists:edit">
            <ItemRulesEditor idItem={rulesItem} idPlaylist={params.id} onClose={() => setRulesItem(null)} t={t} />
          </div>
        )}
      </Drawer>

      {/* Simulation du filtrage par tags §XVII */}
      <Drawer open={simOpen} onClose={() => setSimOpen(false)} title={t('tags.simulate')} width="w-[520px]">
        {simOpen && (
          <SimulationPanel
            idPlaylist={params.id}
            syncMode={pl?.sync_mode ?? 'wall_clock'}
            hasRules={pl?.has_item_rules ?? false}
            t={t}
          />
        )}
      </Drawer>
    </>
  )
}

// ── Éditeur de règles de diffusion d'un item (heure locale) ────────────────────
// P1 = règle 'default' (toggle limiter) ; P2 = overrides par cible (player/groupe).
type RuleDraft = {
  days: number[]
  time_start: string
  time_end: string
  date_from: string
  date_to: string
}
type OverrideDraft = RuleDraft & { scope: 'player' | 'player_group'; target_id: number | null }

const EMPTY_RULE: RuleDraft = { days: [], time_start: '', time_end: '', date_from: '', date_to: '' }

function ruleFromRead(r: ItemRuleRead): RuleDraft {
  return {
    days: r.days_of_week ?? [],
    time_start: r.time_start ? r.time_start.slice(0, 5) : '',
    time_end: r.time_end ? r.time_end.slice(0, 5) : '',
    date_from: r.date_from ?? '',
    date_to: r.date_to ?? '',
  }
}

function draftToApi(d: RuleDraft, scope: string, target_id: number | null) {
  return {
    rule_type: 'weekly',
    days_of_week: d.days.length ? d.days : null,
    time_start: d.time_start || null,
    time_end: d.time_end || null,
    date_from: d.date_from || null,
    date_to: d.date_to || null,
    scope,
    target_id,
  }
}

// Champs de règle réutilisables (jours + créneau + validité).
function RuleFields({ value, onChange, t }: {
  value: RuleDraft
  onChange: (v: RuleDraft) => void
  t: ReturnType<typeof useTranslations>
}) {
  const toggleDay = (i: number) =>
    onChange({ ...value, days: (value.days.includes(i) ? value.days.filter((d) => d !== i) : [...value.days, i]).sort() })
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label className="text-sm font-medium text-gray-700">{t('schedules.days_label')}</label>
        <div className="flex flex-wrap gap-1.5">
          {DAYS.map((d, i) => (
            <button key={d} type="button" onClick={() => toggleDay(i)}
              className={`px-3 py-1.5 rounded text-xs font-medium border transition-sf ${
                value.days.includes(i) ? 'bg-accent text-white border-accent' : 'bg-surface text-gray-600 border-gray-200 hover:border-accent'
              }`}>
              {t(`schedules.day_${d}`)}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-gray-400">{t('playlists.rule_days_hint')}</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Input label={t('schedules.time_start_label')} type="time" value={value.time_start}
               onChange={(e) => onChange({ ...value, time_start: e.target.value })} />
        <Input label={t('schedules.time_end_label')} type="time" value={value.time_end}
               onChange={(e) => onChange({ ...value, time_end: e.target.value })} />
      </div>
      <div className="space-y-1.5">
        <label className="text-sm font-medium text-gray-700">{t('playlists.rule_validity')}</label>
        <div className="grid grid-cols-2 gap-3">
          <Input type="date" value={value.date_from} onChange={(e) => onChange({ ...value, date_from: e.target.value })} />
          <Input type="date" value={value.date_to} onChange={(e) => onChange({ ...value, date_to: e.target.value })} />
        </div>
        <p className="text-[11px] text-gray-400">{t('playlists.rule_validity_hint')}</p>
      </div>
    </div>
  )
}

function ItemRulesEditor({
  idItem, idPlaylist, onClose, t,
}: {
  idItem: number
  idPlaylist: string
  onClose: () => void
  t: ReturnType<typeof useTranslations>
}) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery<ItemRuleRead[]>({
    queryKey: ['item-rules', idItem],
    queryFn: () => api.get<ItemRuleRead[]>(`/playlists/${idPlaylist}/items/${idItem}/rules`).then((r) => r.data),
  })
  const { data: players = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'], queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
  })
  const { data: groups = [] } = useQuery<PlayerGroupRead[]>({
    queryKey: ['player-groups'], queryFn: () => api.get<PlayerGroupRead[]>('/player-groups/').then((r) => r.data),
  })

  const [limited, setLimited] = useState<boolean | null>(null)
  const [defRule, setDefRule] = useState<RuleDraft | null>(null)
  const [overrides, setOverrides] = useState<OverrideDraft[] | null>(null)

  // Initialisation depuis les règles existantes.
  const defaultRead = data?.find((r) => r.scope === 'default')
  const isLimited = limited ?? (defaultRead !== undefined)
  const def = defRule ?? (defaultRead ? ruleFromRead(defaultRead) : EMPTY_RULE)
  const ovr = overrides ?? (data
    ? data.filter((r) => r.scope !== 'default').map((r) => ({
        ...ruleFromRead(r), scope: r.scope as 'player' | 'player_group', target_id: r.target_id,
      }))
    : [])

  const save = useMutation({
    mutationFn: () => {
      const body: ReturnType<typeof draftToApi>[] = []
      if (isLimited) body.push(draftToApi(def, 'default', null))
      for (const o of ovr) {
        if (o.target_id != null) body.push(draftToApi(o, o.scope, o.target_id))
      }
      return api.put(`/playlists/${idPlaylist}/items/${idItem}/rules`, body)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['item-rules', idItem] })
      qc.invalidateQueries({ queryKey: ['playlist', idPlaylist] })
      onClose()
    },
  })

  const setOvrAt = (i: number, patch: Partial<OverrideDraft>) =>
    setOverrides(ovr.map((o, j) => (j === i ? { ...o, ...patch } : o)))
  const addOverride = () =>
    setOverrides([...ovr, { ...EMPTY_RULE, scope: 'player', target_id: null }])
  const removeOverride = (i: number) => setOverrides(ovr.filter((_, j) => j !== i))

  if (isLoading) {
    return <div className="flex justify-center py-10"><span className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>
  }

  return (
    <div className="space-y-5">
      <p className="text-xs text-gray-400">{t('playlists.rules_hint')}</p>

      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input type="checkbox" checked={isLimited} onChange={(e) => setLimited(e.target.checked)}
               className="w-4 h-4 rounded border-gray-300" />
        <span className="text-sm text-gray-700">{t('playlists.rule_limit_toggle')}</span>
      </label>
      {!isLimited && <p className="text-xs text-gray-400 -mt-2">{t('playlists.rule_perpetual_hint')}</p>}

      {isLimited && (
        <div className="border-l-2 border-accent/20 pl-4">
          <RuleFields value={def} onChange={setDefRule} t={t} />
        </div>
      )}

      {/* Overrides par cible (P2) — un magasin/groupe peut suivre une règle différente */}
      <div className="space-y-3 pt-1 border-t border-gray-100">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-700">{t('playlists.rule_overrides')}</p>
            <p className="text-[11px] text-gray-400">{t('playlists.rule_overrides_hint')}</p>
          </div>
          <Button size="sm" variant="secondary" onClick={addOverride}>
            <Plus className="w-3.5 h-3.5 mr-1" />{t('playlists.rule_add_override')}
          </Button>
        </div>

        {ovr.map((o, i) => (
          <div key={i} className="rounded-lg border border-gray-200 p-3 space-y-3 bg-gray-50/50">
            <div className="flex items-center gap-2">
              <select value={o.scope}
                onChange={(e) => setOvrAt(i, { scope: e.target.value as 'player' | 'player_group', target_id: null })}
                className="text-xs border border-gray-200 rounded px-2 py-1.5 bg-surface">
                <option value="player">{t('playlists.rule_target_player')}</option>
                <option value="player_group">{t('playlists.rule_target_group')}</option>
              </select>
              <select value={o.target_id ?? ''}
                onChange={(e) => setOvrAt(i, { target_id: e.target.value ? Number(e.target.value) : null })}
                className="flex-1 text-xs border border-gray-200 rounded px-2 py-1.5 bg-surface">
                <option value="">{t('playlists.rule_pick_target')}</option>
                {(o.scope === 'player' ? players.map((p) => ({ id: p.id_player, name: p.player_name }))
                  : groups.map((g) => ({ id: g.id_group, name: g.group_name }))
                ).map((opt) => <option key={opt.id} value={opt.id}>{opt.name}</option>)}
              </select>
              <button onClick={() => removeOverride(i)} className="text-gray-300 hover:text-danger shrink-0" title={t('common.delete')}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
            <RuleFields value={o} onChange={(v) => setOvrAt(i, v)} t={t} />
          </div>
        ))}
      </div>

      <div className="rounded-md bg-amber-500/10 dark:bg-amber-500/15 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-300">
        {t('playlists.rule_local_time_note')}
      </div>

      <Button data-write-action onClick={() => save.mutate()} loading={save.isPending} className="w-full">{t('common.save')}</Button>
    </div>
  )
}

// ── Éditeur de tags d'un item (additif + override par namespace) ───────────────
function ItemTagsEditor({
  idItem, idPlaylist, onClose, t,
}: {
  idItem: number
  idPlaylist: string
  onClose: () => void
  t: ReturnType<typeof useTranslations>
}) {
  const qc = useQueryClient()
  const { data: namespaces = [] } = useTagNamespaces()
  const { data } = useQuery<PlaylistItemTags>({
    queryKey: ['item-tags', idItem],
    queryFn: () => api.get<PlaylistItemTags>(`/playlist-items/${idItem}/tags`).then((r) => r.data),
  })
  const [tags, setTags] = useState<Set<number> | null>(null)
  const [overrides, setOverrides] = useState<Set<number> | null>(null)
  const selTags = tags ?? new Set(data?.tags ?? [])
  const selOvr = overrides ?? new Set(data?.ns_overrides ?? [])

  const save = useMutation({
    mutationFn: () => api.put(`/playlist-items/${idItem}/tags`, {
      tags: Array.from(selTags), ns_overrides: Array.from(selOvr),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['item-tags', idItem] })
      qc.invalidateQueries({ queryKey: ['playlist', idPlaylist] })
      onClose()
    },
  })

  const toggleTag = (id: number) => {
    const next = new Set(selTags); next.has(id) ? next.delete(id) : next.add(id); setTags(next)
  }
  const toggleOvr = (idNs: number) => {
    const next = new Set(selOvr); next.has(idNs) ? next.delete(idNs) : next.add(idNs); setOverrides(next)
  }

  return (
    <div className="space-y-5">
      {data && Object.keys(data.effective).length > 0 && (
        <div className="rounded-md bg-gray-50 px-3 py-2 text-xs space-y-1">
          <p className="font-medium text-gray-600">{t('tags.effective')}</p>
          {Object.entries(data.effective).map(([ns, vals]) => (
            <p key={ns} className="text-gray-500"><span className="text-gray-400">{ns}: </span>{vals.join(', ')}</p>
          ))}
        </div>
      )}
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">{t('tags.item_additional')}</p>
        <TagPicker namespaces={namespaces} selected={selTags} onToggle={toggleTag} emptyLabel={t('tags.no_namespaces')} />
      </div>
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">{t('tags.override_ns')}</p>
        <p className="text-[11px] text-gray-400 mb-2">{t('tags.override_hint')}</p>
        <div className="flex flex-wrap gap-1.5">
          {namespaces.map((ns) => {
            const on = selOvr.has(ns.id_namespace)
            return (
              <button key={ns.id_namespace} type="button" onClick={() => toggleOvr(ns.id_namespace)}
                className={`px-2 py-1 rounded text-xs font-medium border transition-sf ${
                  on ? 'bg-accent text-white border-transparent' : 'bg-surface text-gray-600 border-gray-300 hover:bg-gray-50'
                }`}>
                {ns.label ?? ns.namespace_key}
              </button>
            )
          })}
        </div>
      </div>
      <Button data-write-action onClick={() => save.mutate()} loading={save.isPending} className="w-full">{t('common.save')}</Button>
    </div>
  )
}

// ── Panneau de simulation du filtrage par player ───────────────────────────────
function SimulationPanel({
  idPlaylist, syncMode, hasRules, t,
}: {
  idPlaylist: string
  syncMode: string
  hasRules: boolean
  t: ReturnType<typeof useTranslations>
}) {
  // wall_clock = timeline déterministe ; loop = simulation de filtrage par tags (+ badge règle).
  const [mode, setMode] = useState<'timeline' | 'tags'>(syncMode === 'wall_clock' ? 'timeline' : 'tags')

  return (
    <div className="space-y-4">
      {syncMode === 'wall_clock' && (
        <div className="flex gap-1.5">
          {(['timeline', 'tags'] as const).map((m) => (
            <button key={m} type="button" onClick={() => setMode(m)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-sf ${
                mode === m ? 'bg-accent text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {t(m === 'timeline' ? 'tags.sim_timeline' : 'tags.sim_tags')}
            </button>
          ))}
        </div>
      )}

      {syncMode !== 'wall_clock' && hasRules && (
        <p className="inline-flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-300 bg-amber-500/10 dark:bg-amber-500/15 border border-amber-400/20 dark:border-amber-500/30 rounded px-2 py-1.5">
          <CalendarClock className="w-3.5 h-3.5 shrink-0" />
          {t('tags.sim_loop_has_rules')}
        </p>
      )}

      {mode === 'timeline' && syncMode === 'wall_clock'
        ? <TimelineSim idPlaylist={idPlaylist} t={t} />
        : <TagSim idPlaylist={idPlaylist} t={t} />}
    </div>
  )
}

// Timeline déterministe : ordre + heure de passage prévue (honore les règles).
function TimelineSim({ idPlaylist, t }: { idPlaylist: string; t: ReturnType<typeof useTranslations> }) {
  const { data: players = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'], queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
  })
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [startTime, setStartTime] = useState('00:00')
  const [playerId, setPlayerId] = useState<string>('')
  const sim = useMutation({
    mutationFn: () => api.post<SimulateTimelineResult>(`/playlists/${idPlaylist}/simulate-timeline`, {
      date, start_time: startTime, player_id: playerId ? Number(playerId) : null,
    }).then((r) => r.data),
  })

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-400">{t('tags.sim_timeline_hint')}</p>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-gray-500">
          {t('tags.sim_date')}
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="mt-1 w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40" />
        </label>
        <label className="text-xs text-gray-500">
          {t('tags.sim_start')}
          <input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)}
            className="mt-1 w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40" />
        </label>
      </div>
      <label className="block text-xs text-gray-500">
        {t('tags.sim_player_optional')}
        <select value={playerId} onChange={(e) => setPlayerId(e.target.value)}
          className="mt-1 w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
          <option value="">{t('tags.sim_all_players')}</option>
          {players.map((p) => <option key={p.id_player} value={p.id_player}>{p.player_name}</option>)}
        </select>
      </label>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => sim.mutate()} loading={sim.isPending}>
          {t('tags.simulate_run')}
        </Button>
        {sim.data && sim.data.segments.length > 0 && (
          <button
            type="button"
            onClick={() => downloadCsv(
              `simulation_${date}_${startTime.replace(':', 'h')}.csv`,
              [
                [t('tags.sim_csv_start'), t('tags.sim_csv_end'), t('tags.sim_csv_content'), t('tags.sim_csv_type'), t('tags.sim_csv_duration_s')],
                ...sim.data!.segments.map((s) =>
                  [s.start, s.end, s.media_name ?? `#${s.id_media}`, s.media_type ?? '', Math.round(s.duration_ms / 1000)]),
              ],
            )}
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
          >
            <Download className="w-3.5 h-3.5" />
            {t('tags.sim_export')}
          </button>
        )}
      </div>

      {sim.data && (
        sim.data.segments.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-6">{t('tags.sim_no_segments')}</p>
        ) : (
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="max-h-80 overflow-y-auto divide-y divide-gray-50">
              {sim.data.segments.map((s, i) => (
                <div key={i} className="flex items-center gap-3 px-3 py-1.5 text-sm">
                  <span className="font-mono text-xs text-accent shrink-0 w-20">{s.start}</span>
                  <span className="text-gray-700 truncate">{s.media_name ?? `#${s.id_media}`}</span>
                </div>
              ))}
            </div>
            {sim.data.truncated && (
              <p className="px-3 py-1.5 text-[11px] text-gray-400 bg-gray-50 border-t border-gray-100">{t('tags.sim_truncated')}</p>
            )}
          </div>
        )
      )}
    </div>
  )
}

// Simulation du filtrage par tags pour des players (existant).
function TagSim({ idPlaylist, t }: { idPlaylist: string; t: ReturnType<typeof useTranslations> }) {
  const { data: players = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'], queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
  })
  const [selected, setSelected] = useState<number[]>([])
  const sim = useMutation({
    mutationFn: () => api.post<SimulatePlayerResult[]>(`/playlists/${idPlaylist}/simulate-tags`, { player_ids: selected }).then((r) => r.data),
  })

  const toggle = (id: number) =>
    setSelected((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-400">{t('tags.simulate_hint')}</p>
      <div className="flex flex-wrap gap-1.5">
        {players.map((p) => (
          <button key={p.id_player} type="button" onClick={() => toggle(p.id_player)}
            className={`px-2 py-1 rounded text-xs font-medium border transition-sf ${
              selected.includes(p.id_player) ? 'bg-accent text-white border-transparent' : 'bg-surface text-gray-600 border-gray-300 hover:bg-gray-50'
            }`}>
            {p.player_name}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => sim.mutate()} loading={sim.isPending} disabled={selected.length === 0}>
          {t('tags.simulate_run')}
        </Button>
        {sim.data && sim.data.length > 0 && (
          <button
            type="button"
            onClick={() => downloadCsv('simulation_tags.csv', [
              [t('tags.sim_csv_player'), t('tags.sim_csv_content'), t('tags.sim_csv_matched')],
              ...sim.data!.flatMap((res) => res.items.map((it) => [
                res.player_name ?? `#${res.id_player}`, it.media_name ?? `#${it.id_media}`, it.matched ? '1' : '0',
              ])),
            ])}
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
          >
            <Download className="w-3.5 h-3.5" />
            {t('tags.sim_export')}
          </button>
        )}
      </div>

      {sim.data && (
        <div className="space-y-4">
          {sim.data.map((res) => {
            const matched = res.items.filter((i) => i.matched).length
            return (
              <div key={res.id_player} className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="px-3 py-2 bg-gray-50 border-b border-gray-100 text-sm font-medium text-gray-800 flex items-center justify-between">
                  <span>{res.player_name}</span>
                  <span className="text-xs text-gray-400">{t('tags.simulate_count', { matched, total: res.items.length })}</span>
                </div>
                <div className="divide-y divide-gray-50">
                  {res.items.map((it) => (
                    <div key={it.id_item} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                      {it.matched
                        ? <Check className="w-3.5 h-3.5 text-success shrink-0" />
                        : <X className="w-3.5 h-3.5 text-gray-300 shrink-0" />}
                      <span className={it.matched ? 'text-gray-700' : 'text-gray-400 line-through'}>{it.media_name ?? `#${it.id_media}`}</span>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Gouvernance §XVIII — contenu gouverné (D6/D7) ────────────────────────────
// Rattache la playlist à un nœud : l'écriture devient réservée aux administrateurs
// de ce nœud (ou d'un ancêtre) et, si le nœud exige la modération, la publication
// passe par une approbation §XXI. La carte disparaît si l'org n'a aucun nœud.
function GovernanceCard({
  idNode, readonly, moderated, onChange, t,
}: {
  idNode: number | null
  readonly: boolean
  moderated: boolean
  onChange: (id: number | null) => void
  t: ReturnType<typeof useTranslations>
}) {
  const { data: nodes = [] } = useGovernanceNodes()
  if (nodes.length === 0) return null

  return (
    <div className="bg-surface border border-gray-200 rounded-lg p-4 space-y-3 shadow-sf-card">
      <div className="flex items-center gap-2">
        <Network className="w-4 h-4 text-gray-400" />
        <h3 className="text-sm font-semibold text-gray-900">{t('governance.content_card_title')}</h3>
        {moderated && (
          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-700 dark:text-amber-300 bg-amber-500/10 px-1.5 py-0.5 rounded">
            <ShieldCheck className="w-3 h-3" />
            {t('governance.content_moderated_badge')}
          </span>
        )}
      </div>
      <NodeSelect value={idNode} onChange={onChange} disabled={readonly} />
      {moderated && (
        <p className="text-xs text-amber-600 dark:text-amber-300">
          {t('governance.content_moderated_hint')}
        </p>
      )}
    </div>
  )
}
