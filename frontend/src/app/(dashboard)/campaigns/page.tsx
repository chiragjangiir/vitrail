'use client'

// Retail Media §2.8 (S1) — campagnes annonceurs : liste + drawer création/édition
// (infos, cibles canoniques, créatifs, transitions de statut).
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BadgeEuro, BarChart2, Trash2, Plus, Play, Pause, Check, CheckCircle2, ChevronDown, ChevronRight, FolderTree as FolderTreeIcon, MapPin, Music, Upload, X, XCircle } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import NumberField from '@/components/ui/NumberField'
import SearchInput from '@/components/ui/SearchInput'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'
import { useCreateShortcut } from '@/lib/useCreateShortcut'
import { useSearchPrefill } from '@/lib/useSearchPrefill'
import FolderTree, { type FolderFilter } from '../media/components/FolderTree'
import CampaignCalendar, { type OccupancyDay } from './CampaignCalendar'
import ImportOrderDrawer from './ImportOrderDrawer'
import SiteMapSelector from '@/components/maps/SiteMapSelector'

interface TargetSpec { target_type: string; target_id?: number | null; tag_expr?: Record<string, string[]> }
interface Creative {
  id_creative: number; id_media: number; duration_ms: number | null; weight: number
  status: string; approval_status: string
  media_name?: string | null; media_type?: string | null; media_duration_ms?: number | null
}
interface Campaign {
  id_campaign: number; id_advertiser: number; campaign_name: string; status: string
  starts_on: string; ends_on: string; daily_hours: { start: string; end: string } | null
  sov_percent: number; pricing_model: string; price_amount: number | null; price_currency: string
  cpm_rate: number | null; priority: number; advertiser_name?: string | null
  // S2 audio (migr 0094) : 'audio' = spots dans la rotation musicale §XIX, vendus en spots/h
  campaign_kind: 'visual' | 'audio'; spots_per_hour: number | null
  creative_count: number; target_player_count: number
  // `target_name` est résolu par le SERVEUR (audit menu ⑨) : la liste ne dépend plus
  // du chargement complet des sites/groupes/ÉCRANS pour nommer une cible.
  targets: { id_target: number; target_type: string; target_id: number | null; target_name?: string | null }[]
  // Demande d'approbation §XXI active (C1) — badge + gate du bouton Publier.
  approval_request?: { id_request: number; status: string } | null
}
interface Advertiser { id_advertiser: number; advertiser_name: string; id_folder?: number | null }
interface OccupancyRow {
  id_player: number; player_name: string | null; current_pct: number; projected_pct: number; cap_pct?: number
  // S2 audio : détail spots/h (les pct sont alors relatifs au plafond)
  current_spots?: number | null; projected_spots?: number | null; cap_spots?: number | null
}
interface PriceEstimate { estimated_price: number; priced_players: number; unpriced_players: number; days: number }
interface FeasibilityRow {
  id_player: number; player_name: string | null; max_sov_pct: number
  home_items: number; home_duration_ms: number
}
interface Feasibility {
  max_sov_pct: number; creative_duration_ms: number
  players: FeasibilityRow[]; unresolved_players: number
}
interface OccupancyCheck {
  blocked: boolean; warning: boolean; max_projected_pct: number; players: OccupancyRow[]
  price?: PriceEstimate | null
  // SOV réalisable (anti-martèlement) — null si aucune boucle courante résolue
  achievable?: Feasibility | null
  // S2 audio : spots/h encore vendables (min du plafond restant des écrans ciblés)
  achievable_spots_per_hour?: number | null
}
interface InventoryRow { id_player: number; player_name: string; occupied_pct: number }
interface SiteLite { id_site: number; site_name: string; latitude: number | null; longitude: number | null }
interface GroupLite { id_group: number; group_name: string; player_ids?: number[] }
interface SiteGroupLite { id_site_group: number; group_name: string; site_ids?: number[] }
interface PlayerLite { id_player: number; player_name: string; player_role?: string; id_site?: number | null }
interface MediaLite {
  id_media: number; media_name: string; media_type: string; duration_ms?: number | null
  thumbnail_url?: string | null; transcode_status?: string
}

const BADGE: Record<string, 'online' | 'info' | 'pending' | 'warning' | 'done' | 'offline'> = {
  live: 'online', scheduled: 'info', draft: 'pending',
  paused: 'warning', completed: 'done', cancelled: 'offline',
}

// Section repliable du drawer (même pattern que MediaDrawer) + pastille de comptage.
function CollapsibleSection({
  title, badge, defaultOpen = false, children,
}: {
  title: ReactNode
  badge?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
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

function CountPill({ children }: { children: ReactNode }) {
  return (
    <span className="px-2 py-0.5 rounded-full bg-accent/10 text-accent text-xs font-medium whitespace-nowrap">
      {children}
    </span>
  )
}

const emptyForm = {
  campaign_name: '', id_advertiser: 0, starts_on: '', ends_on: '',
  hours_start: '', hours_end: '', sov_percent: 10, pricing_model: 'sov',
  price_amount: '', priority: 50,
  campaign_kind: 'visual' as 'visual' | 'audio', spots_per_hour: 6,
}

export default function CampaignsPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const router = useRouter()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<Campaign | null>(null)
  const [search, setSearch] = useState('')
  useSearchPrefill(setSearch)
  const [form, setForm] = useState({ ...emptyForm })
  // Multi-cibles (union canonique — le backend accepte une liste depuis S1)
  const [targets, setTargets] = useState<{ type: string; id: number | null }[]>([{ type: 'org', id: null }])
  const [err, setErr] = useState('')
  // Picker de créatifs (drawer dédié, même UX que « Ajouter un média » des playlists) :
  // scope 'advertiser' = sous-arbre du dossier de l'annonceur (défaut), 'all' = médiathèque
  // complète (recherche server-side + arbre de dossiers).
  const [creativeScope, setCreativeScope] = useState<'advertiser' | 'all'>('advertiser')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerSearchInput, setPickerSearchInput] = useState('')
  const [pickerSearch, setPickerSearch] = useState('')
  const [pickerFolder, setPickerFolder] = useState<FolderFilter>('all')
  const [pickerFoldersOpen, setPickerFoldersOpen] = useState(false)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [pickerDur, setPickerDur] = useState('')
  const [pickerWeight, setPickerWeight] = useState(1)
  useEffect(() => {
    const id = setTimeout(() => setPickerSearch(pickerSearchInput.trim()), 300)
    return () => clearTimeout(id)
  }, [pickerSearchInput])

  const { data: campaigns = [], isLoading } = useQuery<Campaign[]>({
    queryKey: ['campaigns'],
    queryFn: () => api.get<Campaign[]>('/campaigns/').then((r) => r.data),
  })
  const { data: advertisers = [] } = useQuery<Advertiser[]>({
    queryKey: ['advertisers'],
    queryFn: () => api.get<Advertiser[]>('/advertisers/').then((r) => r.data),
  })
  const { data: sites = [] } = useQuery<SiteLite[]>({
    queryKey: ['sites'],
    queryFn: () => api.get<SiteLite[]>('/sites').then((r) => r.data),
  })
  const { data: groups = [] } = useQuery<GroupLite[]>({
    queryKey: ['player-groups'],
    queryFn: () => api.get<GroupLite[]>('/player-groups/').then((r) => r.data),
  })
  const { data: siteGroups = [] } = useQuery<SiteGroupLite[]>({
    queryKey: ['site-groups'],
    queryFn: () => api.get<SiteGroupLite[]>('/site-groups/').then((r) => r.data),
  })
  // ⚠️ Chargé SEULEMENT quand le tiroir est ouvert (audit menu ⑨) : cette requête rend
  // TOUT le parc (~1,9 Ko par écran, soit ~1,8 Mo à 1000 écrans) et ne sert qu'au
  // ciblage. La LISTE n'en a plus besoin depuis que le serveur nomme les cibles.
  const { data: players = [] } = useQuery<PlayerLite[]>({
    queryKey: ['players-lite'],
    queryFn: () => api.get<{ players?: PlayerLite[] } | PlayerLite[]>('/players/').then((r) =>
      Array.isArray(r.data) ? r.data : (r.data.players ?? [])),
    enabled: drawerOpen,
  })
  // Dossier « Annonceurs/<nom> » de l'annonceur sélectionné → le picker filtre son
  // sous-arbre par défaut (échappatoire : toute la médiathèque, contenus génériques).
  const advFolder = advertisers.find((a) => a.id_advertiser === Number(form.id_advertiser))?.id_folder ?? null
  const effectiveScope = advFolder ? creativeScope : 'all'
  // Type de la campagne éditée (S2 audio) : campagne audio = créatifs AUDIO uniquement.
  const isAudio = (editing?.campaign_kind ?? form.campaign_kind) === 'audio'
  // Filtrage des cibles par CAPACITÉ de diffusion du type de campagne (retour Ed 21/07) :
  //  - AUDIO  → players « Audio seul » (audio) ou « Contenus + Audio » (mixed) ;
  //  - VISUEL → players « Contenus » (content) ou « Contenus + Audio » (mixed) — on EXCLUT
  //    les players audio-seul, incapables d'afficher un créatif visuel.
  // Un player « mixed » diffuse les deux → présent dans les deux cas.
  // PLAYERS : filtre strict par capacité. AUDIO = test EXPLICITE (audio|mixed) — un
  // rôle absent/undefined = player Contenus, jamais audio. VISUEL = tout sauf audio-seul.
  const capablePlayerIds = new Set(
    players
      .filter((p) => isAudio
        ? (p.player_role === 'audio' || p.player_role === 'mixed')
        : p.player_role !== 'audio')
      .map((p) => p.id_player))
  const capableSiteIds = new Set(
    players.filter((p) => capablePlayerIds.has(p.id_player) && p.id_site != null)
      .map((p) => p.id_site as number))
  const sitesWithPlayers = new Set(
    players.filter((p) => p.id_site != null).map((p) => p.id_site as number))
  const knownPlayerIds = new Set(players.map((p) => p.id_player))
  // SITES/GROUPES : AUDIO = strict (≥1 player capable — comme l'existant) ; VISUEL =
  // lenient (on ne masque QUE ce dont on peut PROUVER l'incapacité = a des players, tous
  // audio-seul). Un site/groupe sans players connus reste visible en visuel (évite de le
  // faire disparaître pendant le chargement / avant remontée des players).
  const siteOk = (sid: number) => isAudio
    ? capableSiteIds.has(sid)
    : (capableSiteIds.has(sid) || !sitesWithPlayers.has(sid))
  const groupOk = (pids: number[]) => isAudio
    ? pids.some((id) => capablePlayerIds.has(id))
    : (pids.length === 0 || pids.some((id) => capablePlayerIds.has(id) || !knownPlayerIds.has(id)))
  const targetPlayers = players.filter((p) => capablePlayerIds.has(p.id_player))
  const targetSites = sites.filter((s) => siteOk(s.id_site))
  const targetSiteGroups = siteGroups.filter(
    (g) => (g.site_ids ?? []).length === 0 || (g.site_ids ?? []).some((id) => siteOk(id)))
  const targetGroups = groups.filter((g) => groupOk(g.player_ids ?? []))
  const { data: pickerMedia = [], isLoading: pickerLoading } = useQuery<MediaLite[]>({
    queryKey: ['media', 'campaign-picker', effectiveScope, advFolder, pickerFolder, pickerSearch, isAudio],
    queryFn: async () => {
      const params: Record<string, unknown> = { limit: 200 }
      if (pickerSearch) params.q = pickerSearch
      if (effectiveScope === 'advertiser' && advFolder) {
        params.id_folder = advFolder
        params.subtree = true
      } else if (pickerFolder === 'unfiled') {
        params.unfiled = true
      } else if (pickerFolder !== 'all') {
        params.id_folder = pickerFolder
      }
      const types = isAudio ? ['audio'] : ['video', 'image']
      const results = await Promise.all(types.map((mt) =>
        api.get<MediaLite[]>('/media/', { params: { ...params, media_type: mt } })))
      return results.flatMap((r) => r.data)
        .filter((m) => (m.transcode_status ?? 'done') === 'done')
        .sort((a, b) => a.media_name.localeCompare(b.media_name))
    },
    enabled: pickerOpen && !!editing,
  })
  const { data: creatives = [] } = useQuery<Creative[]>({
    queryKey: ['campaign-creatives', editing?.id_campaign],
    queryFn: () => api.get<Creative[]>(`/campaigns/${editing!.id_campaign}/creatives`).then((r) => r.data),
    enabled: !!editing,
  })
  // S2 — projection d'occupation SOV (warning ≥ 80 %, blocage > 100 %) dès que la
  // campagne est datée/ciblée. L'autorité reste le serveur au moment du publish.
  const targetsValid = targets.length > 0 && targets.every((tg) => tg.type === 'org' || tg.id != null)
  const occReady = drawerOpen && !!form.starts_on && !!form.ends_on && targetsValid
    && (isAudio ? Number(form.spots_per_hour) > 0 : Number(form.sov_percent) > 0)
  const { data: occ } = useQuery<OccupancyCheck>({
    queryKey: ['campaign-occupancy', form.starts_on, form.ends_on, form.sov_percent,
               form.campaign_kind, form.spots_per_hour,
               JSON.stringify(targets), editing?.id_campaign, form.id_advertiser],
    queryFn: () => api.post<OccupancyCheck>('/campaigns/occupancy-check', {
      starts_on: form.starts_on, ends_on: form.ends_on,
      sov_percent: Number(form.sov_percent) || 10,
      campaign_kind: isAudio ? 'audio' : 'visual',
      spots_per_hour: isAudio ? Number(form.spots_per_hour) : null,
      targets: buildTargets(),
      exclude_id_campaign: editing?.id_campaign ?? null,
      // Exclusion concurrentielle #10 : projection + devis scopés à l'annonceur
      id_advertiser: form.id_advertiser || null,
    }).then((r) => r.data),
    enabled: occReady,
  })
  const [overbook, setOverbook] = useState(false)
  const { data: inventory = [] } = useQuery<InventoryRow[]>({
    queryKey: ['campaign-inventory'],
    queryFn: () => api.get<InventoryRow[]>('/campaigns/inventory').then((r) => r.data),
  })
  const [showInventory, setShowInventory] = useState(false)
  // S6 — import de campagne par fichier JSON (ordre d'insertion annonceur)
  const [importOpen, setImportOpen] = useState(false)
  // S7 Phase A — sélection des sites cibles sur la carte (second drawer)
  const [mapPickerOpen, setMapPickerOpen] = useState(false)
  const [mapSelection, setMapSelection] = useState<Set<number>>(new Set())
  // Sélection PAR ÉCRAN dans le map picker (retour Ed 21/07, toujours dispo pour le CM) :
  //  - `mapPlayers` = players ciblés individuellement (sites PARTIELS) ;
  //  - `mapExpandedSite` = site déplié dont on coche les écrans (via recherche/recentrage).
  const [mapPlayers, setMapPlayers] = useState<Set<number>>(new Set())
  const [mapExpandedSite, setMapExpandedSite] = useState<number | null>(null)
  // S6 — calendrier des campagnes (occupation par jour + barres par statut)
  const [showCalendar, setShowCalendar] = useState(false)
  const [calCursor, setCalCursor] = useState(() => { const d = new Date(); return { y: d.getFullYear(), m: d.getMonth() } })
  const calFrom = `${calCursor.y}-${String(calCursor.m + 1).padStart(2, '0')}-01`
  const calTo = new Date(calCursor.y, calCursor.m + 1, 0)
  const calToIso = `${calCursor.y}-${String(calCursor.m + 1).padStart(2, '0')}-${String(calTo.getDate()).padStart(2, '0')}`
  const { data: occDaily } = useQuery<{ days: OccupancyDay[] }>({
    queryKey: ['campaign-occupancy-daily', calFrom, calToIso],
    queryFn: () => api.get<{ days: OccupancyDay[] }>(
      `/campaigns/occupancy-daily?date_from=${calFrom}&date_to=${calToIso}`).then((r) => r.data),
    enabled: showCalendar,
  })
  // S5 — approbation des créatifs (flag org, défaut OFF). Toggle réservé org-admin
  // (le serveur répond 403 sinon).
  const { data: cSettings } = useQuery<{
    creative_approval: boolean; sov_daily_rate: number | null
    max_creatives: number; creative_max_mb: number
    portal_player_selection: boolean; creative_max_duration_s: number | null
    audio_spots_cap: number; audio_spot_daily_rate: number | null
  }>({
    queryKey: ['campaign-settings'],
    queryFn: () => api.get<{
      creative_approval: boolean; sov_daily_rate: number | null
      max_creatives: number; creative_max_mb: number
      portal_player_selection: boolean; creative_max_duration_s: number | null
      audio_spots_cap: number; audio_spot_daily_rate: number | null
    }>('/campaigns/settings').then((r) => r.data),
  })
  const approvalOn = cSettings?.creative_approval ?? false
  const [settingsErr, setSettingsErr] = useState('')

  const buildTargets = (): TargetSpec[] =>
    targets.map((tg) => tg.type === 'org'
      ? { target_type: 'org' }
      : { target_type: tg.type, target_id: tg.id })

  const buildBody = () => ({
    campaign_name: form.campaign_name,
    id_advertiser: Number(form.id_advertiser),
    starts_on: form.starts_on,
    ends_on: form.ends_on,
    daily_hours: form.hours_start && form.hours_end ? { start: form.hours_start, end: form.hours_end } : null,
    sov_percent: Number(form.sov_percent) || 10,
    pricing_model: isAudio ? 'flat' : form.pricing_model,
    price_amount: form.price_amount === '' ? null : Number(form.price_amount),
    priority: Number(form.priority),
    targets: buildTargets(),
    // S2 audio : cadence vendue ; le TYPE n'est posé qu'à la création (immuable ensuite)
    ...(isAudio ? { spots_per_hour: Number(form.spots_per_hour) } : {}),
    ...(editing ? { overbook_override: overbook } : { campaign_kind: form.campaign_kind }),
  })

  const openCreate = () => {
    setEditing(null)
    setForm({ ...emptyForm, id_advertiser: advertisers[0]?.id_advertiser ?? 0 })
    setTargets([{ type: 'org', id: null }])
    setCreativeScope('advertiser')
    setErr('')
    setDrawerOpen(true)
  }
  useCreateShortcut(openCreate)

  const openEdit = (c: Campaign) => {
    setEditing(c)
    setForm({
      campaign_name: c.campaign_name, id_advertiser: c.id_advertiser,
      starts_on: c.starts_on, ends_on: c.ends_on,
      hours_start: c.daily_hours?.start ?? '', hours_end: c.daily_hours?.end ?? '',
      sov_percent: Number(c.sov_percent), pricing_model: c.pricing_model,
      price_amount: c.price_amount == null ? '' : String(c.price_amount), priority: c.priority,
      campaign_kind: c.campaign_kind ?? 'visual',
      spots_per_hour: c.spots_per_hour ?? 6,
    })
    setTargets(c.targets.length
      ? c.targets.map((tg) => ({ type: tg.target_type, id: tg.target_id }))
      : [{ type: 'org', id: null }])
    setCreativeScope('advertiser')
    setErr('')
    setOverbook((c as Campaign & { overbook_override?: boolean }).overbook_override ?? false)
    setDrawerOpen(true)
  }

  const onApiError = (e: unknown) => setErr(
    (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('common.error'))

  const save = useMutation({
    mutationFn: () => editing
      ? api.put(`/campaigns/${editing.id_campaign}`, buildBody())
      : api.post('/campaigns/', buildBody()),
    onSuccess: ({ data }) => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      setErr('')
      // Création : rester ouvert pour ajouter les créatifs. Édition : rafraîchir
      // la pastille players ciblés (le PUT renvoie le count résolu à jour).
      setEditing(data as Campaign)
    },
    onError: onApiError,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/campaigns/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['campaigns'] }); setDrawerOpen(false) },
  })
  const changeStatus = useMutation({
    mutationFn: ({ id, action }: { id: number; action: string }) =>
      api.post(`/campaigns/${id}/status`, { action }),
    onSuccess: ({ data }) => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      if (editing) setEditing(data as Campaign)
      setErr('')
    },
    onError: onApiError,
  })
  // Approval Workflow §XXI (C1) : soumettre la campagne draft à validation.
  const submitApproval = useMutation({
    mutationFn: (id: number) => api.post('/approvals/', {
      resource_type: 'campaign', resource_id: id,
    }),
    onSuccess: ({ data }) => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      qc.invalidateQueries({ queryKey: ['approvals'] })
      if (editing) setEditing({
        ...editing,
        approval_request: {
          id_request: (data as { id_request: number }).id_request,
          status: (data as { status: string }).status,
        },
      })
      setErr('')
    },
    onError: onApiError,
  })
  const addCreatives = useMutation({
    mutationFn: async () => {
      const duration_ms = pickerDur === '' ? null : Number(pickerDur) * 1000
      for (const id of Array.from(picked)) {
        await api.post(`/campaigns/${editing!.id_campaign}/creatives`, {
          id_media: id, duration_ms, weight: Number(pickerWeight) || 1,
        })
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-creatives', editing?.id_campaign] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      setPickerOpen(false)
      setErr('')
    },
    onError: (e: unknown) => {
      // Les créatifs déjà postés avant l'erreur sont conservés — rafraîchir la liste.
      qc.invalidateQueries({ queryKey: ['campaign-creatives', editing?.id_campaign] })
      onApiError(e)
      setPickerOpen(false)
    },
  })

  const openPicker = () => {
    setPicked(new Set())
    setPickerSearchInput('')
    setPickerSearch('')
    setPickerFolder('all')
    setPickerFoldersOpen(false)
    setPickerDur('')
    setPickerWeight(1)
    setCreativeScope('advertiser')
    setPickerOpen(true)
  }

  const togglePick = (id: number) => {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Map picker — exclusivité site ENTIER ⟷ site PARTIEL (écrans) par site.
  const toggleMapWholeSite = (sid: number) => {
    setMapSelection((prev) => {
      const next = new Set(prev)
      if (next.has(sid)) { next.delete(sid); return next }
      next.add(sid)
      // Site entier → on efface la sélection partielle d'écrans de ce site.
      setMapPlayers((pp) => {
        const np = new Set(pp)
        players.filter((p) => p.id_site === sid).forEach((p) => np.delete(p.id_player))
        return np
      })
      return next
    })
  }
  const toggleMapPlayer = (sid: number, pid: number) => {
    // Cocher un écran précis → le site n'est plus « entier ».
    setMapSelection((prev) => {
      if (!prev.has(sid)) return prev
      const next = new Set(prev); next.delete(sid); return next
    })
    setMapPlayers((prev) => {
      const next = new Set(prev)
      if (next.has(pid)) next.delete(pid); else next.add(pid)
      return next
    })
  }

  // Une image sans durée native exige une durée d'affichage explicite (règle backend).
  const pickedNeedsDuration = pickerDur === '' && Array.from(picked).some((id) => {
    const m = pickerMedia.find((x) => x.id_media === id)
    return m?.media_type === 'image' && !m?.duration_ms
  })
  const removeCreative = useMutation({
    mutationFn: (id: number) => api.delete(`/campaigns/creatives/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-creatives', editing?.id_campaign] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
  const toggleApproval = useMutation({
    mutationFn: (v: boolean) => api.put('/campaigns/settings', { creative_approval: v }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['campaign-settings'] }); setSettingsErr('') },
    onError: (e: unknown) => setSettingsErr(
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('common.error')),
  })
  // Inventaire v2 : tarif SOV par défaut de l'org (devis) — null explicite = désactivé.
  const saveRate = useMutation({
    mutationFn: (v: number | null) => api.put('/campaigns/settings', { sov_daily_rate: v }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['campaign-settings'] }); setSettingsErr('') },
    onError: (e: unknown) => setSettingsErr(
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('common.error')),
  })
  // Quotas d'upload du portail annonceur (0084) : nb de créatifs + taille max (Mo).
  const saveQuota = useMutation({
    mutationFn: (body: {
      max_creatives?: number; creative_max_mb?: number
      portal_player_selection?: boolean; creative_max_duration_s?: number | null
      audio_spots_cap?: number; audio_spot_daily_rate?: number | null
    }) => api.put('/campaigns/settings', body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['campaign-settings'] }); setSettingsErr('') },
    onError: (e: unknown) => setSettingsErr(
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('common.error')),
  })
  const reviewCreative = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'approve' | 'reject' }) =>
      api.post(`/campaigns/creatives/${id}/${action}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-creatives', editing?.id_campaign] })
      setErr('')
    },
    onError: onApiError,
  })

  const filtered = useMemo(() => campaigns.filter((c) =>
    !search
    || c.campaign_name.toLowerCase().includes(search.toLowerCase())
    || (c.advertiser_name ?? '').toLowerCase().includes(search.toLowerCase())), [campaigns, search])

  const oneTargetLabel = (tg: { target_type: string; target_id: number | null; target_name?: string | null }) => {
    if (tg.target_type === 'org') return t('campaigns.target_org')
    // Nom SERVEUR d'abord ; les listes locales ne servent plus que de repli (drawer
    // ouvert, ou réponse d'une version antérieure du backend).
    if (tg.target_name) return tg.target_name
    if (tg.target_type === 'site') return sites.find((s) => s.id_site === tg.target_id)?.site_name ?? `site #${tg.target_id}`
    if (tg.target_type === 'site_group') return siteGroups.find((g) => g.id_site_group === tg.target_id)?.group_name ?? `#${tg.target_id}`
    if (tg.target_type === 'group') return groups.find((g) => g.id_group === tg.target_id)?.group_name ?? `#${tg.target_id}`
    if (tg.target_type === 'player') return players.find((p) => p.id_player === tg.target_id)?.player_name ?? `#${tg.target_id}`
    return tg.target_type
  }

  const targetLabel = (c: Campaign) => {
    if (!c.targets.length) return '—'
    const first = oneTargetLabel(c.targets[0])
    return c.targets.length > 1 ? `${first} +${c.targets.length - 1}` : first
  }

  const sel = 'w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40'
  const canSave = form.campaign_name.trim() && form.id_advertiser && form.starts_on && form.ends_on
    && targetsValid && (!isAudio || Number(form.spots_per_hour) > 0)

  return (
    <>
      <Topbar title={t('campaigns.title')}>
        <Can perm="campaigns:create">
          <Button size="sm" onClick={() => setImportOpen(true)}>
            <Upload className="w-4 h-4 mr-1" />{t('campaigns.import_title')}
          </Button>
          <Button size="sm" onClick={openCreate}>{t('campaigns.new')}</Button>
        </Can>
      </Topbar>

      {/*
        Page verrouillée au viewport : la recherche ET toute la rangée d'outils
        (inventaire, calendrier, réglages org) restent fixes ; seule la liste
        des campagnes défile.
      */}
      <main className="flex-1 flex flex-col min-h-0 px-6">
          {isLoading ? (
            <div className="flex justify-center py-16">
              <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : campaigns.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3 text-gray-400">
              <BadgeEuro className="w-10 h-10" />
              <p className="text-sm">{t('campaigns.empty')}</p>
            </div>
          ) : (
            <>
              {/* Zone figée */}
              <div className="shrink-0 pt-8 pb-4">
              <div className="flex items-center gap-3 flex-wrap">
                <SearchInput
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('common.search')}
                  wrapperClassName="min-w-[220px]"
                />
                <Button size="sm" variant="secondary" onClick={() => setShowInventory(!showInventory)}>
                  {t('campaigns.inventory_title')}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setShowCalendar(!showCalendar)}>
                  {t('campaigns.calendar_title')}
                </Button>
                {/* Réglages d'organisation — PUT /campaigns/settings = require_org_admin.
                    Masqués pour tout non-admin (le serveur répond 403 de toute façon). */}
                <Can admin>
                {/* Les 2 réglages à case cochée empilés (cases alignées verticalement) */}
                <div className="flex flex-col gap-1.5">
                  <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer whitespace-nowrap"
                         title={t('campaigns.approval_toggle_hint')}>
                    <input type="checkbox" checked={approvalOn}
                           disabled={toggleApproval.isPending}
                           onChange={(e) => toggleApproval.mutate(e.target.checked)} />
                    {t('campaigns.approval_toggle')}
                  </label>
                  {/* Sélection par écran au portail (0089, défaut OFF — liste nominative) */}
                  <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer whitespace-nowrap"
                         title={t('campaigns.portal_players_hint')}>
                    <input type="checkbox" checked={cSettings?.portal_player_selection ?? false}
                           disabled={saveQuota.isPending}
                           onChange={(e) => saveQuota.mutate({ portal_player_selection: e.target.checked })} />
                    {t('campaigns.portal_players_toggle')}
                  </label>
                </div>
                {/* Tarif SOV par défaut (devis, héritage org → site → player) */}
                <label className="flex items-center gap-1.5 text-xs text-gray-600 whitespace-nowrap"
                       title={t('campaigns.default_rate_hint')}>
                  {t('campaigns.default_rate')}
                  <NumberField value={cSettings?.sov_daily_rate ?? null}
                         onCommit={(v) => saveRate.mutate(v)}
                         allowEmpty min={0} step={0.01}
                         disabled={saveRate.isPending}
                         className="w-20 px-2 py-1 text-xs border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40" />
                </label>
                {/* Quotas d'upload du portail annonceur (0084) */}
                <label className="flex items-center gap-1.5 text-xs text-gray-600 whitespace-nowrap"
                       title={t('campaigns.quota_creatives_hint')}>
                  {t('campaigns.quota_creatives')}
                  <NumberField value={cSettings?.max_creatives ?? 20}
                         onCommit={(v) => { if (v !== null) saveQuota.mutate({ max_creatives: v }) }}
                         min={1} max={200} step={1}
                         disabled={saveQuota.isPending}
                         className="w-14 px-2 py-1 text-xs border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40" />
                </label>
                <label className="flex items-center gap-1.5 text-xs text-gray-600 whitespace-nowrap"
                       title={t('campaigns.quota_size_hint')}>
                  {t('campaigns.quota_size')}
                  <NumberField value={cSettings?.creative_max_mb ?? 1024}
                         onCommit={(v) => { if (v !== null) saveQuota.mutate({ creative_max_mb: v }) }}
                         min={1} max={10240} step={1}
                         disabled={saveQuota.isPending}
                         className="w-16 px-2 py-1 text-xs border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40" />
                </label>
                {/* Garde-fou boucle courte (0089) : durée max d'un créatif — vide = illimité */}
                <label className="flex items-center gap-1.5 text-xs text-gray-600 whitespace-nowrap"
                       title={t('campaigns.max_duration_hint')}>
                  {t('campaigns.max_duration')}
                  <NumberField value={cSettings?.creative_max_duration_s ?? null}
                         onCommit={(v) => saveQuota.mutate({ creative_max_duration_s: v })}
                         allowEmpty min={1} max={3600} step={1}
                         disabled={saveQuota.isPending}
                         className="w-14 px-2 py-1 text-xs border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40" />
                </label>
                {/* S2 audio (0094) : plafond spots/h org + tarif audio (€/spot/h/jour) */}
                <label className="flex items-center gap-1.5 text-xs text-gray-600 whitespace-nowrap"
                       title={t('campaigns.audio_cap_hint')}>
                  {t('campaigns.audio_cap')}
                  <NumberField value={cSettings?.audio_spots_cap ?? 12}
                         onCommit={(v) => { if (v !== null) saveQuota.mutate({ audio_spots_cap: v }) }}
                         min={1} max={60} step={1}
                         disabled={saveQuota.isPending}
                         className="w-14 px-2 py-1 text-xs border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40" />
                </label>
                <label className="flex items-center gap-1.5 text-xs text-gray-600 whitespace-nowrap"
                       title={t('campaigns.audio_rate_hint')}>
                  {t('campaigns.audio_rate')}
                  <NumberField value={cSettings?.audio_spot_daily_rate ?? null}
                         onCommit={(v) => saveQuota.mutate({ audio_spot_daily_rate: v })}
                         allowEmpty min={0} step={0.01}
                         disabled={saveQuota.isPending}
                         className="w-20 px-2 py-1 text-xs border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40" />
                </label>
                </Can>
              </div>
              {settingsErr && <p className="text-xs text-danger mt-3">{settingsErr}</p>}
              </div>

              {/* Zone basse : calendrier/inventaire éventuels en hauteur naturelle,
                  puis le panneau de campagnes qui prend TOUT le reste sans jamais
                  déborder de la fenêtre — seules les lignes défilent, sous des
                  en-têtes de colonnes collants (même patron que /settings/messaging,
                  validé par Ed). */}
              <div className="flex-1 min-h-0 flex flex-col gap-4 pb-5">
              {showCalendar && (
                <div className="shrink-0">
                <CampaignCalendar
                  campaigns={campaigns}
                  occupancy={occDaily?.days ?? []}
                  year={calCursor.y}
                  month={calCursor.m}
                  onPrev={() => setCalCursor((c) => (c.m === 0 ? { y: c.y - 1, m: 11 } : { y: c.y, m: c.m - 1 }))}
                  onNext={() => setCalCursor((c) => (c.m === 11 ? { y: c.y + 1, m: 0 } : { y: c.y, m: c.m + 1 }))}
                  onSelect={(id) => { const c = campaigns.find((x) => x.id_campaign === id); if (c) openEdit(c) }}
                />
                </div>
              )}
              {showInventory && (
                <div className="shrink-0 bg-surface border border-gray-200 rounded-xl p-4 shadow-sf-card">
                  <p className="text-sm font-medium text-gray-700 mb-1">{t('campaigns.inventory_title')}</p>
                  <p className="text-xs text-gray-400 mb-3">{t('campaigns.inventory_hint')}</p>
                  <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
                    {inventory.map((r) => {
                      const pct = Math.min(r.occupied_pct, 100)
                      const color = r.occupied_pct > 100 ? 'bg-danger' : r.occupied_pct >= 80 ? 'bg-warning' : 'bg-accent'
                      return (
                        <div key={r.id_player} className="text-xs">
                          <div className="flex justify-between mb-1">
                            <span className="text-gray-600 truncate">{r.player_name}</span>
                            <span className={r.occupied_pct > 100 ? 'text-danger font-semibold' : 'text-gray-500'}>
                              {r.occupied_pct}%
                            </span>
                          </div>
                          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
              <div className="flex-1 min-h-0 overflow-y-auto bg-surface border border-gray-200 rounded-xl shadow-sf-card">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10 bg-surface">
                    <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                      <th className="px-4 py-3 font-medium">{t('campaigns.col_name')}</th>
                      <th className="px-4 py-3 font-medium">{t('campaigns.col_advertiser')}</th>
                      <th className="px-4 py-3 font-medium">{t('campaigns.col_period')}</th>
                      <th className="px-4 py-3 font-medium">{t('campaigns.col_target')}</th>
                      <th className="px-4 py-3 font-medium">{t('campaigns.col_sold')}</th>
                      <th className="px-4 py-3 font-medium">{t('campaigns.col_creatives')}</th>
                      <th className="px-4 py-3 font-medium">{t('campaigns.col_status')}</th>
                      <th className="px-4 py-3 w-10" />
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((c) => (
                      <tr key={c.id_campaign}
                          onClick={() => openEdit(c)}
                          className="border-b border-gray-100 last:border-0 hover:bg-canvas cursor-pointer transition-sf">
                        <td className="px-4 py-3 font-medium text-gray-800">
                          <span className="inline-flex items-center gap-1.5">
                            {c.campaign_kind === 'audio' && (
                              <Music className="w-3.5 h-3.5 text-accent shrink-0" aria-label={t('campaigns.kind_audio')} />
                            )}
                            {c.campaign_name}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-600">{c.advertiser_name}</td>
                        <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                          {new Date(c.starts_on).toLocaleDateString()} → {new Date(c.ends_on).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3 text-gray-600">{targetLabel(c)}</td>
                        <td className="px-4 py-3 text-gray-800 font-medium whitespace-nowrap">
                          {c.campaign_kind === 'audio'
                            ? t('campaigns.spots_cell', { spots: c.spots_per_hour ?? 0 })
                            : `${Number(c.sov_percent)}%`}
                        </td>
                        <td className="px-4 py-3 text-gray-600">{c.creative_count}</td>
                        <td className="px-4 py-3">
                          <StatusBadge status={BADGE[c.status] ?? 'pending'}
                                       label={t(`campaigns.st_${c.status}`)} />
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Can perm="campaigns:delete">
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                if (confirm(t('campaigns.delete_confirm'))) remove.mutate(c.id_campaign)
                              }}
                              className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf"
                              title={t('common.delete')}>
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </Can>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </div>
            </>
          )}
      </main>

      {/* Échap/backdrop ne ferment pas ce drawer tant que le picker est ouvert au-dessus */}
      <Drawer open={drawerOpen} onClose={() => { if (!pickerOpen) setDrawerOpen(false) }}
              title={editing ? editing.campaign_name : t('campaigns.new')}>
        {/* Nudge lecture-seule : édition = campaigns:edit, création = campaigns:create.
            Les boutons d'action à permission propre (Publier/Rapport/Soumettre/Supprimer)
            sont masqués par <Can> ; les CHAMPS du formulaire nudgent via cette zone. */}
        <div className="space-y-5" data-write-perm={editing ? 'campaigns:edit' : 'campaigns:create'}>
          {editing && (
            <div className="space-y-2">
              {/* Ligne 1 : badge d'état seul (demande Ed 10/07) + badge approbation §XXI */}
              <div className="flex items-center gap-2 flex-wrap">
                <StatusBadge status={BADGE[editing.status] ?? 'pending'} label={t(`campaigns.st_${editing.status}`)} />
                {editing.approval_request && (
                  <StatusBadge
                    status={editing.approval_request.status === 'approved' ? 'info'
                      : editing.approval_request.status === 'changes_requested' ? 'warning' : 'pending'}
                    label={t(`approvals.st_${editing.approval_request.status}`)} />
                )}
              </div>
              {/* Ligne 2 : les transitions (Publier/Reprendre · Suspendre/Terminer/Annuler)
                  — POST /campaigns/{id}/status = campaigns:publish ; soumettre = approvals:submit. */}
              {['draft', 'live', 'scheduled', 'paused'].includes(editing.status) && (
                <div className="flex items-center gap-2 flex-wrap"><Can perm="campaigns:publish">
                  {editing.status === 'draft' && (
                    <>
                      {/* Publier masqué tant qu'une demande d'approbation est en revue
                          (le backend renvoie 409 de toute façon). */}
                      {!(editing.approval_request
                         && ['pending_review', 'changes_requested'].includes(editing.approval_request.status)) && (
                        <Button size="sm" onClick={() => changeStatus.mutate({ id: editing.id_campaign, action: 'publish' })}
                                loading={changeStatus.isPending}>
                          <Play className="w-3.5 h-3.5 mr-1" />{t('campaigns.publish')}
                        </Button>
                      )}
                      {!editing.approval_request && (
                        <Button size="sm" variant="secondary"
                                onClick={() => submitApproval.mutate(editing.id_campaign)}
                                loading={submitApproval.isPending}>
                          <Check className="w-3.5 h-3.5 mr-1" />{t('approvals.submit_button')}
                        </Button>
                      )}
                    </>
                  )}
                  {editing.status === 'paused' && (
                    <Button size="sm" onClick={() => changeStatus.mutate({ id: editing.id_campaign, action: 'resume' })}>
                      <Play className="w-3.5 h-3.5 mr-1" />{t('campaigns.resume')}
                    </Button>
                  )}
                  {(editing.status === 'live' || editing.status === 'scheduled') && (
                    <Button size="sm" variant="secondary"
                            onClick={() => changeStatus.mutate({ id: editing.id_campaign, action: 'pause' })}>
                      <Pause className="w-3.5 h-3.5 mr-1" />{t('campaigns.pause')}
                    </Button>
                  )}
                  {editing.status !== 'draft' && (
                    <Button size="sm" variant="secondary"
                            onClick={() => changeStatus.mutate({ id: editing.id_campaign, action: 'complete' })}>
                      <CheckCircle2 className="w-3.5 h-3.5 mr-1" />{t('campaigns.complete')}
                    </Button>
                  )}
                  <Button size="sm" variant="secondary"
                          onClick={() => changeStatus.mutate({ id: editing.id_campaign, action: 'cancel' })}>
                    <XCircle className="w-3.5 h-3.5 mr-1" />{t('campaigns.cancel_action')}
                  </Button>
                  </Can>
                </div>
              )}
              {/* Ligne 3 : Rapport seul sur sa ligne — GET rapport = campaigns:report */}
              {editing.status !== 'draft' && (
                <Can perm="campaigns:report">
                <div>
                  <Button size="sm"
                          onClick={() => router.push(`/campaigns/${editing.id_campaign}/report`)}>
                    <BarChart2 className="w-3.5 h-3.5 mr-1" />{t('campaigns.report_title')}
                  </Button>
                </div>
                </Can>
              )}
            </div>
          )}

          {/* S2 audio : type de campagne — choisi à la CRÉATION, immuable ensuite */}
          {!editing ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('campaigns.kind_label')}</label>
              <div className="flex items-center gap-1.5">
                {(['visual', 'audio'] as const).map((k) => (
                  <button key={k} type="button"
                          onClick={() => setForm({ ...form, campaign_kind: k })}
                          className={`px-3 py-1.5 rounded-full text-xs border transition-sf ${
                            form.campaign_kind === k
                              ? 'bg-accent text-white border-accent'
                              : 'bg-surface text-gray-500 border-gray-200 hover:border-accent hover:text-accent'
                          }`}>
                    {k === 'visual' ? t('campaigns.kind_visual') : t('campaigns.kind_audio')}
                  </button>
                ))}
              </div>
              {form.campaign_kind === 'audio' && (
                <p className="text-xs text-gray-400 mt-1">{t('campaigns.kind_audio_hint')}</p>
              )}
            </div>
          ) : (
            isAudio && (
              <div className="flex items-center gap-2">
                <Music className="w-4 h-4 text-accent" />
                <span className="text-xs text-gray-500">{t('campaigns.kind_audio_badge')}</span>
              </div>
            )
          )}

          <Input label={t('campaigns.name_label')} value={form.campaign_name}
                 onChange={(e) => setForm({ ...form, campaign_name: e.target.value })} autoFocus={!editing} />

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('campaigns.advertiser')}</label>
            <select className={sel} value={form.id_advertiser}
                    onChange={(e) => setForm({ ...form, id_advertiser: Number(e.target.value) })}>
              <option value={0} disabled>—</option>
              {advertisers.map((a) => (
                <option key={a.id_advertiser} value={a.id_advertiser}>{a.advertiser_name}</option>
              ))}
            </select>
            {advertisers.length === 0 && (
              <p className="text-xs text-warning mt-1">{t('campaigns.no_advertiser_hint')}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Input label={t('campaigns.starts_on')} type="date" value={form.starts_on}
                   onChange={(e) => setForm({ ...form, starts_on: e.target.value })} />
            <Input label={t('campaigns.ends_on')} type="date" value={form.ends_on}
                   onChange={(e) => setForm({ ...form, ends_on: e.target.value })} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Input label={t('campaigns.hours_start')} type="time" value={form.hours_start}
                   onChange={(e) => setForm({ ...form, hours_start: e.target.value })} />
            <Input label={t('campaigns.hours_end')} type="time" value={form.hours_end}
                   onChange={(e) => setForm({ ...form, hours_end: e.target.value })} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            {isAudio ? (
              <NumberField label={t('campaigns.spots_label')} min={1} max={60}
                     value={form.spots_per_hour ?? 1}
                     onCommit={(v) => setForm({ ...form, spots_per_hour: v ?? 1 })} />
            ) : (
              <NumberField label={t('campaigns.sov_label')} min={1} max={100}
                     value={form.sov_percent ?? 1}
                     onCommit={(v) => setForm({ ...form, sov_percent: v ?? 1 })} />
            )}
            {/* Priorité = ordre d'allocation des passages VISUELS ; sans effet en audio
                (panier synthétique unique, tirage pondéré par spots/h) → masquée. */}
            {!isAudio && (
              <NumberField label={t('campaigns.priority')} min={1} max={100}
                     value={form.priority ?? 1}
                     onCommit={(v) => setForm({ ...form, priority: v ?? 1 })} />
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            {!isAudio ? (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('campaigns.pricing')}</label>
                <select className={sel} value={form.pricing_model}
                        onChange={(e) => setForm({ ...form, pricing_model: e.target.value })}>
                  <option value="sov">{t('campaigns.pricing_sov')}</option>
                  <option value="flat">{t('campaigns.pricing_flat')}</option>
                </select>
              </div>
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('campaigns.pricing')}</label>
                <p className="px-3 py-2 text-sm text-gray-500 border border-gray-200 rounded-lg bg-canvas">
                  {t('campaigns.pricing_spots')}
                </p>
              </div>
            )}
            <Input label={`${t('campaigns.price')} (EUR)`} type="number" min={0}
                   value={form.price_amount}
                   onChange={(e) => setForm({ ...form, price_amount: e.target.value })} />
          </div>

          {/* Sections repliables (demande Ed 10/07) : Cible = pastille players résolus
              (count serveur, opt-out déduits) · repliée par défaut en édition, ouverte en création. */}
          <CollapsibleSection
            key={`target-${editing?.id_campaign ?? 'new'}`}
            title={t('campaigns.target')}
            defaultOpen={!editing}
            badge={editing ? (
              <CountPill>{t('campaigns.target_players_pill', { count: editing.target_player_count ?? 0 })}</CountPill>
            ) : undefined}
          >
            <div className="space-y-2">
              {isAudio && (
                <p className="text-xs text-gray-400">{t('campaigns.target_audio_hint')}</p>
              )}
              {targets.map((tg, i) => (
                <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2 items-center">
                  <select className={sel} value={tg.type}
                          onChange={(e) => setTargets(targets.map((x, j) =>
                            j === i ? { type: e.target.value, id: null } : x))}>
                    <option value="org">{t('campaigns.target_org')}</option>
                    <option value="site">{t('campaigns.target_site')}</option>
                    <option value="site_group">{t('campaigns.target_site_group')}</option>
                    <option value="group">{t('campaigns.target_group')}</option>
                    <option value="player">{t('campaigns.target_player')}</option>
                  </select>
                  {tg.type !== 'org' ? (
                    <select className={sel} value={tg.id ?? ''}
                            onChange={(e) => setTargets(targets.map((x, j) =>
                              j === i ? { ...x, id: Number(e.target.value) } : x))}>
                      <option value="" disabled>—</option>
                      {tg.type === 'site' && targetSites.map((s) => (
                        <option key={s.id_site} value={s.id_site}>{s.site_name}</option>))}
                      {tg.type === 'site_group' && targetSiteGroups.map((g) => (
                        <option key={g.id_site_group} value={g.id_site_group}>{g.group_name}</option>))}
                      {tg.type === 'group' && targetGroups.map((g) => (
                        <option key={g.id_group} value={g.id_group}>{g.group_name}</option>))}
                      {tg.type === 'player' && targetPlayers.map((p) => (
                        <option key={p.id_player} value={p.id_player}>{p.player_name}</option>))}
                    </select>
                  ) : <div />}
                  <button type="button"
                          onClick={() => setTargets(targets.filter((_, j) => j !== i))}
                          disabled={targets.length <= 1}
                          className="p-1.5 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf disabled:opacity-30 disabled:hover:text-gray-400 disabled:hover:bg-transparent"
                          title={t('common.delete')}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
              <div className="flex items-center gap-4">
                <button type="button"
                        onClick={() => setTargets([...targets, { type: 'site', id: null }])}
                        className="flex items-center gap-1 text-xs text-accent hover:underline">
                  <Plus className="w-3.5 h-3.5" /> {t('campaigns.target_add')}
                </button>
                {/* S7 Phase A — sélection des SITES au clic sur la carte de l'org */}
                <button type="button"
                        onClick={() => {
                          setMapSelection(new Set(
                            targets.filter((tg) => tg.type === 'site' && tg.id != null).map((tg) => tg.id as number)))
                          setMapPlayers(new Set(
                            targets.filter((tg) => tg.type === 'player' && tg.id != null).map((tg) => tg.id as number)))
                          setMapExpandedSite(null)
                          setMapPickerOpen(true)
                        }}
                        className="flex items-center gap-1 text-xs text-accent hover:underline">
                  <MapPin className="w-3.5 h-3.5" /> {t('campaigns.target_map_pick')}
                </button>
              </div>
            </div>
          </CollapsibleSection>

          {occReady && occ && (occ.warning || occ.blocked) && (
            <div className={`rounded-lg px-3 py-2.5 text-sm ${occ.blocked
              ? 'bg-red-500/10 text-danger dark:bg-red-500/15 dark:text-red-300'
              : 'bg-orange-500/15 text-warning dark:bg-orange-500/15 dark:text-orange-300'}`}>
              <p className="font-medium">
                {occ.blocked ? t('campaigns.occupancy_blocked') : t('campaigns.occupancy_warning')}
                {' '}({occ.max_projected_pct}%)
              </p>
              <ul className="mt-1 text-xs space-y-0.5">
                {occ.players
                  .filter((p) => p.projected_pct >= (p.cap_pct ?? 100) * 0.8)
                  .slice(0, 5).map((p) => (
                  <li key={p.id_player}>
                    {p.player_name ?? `#${p.id_player}`} :{' '}
                    {p.cap_spots != null ? (
                      // S2 audio : détail en spots/h (plafond par écran)
                      <>{p.current_spots} → {p.projected_spots} {t('campaigns.spots_unit', { cap: p.cap_spots })}</>
                    ) : (
                      <>
                        {p.current_pct}% → {p.projected_pct}%
                        {(p.cap_pct ?? 100) < 100 && (
                          <span> · {t('campaigns.cap_pill', { cap: p.cap_pct })}</span>
                        )}
                      </>
                    )}
                  </li>
                ))}
              </ul>
              {occ.blocked && editing && (
                <label className="flex items-center gap-2 mt-2 text-xs cursor-pointer">
                  <input type="checkbox" checked={overbook}
                         onChange={(e) => setOverbook(e.target.checked)} />
                  {t('campaigns.occupancy_override')}
                </label>
              )}
            </div>
          )}

          {/* S2 audio : spots/h réalisables = plafond restant du pire écran ciblé */}
          {occReady && isAudio && occ?.achievable_spots_per_hour != null
            && Number(form.spots_per_hour) > occ.achievable_spots_per_hour && (
            <div className="rounded-lg px-3 py-2.5 text-sm bg-orange-500/15 text-warning dark:bg-orange-500/15 dark:text-orange-300">
              <p className="font-medium">
                {t('campaigns.spots_achievable_warning', {
                  spots: Number(form.spots_per_hour), max: occ.achievable_spots_per_hour,
                })}
              </p>
              {occ.achievable_spots_per_hour > 0 && (
                <button type="button"
                        onClick={() => setForm({ ...form, spots_per_hour: occ.achievable_spots_per_hour! })}
                        className="mt-1.5 text-xs font-medium underline hover:no-underline">
                  {t('campaigns.spots_achievable_use', { spots: occ.achievable_spots_per_hour })}
                </button>
              )}
            </div>
          )}

          {/* SOV réalisable (anti-martèlement) : la boucle du pire écran plafonne
              physiquement la SOV (1 spot max par frontière) — avertir + suggérer */}
          {occReady && !isAudio && occ?.achievable
            && Number(form.sov_percent) > occ.achievable.max_sov_pct && (() => {
            const feas = occ.achievable
            const worst = feas.players[0]
            const suggested = feas.max_sov_pct >= 2
              ? Math.floor(feas.max_sov_pct) : feas.max_sov_pct
            return (
              <div className="rounded-lg px-3 py-2.5 text-sm bg-orange-500/15 text-warning dark:bg-orange-500/15 dark:text-orange-300">
                <p className="font-medium">
                  {t('campaigns.sov_achievable_warning', {
                    sov: Number(form.sov_percent), max: feas.max_sov_pct,
                    player: worst?.player_name ?? `#${worst?.id_player}`,
                  })}
                </p>
                <p className="mt-1 text-xs">
                  {t('campaigns.sov_achievable_hint', {
                    items: worst?.home_items ?? 0,
                    minutes: Math.max(1, Math.round((worst?.home_duration_ms ?? 0) / 60000)),
                  })}
                </p>
                {suggested > 0 && (
                  <button type="button"
                          onClick={() => setForm({ ...form, sov_percent: suggested })}
                          className="mt-1.5 text-xs font-medium underline hover:no-underline">
                    {t('campaigns.sov_achievable_use', { pct: suggested })}
                  </button>
                )}
              </div>
            )
          })()}

          {/* Devis (tarifs par écran v2) — indicatif, le prix contractuel = champ Prix */}
          {occReady && occ?.price && (
            <div className="rounded-lg px-3 py-2 text-sm bg-accent/10 text-accent border border-accent/20">
              {t('campaigns.estimated_price', { price: occ.price.estimated_price })}
              <span className="text-xs opacity-80">
                {' '}· {t('campaigns.estimated_price_details', {
                  players: occ.price.priced_players, days: occ.price.days,
                })}
                {occ.price.unpriced_players > 0 && (
                  <> · {t('campaigns.estimated_price_unpriced', { count: occ.price.unpriced_players })}</>
                )}
              </span>
            </div>
          )}

          {editing && (
            <CollapsibleSection
              key={`creatives-${editing.id_campaign}`}
              title={t('campaigns.creatives')}
              defaultOpen={editing.creative_count === 0}
              badge={<CountPill>{creatives.length}</CountPill>}
            >
              <div className="space-y-2 mb-3">
                {creatives.map((cr) => (
                  <div key={cr.id_creative}
                       className="flex items-center justify-between gap-2 px-3 py-2 bg-canvas rounded-lg text-sm">
                    <span className="truncate">{cr.media_name}
                      <span className="text-gray-400 ml-1">
                        · {Math.round((cr.duration_ms ?? cr.media_duration_ms ?? 0) / 1000)}s
                        {cr.weight > 1 ? ` · ×${cr.weight}` : ''}
                      </span>
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
                      {cr.approval_status !== 'approved' && (
                        <StatusBadge
                          status={cr.approval_status === 'pending' ? 'pending' : 'offline'}
                          label={t(cr.approval_status === 'pending'
                            ? 'campaigns.creative_pending' : 'campaigns.creative_rejected')} />
                      )}
                      {approvalOn && cr.approval_status !== 'approved' && (
                        <Can perm="approvals:approve">
                          <button onClick={() => reviewCreative.mutate({ id: cr.id_creative, action: 'approve' })}
                                  className="p-1 rounded text-gray-400 hover:text-accent hover:bg-accent/10 transition-sf"
                                  title={t('campaigns.approve_creative')}>
                            <Check className="w-4 h-4" />
                          </button>
                        </Can>
                      )}
                      {approvalOn && cr.approval_status !== 'rejected' && (
                        <Can perm="approvals:reject">
                          <button onClick={() => reviewCreative.mutate({ id: cr.id_creative, action: 'reject' })}
                                  className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf"
                                  title={t('campaigns.reject_creative')}>
                            <X className="w-4 h-4" />
                          </button>
                        </Can>
                      )}
                      <button data-write-action onClick={() => removeCreative.mutate(cr.id_creative)}
                              className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf"
                              title={t('common.delete')}>
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
                {creatives.length === 0 && (
                  <p className="text-xs text-gray-400">{t('campaigns.no_creatives')}</p>
                )}
              </div>
              <Button data-write-action size="sm" onClick={openPicker}>
                <Plus className="w-3.5 h-3.5 mr-1" />{t('campaigns.picker_title')}
              </Button>
            </CollapsibleSection>
          )}

          {err && <p className="text-sm text-danger">{err}</p>}

          <div className="flex gap-2 pt-2">
            <Button data-write-action onClick={() => save.mutate()} loading={save.isPending}
                    disabled={!canSave} className="flex-1">
              {editing ? t('common.save') : t('common.create')}
            </Button>
            {editing && (
              <Can perm="campaigns:delete">
                <Button variant="secondary"
                        onClick={() => {
                          if (confirm(t('campaigns.delete_confirm'))) remove.mutate(editing.id_campaign)
                        }}>
                  <Trash2 className="w-4 h-4" />
                </Button>
              </Can>
            )}
          </div>
          {!editing && (
            <p className="text-xs text-gray-400">{t('campaigns.create_hint')}</p>
          )}
        </div>
      </Drawer>

      {/* Picker de créatifs — même UX que « Ajouter un média » des playlists :
          recherche server-side, scope annonceur/médiathèque, arbre de dossiers,
          vignettes + multi-sélection, durée/poids appliqués au lot. */}
      <Drawer open={pickerOpen} onClose={() => setPickerOpen(false)}
              title={t('campaigns.picker_title')}>
        {/* Ajouter des créatifs = campaigns:edit */}
        <div className="space-y-4" data-write-perm="campaigns:edit">
          {advFolder != null && (
            <div className="flex items-center gap-1">
              {(['advertiser', 'all'] as const).map((scope) => (
                <button key={scope} type="button"
                        onClick={() => setCreativeScope(scope)}
                        className={`px-2.5 py-1 rounded-full text-xs border transition-sf ${
                          creativeScope === scope
                            ? 'bg-accent text-white border-accent'
                            : 'bg-surface text-gray-500 border-gray-200 hover:border-accent hover:text-accent'
                        }`}>
                  {scope === 'advertiser' ? t('campaigns.scope_advertiser') : t('campaigns.scope_all')}
                </button>
              ))}
            </div>
          )}

          <input
            type="text"
            placeholder={t('media.search_placeholder')}
            value={pickerSearchInput}
            onChange={(e) => setPickerSearchInput(e.target.value)}
            className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-accent/40"
          />

          {/* Arbre de dossiers (scope médiathèque) — collapsé par défaut, comme /media */}
          {effectiveScope === 'all' && (
            <div className="border border-gray-200 rounded">
              <button
                type="button"
                onClick={() => setPickerFoldersOpen((o) => !o)}
                className="flex items-center justify-between w-full px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-sf"
              >
                <span className="flex items-center gap-2">
                  {pickerFoldersOpen ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
                  <FolderTreeIcon className="w-4 h-4 text-gray-400" />
                  {t('media.folders')}
                </span>
                {pickerFolder !== 'all' && (
                  <span className="text-xs text-accent">
                    {pickerFolder === 'unfiled' ? t('media.folder_unfiled') : t('media.folder_filtered')}
                  </span>
                )}
              </button>
              {pickerFoldersOpen && (
                <div className="border-t border-gray-100 p-2 max-h-48 overflow-y-auto">
                  <FolderTree selected={pickerFolder} onSelect={setPickerFolder} />
                </div>
              )}
            </div>
          )}

          <div className="space-y-1 max-h-[45vh] overflow-y-auto">
            {pickerLoading ? (
              <div className="flex justify-center py-8">
                <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
              </div>
            ) : (
              <>
                {pickerMedia.map((m) => {
                  const checked = picked.has(m.id_media)
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
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={m.thumbnail_url} alt="" className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full bg-gray-200" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-800 truncate">{m.media_name}</p>
                        <p className="text-xs text-gray-400">
                          {m.media_type}
                          {m.duration_ms ? ` · ${Math.round(m.duration_ms / 1000)}s` : ''}
                        </p>
                      </div>
                    </button>
                  )
                })}
                {pickerMedia.length === 0 && (
                  <p className="text-sm text-gray-400 text-center py-8">
                    {effectiveScope === 'advertiser' && !pickerSearch
                      ? t('campaigns.scope_empty_hint')
                      : t('media.no_results')}
                  </p>
                )}
              </>
            )}
          </div>

          {/* Pied : durée/poids appliqués au lot + ajout groupé. Un spot AUDIO joue
              toujours sa durée native → pas de champ durée pour une campagne audio. */}
          <div className="border-t border-gray-100 pt-3 space-y-2">
            <div className="grid grid-cols-2 gap-3">
              {!isAudio && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('campaigns.duration_s')}</label>
                  <input type="number" min={1} className={sel} value={pickerDur}
                         onChange={(e) => setPickerDur(e.target.value)} />
                </div>
              )}
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('campaigns.weight')}</label>
                <NumberField min={1} max={100} className={sel} value={pickerWeight}
                       onCommit={(v) => setPickerWeight(v ?? 1)} />
              </div>
            </div>
            {pickedNeedsDuration && (
              <p className="text-xs text-warning">{t('campaigns.picker_needs_duration')}</p>
            )}
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-gray-500">
                {t('campaigns.picker_selected', { count: picked.size })}
              </span>
              <Button
                data-write-action
                size="sm"
                onClick={() => addCreatives.mutate()}
                disabled={picked.size === 0 || pickedNeedsDuration || addCreatives.isPending}
                loading={addCreatives.isPending}
              >
                <Plus className="w-3.5 h-3.5 mr-1" />
                {t('campaigns.picker_add', { count: picked.size })}
              </Button>
            </div>
          </div>
        </div>
      </Drawer>

      <ImportOrderDrawer
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={async () => {
          await qc.refetchQueries({ queryKey: ['campaigns'] })
          qc.invalidateQueries({ queryKey: ['advertisers'] })
        }}
      />

      {/* S7 Phase A — sélection des sites cibles sur la carte (marqueur accent = sélectionné) */}
      <Drawer open={mapPickerOpen} onClose={() => setMapPickerOpen(false)}
              title={t('campaigns.target_map_title')} width="w-[640px]">
        {/* Choix des sites cibles = campaigns:edit (fait partie de l'édition de campagne) */}
        <div className="space-y-3" data-write-perm="campaigns:edit">
          <p className="text-xs text-gray-400">{t('campaigns.target_map_hint')}</p>
          <SiteMapSelector
            sites={targetSites}
            selected={mapSelection}
            searchable
            searchPlaceholder={t('campaigns.target_map_search')}
            onFocusSite={(id) => setMapExpandedSite(id)}
            onToggle={(id) => toggleMapWholeSite(id)}
          />

          {/* Sélection PAR ÉCRAN du site recentré (recherche) — sites entier ⟷ partiel exclusifs */}
          {mapExpandedSite != null && (() => {
            const s = targetSites.find((x) => x.id_site === mapExpandedSite)
            if (!s) return null
            const sitePlayers = players.filter(
              (p) => p.id_site === mapExpandedSite && capablePlayerIds.has(p.id_player))
            if (sitePlayers.length === 0) return null
            const whole = mapSelection.has(mapExpandedSite)
            return (
              <div className="border border-gray-200 rounded-lg p-3 space-y-2 bg-canvas">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-gray-700 truncate">
                    {t('campaigns.target_map_screens_of', { site: s.site_name })}
                  </span>
                  <button type="button" onClick={() => setMapExpandedSite(null)}
                          className="text-gray-400 hover:text-gray-600"><X className="w-3.5 h-3.5" /></button>
                </div>
                <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                  <input type="checkbox" checked={whole}
                         onChange={() => toggleMapWholeSite(mapExpandedSite)} />
                  {t('campaigns.target_map_whole_site')}
                </label>
                <div className="max-h-40 overflow-y-auto divide-y divide-gray-100">
                  {sitePlayers.map((p) => (
                    <label key={p.id_player}
                           className="flex items-center gap-2 px-1 py-1.5 text-sm text-gray-700 cursor-pointer">
                      <input type="checkbox"
                             checked={whole || mapPlayers.has(p.id_player)}
                             onChange={() => toggleMapPlayer(mapExpandedSite, p.id_player)} />
                      <span className="truncate">{p.player_name}</span>
                    </label>
                  ))}
                </div>
              </div>
            )
          })()}

          {/* Récap : sites entiers + sites partiels (n écrans) */}
          <div className="flex flex-wrap gap-1.5">
            {sites.filter((s) => mapSelection.has(s.id_site)).map((s) => (
              <span key={s.id_site}
                    className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-accent/10 text-accent rounded">
                {s.site_name}
                <button type="button" onClick={() => toggleMapWholeSite(s.id_site)}
                        className="hover:text-danger" title={t('common.delete')}>
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
            {[...new Set(players.filter((p) => mapPlayers.has(p.id_player)).map((p) => p.id_site))]
              .filter((sid): sid is number => sid != null && !mapSelection.has(sid))
              .map((sid) => {
                const site = sites.find((s) => s.id_site === sid)
                const n = players.filter((p) => p.id_site === sid && mapPlayers.has(p.id_player)).length
                return (
                  <span key={`p-${sid}`}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-accent/5 text-accent border border-accent/30 rounded">
                    {(site?.site_name ?? `#${sid}`)} · {n} 📺
                    <button type="button"
                            onClick={() => setMapPlayers((prev) => {
                              const next = new Set(prev)
                              players.filter((p) => p.id_site === sid).forEach((p) => next.delete(p.id_player))
                              return next
                            })}
                            className="hover:text-danger" title={t('common.delete')}>
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                )
              })}
            {mapSelection.size === 0 && mapPlayers.size === 0 && (
              <span className="text-xs text-gray-400">{t('campaigns.target_map_none')}</span>
            )}
          </div>
          {sites.some((s) => s.latitude == null || s.longitude == null) && (
            <p className="text-[11px] text-gray-400">
              {t('campaigns.target_map_unplaced', {
                count: sites.filter((s) => s.latitude == null || s.longitude == null).length,
              })}
            </p>
          )}
          <div className="flex gap-2">
            <Button data-write-action onClick={() => {
              // Remplace les cibles SITE et PLAYER par la sélection carte (round-trip depuis
              // le seed à l'ouverture) ; préserve les autres types (org / group / site_group).
              const others = targets.filter(
                (tg) => tg.type !== 'site' && tg.type !== 'player')
              const merged = [
                ...others,
                ...[...mapSelection].map((id) => ({ type: 'site', id })),
                ...[...mapPlayers].map((id) => ({ type: 'player', id })),
              ]
              setTargets(merged.length ? merged : [{ type: 'org', id: null }])
              setMapPickerOpen(false)
            }}>
              {t('campaigns.target_map_apply', { count: mapSelection.size + mapPlayers.size })}
            </Button>
            <Button variant="secondary" onClick={() => setMapPickerOpen(false)}>{t('common.cancel')}</Button>
          </div>
        </div>
      </Drawer>
    </>
  )
}
