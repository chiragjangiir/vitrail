'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Calendar, Pencil, Trash2, Search, Film, Music, AlertTriangle, Layers, Zap, Megaphone, MapPin, X, ChevronDown } from 'lucide-react'

// ── SearchableList ─────────────────────────────────────────────────────────────
interface SearchableListProps<T> {
  items: T[]
  getKey: (item: T) => number
  getLabel: (item: T) => string
  getSecondary?: (item: T) => React.ReactNode
  selected: number[]
  onToggle: (id: number) => void
  searchPlaceholder?: string
  emptyLabel?: string
  maxH?: string
  /**
   * Recherche PILOTÉE DE L'EXTÉRIEUR : quand elle est fournie, la liste n'affiche
   * plus sa propre barre et se filtre sur cette valeur. Sert au picker de cibles
   * du drawer, où un seul champ cherche à travers les 4 familles à la fois.
   */
  query?: string
}
function SearchableList<T>({
  items, getKey, getLabel, getSecondary, selected, onToggle,
  searchPlaceholder = 'Search…', emptyLabel = 'None', maxH = 'max-h-40',
  query: externalQuery,
}: SearchableListProps<T>) {
  const [innerQuery, setInnerQuery] = useState('')
  const controlled = externalQuery !== undefined
  const query = controlled ? externalQuery : innerQuery
  const filtered = query
    ? items.filter((i) => getLabel(i).toLowerCase().includes(query.toLowerCase()))
    : items
  return (
    <div className={controlled ? '' : 'border border-gray-200 rounded'}>
      {!controlled && (
        <div className="relative border-b border-gray-100">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input
            type="search"
            value={innerQuery}
            onChange={(e) => setInnerQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 rounded-t bg-gray-50"
          />
        </div>
      )}
      <div className={`${maxH} overflow-y-auto p-1.5 space-y-0.5`}>
        {filtered.length === 0 ? (
          <p className="text-xs text-gray-400 px-1 py-1">{emptyLabel}</p>
        ) : (
          filtered.map((item) => {
            const id = getKey(item)
            return (
              <label key={id} className="flex items-center gap-2 px-1.5 py-1 rounded hover:bg-gray-50 cursor-pointer">
                <input
                  type="checkbox"
                  checked={selected.includes(id)}
                  onChange={() => onToggle(id)}
                  className="rounded-lg border-gray-300 text-accent focus:ring-accent/40"
                />
                <span className="text-sm text-gray-800 flex-1">{getLabel(item)}</span>
                {getSecondary && getSecondary(item)}
              </label>
            )
          })
        )}
      </div>
    </div>
  )
}
/**
 * Section repliable d'une famille de cibles (players, groupes, sites, groupes de
 * sites) dans le drawer.
 *
 * Repli NON persisté à dessein : l'état par défaut dépend de la sélection du
 * programme ouvert (une famille qui porte des cibles s'ouvre d'office), ce qu'une
 * préférence localStorage écraserait. D'où `useState` local et non `useCollapse`.
 */
function TargetSection({
  label, count, defaultOpen, children,
}: {
  label: string
  /** Nombre d'éléments sélectionnés — affiché en pastille accent si > 0. */
  count: number
  defaultOpen: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [touched, setTouched] = useState(false)

  // Le détail du programme édité arrive APRÈS le montage du drawer : sans cela,
  // une famille qui porte des cibles resterait repliée et la sélection invisible.
  // Respecte un pli/dépli manuel de l'utilisateur (`touched`).
  useEffect(() => {
    if (!touched && count > 0) setOpen(true)
  }, [count, touched])

  return (
    <div className="border border-gray-200 rounded">
      <button
        type="button"
        onClick={() => { setTouched(true); setOpen((o) => !o) }}
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-2.5 py-2 text-left hover:bg-gray-50 transition-sf"
      >
        <ChevronDown className={`w-4 h-4 text-gray-400 transition-sf ${open ? '' : '-rotate-90'}`} />
        <span className="text-sm font-medium text-gray-700 flex-1">{label}</span>
        {count > 0 && (
          <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-accent text-white text-[11px] font-semibold">
            {count}
          </span>
        )}
      </button>
      {open && <div className="border-t border-gray-100">{children}</div>}
    </div>
  )
}

import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import ContentPickerDrawer from '@/components/content/ContentPickerDrawer'
import TargetMapDrawer from '@/components/targets/TargetMapDrawer'
import StorageFitBanner from '@/components/players/StorageFitBanner'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import SearchInput from '@/components/ui/SearchInput'
import StatusBadge from '@/components/ui/StatusBadge'
import NumberField from '@/components/ui/NumberField'
import api from '@/lib/api'
import { useCreateShortcut } from '@/lib/useCreateShortcut'
import { rebalanceRatios } from '@/lib/audioRatio'
import type { AudioBasket, EventRead, GovernanceNode, PlayerGroupRead, PlayerRead, PlaylistRead, ScheduleDetail, ScheduleRead, Site, SiteGroupRead } from '@/types/api'
import ScheduleCalendar, { type CalendarCampaignLite } from './ScheduleCalendar'
import DaySimulationDrawer from './DaySimulationDrawer'

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

// Filtre de type du calendrier unifié (retours beta testeurs : fin des onglets
// Visuel/Audio ambigus — tout est superposé, le filtre tranche).
type TypeFilter = 'all' | 'content' | 'audio' | 'event' | 'campaign'

// Filtre de cible : groupe de sites / site / player — résolu côté serveur
// (targeting canonique) sur les 3 familles.
interface TargetSel {
  type: 'site_group' | 'site' | 'player'
  id: number
  label: string
}

/** Popover « Filtrer par cible » : recherche + 3 groupes (groupes de sites, sites, players). */
function TargetFilter({
  value, onChange, siteGroups, sites, players,
}: {
  value: TargetSel | null
  onChange: (v: TargetSel | null) => void
  siteGroups: SiteGroupRead[]
  sites: Site[]
  players: PlayerRead[]
}) {
  const t = useTranslations()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const ql = q.toLowerCase()
  const groups: { key: TargetSel['type']; label: string; items: { id: number; name: string }[] }[] = [
    {
      key: 'site_group', label: t('schedules.target_site_groups'),
      items: siteGroups.filter((g) => !ql || g.group_name.toLowerCase().includes(ql))
        .map((g) => ({ id: g.id_site_group, name: g.group_name })),
    },
    {
      key: 'site', label: t('schedules.target_sites'),
      items: sites.filter((s) => !ql || s.site_name.toLowerCase().includes(ql))
        .map((s) => ({ id: s.id_site, name: s.site_name })),
    },
    {
      key: 'player', label: t('schedules.target_players'),
      items: players.filter((p) => !ql || p.player_name.toLowerCase().includes(ql))
        .map((p) => ({ id: p.id_player, name: p.player_name })),
    },
  ]

  return (
    <div className="relative" ref={ref}>
      <div className="flex items-center gap-1">
        <button
          onClick={() => { setOpen((o) => !o); setQ('') }}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-sf ${
            value ? 'bg-accent/10 text-accent border-accent/40' : 'bg-surface text-gray-600 border-gray-200 hover:border-accent'
          }`}
        >
          <MapPin className="w-3.5 h-3.5" />
          <span className="max-w-[180px] truncate">{value ? value.label : t('schedules.target_filter_all')}</span>
          <ChevronDown className="w-3 h-3 opacity-60" />
        </button>
        {value && (
          <button
            onClick={() => onChange(null)}
            className="p-1 text-gray-400 hover:text-danger transition-sf"
            title={t('schedules.target_filter_clear')}
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {open && (
        <div className="absolute z-30 mt-1.5 w-72 bg-surface border border-gray-200 rounded-lg shadow-sf-card overflow-hidden">
          <div className="relative border-b border-gray-100">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
            <input
              type="search"
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('common.search')}
              className="w-full pl-8 pr-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 bg-gray-50"
            />
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {groups.every((g) => g.items.length === 0) ? (
              <p className="text-xs text-gray-400 px-3 py-2">{t('common.no_results')}</p>
            ) : groups.map((g) => g.items.length === 0 ? null : (
              <div key={g.key}>
                <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400">{g.label}</p>
                {g.items.map((it) => (
                  <button
                    key={`${g.key}-${it.id}`}
                    onClick={() => { onChange({ type: g.key, id: it.id, label: it.name }); setOpen(false) }}
                    className={`w-full text-left px-3 py-1.5 text-sm transition-sf hover:bg-gray-50 ${
                      value?.type === g.key && value?.id === it.id ? 'text-accent font-medium' : 'text-gray-700'
                    }`}
                  >
                    {it.name}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/** Résumé court de la règle de récurrence d'un programme (pour la vignette). */
function ruleSummary(s: ScheduleRead, t: ReturnType<typeof useTranslations>): string {
  const r = s.rules?.[0]
  if (!r || r.rule_type !== 'weekly' || !r.days_of_week?.length) return t('schedules.rule_always')
  const days = r.days_of_week.length === 7
    ? t('schedules.all_days')
    : r.days_of_week.map((d) => t(`schedules.day_${DAYS[d]}`)).join(' ')
  const time = r.time_start && r.time_end ? ` ${r.time_start.slice(0, 5)}–${r.time_end.slice(0, 5)}` : ''
  return `${days}${time}`
}

/** Résumé court de la plage de validité (dates début/fin) pour la vignette. */
function validitySummary(s: ScheduleRead, t: ReturnType<typeof useTranslations>): string {
  const fmt = (d: string) => {
    const [y, m, day] = d.split('-')
    return `${day}/${m}/${y.slice(2)}`
  }
  if (s.valid_from && s.valid_until) return t('schedules.validity_range_short', { from: fmt(s.valid_from), until: fmt(s.valid_until) })
  if (s.valid_from) return t('schedules.validity_from_short', { date: fmt(s.valid_from) })
  if (s.valid_until) return t('schedules.validity_until_short', { date: fmt(s.valid_until) })
  return ''
}

export default function SchedulesPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [daySimOpen, setDaySimOpen] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  // Calendrier unifié : filtre de type (Tout/Visuels/Audio/Events/Campagnes) + filtre cible.
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [targetSel, setTargetSel] = useState<TargetSel | null>(null)
  // Type du programme en cours de création/édition dans le drawer (ex-onglet).
  const [formKind, setFormKind] = useState<'content' | 'audio'>('content')

  // form fields
  const [name, setName] = useState('')
  const [selectedPlaylist, setSelectedPlaylist] = useState<number | null>(null)
  // Nom de la playlist choisie via le tiroir de recherche : elle peut venir d'une
  // RECHERCHE serveur, donc être absente de la liste paginée chargée par la page.
  const [pickedPlaylistLabel, setPickedPlaylistLabel] = useState<string | null>(null)
  const [playlistPickerOpen, setPlaylistPickerOpen] = useState(false)
  // Carte de ciblage partagée (demande d'Ed) : désigner écrans/sites par l'emplacement.
  const [mapOpen, setMapOpen] = useState(false)
  const [mapMode, setMapMode] = useState<'player' | 'site'>('player')
  // Programme audio multi-paniers : liste de { id_basket, mix_ratio }
  const [audioBaskets, setAudioBaskets] = useState<{ id_basket: number; mix_ratio: number }[]>([])
  const [priority, setPriority] = useState(0)
  const [isActive, setIsActive] = useState(true)
  const [ruleType, setRuleType] = useState<'always' | 'weekly'>('always')
  const [selectedDays, setSelectedDays] = useState<number[]>([0, 1, 2, 3, 4, 5, 6])
  const [timeStart, setTimeStart] = useState('08:00')
  const [timeEnd, setTimeEnd] = useState('22:00')
  // Plage de validité (dates début/fin) du programme — '' = borne ouverte.
  const [validFrom, setValidFrom] = useState('')
  const [validUntil, setValidUntil] = useState('')
  const [selectedPlayers, setSelectedPlayers] = useState<number[]>([])
  const [selectedGroups, setSelectedGroups] = useState<number[]>([])
  const [selectedSites, setSelectedSites] = useState<number[]>([])
  const [selectedSiteGroups, setSelectedSiteGroups] = useState<number[]>([])
  // Recherche unique du picker de cibles — filtre les 4 familles simultanément.
  const [targetQuery, setTargetQuery] = useState('')
  // Nœud de gouvernance (§XVIII) — null = programme libre (pas de couche).
  const [governanceNode, setGovernanceNode] = useState<number | null>(null)
  const [mutateError, setMutateError] = useState<string | null>(null)

  // Filtre cible → query string commune aux 3 familles (résolution serveur).
  const targetQS = targetSel ? `target_type=${targetSel.type}&target_id=${targetSel.id}` : ''
  const targetKey = targetSel ? `${targetSel.type}:${targetSel.id}` : 'all'

  const { data: schedules = [], isLoading } = useQuery<ScheduleRead[]>({
    queryKey: ['schedules', targetKey],
    queryFn: () => api.get<ScheduleRead[]>(`/schedules?limit=200${targetQS ? '&' + targetQS : ''}`).then((r) => r.data),
  })

  // Events — superposés au calendrier (programmation à dates précises).
  const { data: events = [] } = useQuery<EventRead[]>({
    queryKey: ['events', targetKey],
    queryFn: () => api.get<EventRead[]>(`/events${targetQS ? '?' + targetQS : ''}`).then((r) => r.data),
  })

  // Campagnes Retail Media — 3e famille du calendrier unifié. Un utilisateur sans
  // permission campaigns:read (403) voit simplement le calendrier sans campagnes.
  const { data: campaigns = [] } = useQuery<CalendarCampaignLite[]>({
    queryKey: ['campaigns-calendar', targetKey],
    queryFn: () => api.get<CalendarCampaignLite[]>(`/campaigns/${targetQS ? '?' + targetQS : ''}`)
      .then((r) => r.data)
      .catch(() => []),
    retry: false,
  })

  // Sites — alimente le popover de filtre par cible.
  const { data: sites = [] } = useQuery<Site[]>({
    queryKey: ['sites'],
    queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
  })

  const { data: playlists = [] } = useQuery<PlaylistRead[]>({
    queryKey: ['playlists'],
    queryFn: () => api.get<PlaylistRead[]>('/playlists/').then((r) => r.data),
  })

  const { data: baskets = [] } = useQuery<AudioBasket[]>({
    queryKey: ['audio-baskets'],
    queryFn: () => api.get<AudioBasket[]>('/audio-baskets').then((r) => r.data),
    enabled: drawerOpen,
  })

  // Toujours chargés : alimentent aussi le popover de filtre par cible.
  const { data: players = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'],
    queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
  })

  const { data: playerGroups = [] } = useQuery<PlayerGroupRead[]>({
    queryKey: ['player-groups'],
    // Trailing slash obligatoire : sans slash FastAPI redirige en 307 vers l'URL interne Docker
    queryFn: () => api.get<PlayerGroupRead[]>('/player-groups/').then((r) => r.data),
  })

  // Groupes de sites (S6) — cible « région » : tous les players des sites membres.
  const { data: siteGroups = [] } = useQuery<SiteGroupRead[]>({
    queryKey: ['site-groups'],
    queryFn: () => api.get<SiteGroupRead[]>('/site-groups/').then((r) => r.data),
  })

  // Nœuds de gouvernance (§XVIII) — pour rattacher un programme à une couche.
  const { data: govNodes = [] } = useQuery<GovernanceNode[]>({
    queryKey: ['gov-nodes'],
    queryFn: () => api.get<GovernanceNode[]>('/governance/nodes').then((r) => r.data),
    enabled: drawerOpen,
  })

  const { data: editDetail } = useQuery<ScheduleDetail>({
    queryKey: ['schedule', editId],
    queryFn: () => api.get<ScheduleDetail>(`/schedules/${editId}`).then((r) => r.data),
    enabled: editId !== null,
  })

  // Warning d'affectation HDMI-in (non bloquant) : playlist contenant un item « Entrée HDMI »
  // ciblant des players SANS entrée physique → l'item ne leur sera jamais servi (gate au sync,
  // résolution des cibles player/groupe côté serveur).
  const { data: hdmiCheck } = useQuery<{
    has_hdmi_item: boolean
    incompatible_players: { id_player: number; player_name: string | null }[]
  }>({
    queryKey: ['schedule-hdmi-check', selectedPlaylist, selectedPlayers, selectedGroups, selectedSites, selectedSiteGroups],
    queryFn: () => api.post('/schedules/hdmi-check', {
      id_playlist: selectedPlaylist, targets: buildTargets(),
    }).then((r) => r.data),
    enabled: drawerOpen && formKind === 'content' && selectedPlaylist !== null
      && (selectedPlayers.length > 0 || selectedGroups.length > 0 || selectedSites.length > 0 || selectedSiteGroups.length > 0),
  })
  const hdmiIncompat = (hdmiCheck?.has_hdmi_item ? hdmiCheck.incompatible_players : null) ?? []

  // D-b : sous gouvernance, les cibles RESTREIGNENT le périmètre du nœud (elles ne sont plus
  // ignorées). On montre toujours le RÉSULTAT RÉSOLU — sinon on croit avoir ciblé un magasin
  // qui ne recevra rien. Même service que la validation serveur : l'aperçu ne peut pas
  // annoncer autre chose que ce que l'enregistrement acceptera.
  const { data: govScope } = useQuery<{
    node_name: string
    perimeter_count: number
    resolved_count: number
    target_count: number
    out_of_scope: { target_type: string; target_id: number; target_name: string | null }[]
    lan_sync_split: { group: string; kept: string[]; excluded: string[] }[]
  }>({
    queryKey: ['schedule-gov-scope', governanceNode, selectedPlayers, selectedGroups, selectedSites, selectedSiteGroups],
    queryFn: () => api.post('/schedules/governance-scope', {
      id_governance_node: governanceNode, targets: buildTargets(),
    }).then((r) => r.data),
    enabled: drawerOpen && governanceNode != null,
  })

  useEffect(() => {
    if (!editDetail || editId === null) return
    setFormKind(editDetail.schedule_kind === 'audio' ? 'audio' : 'content')
    setName(editDetail.schedule_name)
    setSelectedPlaylist(editDetail.id_playlist ?? null)
    setPickedPlaylistLabel(editDetail.playlist_name ?? null)
    setAudioBaskets((editDetail.baskets ?? []).map((b) => ({ id_basket: b.id_basket, mix_ratio: b.mix_ratio })))
    setPriority(editDetail.priority)
    setIsActive(editDetail.is_active)
    setGovernanceNode(editDetail.id_governance_node ?? null)
    setValidFrom(editDetail.valid_from ?? '')
    setValidUntil(editDetail.valid_until ?? '')
    // Recharge la règle de récurrence dans le formulaire (sinon non modifiable en édition).
    const r = editDetail.rules?.[0]
    if (r && r.rule_type === 'weekly') {
      setRuleType('weekly')
      setSelectedDays(r.days_of_week?.length ? r.days_of_week : [0, 1, 2, 3, 4, 5, 6])
      setTimeStart((r.time_start ?? '08:00').slice(0, 5))
      setTimeEnd((r.time_end ?? '22:00').slice(0, 5))
    } else {
      setRuleType('always')
    }
    setSelectedPlayers(
      editDetail.targets.filter((t) => t.target_type === 'player').map((t) => t.target_id)
    )
    setSelectedGroups(
      editDetail.targets.filter((t) => t.target_type === 'player_group').map((t) => t.target_id)
    )
    setSelectedSites(
      editDetail.targets.filter((t) => t.target_type === 'site').map((t) => t.target_id)
    )
    setSelectedSiteGroups(
      editDetail.targets.filter((t) => t.target_type === 'site_group').map((t) => t.target_id)
    )
  }, [editDetail, editId])

  // Auto-équilibrage des % (option C) PAR FAMILLE : music et ambiance sont 2 couches
  // aux budgets 100% indépendants → on ne rééquilibre QUE les paniers de la même famille
  // que celui qu'on bouge.
  function applyRebalance(changedId: number, newValue: number) {
    const changedType = baskets.find((x) => x.id_basket === changedId)?.basket_type
    if (!changedType || !['music', 'ambiance'].includes(changedType)) return
    const items = audioBaskets
      .map((ab) => ({ ab, b: baskets.find((x) => x.id_basket === ab.id_basket) }))
      .filter(({ b }) => b && b.basket_type === changedType)
      .map(({ ab, b }) => ({ id: ab.id_basket, ratio: ab.mix_ratio, min: b!.min_ratio ?? 0, max: b!.max_ratio ?? 100 }))
    const res = rebalanceRatios(items, changedId, newValue)
    setAudioBaskets((p) => p.map((x) => (res[x.id_basket] !== undefined ? { ...x, mix_ratio: res[x.id_basket] } : x)))
  }

  // Nombre de paniers d'une même famille (music/ambiance) présents dans le programme.
  function mixFamilyCount(type: string | undefined): number {
    if (!type || !['music', 'ambiance'].includes(type)) return 0
    return audioBaskets.filter(
      (ab) => baskets.find((b) => b.id_basket === ab.id_basket)?.basket_type === type,
    ).length
  }

  // Panier UNIQUE dans sa famille (music ou ambiance) → 100% verrouillé (rien à
  // rééquilibrer dans cette famille). Normalise la donnée pour que la sauvegarde
  // enregistre bien 100. Le guard `changed` évite toute boucle de rendu.
  useEffect(() => {
    setAudioBaskets((prev) => {
      let changed = false
      const next = prev.map((ab) => {
        const b = baskets.find((x) => x.id_basket === ab.id_basket)
        if (!b || !['music', 'ambiance'].includes(b.basket_type)) return ab
        const count = prev.filter(
          (x) => baskets.find((y) => y.id_basket === x.id_basket)?.basket_type === b.basket_type,
        ).length
        if (count === 1 && ab.mix_ratio !== 100) { changed = true; return { ...ab, mix_ratio: 100 } }
        return ab
      })
      return changed ? next : prev
    })
  }, [audioBaskets, baskets])

  function buildTargets() {
    return [
      ...selectedPlayers.map((id) => ({ target_type: 'player', target_id: id })),
      ...selectedGroups.map((id) => ({ target_type: 'player_group', target_id: id })),
      ...selectedSites.map((id) => ({ target_type: 'site', target_id: id })),
      ...selectedSiteGroups.map((id) => ({ target_type: 'site_group', target_id: id })),
    ]
  }

  function buildRules() {
    return [
      ruleType === 'always'
        ? { rule_type: 'always' }
        : { rule_type: 'weekly', days_of_week: selectedDays, time_start: timeStart, time_end: timeEnd },
    ]
  }

  // La plage de validité n'a de sens qu'en mode « Récurrent » ; « Toujours » = perpétuel.
  function validityPayload() {
    if (ruleType === 'always') return { valid_from: null, valid_until: null }
    return { valid_from: validFrom || null, valid_until: validUntil || null }
  }

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/schedules', {
        schedule_name: name,
        schedule_kind: formKind,
        id_playlist: formKind === 'content' ? selectedPlaylist : null,
        baskets: formKind === 'audio' ? audioBaskets : [],
        id_governance_node: governanceNode,
        priority,
        ...validityPayload(),
        rules: buildRules(),
        targets: buildTargets(),
      }),
    onSuccess: async () => {
      await qc.refetchQueries({ queryKey: ['schedules'] })
      closeDrawer()
    },
    onError: (e: unknown) => setMutateError(govErr(e)),
  })

  const updateMutation = useMutation({
    mutationFn: async () => {
      await api.put(`/schedules/${editId}`, {
        schedule_name: name,
        id_playlist: formKind === 'content' ? selectedPlaylist : null,
        baskets: formKind === 'audio' ? audioBaskets : undefined,
        id_governance_node: governanceNode,
        priority,
        is_active: isActive,
        ...validityPayload(),
        rules: buildRules(),
      })
      await api.put(
        `/schedules/${editId}/targets`,
        buildTargets()
      )
    },
    onSuccess: async () => {
      qc.invalidateQueries({ queryKey: ['schedule', editId] })
      await qc.refetchQueries({ queryKey: ['schedules'] })
      closeDrawer()
    },
    onError: (e: unknown) => setMutateError(govErr(e)),
  })

  // Message d'erreur : surface le détail backend (403 immutabilité gouvernance, et 422 D-b
  // « cible hors du périmètre du nœud » — ce message NOMME la cible refusée, le remplacer par
  // un « erreur » générique reviendrait à jeter la seule information utile).
  function govErr(e: unknown): string {
    const r = (e as { response?: { status?: number; data?: { detail?: string } } })?.response
    if ((r?.status === 403 || r?.status === 422) && typeof r.data?.detail === 'string') {
      return r.data.detail
    }
    return t('common.error')
  }

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/schedules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schedules'] }),
    onError: (e: unknown) => alert(govErr(e)),
  })

  function resetForm() {
    setName('')
    setSelectedPlaylist(null)
    setPickedPlaylistLabel(null)
    setAudioBaskets([])
    setPriority(0)
    setIsActive(true)
    setRuleType('always')
    setSelectedDays([0, 1, 2, 3, 4, 5, 6])
    setTimeStart('08:00')
    setTimeEnd('22:00')
    setValidFrom('')
    setValidUntil('')
    setSelectedPlayers([])
    setSelectedGroups([])
    setSelectedSites([])
    setSelectedSiteGroups([])
    setTargetQuery('')
    setGovernanceNode(null)
    setMutateError(null)
  }

  function closeDrawer() {
    setDrawerOpen(false)
    setEditId(null)
    resetForm()
  }

  function openEditById(id: number) {
    resetForm()
    setEditId(id)
    setDrawerOpen(true)
  }

  function openEdit(s: ScheduleRead) {
    openEditById(s.id_schedule)
  }

  function openCreate() {
    resetForm()
    // Pré-sélectionne le type selon le filtre actif (filtre Audio → programme audio).
    setFormKind(typeFilter === 'audio' ? 'audio' : 'content')
    setEditId(null)
    setDrawerOpen(true)
  }
  useCreateShortcut(openCreate)

  function toggleGroup(id: number) {
    setSelectedGroups((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

  function toggleDay(d: number) {
    setSelectedDays((prev) =>
      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]
    )
  }

  const isEdit = editId !== null
  const isPending = createMutation.isPending || updateMutation.isPending

  // Application du filtre de type (le filtre cible est déjà appliqué côté serveur).
  const visSchedules = typeFilter === 'all' ? schedules
    : typeFilter === 'content' || typeFilter === 'audio'
      ? schedules.filter((s) => s.schedule_kind === typeFilter)
      : []
  const visEvents = typeFilter === 'all' || typeFilter === 'event' ? events : []
  const visCampaigns = typeFilter === 'all' || typeFilter === 'campaign' ? campaigns : []
  // Vignettes latérales : liste des programmes (events/campagnes ont leurs pages dédiées).
  const sideSchedules = typeFilter === 'content' || typeFilter === 'audio'
    ? schedules.filter((s) => s.schedule_kind === typeFilter)
    : schedules

  const TYPE_FILTERS: { key: TypeFilter; label: string; icon: React.ReactNode }[] = [
    { key: 'all', label: t('schedules.filter_all'), icon: <Layers className="w-3.5 h-3.5" /> },
    { key: 'content', label: t('schedules.filter_content'), icon: <Film className="w-3.5 h-3.5" /> },
    { key: 'audio', label: t('schedules.filter_audio'), icon: <Music className="w-3.5 h-3.5" /> },
    { key: 'event', label: t('schedules.filter_events'), icon: <Zap className="w-3.5 h-3.5" /> },
    { key: 'campaign', label: t('schedules.filter_campaigns'), icon: <Megaphone className="w-3.5 h-3.5" /> },
  ]

  return (
    <>
      <Topbar title={t('schedules.title')}>
        <Can perm="schedules:read">
          <Button size="sm" onClick={() => setDaySimOpen(true)}>
            {t('schedules.daysim_button')}
          </Button>
        </Can>
        <Can perm="schedules:create">
          <Button size="sm" onClick={openCreate}>
            {t('schedules.new')}
          </Button>
        </Can>
      </Topbar>

      <DaySimulationDrawer open={daySimOpen} onClose={() => setDaySimOpen(false)} />

      {/* Page verrouillée au viewport : filtres figés, seul le calendrier (ou la
          colonne de vignettes) défile — sinon la vue mois ne peut pas se caler
          sur la hauteur disponible. */}
      <main className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 min-h-0 flex flex-col px-6 py-6 gap-5">

          {/* Filtres du calendrier unifié : type (pills) + cible (popover) */}
          <div className="shrink-0 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {TYPE_FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setTypeFilter(f.key)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-sf ${
                    typeFilter === f.key
                      ? 'bg-accent text-white border-accent shadow-sf-accent'
                      : 'bg-surface text-gray-600 border-gray-200 hover:border-accent'
                  }`}
                >
                  {f.icon}
                  {f.label}
                </button>
              ))}
            </div>
            <TargetFilter
              value={targetSel}
              onChange={setTargetSel}
              siteGroups={siteGroups}
              sites={sites}
              players={players}
            />
          </div>

          {/* Calendrier (gauche) + liste des programmes en vignettes (droite, scroll propre) */}
          <div className="flex-1 min-h-0 flex items-stretch gap-6">
            <div className="flex-1 min-w-0 min-h-0">
              <ScheduleCalendar
                schedules={visSchedules}
                events={visEvents}
                campaigns={visCampaigns}
                exportTag={`${typeFilter}${targetSel ? '_' + targetSel.label.replace(/\s+/g, '-') : ''}`}
                onOpenSchedule={openEditById}
              />
            </div>

            <aside className="w-72 shrink-0 min-h-0">
              <div className="bg-surface border border-gray-200 rounded-lg flex flex-col h-full min-h-0 shadow-sf-card">
                {/* Recherche — toujours visible (hors zone de scroll) */}
                <div className="p-3 border-b border-gray-100">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                    <input
                      type="search"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder={t('common.search')}
                      className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                    />
                  </div>
                </div>

                {/* Vignettes scrollables */}
                <div className="flex-1 overflow-y-auto p-2 space-y-2">
                  {isLoading ? (
                    <div className="flex justify-center py-8">
                      <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : (() => {
                    const filtered = sideSchedules.filter((s) => !search || s.schedule_name.toLowerCase().includes(search.toLowerCase()))
                    if (filtered.length === 0) {
                      return (
                        <div className="flex flex-col items-center justify-center py-12 gap-3 text-gray-400">
                          <Calendar className="w-8 h-8" />
                          <p className="text-xs text-center px-2">{t(sideSchedules.length === 0 ? 'schedules.no_schedules' : 'common.no_results')}</p>
                        </div>
                      )
                    }
                    return filtered.map((s) => (
                      <div
                        key={s.id_schedule}
                        onClick={() => openEdit(s)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => { if (e.key === 'Enter') openEdit(s) }}
                        className={`rounded-lg border p-2.5 cursor-pointer transition-sf hover:border-accent ${s.is_active ? 'bg-surface border-gray-200' : 'bg-gray-50 border-gray-200 opacity-70'}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="text-sm font-medium text-gray-900 truncate inline-flex items-center gap-1.5" title={s.schedule_name}>
                            {s.schedule_kind === 'audio'
                              ? <Music className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                              : <Film className="w-3.5 h-3.5 text-gray-400 shrink-0" />}
                            <span className="truncate">{s.schedule_name}</span>
                          </span>
                          <StatusBadge status={s.is_active ? 'online' : 'offline'} label={t(s.is_active ? 'schedules.active' : 'schedules.inactive')} />
                        </div>
                        <p className="text-xs text-gray-500 truncate mt-0.5">
                          {s.schedule_kind === 'audio'
                            ? t('schedules.audio_program')
                            : s.playlist_name ?? `#${s.id_playlist}`}
                        </p>
                        {(s.valid_from || s.valid_until) && (
                          <p className="text-[11px] text-accent inline-flex items-center gap-1 mt-0.5">
                            <Calendar className="w-3 h-3 shrink-0" />
                            <span className="truncate">{validitySummary(s, t)}</span>
                          </p>
                        )}
                        <div className="flex items-center justify-between gap-2 mt-1.5">
                          <span className="text-[11px] text-gray-400 truncate">{ruleSummary(s, t)} · P{s.priority}</span>
                          <div className="flex items-center gap-1 shrink-0">
                            <Can perm="schedules:edit">
                              <button
                                onClick={(e) => { e.stopPropagation(); openEdit(s) }}
                                className="p-1 text-gray-300 hover:text-accent transition-sf"
                                title={t('schedules.edit')}
                              >
                                <Pencil className="w-3.5 h-3.5" />
                              </button>
                            </Can>
                            <Can perm="schedules:delete">
                              <button
                                onClick={(e) => { e.stopPropagation(); if (confirm(t('schedules.delete_confirm'))) deleteMutation.mutate(s.id_schedule) }}
                                className="p-1 text-gray-300 hover:text-danger transition-sf"
                                title={t('common.delete')}
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </Can>
                          </div>
                        </div>
                      </div>
                    ))
                  })()}
                </div>
              </div>
            </aside>
          </div>
        </div>
      </main>

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        title={isEdit ? t('schedules.edit') : t('schedules.new')}
      >
        {/* Nudge lecture-seule : édition = schedules:edit, création = schedules:create.
            Un rôle en lecture ouvre ce drawer via la vignette pour consulter. */}
        <div className="space-y-5" data-write-perm={isEdit ? 'schedules:edit' : 'schedules:create'}>
          {/* Type de programme (ex-onglets Visuel/Audio) — figé en édition. */}
          {!isEdit && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700">{t('schedules.kind_label')}</label>
              <div className="flex gap-2">
                {(['content', 'audio'] as const).map((k) => (
                  <button
                    key={k}
                    onClick={() => { setFormKind(k); if (k === 'audio') setSelectedPlaylist(null); else setAudioBaskets([]) }}
                    className={`inline-flex items-center gap-1.5 px-4 py-2 rounded text-sm font-medium border transition-sf ${
                      formKind === k
                        ? 'bg-accent text-white border-accent'
                        : 'bg-surface text-gray-600 border-gray-200 hover:border-accent'
                    }`}
                  >
                    {k === 'content' ? <Film className="w-4 h-4" /> : <Music className="w-4 h-4" />}
                    {t(k === 'content' ? 'schedules.tab_content' : 'schedules.tab_audio')}
                  </button>
                ))}
              </div>
            </div>
          )}

          <Input
            label={t('schedules.name_label')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />

          {formKind === 'content' ? (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700">{t('schedules.playlist_label')}</label>
              {/* 🔴 L'ancien <select> appelait l'API sans paramètre — plafond serveur de
                  50 playlists, sans recherche : au-delà, invisible ET introuvable (même
                  défaut que les événements avant l'audit du 29/07). Le tiroir partagé
                  cherche côté SERVEUR et parcourt les dossiers. */}
              <button
                type="button"
                data-testid="schedule-playlist-select"
                onClick={() => setPlaylistPickerOpen(true)}
                className="w-full flex items-center justify-between gap-2 border border-gray-300 rounded-lg px-3 py-2 text-sm text-left hover:border-accent transition-sf"
              >
                <span className={selectedPlaylist ? 'text-gray-800 truncate' : 'text-gray-400'}>
                  {selectedPlaylist
                    ? (pickedPlaylistLabel
                        ?? playlists.find((p) => p.id_playlist === selectedPlaylist)?.playlist_name
                        ?? `#${selectedPlaylist}`)
                    : t('schedules.playlist_placeholder')}
                </span>
                <Search className="w-4 h-4 text-gray-400 shrink-0" />
              </button>
              {(() => {
                const chosen = playlists.find((p) => p.id_playlist === selectedPlaylist)
                const lanSyncedSelected = players.some(
                  (p) => selectedPlayers.includes(p.id_player) && p.display_config?.lan_sync_enabled,
                )
                if (!chosen || chosen.sync_ready || !lanSyncedSelected) return null
                return (
                  <div className="flex items-start gap-2 rounded border border-amber-400/20 dark:border-amber-500/30 bg-amber-500/10 dark:bg-amber-500/15 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                    <span>{t('schedules.lan_sync_warn')}</span>
                  </div>
                )
              })()}
              {/* Item « Entrée HDMI » ciblant des players sans entrée physique (non bloquant) */}
              {hdmiIncompat.length > 0 && (
                <div className="flex items-start gap-2 rounded border border-amber-400/20 dark:border-amber-500/30 bg-amber-500/10 dark:bg-amber-500/15 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{t('schedules.hdmi_incompat_warn', {
                    players: hdmiIncompat.map((p) => p.player_name ?? `#${p.id_player}`).join(', '),
                  })}</span>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">{t('schedules.baskets_label')}</label>
              {audioBaskets.length === 0 && (
                <p className="text-xs text-gray-400 italic">{t('schedules.baskets_empty')}</p>
              )}
              {audioBaskets.map((ab) => {
                const b = baskets.find((x) => x.id_basket === ab.id_basket)
                const isMix = ['music', 'ambiance'].includes(b?.basket_type ?? '')
                const soloInFamily = isMix && mixFamilyCount(b?.basket_type) === 1
                return (
                  <div key={ab.id_basket} className="bg-canvas border border-gray-100 rounded-lg p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <span className="text-sm font-medium text-gray-800">{b?.basket_name ?? `#${ab.id_basket}`}</span>
                        <span className="text-[11px] text-gray-400 ml-1.5">{b ? t(`ab.type_${b.basket_type}`) : ''}</span>
                      </div>
                      <button
                        onClick={() => setAudioBaskets((p) => p.filter((x) => x.id_basket !== ab.id_basket))}
                        className="text-gray-300 hover:text-danger shrink-0"
                      >×</button>
                    </div>
                    {isMix ? (
                      <div className="flex items-center gap-2 mt-1.5">
                        <input
                          type="range" min={0} max={100} value={soloInFamily ? 100 : ab.mix_ratio}
                          disabled={soloInFamily}
                          onChange={(e) => applyRebalance(ab.id_basket, Number(e.target.value))}
                          className="flex-1 accent-accent disabled:opacity-50"
                        />
                        <span className="text-xs text-gray-500 w-10 text-right">{soloInFamily ? 100 : ab.mix_ratio}%</span>
                      </div>
                    ) : (
                      <p className="text-[11px] text-amber-600 dark:text-amber-300 mt-1">
                        {b?.basket_type === 'emergency' ? t('schedules.trigger_emergency')
                          : b?.basket_type === 'message' ? t('schedules.trigger_message')
                          : t('schedules.trigger_jingle')}
                      </p>
                    )}
                  </div>
                )
              })}

              {/* Ajouter un panier */}
              {baskets.some((b) => !audioBaskets.some((ab) => ab.id_basket === b.id_basket)) && (
                <select
                  value=""
                  onChange={(e) => {
                    const id = Number(e.target.value)
                    if (id) setAudioBaskets((p) => [...p, { id_basket: id, mix_ratio: 50 }])
                  }}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                >
                  <option value="">+ {t('schedules.add_basket')}</option>
                  {baskets
                    .filter((b) => !audioBaskets.some((ab) => ab.id_basket === b.id_basket))
                    .map((b) => (
                      <option key={b.id_basket} value={b.id_basket}>{b.basket_name}</option>
                    ))}
                </select>
              )}

              {/* Total du mix PAR FAMILLE (music et ambiance ont chacune leur budget ≤100) */}
              {(['music', 'ambiance'] as const).map((fam) => {
                const inFam = audioBaskets.filter(
                  (ab) => baskets.find((b) => b.id_basket === ab.id_basket)?.basket_type === fam,
                )
                if (inFam.length === 0) return null
                const total = inFam.reduce((s, ab) => s + ab.mix_ratio, 0)
                return (
                  <p key={fam} className={`text-xs ${total > 100 ? 'text-danger font-medium' : 'text-gray-400'}`}>
                    {t(`ab.type_${fam}`)} — {t('schedules.mix_total', { total })}
                  </p>
                )
              })}
            </div>
          )}

          <NumberField
            label={t('schedules.priority_label')}
            min={0}
            max={100}
            value={priority}
            onCommit={(v) => setPriority(v ?? 0)}
          />

          {/* Nœud de gouvernance (§XVIII) — rattache le programme à une couche. */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">{t('schedules.governance_node_label')}</label>
            <select
              value={governanceNode ?? ''}
              onChange={(e) => setGovernanceNode(e.target.value ? Number(e.target.value) : null)}
              className="w-full border border-gray-300 rounded-md px-2.5 py-2 text-sm bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
            >
              <option value="">{t('schedules.governance_node_none')}</option>
              {govNodes.map((n) => (
                <option key={n.id_node} value={n.id_node}>
                  {'— '.repeat(n.node_level)}{n.node_name}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-gray-400">{t('schedules.governance_node_hint')}</p>
          </div>

          {isEdit && (
            <div className="flex items-center gap-3">
              <input
                id="is-active"
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="rounded-lg border-gray-300 text-accent focus:ring-accent/40"
              />
              <label htmlFor="is-active" className="text-sm font-medium text-gray-700">
                {t('schedules.active')}
              </label>
            </div>
          )}

          {/* Quand diffuser ? — récurrence (création ET édition) */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">{t('schedules.when_label')}</label>
            <div className="flex gap-2">
              {(['always', 'weekly'] as const).map((type) => (
                <button
                  key={type}
                  onClick={() => setRuleType(type)}
                  className={`px-4 py-2 rounded text-sm font-medium border transition-sf ${
                    ruleType === type
                      ? 'bg-accent text-white border-accent'
                      : 'bg-surface text-gray-600 border-gray-200 hover:border-accent'
                  }`}
                >
                  {t(`schedules.rule_${type}`)}
                </button>
              ))}
            </div>
          </div>

          {ruleType === 'weekly' && (
            <>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-gray-700">{t('schedules.days_label')}</label>
                <div className="flex flex-wrap gap-1.5">
                  {DAYS.map((d, i) => (
                    <button
                      key={d}
                      onClick={() => toggleDay(i)}
                      className={`px-3 py-1.5 rounded text-xs font-medium border transition-sf ${
                        selectedDays.includes(i)
                          ? 'bg-accent text-white border-accent'
                          : 'bg-surface text-gray-600 border-gray-200 hover:border-accent'
                      }`}
                    >
                      {t(`schedules.day_${d}`)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <Input
                  label={t('schedules.time_start_label')}
                  type="time"
                  value={timeStart}
                  onChange={(e) => setTimeStart(e.target.value)}
                />
                <Input
                  label={t('schedules.time_end_label')}
                  type="time"
                  value={timeEnd}
                  onChange={(e) => setTimeEnd(e.target.value)}
                />
              </div>

              {/* Plage de validité (dates début/fin, optionnel) — seulement en mode Récurrent */}
              <div className="space-y-1.5 pt-1">
                <label className="text-sm font-medium text-gray-700">{t('schedules.validity_label')}</label>
                <div className="grid grid-cols-2 gap-3">
                  <Input
                    label={t('schedules.valid_from_label')}
                    type="date"
                    value={validFrom}
                    max={validUntil || undefined}
                    onChange={(e) => setValidFrom(e.target.value)}
                  />
                  <Input
                    label={t('schedules.valid_until_label')}
                    type="date"
                    value={validUntil}
                    min={validFrom || undefined}
                    onChange={(e) => setValidUntil(e.target.value)}
                  />
                </div>
                <p className="text-xs text-gray-400">{t('schedules.validity_hint')}</p>
              </div>
            </>
          )}

          {/* Cibles — un seul champ de recherche pour les 4 familles (players,
              groupes de players, sites, groupes de sites), chacune repliable avec
              une pastille accent quand elle porte une sélection. */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">{t('schedules.targets_label')}</label>
            {/* « Est-ce que ca rentre ? » — le contenu affecte tient-il sur les ecrans vises ?
                Muet quand tout va bien. Le serveur resout lui-meme les cibles et deplie les
                sous-playlists : lui envoyer des listes deja resolues ferait porter le controle
                sur autre chose que ce qui sera diffuse. */}
            {formKind === 'content' && (
              <StorageFitBanner
                targets={buildTargets()}
                idPlaylist={selectedPlaylist}
                enabled={drawerOpen}
              />
            )}
            {/* D-b : le bandeau disait l'INVERSE jusqu'ici (« les cibles sont ignorées », D2).
                Elles filtrent désormais le périmètre du nœud — et ne peuvent que le
                restreindre, jamais l'élargir. Le compteur montre le résultat résolu. */}
            {governanceNode != null && (
              <div className="text-[11px] text-amber-600 dark:text-amber-300 bg-amber-500/10 dark:bg-amber-500/15 rounded-md px-2 py-1.5 space-y-1">
                <p>{t('schedules.targets_governed_note')}</p>
                {govScope && (
                  <p data-testid="gov-scope-count">
                    {govScope.target_count === 0
                      ? t('schedules.targets_governed_all', {
                          node: govScope.node_name, count: govScope.perimeter_count })
                      : t('schedules.targets_governed_resolved', {
                          count: govScope.resolved_count,
                          total: govScope.perimeter_count,
                          targets: govScope.target_count })}
                  </p>
                )}
                {govScope && govScope.out_of_scope.length > 0 && (
                  <p className="text-danger">
                    {t('schedules.targets_governed_out_of_scope', {
                      names: govScope.out_of_scope
                        .map((o) => o.target_name ?? `#${o.target_id}`).join(', '),
                    })}
                  </p>
                )}
                {/* D4 — le ciblage coupe un groupe de synchro LAN : on AVERTIT, on ne bloque
                    pas. Rien ne casse techniquement (la clé de synchro dérive des couches
                    actives, chaque sous-ensemble se resynchronise), mais personne ne peut le
                    deviner devant l'écran : deux dalles côte à côte, synchronisées, qui ne
                    jouent plus la même chose. */}
                {govScope?.lan_sync_split.map((g) => (
                  <p key={g.group} data-testid="gov-lan-split">
                    {t('schedules.targets_governed_lan_split', {
                      group: g.group,
                      kept: g.kept.join(', '),
                      excluded: g.excluded.join(', '),
                    })}
                  </p>
                ))}
              </div>
            )}
            <div>
            <SearchInput
              value={targetQuery}
              onChange={(e) => setTargetQuery(e.target.value)}
              placeholder={t('schedules.targets_search_placeholder')}
              wrapperClassName="max-w-none"
            />

            {/* Carte partagée (demande d'Ed) : à 200+ écrans on ne cherche plus un nom,
                on désigne un emplacement. Deux entrées car la carte alimente deux
                familles distinctes : les écrans (selectedPlayers) ou les sites entiers
                (selectedSites) — les autres familles restent aux listes. */}
            <div className="flex items-center gap-4 mt-1.5 mb-1">
              <button
                type="button"
                data-testid="schedule-target-map-players"
                onClick={() => { setMapMode('player'); setMapOpen(true) }}
                className="text-xs text-accent hover:underline inline-flex items-center gap-1"
              >
                <MapPin className="w-3.5 h-3.5" />
                {t('schedules.map_players')}
              </button>
              <button
                type="button"
                data-testid="schedule-target-map-sites"
                onClick={() => { setMapMode('site'); setMapOpen(true) }}
                className="text-xs text-accent hover:underline inline-flex items-center gap-1"
              >
                <MapPin className="w-3.5 h-3.5" />
                {t('schedules.map_sites')}
              </button>
            </div>

            {players.length > 0 && (
              <TargetSection
                label={t('schedules.players_label')}
                count={selectedPlayers.length}
                defaultOpen={selectedPlayers.length > 0}
              >
                <SearchableList
                  items={formKind === 'audio'
                    ? players.filter((pl) => (pl.player_os ?? '').toLowerCase().startsWith('linux'))
                    : players}
                  getKey={(pl) => pl.id_player}
                  getLabel={(pl) => pl.player_name}
                  getSecondary={(pl) => (
                    <span className={`w-2 h-2 rounded-full shrink-0 ${pl.status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
                  )}
                  selected={selectedPlayers}
                  onToggle={(id) =>
                    setSelectedPlayers((prev) =>
                      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
                    )
                  }
                  emptyLabel={t('common.no_results')}
                  maxH="max-h-36"
                  query={targetQuery}
                />
              </TargetSection>
            )}

            {playerGroups.length > 0 && (
              <TargetSection
                label={t('schedules.groups_label')}
                count={selectedGroups.length}
                defaultOpen={selectedGroups.length > 0}
              >
                <SearchableList
                  items={formKind === 'audio'
                    ? playerGroups.filter((g) => g.group_type !== 'content')
                    : playerGroups.filter((g) => g.group_type !== 'audio')}
                  getKey={(g) => g.id_group}
                  getLabel={(g) => g.group_name}
                  selected={selectedGroups}
                  onToggle={toggleGroup}
                  emptyLabel={t('common.no_results')}
                  maxH="max-h-28"
                  query={targetQuery}
                />
              </TargetSection>
            )}

            {/* Sites — cible « tout le magasin » (audit ciblage 2026-07-18 : le
                targeting canonique la supportait, l'UI ne l'offrait pas). */}
            {sites.length > 0 && (
              <TargetSection
                label={t('schedules.target_sites')}
                count={selectedSites.length}
                defaultOpen={selectedSites.length > 0}
              >
                <SearchableList
                  items={sites}
                  getKey={(s) => s.id_site}
                  getLabel={(s) => s.site_name}
                  selected={selectedSites}
                  onToggle={(id) =>
                    setSelectedSites((prev) =>
                      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
                    )
                  }
                  emptyLabel={t('common.no_results')}
                  maxH="max-h-28"
                  query={targetQuery}
                />
              </TargetSection>
            )}

            {/* Groupes de sites (S6 — cible « région ») */}
            {siteGroups.length > 0 && (
              <TargetSection
                label={t('schedules.site_groups_label')}
                count={selectedSiteGroups.length}
                defaultOpen={selectedSiteGroups.length > 0}
              >
                <SearchableList
                  items={siteGroups}
                  getKey={(g) => g.id_site_group}
                  getLabel={(g) => g.group_name}
                  selected={selectedSiteGroups}
                  onToggle={(id) =>
                    setSelectedSiteGroups((prev) =>
                      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
                    )
                  }
                  emptyLabel={t('common.no_results')}
                  maxH="max-h-28"
                  query={targetQuery}
                />
              </TargetSection>
            )}
            </div>
          </div>

          {mutateError && (
            <p className="text-sm text-danger">{mutateError}</p>
          )}

          <Button
            data-write-action
            onClick={() => isEdit ? updateMutation.mutate() : createMutation.mutate()}
            loading={isPending}
            disabled={!name.trim() || (formKind === 'content' ? !selectedPlaylist : audioBaskets.length === 0)}
            className="w-full"
          >
            {isEdit ? t('common.save') : t('common.create')}
          </Button>
        </div>
      </Drawer>

      {/* Tiroirs partagés — au niveau PAGE : un Drawer imbriqué dans un Drawer serait
          découpé par le `transform` du panneau parent (même montage que /events). */}
      <TargetMapDrawer
        open={mapOpen}
        onClose={() => setMapOpen(false)}
        mode={mapMode}
        sites={sites.map((s) => ({
          id_site: s.id_site, site_name: s.site_name,
          latitude: s.latitude ?? null, longitude: s.longitude ?? null,
          screen_count: players.filter((p) => p.id_site === s.id_site).length,
        }))}
        players={players.map((p) => ({
          id_player: p.id_player, player_name: p.player_name, id_site: p.id_site ?? null,
        }))}
        value={mapMode === 'site' ? selectedSites : selectedPlayers}
        onApply={(ids) => {
          if (mapMode === 'site') setSelectedSites(ids)
          else setSelectedPlayers(ids)
        }}
      />

      <ContentPickerDrawer
        open={playlistPickerOpen}
        onClose={() => setPlaylistPickerOpen(false)}
        mediaTypes={[]}
        multiple={false}
        withPlaylists
        onPick={(pick) => {
          if (pick.playlist) {
            setSelectedPlaylist(pick.playlist)
            setPickedPlaylistLabel(pick.label ?? null)
          }
        }}
      />
    </>
  )
}
