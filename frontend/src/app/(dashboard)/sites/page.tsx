'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Building2, Layers, MapPin, Power, Plus, Trash2, Clock, Search, ChevronDown, ChevronRight, X } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import StatusBadge from '@/components/ui/StatusBadge'
import TabBar from '@/components/ui/TabBar'
import NumberField from '@/components/ui/NumberField'
import LatLngPicker from '@/components/maps/LatLngPicker'
import api from '@/lib/api'
import { useSearchPrefill } from '@/lib/useSearchPrefill'
import { isDemoBlocked } from '@/lib/demo'
import type { PlayerRead, Site, SiteException, SiteGroupRead, SiteHoursItem, SitePlayer } from '@/types/api'

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

// Tooltip au survol d'un site (retour Ed #4) : players / éligibles campagnes +
// occupation SOV par jour (moyenne par écran éligible, couleur = pire écran).
interface SiteStats {
  id_site: number
  player_count: number
  eligible_count: number
  days: { date: string; avg_pct: number; max_pct: number }[]
}

function SiteStatsPopover({ stats, t }: {
  stats: SiteStats | undefined
  t: (key: string, values?: Record<string, string | number>) => string
}) {
  return (
    <div
      className="absolute left-2 right-2 top-full -mt-1 z-30 bg-surface border border-gray-200 rounded-lg shadow-sf-card p-3 text-xs"
      onClick={(e) => e.stopPropagation()}
    >
      {!stats ? (
        <span className="text-gray-400">…</span>
      ) : (
        <>
          <p className="text-gray-800 font-medium">
            {t('sites.stats_players', { total: stats.player_count, eligible: stats.eligible_count })}
          </p>
          {stats.days.length > 0 && (
            <>
              <p className="text-gray-400 mt-1.5 mb-1">{t('sites.stats_occupancy_title')}</p>
              <div className="flex gap-1">
                {stats.days.map((d) => (
                  <div key={d.date} className="flex-1 text-center min-w-0">
                    <div className={`rounded px-0.5 py-0.5 font-medium ${
                      d.max_pct > 100 ? 'bg-red-500/10 text-danger'
                        : d.max_pct >= 80 ? 'bg-amber-500/10 text-warning'
                          : 'bg-accent/10 text-accent'
                    }`} title={t('sites.stats_day_detail', { avg: d.avg_pct, max: d.max_pct })}>
                      {Math.round(d.avg_pct)}%
                    </div>
                    <div className="text-[10px] text-gray-400 mt-0.5">{d.date.slice(8)}/{d.date.slice(5, 7)}</div>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-gray-400 mt-1">{t('sites.stats_hint')}</p>
            </>
          )}
        </>
      )}
    </div>
  )
}

function emptyHours(): SiteHoursItem[] {
  return DAYS.map((_, i) => ({ weekday: i, is_closed: i === 6, open_time: '08:00', close_time: '19:00' }))
}

// Liste IANA complète du navigateur (Chrome ≥ 99) pour le select de fuseau du site.
function browserTimezones(): string[] {
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    if (typeof intl.supportedValuesOf === 'function') return intl.supportedValuesOf('timeZone')
  } catch { /* navigateur ancien */ }
  return []
}

// Régions dont le CALENDRIER DE FÉRIÉS est réellement implémenté côté serveur
// (services/site_hours.holidays_for — région inconnue = aucun férié). Étendre ICI
// ET côté backend quand un client demande un nouveau pays.
const HOLIDAY_REGIONS = ['FR'] as const
// Fuseau sélectionné → région de fériés suggérée (auto-remplie au changement de fuseau).
const REGION_BY_TZ: Record<string, string> = {
  'Europe/Paris': 'FR', 'Europe/Monaco': 'FR',
}

export default function SitesPage() {
  const t = useTranslations()
  const qc = useQueryClient()

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  useSearchPrefill(setSearch)
  // Tooltip stats (Ed #4) — la requête ne part qu'au premier survol
  const [statsOn, setStatsOn] = useState(false)
  const [hoverSite, setHoverSite] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<'sites' | 'groups'>('sites')
  const [groupCreateOpen, setGroupCreateOpen] = useState(false)

  // Form state
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [country, setCountry] = useState('')
  const [siteNumber, setSiteNumber] = useState('')
  const [lat, setLat] = useState('')
  const [lng, setLng] = useState('')
  const [timezone, setTimezone] = useState('')
  const [autoPower, setAutoPower] = useState(false)
  const [leadMin, setLeadMin] = useState(15)
  const [lagMin, setLagMin] = useState(15)
  const [respectHolidays, setRespectHolidays] = useState(false)
  const [holidayRegion, setHolidayRegion] = useState('FR')
  // Inventaire v2 (0082) : plafond campagnes (%) + tarif SOV du site ('' = héritage)
  const [campCap, setCampCap] = useState('')
  // Exclusion concurrentielle #10 : catégories d'industrie exclues du site
  const [excludedCats, setExcludedCats] = useState<number[]>([])
  const [campRate, setCampRate] = useState('')
  const [ntpServer, setNtpServer] = useState('')
  const [hours, setHours] = useState<SiteHoursItem[]>(emptyHours())
  const [mutateError, setMutateError] = useState<string | null>(null)

  // UI state
  const [excSectionOpen, setExcSectionOpen] = useState(false)  // « Exceptions datées » repliée par défaut
  const [mapOpen, setMapOpen] = useState(false)                 // mini-carte de placement (S7 Phase A)
  const [attachId, setAttachId] = useState<number | ''>('')     // player sélectionné dans le picker

  // Exception form
  const [excFrom, setExcFrom] = useState('')
  const [excTo, setExcTo] = useState('')
  const [excKind, setExcKind] = useState<'closed' | 'hours' | 'open_24h'>('closed')
  const [excOpen, setExcOpen] = useState('08:00')
  const [excClose, setExcClose] = useState('23:00')
  const [excLabel, setExcLabel] = useState('')

  const { data: sites = [], isLoading } = useQuery<Site[]>({
    queryKey: ['sites'],
    queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
  })

  // Stats campagnes par site (tooltip Ed #4) — chargées au premier survol seulement
  const { data: siteStats } = useQuery<SiteStats[]>({
    queryKey: ['site-campaign-stats'],
    queryFn: () => api.get<SiteStats[]>('/sites/campaign-stats').then((r) => r.data),
    enabled: statsOn,
    staleTime: 60_000,
  })
  const statsById = useMemo(
    () => new Map((siteStats ?? []).map((s) => [s.id_site, s])), [siteStats])

  const { data: siteGroups = [], refetch: refetchSiteGroups } = useQuery<SiteGroupRead[]>({
    queryKey: ['site-groups'],
    queryFn: () => api.get<SiteGroupRead[]>('/site-groups/').then((r) => r.data),
  })

  // Catégories d'industrie (#10) — pour les exclusions par site ; 403 toléré
  // (user sans campaigns:read → bloc masqué).
  const { data: industryCategories = [] } = useQuery<
    { id_category: number; category_name: string }[]
  >({
    queryKey: ['industry-categories'],
    queryFn: () => api.get<{ id_category: number; category_name: string }[]>(
      '/campaigns/industry-categories').then((r) => r.data),
    retry: false,
  })

  const { data: exceptions = [] } = useQuery<SiteException[]>({
    queryKey: ['site-exceptions', editId],
    queryFn: () => api.get<SiteException[]>(`/sites/${editId}/exceptions`).then((r) => r.data),
    enabled: editId !== null,
  })

  const { data: sitePlayers = [] } = useQuery<SitePlayer[]>({
    queryKey: ['site-players', editId],
    queryFn: () => api.get<SitePlayer[]>(`/sites/${editId}/players`).then((r) => r.data),
    enabled: editId !== null,
  })

  // Tous les players de l'org — pour le picker d'attache (on exclut ceux déjà sur ce site).
  const { data: allPlayers = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'],
    queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
    enabled: editId !== null,
  })

  function resetForm() {
    setName(''); setAddress(''); setCountry(''); setSiteNumber(''); setLat(''); setLng('')
    setTimezone(''); setNtpServer(''); setAutoPower(false)
    setLeadMin(15); setLagMin(15); setRespectHolidays(false); setHolidayRegion('FR')
    setCampCap(''); setCampRate(''); setExcludedCats([])
    setHours(emptyHours()); setMutateError(null)
    setExcFrom(''); setExcTo(''); setExcKind('closed'); setExcOpen('08:00'); setExcClose('23:00'); setExcLabel('')
  }

  function loadSite(s: Site) {
    setName(s.site_name); setAddress(s.address ?? ''); setTimezone(s.timezone ?? '')
    setNtpServer(s.ntp_server ?? '')
    setCountry(s.country ?? ''); setSiteNumber(s.site_number ?? '')
    setLat(s.latitude != null ? String(s.latitude) : '')
    setLng(s.longitude != null ? String(s.longitude) : '')
    setAutoPower(s.auto_power_enabled); setLeadMin(s.power_lead_min); setLagMin(s.power_lag_min)
    setRespectHolidays(s.respect_holidays); setHolidayRegion(s.holiday_region)
    setCampCap(s.campaign_max_occupancy_pct != null ? String(s.campaign_max_occupancy_pct) : '')
    setCampRate(s.campaign_sov_daily_rate != null ? String(s.campaign_sov_daily_rate) : '')
    setExcludedCats(s.campaign_excluded_categories ?? [])
    // Fusionne les horaires reçus dans une grille 7 jours complète.
    const base = emptyHours()
    for (const h of s.hours) {
      base[h.weekday] = {
        weekday: h.weekday, is_closed: h.is_closed,
        open_time: (h.open_time ?? '08:00').slice(0, 5),
        close_time: (h.close_time ?? '19:00').slice(0, 5),
      }
    }
    setHours(base)
  }

  function openCreate() { resetForm(); setEditId(null); setMapOpen(false); setDrawerOpen(true) }
  function openEdit(s: Site) { resetForm(); loadSite(s); setEditId(s.id_site); setMapOpen(false); setDrawerOpen(true) }
  function closeDrawer() { setDrawerOpen(false); setEditId(null); setMapOpen(false); resetForm() }

  const settingsBody = () => ({
    site_name: name, address: address || null, timezone: timezone || null,
    ntp_server: ntpServer.trim() || null,
    country: country.trim() || null, site_number: siteNumber.trim() || null,
    latitude: lat.trim() ? Number(lat) : null,
    longitude: lng.trim() ? Number(lng) : null,
    auto_power_enabled: autoPower, power_lead_min: leadMin, power_lag_min: lagMin,
    respect_holidays: respectHolidays, holiday_region: holidayRegion,
    campaign_max_occupancy_pct: campCap.trim() ? Number(campCap) : null,
    campaign_sov_daily_rate: campRate.trim() ? Number(campRate) : null,
    campaign_excluded_categories: excludedCats,
  })

  const saveMutation = useMutation({
    mutationFn: async () => {
      let id = editId
      if (id === null) {
        const r = await api.post<Site>('/sites', settingsBody())
        id = r.data.id_site
      } else {
        await api.put(`/sites/${id}`, settingsBody())
      }
      await api.put(`/sites/${id}/hours`, {
        hours: hours.map((h) => h.is_closed
          ? { weekday: h.weekday, is_closed: true }
          : { weekday: h.weekday, is_closed: false, open_time: h.open_time, close_time: h.close_time }),
      })
    },
    onSuccess: async () => { await qc.refetchQueries({ queryKey: ['sites'] }); closeDrawer() },
    onError: (e: unknown) => { if (!isDemoBlocked(e)) setMutateError(t('common.error')) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/sites/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sites'] }),
  })

  const addExcMutation = useMutation({
    mutationFn: () => api.post(`/sites/${editId}/exceptions`, {
      date_from: excFrom, date_to: excTo || excFrom, kind: excKind,
      open_time: excKind === 'hours' ? excOpen : null,
      close_time: excKind === 'hours' ? excClose : null,
      label: excLabel || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-exceptions', editId] })
      setExcFrom(''); setExcTo(''); setExcLabel('')
    },
  })

  const delExcMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/sites/${editId}/exceptions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['site-exceptions', editId] }),
  })

  function refreshPlayers() {
    qc.invalidateQueries({ queryKey: ['site-players', editId] })
    qc.invalidateQueries({ queryKey: ['players'] })
    qc.invalidateQueries({ queryKey: ['sites'] })  // player_count
  }

  const attachMutation = useMutation({
    mutationFn: (id_player: number) => api.post(`/sites/${editId}/players/${id_player}`),
    onSuccess: () => { refreshPlayers(); setAttachId('') },
  })

  const detachMutation = useMutation({
    mutationFn: (id_player: number) => api.delete(`/sites/${editId}/players/${id_player}`),
    onSuccess: refreshPlayers,
  })

  function setHour(i: number, patch: Partial<SiteHoursItem>) {
    setHours((prev) => prev.map((h, idx) => (idx === i ? { ...h, ...patch } : h)))
  }

  const filtered = sites.filter((s) => !search || s.site_name.toLowerCase().includes(search.toLowerCase()))
  const isEdit = editId !== null

  return (
    <>
      <Topbar title={t('sites.title')}>
        {activeTab === 'sites' ? (
          <Can perm="players:edit">
            <Button size="sm" onClick={openCreate}>
              <Plus className="w-4 h-4 mr-1" />{t('sites.new')}
            </Button>
          </Can>
        ) : (
          <Can perm="players:edit">
            <Button size="sm" onClick={() => setGroupCreateOpen(true)}>
              <Plus className="w-4 h-4 mr-1" />{t('sites.new_group')}
            </Button>
          </Can>
        )}
      </Topbar>

      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-8 space-y-6">
          <TabBar
            tabs={[
              { key: 'sites', label: t('sites.tab_sites'), count: sites.length },
              { key: 'groups', label: t('sites.tab_groups'), count: siteGroups.length },
            ]}
            active={activeTab}
            onChange={(k) => setActiveTab(k as 'sites' | 'groups')}
          />

          {activeTab === 'groups' ? (
            <SiteGroupsTab
              groups={siteGroups}
              sites={sites}
              t={t}
              createOpen={groupCreateOpen}
              setCreateOpen={setGroupCreateOpen}
              refetch={refetchSiteGroups}
            />
          ) : (
          <>
          <p className="text-sm text-gray-500">{t('sites.intro')}</p>

          <div className="relative max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <input
              type="search" value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder={t('common.search')}
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
            />
          </div>

          {isLoading ? (
            <p className="text-sm text-gray-400">{t('common.loading')}</p>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400">
              <Building2 className="w-10 h-10" />
              <p className="text-sm">{t('sites.empty')}</p>
            </div>
          ) : (
            <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
              {filtered.map((s) => (
                <div
                  key={s.id_site}
                  role="button" tabIndex={0}
                  onClick={() => openEdit(s)}
                  onKeyDown={(e) => { if (e.key === 'Enter') openEdit(s) }}
                  onMouseEnter={() => { setStatsOn(true); setHoverSite(s.id_site) }}
                  onMouseLeave={() => setHoverSite(null)}
                  className="relative bg-surface border border-gray-200 rounded-lg p-4 cursor-pointer transition-sf hover:border-accent shadow-sf-card"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <Building2 className="w-4 h-4 text-gray-400 shrink-0" />
                      <span className="text-sm font-medium text-gray-900 truncate" title={s.site_name}>{s.site_name}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {s.auto_power_enabled
                        ? <StatusBadge status="online" label={t('sites.auto_power_on')} />
                        : <StatusBadge status="offline" label={t('sites.auto_power_off')} />}
                      <Can perm="players:edit">
                        <button type="button" title={t('common.delete')}
                          onClick={(e) => { e.stopPropagation(); if (confirm(t('sites.delete_confirm', { name: s.site_name }))) deleteMutation.mutate(s.id_site) }}
                          className="p-0.5 text-gray-300 transition-sf hover:text-danger">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </Can>
                    </div>
                  </div>
                  {s.address && <p className="text-xs text-gray-400 truncate mt-1">{s.address}</p>}
                  <div className="flex items-center gap-3 mt-3 text-[11px] text-gray-500">
                    <span className="inline-flex items-center gap-1"><Power className="w-3 h-3" />{s.player_count} {t('sites.players_count')}</span>
                    {s.timezone && <span className="inline-flex items-center gap-1"><Clock className="w-3 h-3" />{s.timezone}</span>}
                  </div>
                  {hoverSite === s.id_site && (
                    <SiteStatsPopover stats={statsById.get(s.id_site)} t={t} />
                  )}
                </div>
              ))}
            </div>
          )}
          </>
          )}
        </div>
      </main>

      <Drawer open={drawerOpen} onClose={closeDrawer} title={isEdit ? t('sites.edit') : t('sites.new')} width="w-[560px]">
        <div className="space-y-5" data-write-perm="players:edit">
          <Input label={t('sites.name_label')} value={name} onChange={(e) => setName(e.target.value)} />
          <Input label={t('sites.address_label')} value={address} onChange={(e) => setAddress(e.target.value)} />
          <div className="grid grid-cols-2 gap-3">
            <Input label={t('sites.country_label')} value={country} onChange={(e) => setCountry(e.target.value)} placeholder="France" />
            <Input label={t('sites.number_label')} value={siteNumber} onChange={(e) => setSiteNumber(e.target.value)} placeholder="FR-001" hint={t('sites.number_hint')} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label={t('sites.latitude_label')} value={lat} onChange={(e) => setLat(e.target.value)} placeholder="45.7640" hint={t('sites.coords_hint')} />
            <Input label={t('sites.longitude_label')} value={lng} onChange={(e) => setLng(e.target.value)} placeholder="4.8357" />
          </div>

          {/* Placement sur carte (S7 Phase A) — clic ou drag du marqueur → lat/long */}
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setMapOpen((v) => !v)}
              className="flex items-center gap-1.5 text-sm font-medium text-gray-700"
            >
              {mapOpen ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
              <MapPin className="w-4 h-4 text-gray-400" />
              {t('sites.map_place_label')}
            </button>
            {mapOpen && (
              <>
                <LatLngPicker lat={lat} lng={lng} onChange={(la, lo) => { setLat(la); setLng(lo) }} />
                <p className="text-xs text-gray-400">{t('sites.map_place_hint')}</p>
              </>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            {/* Liste IANA du navigateur (retour Ed : dropdown plutôt que saisie libre).
                Valeur legacy hors liste = injectée en option explicite (le select ne ment pas). */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('sites.timezone_label')}</label>
              <select
                value={timezone}
                onChange={(e) => {
                  const tz = e.target.value
                  setTimezone(tz)
                  // La région de fériés suit le fuseau (retour Ed) : FR pour les zones
                  // françaises, sinon vide (aucun calendrier serveur pour cette région).
                  setHolidayRegion(REGION_BY_TZ[tz] ?? '')
                }}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-surface text-gray-800 focus:outline-none focus:ring-2 focus:ring-accent/40"
              >
                <option value="">—</option>
                {timezone && !browserTimezones().includes(timezone) && (
                  <option value={timezone}>{timezone}</option>
                )}
                {browserTimezones().map((z) => (
                  <option key={z} value={z}>{z}</option>
                ))}
              </select>
              <p className="mt-1 text-xs text-gray-400">{t('sites.timezone_hint')}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('sites.holiday_region_label')}</label>
              <select
                value={holidayRegion}
                onChange={(e) => setHolidayRegion(e.target.value)}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-surface text-gray-800 focus:outline-none focus:ring-2 focus:ring-accent/40"
              >
                <option value="">—</option>
                {holidayRegion && !HOLIDAY_REGIONS.includes(holidayRegion as typeof HOLIDAY_REGIONS[number]) && (
                  <option value={holidayRegion}>{holidayRegion}</option>
                )}
                {HOLIDAY_REGIONS.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
              <p className="mt-1 text-xs text-gray-400">{t('sites.holiday_region_hint')}</p>
            </div>
          </div>

          {/* Serveur NTP du site (migr 0071) : herite par les players sans config NTP propre
              (le relais NTP LAN sync par player prime). Horloge juste = auto-power offline fiable. */}
          <Input
            label={t('sites.ntp_label')}
            value={ntpServer}
            onChange={(e) => setNtpServer(e.target.value)}
            placeholder="pool.ntp.org / 192.168.1.10"
            hint={t('sites.ntp_hint')}
          />

          {/* Auto-power */}
          <div className="border border-gray-200 rounded-lg p-3 space-y-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={autoPower} onChange={(e) => setAutoPower(e.target.checked)} className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
              <span className="text-sm font-medium text-gray-800">{t('sites.auto_power_label')}</span>
            </label>
            <p className="text-xs text-gray-400">{t('sites.auto_power_hint')}</p>
            {autoPower && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <NumberField label={t('sites.lead_label')} min={0} value={leadMin} onCommit={(v) => setLeadMin(v ?? 0)} />
                  <NumberField label={t('sites.lag_label')} min={0} value={lagMin} onCommit={(v) => setLagMin(v ?? 0)} />
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={respectHolidays} onChange={(e) => setRespectHolidays(e.target.checked)} className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                  <span className="text-sm text-gray-700">{t('sites.respect_holidays_label')}</span>
                </label>
                <p className="text-xs text-gray-400">{t('sites.respect_holidays_hint')}</p>
              </>
            )}
          </div>

          {/* Inventaire retail media v2 (0082) : plafond + tarif SOV du site */}
          <div className="border border-gray-200 rounded-lg p-3 space-y-2">
            <p className="text-sm font-medium text-gray-800">{t('sites.campaign_inv_title')}</p>
            <div className="grid grid-cols-2 gap-3">
              <Input label={t('players.campaign_cap')} type="number" min={0} max={100}
                     value={campCap} placeholder={t('players.campaign_inherited')}
                     onChange={(e) => setCampCap(e.target.value)} />
              <Input label={t('players.campaign_rate')} type="number" min={0} step={0.01}
                     value={campRate} placeholder={t('players.campaign_inherited')}
                     onChange={(e) => setCampRate(e.target.value)} />
            </div>
            <p className="text-xs text-gray-400">{t('sites.campaign_inv_hint')}</p>
            {/* Exclusion concurrentielle #10 : catégories exclues de CE site
                (héritées par ses players — l'annonceur de la catégorie n'y diffuse jamais) */}
            {industryCategories.length > 0 && (
              <div className="pt-1">
                <p className="text-sm font-medium text-gray-700 mb-1.5">
                  {t('sites.excluded_categories')}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {industryCategories.map((c) => {
                    const active = excludedCats.includes(c.id_category)
                    return (
                      <button key={c.id_category} type="button"
                              onClick={() => setExcludedCats(active
                                ? excludedCats.filter((id) => id !== c.id_category)
                                : [...excludedCats, c.id_category])}
                              className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-sf ${
                                active
                                  ? 'bg-red-500/10 text-danger border-red-400/20'
                                  : 'bg-surface text-gray-600 border-gray-200 hover:bg-canvas'
                              }`}>
                        {c.category_name}
                      </button>
                    )
                  })}
                </div>
                <p className="text-xs text-gray-400 mt-1">{t('sites.excluded_categories_hint')}</p>
              </div>
            )}
          </div>

          {/* Horaires hebdo */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">{t('sites.hours_label')}</label>
            <div className="space-y-1.5">
              {hours.map((h, i) => (
                <div key={h.weekday} className="flex items-center gap-2">
                  <span className="w-10 text-xs text-gray-500 capitalize">{t(`schedules.day_${DAYS[i]}`)}</span>
                  <label className="flex items-center gap-1.5 text-xs text-gray-500 w-20">
                    <input type="checkbox" checked={!h.is_closed} onChange={(e) => setHour(i, { is_closed: !e.target.checked })} className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                    {h.is_closed ? t('sites.closed') : t('sites.open')}
                  </label>
                  {!h.is_closed && (
                    <div className="flex items-center gap-1.5 flex-1">
                      <input type="time" value={h.open_time ?? ''} onChange={(e) => setHour(i, { open_time: e.target.value })} className="px-2 py-1 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40" />
                      <span className="text-gray-300">→</span>
                      <input type="time" value={h.close_time ?? ''} onChange={(e) => setHour(i, { close_time: e.target.value })} className="px-2 py-1 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40" />
                    </div>
                  )}
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-400">{t('sites.overnight_hint')}</p>
          </div>

          {mutateError && <p className="text-sm text-danger">{mutateError}</p>}
          <div className="flex gap-2">
            <Button data-write-action onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !name}>
              {saveMutation.isPending ? t('common.saving') : t('common.save')}
            </Button>
            <Button variant="secondary" onClick={closeDrawer}>{t('common.cancel')}</Button>
          </div>

          {/* Exceptions + players (édition uniquement) */}
          {isEdit && (
            <>
              <div className="border-t border-gray-100 pt-4 space-y-2">
                {/* En-tête repliable */}
                <button
                  type="button"
                  onClick={() => setExcSectionOpen((v) => !v)}
                  className="flex items-center gap-1.5 w-full text-left text-sm font-medium text-gray-700"
                >
                  {excSectionOpen ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
                  {t('sites.exceptions_label')}
                  {exceptions.length > 0 && <span className="text-xs text-gray-400 font-normal">({exceptions.length})</span>}
                </button>
                {excSectionOpen && (
                  <>
                    <p className="text-xs text-gray-400">{t('sites.exceptions_hint')}</p>
                    <div className="space-y-1">
                      {exceptions.map((e) => (
                        <div key={e.id_exception} className="flex items-center justify-between gap-2 text-xs bg-gray-50 rounded px-2 py-1.5">
                          <span className="text-gray-700 truncate">
                            {e.date_from}{e.date_to !== e.date_from ? `→${e.date_to}` : ''} · {t(`sites.exc_${e.kind}`)}
                            {e.kind === 'hours' && e.open_time ? ` ${e.open_time.slice(0, 5)}–${(e.close_time ?? '').slice(0, 5)}` : ''}
                            {e.label ? ` · ${e.label}` : ''}
                          </span>
                          <button data-write-action onClick={() => delExcMutation.mutate(e.id_exception)} className="p-1 text-gray-300 hover:text-danger transition-sf">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))}
                      {exceptions.length === 0 && <p className="text-xs text-gray-400 px-1">{t('sites.no_exceptions')}</p>}
                    </div>
                    {/* Ajout d'exception */}
                    <div className="border border-gray-200 rounded-lg p-3 space-y-2 mt-2">
                      <div className="grid grid-cols-2 gap-2">
                        <Input label={t('schedules.valid_from_label')} type="date" value={excFrom} onChange={(e) => setExcFrom(e.target.value)} />
                        <Input label={t('schedules.valid_until_label')} type="date" value={excTo} min={excFrom || undefined} onChange={(e) => setExcTo(e.target.value)} />
                      </div>
                      <div className="space-y-1">
                        <label className="text-xs font-medium text-gray-600">{t('sites.exc_kind_label')}</label>
                        <select value={excKind} onChange={(e) => setExcKind(e.target.value as typeof excKind)} className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface">
                          <option value="closed">{t('sites.exc_closed')}</option>
                          <option value="hours">{t('sites.exc_hours')}</option>
                          <option value="open_24h">{t('sites.exc_open_24h')}</option>
                        </select>
                      </div>
                      {excKind === 'hours' && (
                        <div className="grid grid-cols-2 gap-2">
                          <Input label={t('schedules.time_start_label')} type="time" value={excOpen} onChange={(e) => setExcOpen(e.target.value)} />
                          <Input label={t('schedules.time_end_label')} type="time" value={excClose} onChange={(e) => setExcClose(e.target.value)} />
                        </div>
                      )}
                      <Input label={t('sites.exc_label_label')} value={excLabel} onChange={(e) => setExcLabel(e.target.value)} placeholder={t('sites.exc_label_ph')} />
                      <Button data-write-action size="sm" variant="secondary" onClick={() => addExcMutation.mutate()} disabled={!excFrom || addExcMutation.isPending}>
                        <Plus className="w-3.5 h-3.5 mr-1" />{t('sites.add_exception')}
                      </Button>
                    </div>
                  </>
                )}
              </div>

              {/* Players rattachés */}
              <div className="border-t border-gray-100 pt-4 space-y-2">
                <label className="text-sm font-medium text-gray-700">{t('sites.players_label')}</label>
                <div className="space-y-1">
                  {sitePlayers.map((p) => (
                    <div key={p.id_player} className="flex items-center justify-between gap-2 text-xs bg-gray-50 rounded px-2 py-1.5">
                      <span className="inline-flex items-center gap-1.5 text-gray-700 truncate">
                        <span className={`w-2 h-2 rounded-full shrink-0 ${p.status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
                        {p.player_name}
                      </span>
                      <span className="inline-flex items-center gap-2 shrink-0">
                        <span className="text-gray-400">{t(`sites.mode_${p.power_mode}`)}</span>
                        {p.last_power_state !== null && (
                          <Power className={`w-3.5 h-3.5 ${p.last_power_state ? 'text-green-500' : 'text-gray-300'}`} />
                        )}
                        <button data-write-action onClick={() => detachMutation.mutate(p.id_player)} disabled={detachMutation.isPending} className="p-0.5 text-gray-300 hover:text-danger transition-sf" title={t('sites.detach_player')}>
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </span>
                    </div>
                  ))}
                  {sitePlayers.length === 0 && <p className="text-xs text-gray-400 px-1">{t('sites.no_players')}</p>}
                </div>
                {/* Picker d'attache : players non rattachés à CE site */}
                {(() => {
                  const attachedIds = new Set(sitePlayers.map((p) => p.id_player))
                  const candidates = allPlayers.filter((p) => !attachedIds.has(p.id_player))
                  return (
                    <div className="flex items-center gap-2">
                      <select
                        value={attachId}
                        onChange={(e) => setAttachId(e.target.value ? Number(e.target.value) : '')}
                        className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                      >
                        <option value="">{t('sites.attach_placeholder')}</option>
                        {candidates.map((p) => (
                          <option key={p.id_player} value={p.id_player}>
                            {p.player_name}{p.id_site ? ` (${t('sites.attach_move')})` : ''}
                          </option>
                        ))}
                      </select>
                      <Button data-write-action size="sm" variant="secondary" disabled={attachId === '' || attachMutation.isPending} onClick={() => attachId !== '' && attachMutation.mutate(attachId)}>
                        <Plus className="w-3.5 h-3.5 mr-1" />{t('sites.attach_player')}
                      </Button>
                    </div>
                  )
                })()}
                <p className="text-xs text-gray-400">{t('sites.players_hint')}</p>
              </div>
            </>
          )}
        </div>
      </Drawer>
    </>
  )
}

// ── Groupes de sites (S6 Retail Media — cible « région » pour campagnes/schedules/events) ──
// Même design que l'onglet Sites (retour Ed 10/07) : recherche + grille de cartes
// compactes ; clic sur une carte → drawer (nom/description + sites membres, pattern
// « Players rattachés » du drawer site).

function SiteGroupsTab({
  groups, sites, t, createOpen, setCreateOpen, refetch,
}: {
  groups: SiteGroupRead[]
  sites: Site[]
  t: ReturnType<typeof useTranslations>
  createOpen: boolean
  setCreateOpen: (v: boolean) => void
  refetch: () => void
}) {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [editGroup, setEditGroup] = useState<SiteGroupRead | null>(null)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [attachId, setAttachId] = useState<number | ''>('')

  const drawerOpen = createOpen || editGroup !== null
  const isEdit = editGroup !== null

  const { data: memberIds = [], refetch: refetchMembers } = useQuery<number[]>({
    queryKey: ['site-group-sites', editGroup?.id_site_group],
    queryFn: () =>
      api.get<Site[]>(`/site-groups/${editGroup!.id_site_group}/sites`)
        .then((r) => r.data.map((s) => s.id_site)),
    enabled: editGroup !== null,
  })

  function openEdit(g: SiteGroupRead) {
    setEditGroup(g); setName(g.group_name); setDesc(g.description ?? ''); setAttachId('')
    setCreateOpen(false)
  }
  function closeDrawer() {
    setEditGroup(null); setCreateOpen(false); setName(''); setDesc(''); setAttachId('')
  }

  const handleSave = async () => {
    if (!name.trim()) return
    const body = { group_name: name.trim(), description: desc.trim() || null }
    if (isEdit) {
      await api.put(`/site-groups/${editGroup!.id_site_group}`, body)
      closeDrawer()
    } else {
      // Création → on reste dans le drawer en mode édition pour ajouter les sites
      const r = await api.post<SiteGroupRead>('/site-groups/', body)
      setEditGroup(r.data)
      setCreateOpen(false)
    }
    refetch()
  }

  const handleDelete = async (g: SiteGroupRead) => {
    if (!confirm(t('sites.delete_group_confirm', { name: g.group_name }))) return
    await api.delete(`/site-groups/${g.id_site_group}`)
    refetch()
  }

  function refreshMembers() {
    refetchMembers()
    refetch()
    qc.invalidateQueries({ queryKey: ['site-groups'] })
  }

  const addSite = async (id: number) => {
    await api.post(`/site-groups/${editGroup!.id_site_group}/sites`, { id_site: id })
    setAttachId(''); refreshMembers()
  }
  const removeSite = async (id: number) => {
    await api.delete(`/site-groups/${editGroup!.id_site_group}/sites/${id}`)
    refreshMembers()
  }

  const filtered = groups.filter((g) => !search
    || g.group_name.toLowerCase().includes(search.toLowerCase())
    || (g.description ?? '').toLowerCase().includes(search.toLowerCase()))
  const members = sites.filter((s) => memberIds.includes(s.id_site))
  const candidates = sites.filter((s) => !memberIds.includes(s.id_site))

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-500">{t('sites.groups_intro')}</p>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
        <input
          type="search" value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder={t('common.search')}
          className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
        />
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400">
          <Layers className="w-10 h-10" />
          <p className="text-sm">{groups.length === 0 ? t('sites.no_groups') : t('common.no_results')}</p>
        </div>
      ) : (
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
          {filtered.map((g) => (
            <div
              key={g.id_site_group}
              role="button" tabIndex={0}
              onClick={() => openEdit(g)}
              onKeyDown={(e) => { if (e.key === 'Enter') openEdit(g) }}
              className="bg-surface border border-gray-200 rounded-lg p-4 cursor-pointer transition-sf hover:border-accent shadow-sf-card"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <Layers className="w-4 h-4 text-gray-400 shrink-0" />
                  <span className="text-sm font-medium text-gray-900 truncate" title={g.group_name}>{g.group_name}</span>
                </div>
                <Can perm="players:edit">
                  <button type="button" title={t('common.delete')}
                    onClick={(e) => { e.stopPropagation(); handleDelete(g) }}
                    className="p-0.5 text-gray-300 transition-sf hover:text-danger shrink-0">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </Can>
              </div>
              {g.description && <p className="text-xs text-gray-400 truncate mt-1">{g.description}</p>}
              <div className="flex items-center gap-3 mt-3 text-[11px] text-gray-500">
                <span className="inline-flex items-center gap-1"><Building2 className="w-3 h-3" />{g.site_count} {t('sites.sites_count')}</span>
                <span className="inline-flex items-center gap-1"><Power className="w-3 h-3" />{g.player_count} {t('sites.players_count')}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <Drawer open={drawerOpen} onClose={closeDrawer} title={isEdit ? t('sites.edit_group') : t('sites.new_group')} width="w-[560px]">
        <div className="space-y-5" data-write-perm="players:edit">
          <Input
            label={t('sites.group_name_label')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('sites.group_name_placeholder')}
            autoFocus={!isEdit}
          />
          <Input
            label={t('sites.group_desc_label')}
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder={t('sites.group_desc_placeholder')}
          />
          <div className="flex gap-2">
            <Button data-write-action onClick={handleSave} disabled={!name.trim()}>{t('common.save')}</Button>
            <Button variant="secondary" onClick={closeDrawer}>{t('common.cancel')}</Button>
          </div>

          {/* Sites membres (édition uniquement — pattern « Players rattachés » du drawer site) */}
          {isEdit && (
            <div className="border-t border-gray-100 pt-4 space-y-2">
              <label className="text-sm font-medium text-gray-700">{t('sites.group_sites_label')}</label>
              <div className="space-y-1">
                {members.map((s) => (
                  <div key={s.id_site} className="flex items-center justify-between gap-2 text-xs bg-gray-50 rounded px-2 py-1.5">
                    <span className="inline-flex items-center gap-1.5 text-gray-700 truncate">
                      <Building2 className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                      {s.site_name}
                    </span>
                    <span className="inline-flex items-center gap-2 shrink-0">
                      <span className="text-gray-400">{s.player_count} {t('sites.players_count')}</span>
                      <button data-write-action onClick={() => removeSite(s.id_site)} className="p-0.5 text-gray-300 hover:text-danger transition-sf" title={t('sites.remove_site_from_group')}>
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </span>
                  </div>
                ))}
                {members.length === 0 && <p className="text-xs text-gray-400 px-1">{t('sites.group_no_sites')}</p>}
              </div>
              {candidates.length > 0 && (
                <div className="flex items-center gap-2">
                  <select
                    value={attachId}
                    onChange={(e) => setAttachId(e.target.value ? Number(e.target.value) : '')}
                    className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                  >
                    <option value="">{t('sites.add_site_to_group')}</option>
                    {candidates.map((s) => (
                      <option key={s.id_site} value={s.id_site}>{s.site_name}</option>
                    ))}
                  </select>
                  <Button data-write-action size="sm" variant="secondary" disabled={attachId === ''} onClick={() => attachId !== '' && addSite(attachId)}>
                    <Plus className="w-3.5 h-3.5 mr-1" />{t('sites.attach_player')}
                  </Button>
                </div>
              )}
              <p className="text-xs text-gray-400">{t('sites.group_sites_hint')}</p>
            </div>
          )}
        </div>
      </Drawer>
    </div>
  )
}
