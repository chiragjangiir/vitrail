'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Zap, Play, Square, X, Trash2, Search, Pencil, Info, Lock, Film, Music, MonitorCheck, MapPin } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import SearchInput from '@/components/ui/SearchInput'
import StatusBadge from '@/components/ui/StatusBadge'
import { CardGrid, EntityCard } from '@/components/ui/CardGrid'
import NumberField from '@/components/ui/NumberField'
import ContentPickerDrawer from '@/components/content/ContentPickerDrawer'
import TargetMapDrawer from '@/components/targets/TargetMapDrawer'
import api from '@/lib/api'
import { useCreateShortcut } from '@/lib/useCreateShortcut'
import { useSearchPrefill } from '@/lib/useSearchPrefill'
import { msToWholeSeconds } from '@/lib/eventDuration'
import { isDemoBlocked } from '@/lib/demo'
import NodeSelect from '@/components/governance/NodeSelect'
import type {
  AudioBasket, EventRead, MediaListItem,
  PlayerGroupRead, PlaylistRead, PlayerRead, Site, SiteGroupRead,
} from '@/types/api'

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
const DAY_SHORT = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

type EventStatus  = 'inactive' | 'active' | 'reverting' | 'completed' | 'cancelled'
type EventType    = 'manual' | 'scheduled' | 'conditional' | 'ai_predicted'
type BadgeStatus  = 'done' | 'warning' | 'offline' | 'info' | 'pending'
type ContentMode  = 'playlist' | 'media'
type TargetType   = 'org' | 'player' | 'group' | 'site' | 'site_group'

function statusBadge(s: EventStatus): BadgeStatus {
  if (s === 'active')    return 'done'
  if (s === 'reverting') return 'warning'
  if (s === 'cancelled') return 'offline'
  if (s === 'completed') return 'info'
  return 'pending'
}

function typeBadge(t: EventType): string {
  const map: Record<EventType, string> = {
    manual:       'bg-white/10 text-gray-600',
    scheduled:    'bg-accent/10 dark:bg-blue-500/15 text-blue-700 dark:text-blue-300',
    conditional:  'bg-purple-50 dark:bg-purple-500/15 text-purple-700 dark:text-purple-300',
    ai_predicted: 'bg-amber-500/10 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300',
  }
  return map[t] ?? 'bg-gray-100 text-gray-600'
}

function schedSummary(trigger_config: Record<string, unknown> | null): string | null {
  if (!trigger_config) return null
  const conditions = (trigger_config.conditions as Array<Record<string, unknown>>) ?? []
  const sched = conditions.find((c) => c.source === 'schedule')
  if (!sched) return null
  const days = (sched.days_of_week as number[]) ?? []
  const daysStr = days.map((d) => DAY_SHORT[d]).join(' ')
  return `${daysStr} ${sched.time_start}–${sched.time_end}`
}

type TargetEntry = { target_type: string; target_ids: number[] }

/** Les DEUX formes de target_config — héritée mono-type et hétérogène {targets:[...]}
 *  (2026-07-30, union des entrées) — normalisées en liste d'entrées. Miroir du
 *  normaliseur serveur `targeting.event_target_entries`. */
function targetEntries(tc: Record<string, unknown>): TargetEntry[] {
  const raw = (tc as { targets?: unknown }).targets
  if (Array.isArray(raw)) {
    return (raw as Record<string, unknown>[]).map((e) => ({
      target_type: (e.target_type as string) ?? 'player',
      target_ids: (e.target_ids as number[]) ?? [],
    }))
  }
  return [{
    target_type: (tc.target_type as string) ?? 'player',
    target_ids: (tc.target_ids as number[]) ?? [],
  }]
}

function isOrgTarget(tc: Record<string, unknown>): boolean {
  return targetEntries(tc).some((e) => e.target_type === 'org')
}

function targetSummary(target_config: Record<string, unknown>): string {
  if (isOrgTarget(target_config)) return '—'
  const parts = targetEntries(target_config)
    .filter((e) => e.target_ids.length)
    .map((e) => {
      if (e.target_type === 'group') return `${e.target_ids.length}g`
      // site / site_group comptent des SITES, pas des players — le suffixe 'p' était
      // trompeur pour site_group (imprécision préexistante corrigée au passage).
      if (e.target_type === 'site' || e.target_type === 'site_group') return `${e.target_ids.length}s`
      return `${e.target_ids.length}p`
    })
  return parts.join('+') || '0p'
}

function contentLabel(ev: EventRead): string {
  if (ev.event_kind === 'audio') {
    return ev.basket_name ? `${ev.basket_name} · ${ev.mix_ratio ?? 0}%` : '—'
  }
  return ev.playlist_name ?? ev.media_name ?? '—'
}

/** Convertit un ISO UTC en valeur date "YYYY-MM-DD" (heure locale du navigateur) */
function toDateLocal(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Convertit une valeur date "YYYY-MM-DD" en ISO UTC début de journée (null si vide) */
function fromDateLocalStart(val: string): string | null {
  if (!val) return null
  return new Date(`${val}T00:00:00`).toISOString()
}

/** Convertit une valeur date "YYYY-MM-DD" en ISO UTC fin de journée (null si vide) */
function fromDateLocalEnd(val: string): string | null {
  if (!val) return null
  return new Date(`${val}T23:59:59`).toISOString()
}

/** Formate une date ISO en affichage compact "DD/MM" */
function fmtDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`
}

/** Formate une durée en ms en affichage compact */
function fmtDuration(ms: number): string {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60), rem = s % 60
  if (m < 60) return rem ? `${m}m${rem}s` : `${m}m`
  return `${Math.floor(m / 60)}h${m % 60 ? (m % 60) + 'm' : ''}`
}

/** Retourne true si l'event est hors de sa fenêtre de validité ou sous embargo */
function isOutOfValidity(ev: EventRead): boolean {
  const now = Date.now()
  if (ev.valid_from && new Date(ev.valid_from).getTime() > now) return true
  if (ev.valid_until && new Date(ev.valid_until).getTime() < now) return true
  if (ev.not_before_utc && new Date(ev.not_before_utc).getTime() > now) return true
  return false
}

const EMBARGO_TIMEZONES = [
  { value: 'UTC',                  label: 'UTC' },
  { value: 'Europe/Zurich',        label: 'Europe/Zurich (Geneva)' },
  { value: 'Europe/Paris',         label: 'Europe/Paris' },
  { value: 'Europe/London',        label: 'Europe/London' },
  { value: 'Europe/Berlin',        label: 'Europe/Berlin' },
  { value: 'Europe/Madrid',        label: 'Europe/Madrid' },
  { value: 'America/New_York',     label: 'America/New_York (ET)' },
  { value: 'America/Chicago',      label: 'America/Chicago (CT)' },
  { value: 'America/Los_Angeles',  label: 'America/Los_Angeles (PT)' },
  { value: 'America/Sao_Paulo',    label: 'America/Sao_Paulo' },
  { value: 'Asia/Dubai',           label: 'Asia/Dubai' },
  { value: 'Asia/Kolkata',         label: 'Asia/Kolkata' },
  { value: 'Asia/Singapore',       label: 'Asia/Singapore' },
  { value: 'Asia/Tokyo',           label: 'Asia/Tokyo' },
  { value: 'Australia/Sydney',     label: 'Australia/Sydney' },
]

/** Convertit un datetime-local "YYYY-MM-DDTHH:mm" + timezone IANA en ISO UTC */
function localDtToUtc(localDtStr: string, tz: string): string | null {
  if (!localDtStr) return null
  try {
    const naive = new Date(localDtStr + ':00Z')
    const fmt = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    })
    const p = fmt.formatToParts(naive).reduce((a, x) => ({ ...a, [x.type]: x.value }), {} as Record<string, string>)
    const h = p.hour === '24' ? '00' : p.hour
    const tzAsUtc = new Date(`${p.year}-${p.month}-${p.day}T${h}:${p.minute}:${p.second}Z`)
    return new Date(naive.getTime() + (naive.getTime() - tzAsUtc.getTime())).toISOString()
  } catch { return null }
}

/** Convertit un ISO UTC en datetime-local "YYYY-MM-DDTHH:mm" dans la timezone donnée */
function utcToLocalDt(utcStr: string | null | undefined, tz: string): string {
  if (!utcStr) return ''
  try {
    const d = new Date(utcStr)
    const fmt = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
    const p = fmt.formatToParts(d).reduce((a, x) => ({ ...a, [x.type]: x.value }), {} as Record<string, string>)
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
  } catch { return '' }
}

/** Composant de liste avec recherche intégrée */
function SearchableList<T>({
  items,
  getKey,
  getLabel,
  getSecondary,
  selected,
  onToggle,
  searchPlaceholder,
  emptyLabel,
  maxH = 'max-h-40',
}: {
  items: T[]
  getKey: (item: T) => number
  getLabel: (item: T) => string
  getSecondary?: (item: T) => React.ReactNode
  selected: number[]
  onToggle: (id: number) => void
  searchPlaceholder: string
  emptyLabel: string
  maxH?: string
}) {
  const [query, setQuery] = useState('')
  const filtered = query
    ? items.filter((i) => getLabel(i).toLowerCase().includes(query.toLowerCase()))
    : items

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="px-2.5 py-1.5 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center gap-1.5">
          <Search className="w-3 h-3 text-gray-400 shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="flex-1 text-xs bg-transparent border-0 focus:outline-none text-gray-700 placeholder:text-gray-400"
          />
          {query && (
            <button onClick={() => setQuery('')} className="text-gray-400 hover:text-gray-600 text-xs leading-none">×</button>
          )}
        </div>
      </div>
      <div className={`${maxH} overflow-y-auto divide-y divide-gray-100`}>
        {filtered.length === 0 ? (
          <p className="px-3 py-2 text-xs text-gray-400 italic">{emptyLabel}</p>
        ) : (
          filtered.map((item) => {
            const id = getKey(item)
            const checked = selected.includes(id)
            return (
              <label
                key={id}
                className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-50 transition-sf"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(id)}
                  className="accent-accent w-4 h-4 shrink-0"
                />
                <span className="text-sm text-gray-800 truncate flex-1">{getLabel(item)}</span>
                {getSecondary && getSecondary(item)}
              </label>
            )
          })
        )}
      </div>
    </div>
  )
}

export default function EventsPage() {
  const t = useTranslations()
  const qc = useQueryClient()

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingEvent, setEditingEvent] = useState<EventRead | null>(null)
  useCreateShortcut(() => { setEditingEvent(null); setDrawerOpen(true) })
  const [search, setSearch] = useState('')
  useSearchPrefill(setSearch)
  const [mutateError, setMutateError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  // form fields
  const [name, setName] = useState('')
  const [eventType, setEventType] = useState<EventType>('manual')
  const [kind, setKind] = useState<'content' | 'audio'>('content')
  const [contentMode, setContentMode] = useState<ContentMode>('playlist')
  const [selectedPlaylist, setSelectedPlaylist] = useState<number | null>(null)
  const [selectedMedia, setSelectedMedia] = useState<number | null>(null)
  // Tiroir de contenu partagé (audit 2026-07-29) — remplace les deux menus déroulants.
  const [contentPickerOpen, setContentPickerOpen] = useState(false)
  // Nom et durée du contenu retenu, RENDUS PAR LE TIROIR : le contenu peut venir d'une
  // recherche, donc être absent des listes chargées d'avance (c'est tout l'intérêt).
  const [pickedLabel, setPickedLabel] = useState<string | null>(null)
  const [pickedDuration, setPickedDuration] = useState<number | null>(null)
  // Choix des écrans SUR LA CARTE (demande d'Ed) — indispensable au-delà de quelques
  // dizaines d'écrans, où l'on ne cherche plus par nom mais par emplacement.
  const [mapOpen, setMapOpen] = useState(false)
  const [selectedBasket, setSelectedBasket] = useState<number | null>(null)
  const [audioRatio, setAudioRatio] = useState(50)
  const [priority, setPriority] = useState(70)
  const [govNode, setGovNode] = useState<number | null>(null)
  const [durationSec, setDurationSec] = useState<string>('')
  const [autoDuration, setAutoDuration] = useState(false)
  const [schedLoop, setSchedLoop] = useState(true)  // true=boucler jusqu'à time_end, false=play-once
  // Récurrence par intervalle (« spot toutes les N min ») : modificateur du play-once. '' = off.
  // Si renseigné, l'occurrence (durée play-once) rejoue à chaque créneau de N min dans la fenêtre.
  const [intervalMin, setIntervalMin] = useState('')
  const [targetType, setTargetType] = useState<TargetType>('org')
  const [selectedPlayers, setSelectedPlayers] = useState<number[]>([])
  const [selectedGroups, setSelectedGroups] = useState<number[]>([])
  const [selectedSites, setSelectedSites] = useState<number[]>([])
  const [selectedSiteGroups, setSelectedSiteGroups] = useState<number[]>([])
  const [schedDays, setSchedDays] = useState<number[]>([0, 1, 2, 3, 4, 5, 6])
  const [schedStart, setSchedStart] = useState('08:00')
  const [schedEnd, setSchedEnd] = useState('22:00')
  // "Valide tout le temps" : défaut = true (pas de restriction de dates).
  // Quand false, les champs valid_from / valid_until sont affichés.
  const [validForever, setValidForever] = useState(true)
  const [validFrom, setValidFrom] = useState('')
  const [validUntil, setValidUntil] = useState('')
  // Récurrence : masquée pour type manual (non pertinent)
  const [isRecurring, setIsRecurring] = useState(false)
  // Préemptif : coupe à l'heure exacte (scheduled uniquement)
  const [isPreemptive, setIsPreemptive] = useState(false)
  // Auto-power lot 2 : garde les écrans allumés tant que l'event est actif
  const [keepScreensOn, setKeepScreensOn] = useState(false)
  // Embargo UTC : verrou mondial de diffusion indépendant de SIGNFLOW_TZ
  const [embargoEnabled, setEmbargoEnabled] = useState(false)
  const [embargoDatetime, setEmbargoDatetime] = useState('')
  const [embargoTz, setEmbargoTz] = useState('Europe/Zurich')
  // Fuseau de REFERENCE des heures du declenchement (P3.13). '' = defaut serveur.
  // A ne pas confondre avec embargoTz juste au-dessus, qui ne sert qu'a SAISIR un instant
  // absolu : l'embargo, lui, ne depend d'aucun fuseau une fois enregistre.
  const [eventTz, setEventTz] = useState('')

  // Fetch lists
  const { data: events = [], isLoading } = useQuery<EventRead[]>({
    queryKey: ['events', kind],
    queryFn: () => api.get<EventRead[]>(`/events?kind=${kind}`).then((r) => r.data),
    // Polling 10s pour voir les transitions d'état sans F5
    refetchInterval: 10000,
  })

  const { data: baskets = [] } = useQuery<AudioBasket[]>({
    queryKey: ['audio-baskets'],
    queryFn: () => api.get<AudioBasket[]>('/audio-baskets').then((r) => r.data),
    enabled: kind === 'audio' || drawerOpen,
  })

  const { data: playlists = [] } = useQuery<PlaylistRead[]>({
    queryKey: ['playlists'],
    queryFn: () => api.get<PlaylistRead[]>('/playlists/').then((r) => r.data),
  })

  // Chargé dès que le drawer est ouvert (préchargement, pas seulement en mode media)
  // pour que l'auto-fill durée soit disponible immédiatement.
  const { data: mediaList = [] } = useQuery<MediaListItem[]>({
    queryKey: ['media-list'],
    queryFn: () => api.get<MediaListItem[]>('/media/').then((r) => r.data),
    enabled: drawerOpen,
  })

  const { data: players = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'],
    queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
  })

  const { data: siteGroups = [] } = useQuery<SiteGroupRead[]>({
    queryKey: ['site-groups'],
    queryFn: () => api.get<SiteGroupRead[]>('/site-groups/').then((r) => r.data),
  })

  const { data: sites = [] } = useQuery<Site[]>({
    queryKey: ['sites'],
    queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
  })

  const { data: playerGroups = [] } = useQuery<PlayerGroupRead[]>({
    queryKey: ['player-groups'],
    // Trailing slash obligatoire : sans slash FastAPI redirige en 307 vers l'URL interne Docker
    queryFn: () => api.get<PlayerGroupRead[]>('/player-groups/').then((r) => r.data),
  })

  // Mutations
  const createMutation = useMutation({
    mutationFn: (body: object) => api.post('/events', body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['events'] }); closeDrawer() },
    onError: (e: unknown) => { if (!isDemoBlocked(e)) setMutateError((e as { message?: string }).message ?? 'Error') },
  })

  const editMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: object }) =>
      api.put(`/events/${id}`, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['events'] }); closeDrawer() },
    onError: (e: unknown) => { if (!isDemoBlocked(e)) setMutateError((e as { message?: string }).message ?? 'Error') },
  })

  const activateMutation = useMutation({
    mutationFn: (id: number) => api.post(`/events/${id}/activate`),
    onSuccess: () => { setActionError(null); qc.invalidateQueries({ queryKey: ['events'] }) },
    onError: (e: unknown) => { if (!isDemoBlocked(e)) setActionError((e as { message?: string }).message ?? t('common.error')) },
  })

  const deactivateMutation = useMutation({
    mutationFn: (id: number) => api.post(`/events/${id}/deactivate`),
    onSuccess: () => { setActionError(null); qc.invalidateQueries({ queryKey: ['events'] }) },
    onError: (e: unknown) => { if (!isDemoBlocked(e)) setActionError((e as { message?: string }).message ?? t('common.error')) },
  })

  const cancelMutation = useMutation({
    mutationFn: (id: number) => api.post(`/events/${id}/cancel`),
    onSuccess: () => { setActionError(null); qc.invalidateQueries({ queryKey: ['events'] }) },
    onError: (e: unknown) => { if (!isDemoBlocked(e)) setActionError((e as { message?: string }).message ?? t('common.error')) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/events/${id}`),
    onSuccess: () => { setActionError(null); qc.invalidateQueries({ queryKey: ['events'] }) },
    onError: (e: unknown) => { if (!isDemoBlocked(e)) setActionError((e as { message?: string }).message ?? t('common.error')) },
  })

  function openEdit(ev: EventRead) {
    setEditingEvent(ev)
    setName(ev.event_name)
    setEventType(ev.event_type as EventType)
    setPriority(ev.priority)
    setGovNode(ev.id_governance_node ?? null)
    setDurationSec(ev.duration_ms ? String(msToWholeSeconds(ev.duration_ms)) : '')
    setAutoDuration(false)
    setSchedLoop(ev.event_type === 'scheduled' ? !ev.duration_ms : true)
    // Récurrence par intervalle (trigger_config.recurrence) → champ minutes (sinon off).
    const rec = (ev.trigger_config?.recurrence ?? null) as { type?: string; every_minutes?: number } | null
    setIntervalMin(rec?.type === 'interval' && rec.every_minutes ? String(rec.every_minutes) : '')

    // Kind + content
    setKind((ev.event_kind as 'content' | 'audio') ?? 'content')
    setSelectedBasket(ev.id_basket ?? null)
    setAudioRatio(ev.mix_ratio ?? 50)
    if (ev.id_media && !ev.id_playlist) {
      setContentMode('media')
      setSelectedMedia(ev.id_media)
      setSelectedPlaylist(null)
    } else {
      setContentMode('playlist')
      setSelectedPlaylist(ev.id_playlist ?? null)
      setSelectedMedia(null)
    }

    // Targets — les deux formes ; un mélange remplit PLUSIEURS listes à la fois.
    const tc = ev.target_config
    const entries = targetEntries(tc)
    const byType = (t: string) =>
      entries.filter((e) => e.target_type === t).flatMap((e) => e.target_ids)
    setSelectedPlayers(byType('player'))
    setSelectedGroups(byType('group'))
    setSelectedSites(byType('site'))
    setSelectedSiteGroups(byType('site_group'))
    const firstFilled = (['player', 'group', 'site', 'site_group'] as TargetType[])
      .find((t) => byType(t).length)
    setTargetType(isOrgTarget(tc) ? 'org'
      : firstFilled ?? ((tc.target_type as TargetType) ?? 'org'))

    // Schedule condition
    const conditions = ((ev.trigger_config?.conditions ?? []) as Array<Record<string, unknown>>)
    const sched = conditions.find((c) => c.source === 'schedule')
    if (sched) {
      setSchedDays((sched.days_of_week as number[]) ?? [0, 1, 2, 3, 4, 5, 6])
      setSchedStart((sched.time_start as string) ?? '08:00')
      setSchedEnd((sched.time_end as string) ?? '22:00')
    } else {
      setSchedDays([0, 1, 2, 3, 4, 5, 6])
      setSchedStart('08:00')
      setSchedEnd('22:00')
    }

    // Validity + recurrence
    const hasValidityDates = !!(ev.valid_from || ev.valid_until)
    setValidForever(!hasValidityDates)
    setValidFrom(toDateLocal(ev.valid_from))
    setValidUntil(toDateLocal(ev.valid_until))
    setIsRecurring(ev.is_recurring ?? false)
    setIsPreemptive(ev.is_preemptive ?? false)
    setKeepScreensOn(ev.keep_screens_on ?? false)
    setEventTz(ev.timezone ?? '')
    if (ev.not_before_utc) {
      setEmbargoEnabled(true)
      setEmbargoDatetime(utcToLocalDt(ev.not_before_utc, embargoTz))
    } else {
      setEmbargoEnabled(false)
      setEmbargoDatetime('')
    }

    setMutateError(null)
    setDrawerOpen(true)
  }

  function closeDrawer() {
    setDrawerOpen(false)
    setEditingEvent(null)
    setName('')
    setEventType('manual')
    setContentMode('playlist')
    setSelectedPlaylist(null)
    setSelectedMedia(null)
    setSelectedBasket(null)
    setAudioRatio(50)
    setPriority(70)
    setGovNode(null)
    setDurationSec('')
    setAutoDuration(false)
    setIntervalMin('')
    setSchedLoop(true)
    setTargetType('org')
    setSelectedPlayers([])
    setSelectedGroups([])
    // `selectedSites` manquait à cette remise à zéro : inoffensif tant que seul le type
    // COURANT était envoyé, mais avec l'union une sélection de sites d'un drawer
    // précédent aurait fui en silence dans le prochain événement.
    setSelectedSites([])
    setSelectedSiteGroups([])
    setSchedDays([0, 1, 2, 3, 4, 5, 6])
    setSchedStart('08:00')
    setSchedEnd('22:00')
    setValidForever(true)
    setValidFrom('')
    setValidUntil('')
    setIsRecurring(false)
    setIsPreemptive(false)
    setKeepScreensOn(false)
    setEmbargoEnabled(false)
    setEmbargoDatetime('')
    setEmbargoTz('Europe/Zurich')
    setMutateError(null)
  }

  // Chips du récapitulatif inter-types (drawer) : chaque cible retenue, NOMMÉE, avec sa
  // croix — quel que soit le type actuellement affiché par le sélecteur.
  const targetChips = [
    ...selectedPlayers.map((id) => ({
      key: `p${id}`,
      label: players.find((p) => p.id_player === id)?.player_name ?? `#${id}`,
      onRemove: () => setSelectedPlayers((prev) => prev.filter((x) => x !== id)),
    })),
    ...selectedGroups.map((id) => ({
      key: `g${id}`,
      label: playerGroups.find((g) => g.id_group === id)?.group_name ?? `#${id}`,
      onRemove: () => setSelectedGroups((prev) => prev.filter((x) => x !== id)),
    })),
    ...selectedSites.map((id) => ({
      key: `s${id}`,
      label: sites.find((s) => s.id_site === id)?.site_name ?? `#${id}`,
      onRemove: () => setSelectedSites((prev) => prev.filter((x) => x !== id)),
    })),
    ...selectedSiteGroups.map((id) => ({
      key: `sg${id}`,
      label: siteGroups.find((g) => g.id_site_group === id)?.group_name ?? `#${id}`,
      onRemove: () => setSelectedSiteGroups((prev) => prev.filter((x) => x !== id)),
    })),
  ]

  function buildBody() {
    // Cibles hétérogènes (2026-07-30) : les sélections de types différents se CUMULENT
    // — « ce site » + « ces 3 écrans » dans un seul événement, comme les campagnes.
    // Un seul type sélectionné → forme héritée mono-type (les events simples restent
    // simples, et le filet de specs du 29/07 reste identique) ; un mélange → {targets:[...]}.
    const entries: TargetEntry[] = []
    if (selectedPlayers.length) entries.push({ target_type: 'player', target_ids: selectedPlayers })
    if (selectedGroups.length) entries.push({ target_type: 'group', target_ids: selectedGroups })
    if (selectedSites.length) entries.push({ target_type: 'site', target_ids: selectedSites })
    if (selectedSiteGroups.length) entries.push({ target_type: 'site_group', target_ids: selectedSiteGroups })

    let target_config: object
    if (targetType === 'org') {
      // « Toute l'organisation » absorbe tout : les autres sélections sont ignorées
      // (le bandeau du drawer le dit quand c'est le cas).
      target_config = { target_type: 'org', target_ids: [] }
    } else if (entries.length === 1) {
      target_config = entries[0]
    } else if (entries.length > 1) {
      target_config = { targets: entries }
    } else {
      target_config = { target_type: targetType, target_ids: [] }
    }

    let trigger_config: object | null = null
    if (eventType === 'scheduled') {
      const everyMin = parseInt(intervalMin, 10)
      trigger_config = {
        logic: 'AND',
        conditions: [{ source: 'schedule', days_of_week: schedDays, time_start: schedStart, time_end: schedEnd }],
        // Spot toutes les N min (play-once seulement) : l'occurrence rejoue à chaque créneau.
        ...(!schedLoop && everyMin > 0 ? { recurrence: { type: 'interval', every_minutes: everyMin } } : {}),
      }
    }

    // Durée : pour autoDuration, utilise contentDurationMs. Fallback sur durationSec si
    // contentDurationMs est null (ex. image sans durée — le champ restera vide et la durée
    // sera null, ce qui est correct pour une diffusion en boucle indéfinie).
    const durationMs =
      eventType === 'scheduled' && schedLoop
        ? null
        : autoDuration && contentDurationMs
          ? contentDurationMs
          : durationSec ? parseInt(durationSec, 10) * 1000 : null

    return {
      event_name: name.trim(),
      event_type: eventType,
      event_kind: kind,
      id_playlist: kind === 'content' && contentMode === 'playlist' ? selectedPlaylist : null,
      id_media: kind === 'content' && contentMode === 'media' ? selectedMedia : null,
      id_basket: kind === 'audio' ? selectedBasket : null,
      mix_ratio: kind === 'audio' ? audioRatio : null,
      priority,
      duration_ms: durationMs,
      valid_from: validForever ? null : fromDateLocalStart(validFrom),
      valid_until: validForever ? null : fromDateLocalEnd(validUntil),
      // is_recurring n'est pertinent que pour les events planifiés
      is_recurring: eventType !== 'manual' ? isRecurring : false,
      // is_preemptive n'est pertinent que pour les events schedulés
      is_preemptive: eventType === 'scheduled' ? isPreemptive : false,
      // Auto-power : garder les écrans allumés pendant l'event (tous types)
      keep_screens_on: keepScreensOn,
      // Embargo UTC : plancher absolu de diffusion mondiale
      not_before_utc: embargoEnabled && embargoDatetime ? localDtToUtc(embargoDatetime, embargoTz) : null,
      // '' = le serveur retombe sur son fuseau par defaut (colonne NULL).
      timezone: eventTz || null,
      target_config,
      trigger_config,
      // Gouvernance §XVIII (migr 0112) : nœud propriétaire. Rattacher un événement le
      // confie à son administrateur ET contraint ses cibles au périmètre du nœud.
      id_governance_node: govNode,
    }
  }

  function handleSubmit() {
    if (!name.trim() || !hasContent) return
    // play-once sans durée = erreur
    if (eventType === 'scheduled' && !schedLoop) {
      const dur = autoDuration ? contentDurationMs : (durationSec ? parseInt(durationSec) * 1000 : null)
      if (!dur) { setMutateError(t('events.duration_required')); return }
    }
    setMutateError(null)
    if (editingEvent) {
      editMutation.mutate({ id: editingEvent.id_event, body: buildBody() })
    } else {
      createMutation.mutate(buildBody())
    }
  }

  const isPending = createMutation.isPending || editMutation.isPending
  const hasContent = kind === 'audio'
    ? !!selectedBasket
    : contentMode === 'playlist' ? !!selectedPlaylist : !!selectedMedia

  /** Durée du contenu sélectionné en ms (média ou playlist), null si inconnue */
  const contentDurationMs = useMemo<number | null>(() => {
    // Ce que le tiroir vient de rendre fait foi ; sinon on retombe sur les listes (cas de
    // l'ÉDITION d'un événement existant, où le contenu n'est pas passé par le tiroir).
    if (pickedDuration != null) return pickedDuration
    if (contentMode === 'media' && selectedMedia) {
      return mediaList.find((m) => m.id_media === selectedMedia)?.duration_ms ?? null
    }
    if (contentMode === 'playlist' && selectedPlaylist) {
      return playlists.find((p) => p.id_playlist === selectedPlaylist)?.total_duration_ms ?? null
    }
    return null
  }, [contentMode, selectedMedia, selectedPlaylist, mediaList, playlists, pickedDuration])

  /** Libellé du contenu retenu — tiroir, puis listes, puis payload de l'événement édité. */
  const chosenContentLabel = useMemo<string | null>(() => {
    if (pickedLabel) return pickedLabel
    if (contentMode === 'media' && selectedMedia) {
      return mediaList.find((m) => m.id_media === selectedMedia)?.media_name
        ?? editingEvent?.media_name ?? null
    }
    if (contentMode === 'playlist' && selectedPlaylist) {
      return playlists.find((p) => p.id_playlist === selectedPlaylist)?.playlist_name
        ?? editingEvent?.playlist_name ?? null
    }
    return null
  }, [contentMode, selectedMedia, selectedPlaylist, mediaList, playlists, pickedLabel, editingEvent])

  // Auto-fill durationSec quand autoDuration est actif et le contenu change
  useEffect(() => {
    if (autoDuration && contentDurationMs) {
      setDurationSec(String(msToWholeSeconds(contentDurationMs)))
    }
  }, [autoDuration, contentDurationMs])

  const filtered = events.filter((e) =>
    e.event_name.toLowerCase().includes(search.toLowerCase()) ||
    (e.playlist_name ?? '').toLowerCase().includes(search.toLowerCase()) ||
    (e.media_name ?? '').toLowerCase().includes(search.toLowerCase())
  )

  return (
    <>
      <Topbar title={t('events.title')}>
        <Can perm="events:create">
          <Button size="sm" data-testid="event-new"
                  onClick={() => { setEditingEvent(null); setDrawerOpen(true) }}>
            <Zap className="w-4 h-4 mr-1.5" />
            {t('events.new')}
          </Button>
        </Can>
      </Topbar>

      {/*
        Page verrouillée au viewport : `DashboardShell` fournit déjà
        `h-screen overflow-hidden`, il suffit donc de `flex-1 min-h-0` ici.
        ⚠️ Cette page n'avait AUCUN conteneur de défilement — le contenu qui
        dépassait était purement coupé et inatteignable, pas simplement mal
        présenté (corrigé le 2026-07-20).
      */}
      <main className="flex-1 flex flex-col min-h-0">
        {/* Zone figée : onglets + erreur d'action + recherche */}
        <div className="shrink-0 px-6 pt-6 pb-4 space-y-4">
        {/* Onglets Visuel / Audio (§XIX) */}
        <div className="flex items-center gap-1 border-b border-gray-200">
          <button
            onClick={() => setKind('content')}
            className={`px-3 py-2 text-sm font-medium -mb-px border-b-2 inline-flex items-center gap-1.5 ${
              kind === 'content' ? 'border-accent text-accent' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <Film className="w-4 h-4" />
            {t('events.tab_content')}
          </button>
          <button
            onClick={() => setKind('audio')}
            className={`px-3 py-2 text-sm font-medium -mb-px border-b-2 inline-flex items-center gap-1.5 ${
              kind === 'audio' ? 'border-accent text-accent' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <Music className="w-4 h-4" />
            {t('events.tab_audio')}
          </button>
        </div>

        {/* Erreur des actions inline (activate/deactivate/cancel/delete) */}
        {actionError && (
          <div className="text-sm text-red-600 dark:text-red-300 bg-red-500/10 dark:bg-red-500/15 px-3 py-2 rounded border border-red-400/20 dark:border-red-500/30 flex items-center justify-between">
            <span>{actionError}</span>
            <button onClick={() => setActionError(null)} className="text-red-400 hover:text-red-600 ml-3">×</button>
          </div>
        )}

        <SearchInput
          placeholder={t('common.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        </div>

        {/* Seule zone défilante de la page */}
        <div className="flex-1 min-h-0 overflow-y-auto px-6 pb-6">
        {isLoading ? (
          <p className="text-sm text-gray-500">{t('common.loading')}</p>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-gray-500">{t('events.no_events')}</p>
        ) : (
          <CardGrid minItemWidth={320}>
            {filtered.map((ev) => {
              const sched = schedSummary(ev.trigger_config)
              const target = targetSummary(ev.target_config)
              const canEdit = ev.status !== 'active'
              const outOfRange = isOutOfValidity(ev)
              return (
                <EntityCard
                  key={ev.id_event}
                  title={ev.event_name}
                  titleTitle={ev.event_name}
                  subtitle={ev.duration_ms ? fmtDuration(ev.duration_ms) : undefined}
                  actions={
                    <>
                      {/* Édition + contrôle temps réel = events:trigger côté serveur */}
                      <Can perm="events:trigger">
                        {canEdit && (
                          <button
                            onClick={() => openEdit(ev)}
                            className="p-1 rounded text-gray-400 hover:bg-gray-100 transition-sf"
                            title={t('common.edit')}
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                        )}
                        {(ev.status === 'inactive' || ev.status === 'completed') && (
                          <button
                            onClick={() => {
                              if (outOfRange) { setActionError(t('events.activate_out_of_range')); return }
                              activateMutation.mutate(ev.id_event)
                            }}
                            className={`p-1 rounded transition-sf ${outOfRange ? 'text-gray-300 cursor-not-allowed' : 'text-green-600 dark:text-green-300 hover:bg-green-50'}`}
                            title={outOfRange ? t('events.validity_error') : t('events.activate')}
                          >
                            <Play className="w-4 h-4" />
                          </button>
                        )}
                        {ev.status === 'active' && (
                          <button
                            onClick={() => deactivateMutation.mutate(ev.id_event)}
                            className="p-1 rounded text-amber-600 dark:text-amber-300 hover:bg-amber-500/10 transition-sf"
                            title={t('events.deactivate')}
                          >
                            <Square className="w-4 h-4" />
                          </button>
                        )}
                        {ev.status !== 'cancelled' && ev.status !== 'completed' && (
                          <button
                            onClick={() => {
                              if (confirm(t('events.cancel_confirm'))) { setActionError(null); cancelMutation.mutate(ev.id_event) }
                            }}
                            className="p-1 rounded text-gray-500 hover:bg-gray-100 transition-sf"
                            title={t('events.cancel')}
                          >
                            <X className="w-4 h-4" />
                          </button>
                        )}
                      </Can>
                      {/* Suppression = events:delete côté serveur */}
                      <Can perm="events:delete">
                        {(ev.status === 'inactive' || ev.status === 'cancelled' || ev.status === 'completed') && (
                          <button
                            onClick={() => {
                              if (confirm(t('events.delete_confirm'))) { setActionError(null); deleteMutation.mutate(ev.id_event) }
                            }}
                            className="p-1 rounded text-red-500 hover:bg-red-500/10 transition-sf"
                            title={t('common.delete')}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </Can>
                    </>
                  }
                  badges={
                    <>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${typeBadge(ev.event_type as EventType)}`}>
                        {t(`events.type_${ev.event_type}`)}
                      </span>
                      <StatusBadge status={statusBadge(ev.status as EventStatus)} label={t(`events.status_${ev.status}`)} />
                      {ev.is_recurring && <span className="text-[10px] text-blue-500" title={t('events.col_schedule')}>↻</span>}
                      {ev.keep_screens_on && (
                        <span title={t('events.keep_screens_on_label')} className="inline-flex">
                          <MonitorCheck className="w-3.5 h-3.5 text-amber-600 dark:text-amber-300" />
                        </span>
                      )}
                    </>
                  }
                  footer={
                    <div className="space-y-1">
                      <div className="flex items-center gap-1.5 text-gray-600">
                        <span className="truncate">{contentLabel(ev)}</span>
                        {ev.id_media && !ev.id_playlist && (
                          <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 dark:bg-indigo-500/15 text-indigo-600 dark:text-indigo-300 font-medium">
                            {t('events.content_media')}
                          </span>
                        )}
                      </div>
                      {sched && (
                        <div className="font-mono text-[11px] text-gray-400 truncate"
                             title={`${sched} — ${ev.timezone}`}>
                          {/* Le fuseau accompagne TOUJOURS l'heure : « 18:00 » seul ne veut rien
                              dire des qu'un parc traverse deux fuseaux (P3.13). */}
                          {sched} <span className="text-gray-500">{ev.timezone}</span>
                        </div>
                      )}
                      <div className="text-[11px] text-gray-400">
                        {!ev.valid_from && !ev.valid_until ? '∞' : `${fmtDate(ev.valid_from) || '…'} → ${fmtDate(ev.valid_until) || '∞'}`}
                      </div>
                      <div className="flex items-center justify-between text-[11px] text-gray-500">
                        <span className="truncate">{isOrgTarget(ev.target_config) ? t('events.target_org_short') : target}</span>
                        <span className="font-mono shrink-0 ml-2">{t('events.col_priority')}: {ev.priority}</span>
                      </div>
                      {ev.not_before_utc && new Date(ev.not_before_utc) > new Date() && (
                        <div className="inline-flex items-center gap-0.5 text-[10px] text-orange-600 dark:text-orange-300 font-medium">
                          <Lock className="w-2.5 h-2.5" />
                          {new Date(ev.not_before_utc).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} UTC
                        </div>
                      )}
                    </div>
                  }
                />
              )
            })}
          </CardGrid>
        )}
        </div>
      </main>

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        title={editingEvent ? t('events.edit') : t('events.new')}
      >
        {/* Nudge lecture-seule : édition d'un event = events:trigger, création = events:create.
            Un rôle en lecture peut ouvrir ce drawer pour consulter — les champs sont neutralisés. */}
        <div className="space-y-4" data-write-perm={editingEvent ? 'events:trigger' : 'events:create'}>
          {mutateError && (
            <p className="text-sm text-red-600 dark:text-red-300 bg-red-500/10 dark:bg-red-500/15 px-3 py-2 rounded">{mutateError}</p>
          )}

          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t('events.name_label')}</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('events.name_label')} />
          </div>

          {/* Type */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t('events.type_label')}</label>
            <select
              data-testid="event-type"
              value={eventType}
              onChange={(e) => setEventType(e.target.value as EventType)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
            >
              <option value="manual">{t('events.type_manual')}</option>
              <option value="scheduled">{t('events.type_scheduled')}</option>
              <option value="conditional">{t('events.type_conditional')}</option>
            </select>
            {eventType === 'manual' && (
              <p className="mt-1 text-xs text-gray-400 flex items-center gap-1">
                <Info className="w-3 h-3 shrink-0" />
                {t('events.manual_hint')}
              </p>
            )}
          </div>

          {/* Content — Playlist or single media */}
          {kind === 'audio' ? (
            <div className="border border-gray-200 rounded-lg p-3 space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">{t('events.basket_label')}</label>
                <select
                  value={selectedBasket ?? ''}
                  onChange={(e) => setSelectedBasket(Number(e.target.value) || null)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                >
                  <option value="">—</option>
                  {baskets.map((b) => (
                    <option key={b.id_basket} value={b.id_basket}>{b.basket_name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">{t('events.ratio_label')}</label>
                <div className="flex items-center gap-2">
                  <input type="range" min={0} max={100} value={audioRatio}
                    onChange={(e) => setAudioRatio(Number(e.target.value))} className="flex-1 accent-accent" />
                  <span className="text-sm text-gray-500 w-10 text-right">{audioRatio}%</span>
                </div>
              </div>
            </div>
          ) : (
          <div className="border border-gray-200 rounded-lg p-3 space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-gray-700">{t('events.content_label')}</label>
              <div className="flex rounded overflow-hidden border border-gray-200 text-xs">
                {(['playlist', 'media'] as ContentMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => {
                      setContentMode(mode)
                      setAutoDuration(false)
                      setDurationSec('')  // reset durée quand on change de mode
                      setPickedLabel(null); setPickedDuration(null)
                      setSelectedPlaylist(null); setSelectedMedia(null)
                    }}
                    className={`px-3 py-1 font-medium transition-sf ${
                      contentMode === mode
                        ? 'bg-accent text-white'
                        : 'bg-surface text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {t(`events.content_${mode}`)}
                  </button>
                ))}
              </div>
            </div>

            {/* 🔴 Les deux menus déroulants ont disparu (audit 2026-07-29). Ils appelaient
                l'API SANS paramètre — donc au plafond serveur de 50 playlists / 500 médias —
                et SANS recherche : au-delà, le contenu était invisible ET introuvable.
                Le tiroir partagé cherche côté SERVEUR et parcourt les dossiers. */}
            <button
              type="button"
              data-testid="event-content-select"
              onClick={() => setContentPickerOpen(true)}
              className="w-full flex items-center justify-between gap-2 border border-gray-300 rounded-lg px-3 py-2 text-sm text-left hover:border-accent transition-sf"
            >
              <span className={chosenContentLabel ? 'text-gray-800 truncate' : 'text-gray-400'}>
                {chosenContentLabel
                  ?? (contentMode === 'playlist'
                      ? t('events.playlist_placeholder')
                      : t('events.media_placeholder'))}
              </span>
              <Search className="w-4 h-4 text-gray-400 shrink-0" />
            </button>
          </div>
          )}

          {/* Priority */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {t('events.priority_label')} (0–100)
            </label>
            <NumberField min={0} max={100} value={priority} onCommit={(v) => setPriority(v ?? 0)} />
          </div>

          {/* Gouvernance §XVIII : le sélecteur se masque si l'org n'a aucun nœud. Rattacher
              un événement contraint ses cibles au périmètre du nœud (422 sinon). */}
          <NodeSelect value={govNode} onChange={setGovNode} />

          {/* Fenêtre de validité */}
          <div className="border border-gray-200 rounded-lg p-3 space-y-3">
            <p className="text-xs font-medium text-gray-700">{t('events.validity_label')}</p>

            {/* Case "Valide tout le temps" */}
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={validForever}
                onChange={(e) => {
                  setValidForever(e.target.checked)
                  if (e.target.checked) { setValidFrom(''); setValidUntil('') }
                }}
                className="accent-accent w-4 h-4"
              />
              <span className="text-xs text-gray-600">{t('events.valid_forever_label')}</span>
            </label>

            {/* Dates début/fin — visibles seulement si not validForever */}
            {!validForever && (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('events.valid_from_label')}</label>
                  <input
                    type="date"
                    value={validFrom}
                    onChange={(e) => setValidFrom(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('events.valid_until_label')}</label>
                  <input
                    type="date"
                    value={validUntil}
                    onChange={(e) => setValidUntil(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                </div>
              </div>
            )}

            {/* Jours + heures — scheduled uniquement */}
            {eventType === 'scheduled' && (
              <>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('events.sched_days')}</label>
                  <div className="flex gap-1 flex-wrap">
                    {DAYS.map((d, i) => (
                      <button
                        key={d}
                        type="button"
                        onClick={() =>
                          setSchedDays((prev) =>
                            prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i]
                          )
                        }
                        className={`px-2 py-1 rounded text-xs font-medium transition-sf ${
                          schedDays.includes(i)
                            ? 'bg-accent text-white'
                            : 'bg-surface border border-gray-300 text-gray-600'
                        }`}
                      >
                        {t(`schedules.day_${d}`)}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('schedules.time_start_label')}</label>
                    <Input type="time" value={schedStart} onChange={(e) => setSchedStart(e.target.value)} />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('schedules.time_end_label')}</label>
                    <Input type="time" value={schedEnd} onChange={(e) => setSchedEnd(e.target.value)} />
                  </div>
                </div>
                {/* P3.13 : un evenement porte UNE ligne et UN activated_at, il ne peut donc
                    pas s'activer a l'heure locale de chaque ecran. Il declare, une fois, ce
                    que « 18 h » veut dire. Place SOUS les heures : c'est ce qu'il qualifie. */}
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('events.tz_label')}</label>
                  <select
                    data-testid="event-timezone"
                    value={eventTz}
                    onChange={(e) => setEventTz(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                  >
                    <option value="">{t('events.tz_default')}</option>
                    {EMBARGO_TIMEZONES.map(({ value, label }) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                  <p className="mt-1 text-[10px] text-gray-400">{t('events.tz_hint')}</p>
                </div>
              </>
            )}

            {/* Récurrent — uniquement pour les events non-manual */}
            {eventType !== 'manual' && (
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={isRecurring}
                  onChange={(e) => setIsRecurring(e.target.checked)}
                  className="accent-accent w-4 h-4"
                />
                <span className="text-xs text-gray-600">{t('events.recurring_label')}</span>
              </label>
            )}
          </div>

          {/* Embargo mondial */}
          <div className="border border-orange-200 dark:border-orange-500/30 rounded-lg p-3 space-y-3 bg-orange-50/40">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={embargoEnabled}
                onChange={(e) => {
                  setEmbargoEnabled(e.target.checked)
                  if (!e.target.checked) setEmbargoDatetime('')
                }}
                className="accent-accent w-4 h-4"
              />
              <Lock className="w-3.5 h-3.5 text-orange-600 dark:text-orange-300" />
              <span className="text-xs font-medium text-gray-700">{t('events.embargo_label')}</span>
            </label>
            {embargoEnabled && (
              <div className="space-y-2 pl-4">
                <div className="flex gap-2">
                  <input
                    type="datetime-local"
                    value={embargoDatetime}
                    onChange={(e) => setEmbargoDatetime(e.target.value)}
                    className="flex-1 border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                  <select
                    value={embargoTz}
                    onChange={(e) => setEmbargoTz(e.target.value)}
                    className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                  >
                    {EMBARGO_TIMEZONES.map(({ value, label }) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </div>
                {embargoDatetime && (
                  <p className="text-[10px] text-gray-400 font-mono">
                    = {localDtToUtc(embargoDatetime, embargoTz)?.slice(0, 16).replace('T', ' ') ?? '—'} UTC
                  </p>
                )}
                <p className="text-[10px] text-orange-600 dark:text-orange-300">{t('events.embargo_hint')}</p>
              </div>
            )}
          </div>

          {/* Mode de diffusion + préemption — scheduled uniquement */}
          {eventType === 'scheduled' && (
            <div className="border border-gray-200 rounded-lg p-3 space-y-2 bg-gray-50">
              <p className="text-xs font-medium text-gray-700">{t('events.play_mode_label')}</p>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="radio"
                  name="schedLoop"
                  checked={schedLoop}
                  onChange={() => { setSchedLoop(true); setDurationSec(''); setAutoDuration(false) }}
                  className="accent-accent w-4 h-4"
                />
                <span className="text-xs text-gray-700">{t('events.play_loop')}</span>
              </label>
              {schedLoop && schedEnd && (
                <p className="text-xs text-gray-400 ml-6">
                  {t('events.play_loop_hint', { end: schedEnd })}
                </p>
              )}
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="radio"
                  name="schedLoop"
                  checked={!schedLoop}
                  onChange={() => setSchedLoop(false)}
                  className="accent-accent w-4 h-4"
                />
                <span className="text-xs text-gray-700">{t('events.play_once')}</span>
              </label>
              {!schedLoop && (
                <div className="ml-6 space-y-2">
                  <Input
                    type="number"
                    min={1}
                    value={durationSec}
                    onChange={(e) => { setDurationSec(e.target.value); setAutoDuration(false) }}
                    placeholder={t('events.duration_sec_placeholder')}
                    disabled={autoDuration}
                  />
                  {hasContent && (
                    <label className="flex items-center gap-2 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={autoDuration}
                        disabled={!contentDurationMs}
                        onChange={(e) => {
                          if (!contentDurationMs) return
                          setAutoDuration(e.target.checked)
                          if (!e.target.checked) setDurationSec('')
                        }}
                        className="accent-accent w-4 h-4"
                      />
                      <span className={`text-xs ${contentDurationMs ? 'text-gray-600' : 'text-gray-400'}`}>
                        {t('events.auto_duration')}
                        {autoDuration && contentDurationMs && (
                          <span className="ml-1 text-gray-400">({fmtDuration(contentDurationMs)})</span>
                        )}
                        {!contentDurationMs && (
                          <span className="ml-1 text-gray-400">(—)</span>
                        )}
                      </span>
                    </label>
                  )}
                  {/* Spot horaire : rejouer l'occurrence toutes les N min dans la fenêtre */}
                  <label className="flex items-center gap-2 cursor-pointer select-none pt-1 border-t border-gray-200">
                    <input
                      type="checkbox"
                      checked={!!intervalMin}
                      onChange={(e) => setIntervalMin(e.target.checked ? '60' : '')}
                      className="accent-accent w-4 h-4 mt-1"
                    />
                    <span className="text-xs text-gray-600">{t('events.interval_label')}</span>
                  </label>
                  {!!intervalMin && (
                    <div className="ml-6 space-y-1">
                      <div className="flex items-center gap-2">
                        <Input
                          type="number"
                          min={1}
                          value={intervalMin}
                          onChange={(e) => setIntervalMin(e.target.value)}
                          className="w-24"
                        />
                        <span className="text-xs text-gray-500">{t('events.interval_minutes')}</span>
                      </div>
                      <p className="text-[10px] text-gray-400">{t('events.interval_hint')}</p>
                    </div>
                  )}
                </div>
              )}
              {/* Préemption */}
              <div className="pt-1 border-t border-gray-200 mt-2">
                <label className="flex items-start gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={isPreemptive}
                    onChange={(e) => setIsPreemptive(e.target.checked)}
                    className="accent-accent w-4 h-4 mt-0.5 shrink-0"
                  />
                  <span className="text-xs text-gray-700">
                    {t('events.preemptive_label')}
                    <span className="block text-gray-400 mt-0.5">{t('events.preemptive_hint')}</span>
                  </span>
                </label>
              </div>
            </div>
          )}

          {/* Durée — manual / conditional uniquement */}
          {eventType !== 'scheduled' && (
            <div className="space-y-2">
              <label className="block text-xs font-medium text-gray-600">
                {t('events.duration_label')} ({t('events.duration_unit')})
              </label>
              <Input
                type="number"
                min={1}
                value={durationSec}
                onChange={(e) => { setDurationSec(e.target.value); setAutoDuration(false) }}
                placeholder={t('events.duration_sec_placeholder')}
                disabled={autoDuration}
              />
              {hasContent && (
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={autoDuration}
                    disabled={!contentDurationMs}
                    onChange={(e) => {
                      if (!contentDurationMs) return
                      setAutoDuration(e.target.checked)
                      if (!e.target.checked) setDurationSec('')
                    }}
                    className="accent-accent w-4 h-4"
                  />
                  <span className={`text-xs ${contentDurationMs ? 'text-gray-600' : 'text-gray-400'}`}>
                    {t('events.auto_duration')}
                    {autoDuration && contentDurationMs && (
                      <span className="ml-1 text-gray-400">({fmtDuration(contentDurationMs)})</span>
                    )}
                    {!contentDurationMs && hasContent && (
                      <span className="ml-1 text-gray-400">(—)</span>
                    )}
                  </span>
                </label>
              )}
            </div>
          )}

          {/* Target */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t('events.target_label')}</label>
            <select
              data-testid="event-target-type"
              value={targetType}
              onChange={(e) => setTargetType(e.target.value as TargetType)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
            >
              <option value="org">{t('events.target_org')}</option>
              <option value="player">{t('events.target_player')}</option>
              <option value="group">{t('events.target_group')}</option>
              <option value="site">{t('events.target_site')}</option>
              <option value="site_group">{t('events.target_site_group')}</option>
            </select>
            {(targetType === 'player' || targetType === 'site') && (
              <button
                type="button"
                data-testid="event-target-map"
                onClick={() => setMapOpen(true)}
                className="mt-1.5 text-xs text-accent hover:underline inline-flex items-center gap-1"
              >
                <MapPin className="w-3.5 h-3.5" />
                {t('target_map.title')}
              </button>
            )}
            {targetType !== 'org' && (
              <p className="text-[10px] text-gray-400 mt-1">{t('events.target_mix_hint')}</p>
            )}
          </div>

          {/* Récapitulatif inter-types : ce que l'événement VISE réellement (l'UNION des
              sélections, tous types confondus) — sans lui, une sélection faite sous un
              autre type serait embarquée sans que rien ne le montre. */}
          {targetChips.length > 0 && targetType !== 'org' && (
            <div className="border border-gray-200 rounded-lg p-2" data-testid="event-target-recap">
              <div className="flex flex-wrap gap-1.5">
                {targetChips.map((c) => (
                  <span key={c.key}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-accent/10 text-accent rounded">
                    {c.label}
                    <button type="button" onClick={c.onRemove} className="hover:text-danger">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}
          {targetChips.length > 0 && targetType === 'org' && (
            <p className="text-[10px] text-amber-600 dark:text-amber-300">
              {t('events.target_org_overrides')}
            </p>
          )}

          {/* Players list with search */}
          {targetType === 'player' && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('events.target_players_label')}</label>
              <SearchableList
                items={players}
                getKey={(p) => p.id_player}
                getLabel={(p) => p.player_name}
                getSecondary={(p) => (
                  <span className={`shrink-0 w-2 h-2 rounded-full ${p.status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
                )}
                selected={selectedPlayers}
                onToggle={(id) =>
                  setSelectedPlayers((prev) =>
                    prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
                  )
                }
                searchPlaceholder={t('common.search')}
                emptyLabel={t('common.no_results')}
              />
              {selectedPlayers.length > 0 && (
                <p className="text-xs text-gray-400 mt-1">{selectedPlayers.length} {t('events.players_selected')}</p>
              )}
            </div>
          )}

          {/* Groups list with search */}
          {targetType === 'group' && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('events.target_group_ids_label')}</label>
              <SearchableList
                items={playerGroups}
                getKey={(g) => g.id_group}
                getLabel={(g) => g.group_name}
                selected={selectedGroups}
                onToggle={(id) =>
                  setSelectedGroups((prev) =>
                    prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
                  )
                }
                searchPlaceholder={t('common.search')}
                emptyLabel={t('common.no_results')}
              />
              {selectedGroups.length > 0 && (
                <p className="text-xs text-gray-400 mt-1">{selectedGroups.length} {t('schedules.groups_label').toLowerCase()}</p>
              )}
            </div>
          )}

          {/* Sites list with search — cible « tout le magasin » (audit ciblage 2026-07-18) */}
          {targetType === 'site' && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('events.target_site_ids_label')}</label>
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
                searchPlaceholder={t('common.search')}
                emptyLabel={t('common.no_results')}
              />
              {selectedSites.length > 0 && (
                <p className="text-xs text-gray-400 mt-1">{selectedSites.length} {t('nav.sites').toLowerCase()}</p>
              )}
            </div>
          )}

          {/* Site groups list with search (S6 — cible « région ») */}
          {targetType === 'site_group' && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('events.target_site_group_ids_label')}</label>
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
                searchPlaceholder={t('common.search')}
                emptyLabel={t('common.no_results')}
              />
              {selectedSiteGroups.length > 0 && (
                <p className="text-xs text-gray-400 mt-1">{selectedSiteGroups.length} {t('sites.tab_groups').toLowerCase()}</p>
              )}
            </div>
          )}

          {/* Auto-power : garder les écrans allumés pendant l'event */}
          <div className="pt-2 border-t border-gray-200">
            <label className="flex items-start gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={keepScreensOn}
                onChange={(e) => setKeepScreensOn(e.target.checked)}
                className="accent-accent w-4 h-4 mt-0.5 shrink-0"
              />
              <span className="text-xs text-gray-700">
                {t('events.keep_screens_on_label')}
                <span className="block text-gray-400 mt-0.5">{t('events.keep_screens_on_hint')}</span>
              </span>
            </label>
          </div>

          <div className="flex gap-2 pt-2">
            <Button
              data-write-action
              data-testid="event-save"
              onClick={handleSubmit}
              disabled={!name.trim() || !hasContent || isPending}
              className="flex-1"
            >
              {isPending ? t('common.loading') : editingEvent ? t('common.save') : t('common.create')}
            </Button>
            <Button variant="ghost" onClick={closeDrawer}>{t('common.cancel')}</Button>
          </div>
        </div>
      </Drawer>

      {/* Tiroir de contenu partagé — au niveau PAGE : un Drawer imbriqué dans un Drawer
          serait découpé par le `transform` du panneau parent. */}
      {/* Carte de ciblage — au niveau PAGE, comme le tiroir de contenu. */}
      <TargetMapDrawer
        open={mapOpen}
        onClose={() => setMapOpen(false)}
        mode={targetType === 'site' ? 'site' : 'player'}
        sites={sites.map((s) => ({
          id_site: s.id_site, site_name: s.site_name,
          latitude: s.latitude ?? null, longitude: s.longitude ?? null,
          screen_count: players.filter((p) => p.id_site === s.id_site).length,
        }))}
        players={players.map((p) => ({
          id_player: p.id_player, player_name: p.player_name, id_site: p.id_site ?? null,
        }))}
        value={targetType === 'site' ? selectedSites : selectedPlayers}
        onApply={(ids) => {
          if (targetType === 'site') setSelectedSites(ids)
          else setSelectedPlayers(ids)
        }}
      />

      <ContentPickerDrawer
        open={contentPickerOpen}
        onClose={() => setContentPickerOpen(false)}
        mediaTypes={contentMode === 'media' ? ['video', 'image', 'document'] : []}
        multiple={false}
        withPlaylists={contentMode === 'playlist'}
        onPick={(pick) => {
          if (pick.playlist) {
            setContentMode('playlist')
            setSelectedPlaylist(pick.playlist)
            setSelectedMedia(null)
          } else if (pick.medias.length) {
            setContentMode('media')
            setSelectedMedia(pick.medias[0])
            setSelectedPlaylist(null)
          }
          setPickedLabel(pick.label ?? null)
          setPickedDuration(pick.durationMs ?? null)
        }}
      />
    </>
  )
}
