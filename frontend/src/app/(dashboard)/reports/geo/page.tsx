'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { MapPin, AlertCircle, Search, Circle } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import BackButton from '@/components/ui/BackButton'
import api from '@/lib/api'
import { loadLeaflet, OSM_ATTRIBUTION, OSM_TILES } from '@/lib/leaflet'

interface GeoSite {
  id_site: number; site_name: string; country: string | null; site_number: string | null
  latitude: number; longitude: number
  players_total: number; players_online: number; players_warning: number; players_offline: number
}
interface GeoResponse { sites: GeoSite[]; unplaced: number }

const COLORS = { online: '#2E7D32', warning: '#E65100', offline: '#C62828', empty: '#9CA3AF' }

function siteColor(s: GeoSite): keyof typeof COLORS {
  if (s.players_total === 0) return 'empty'
  if (s.players_offline > 0) return 'offline'
  if (s.players_warning > 0) return 'warning'
  return 'online'
}

export default function GeoDashboardPage() {
  const t = useTranslations('reports')
  const mapRef = useRef<HTMLDivElement>(null)
  const mapObj = useRef<any>(null)
  const layerRef = useRef<any>(null)
  const markers = useRef<Record<number, any>>({})
  const [mapReady, setMapReady] = useState(false)
  const [mapError, setMapError] = useState(false)
  const [search, setSearch] = useState('')
  const [country, setCountry] = useState('')
  const [siteId, setSiteId] = useState<string>('')

  const { data } = useQuery({
    queryKey: ['analytics-geo'],
    queryFn: async () => (await api.get<GeoResponse>('/analytics/geo')).data,
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    staleTime: 0,
  })

  const countries = useMemo(
    () => Array.from(new Set((data?.sites ?? []).map((s) => s.country).filter(Boolean))).sort() as string[],
    [data])

  // sites du pays choisi (pour la 2e liste) ; tous si aucun pays
  const countrySites = useMemo(
    () => (data?.sites ?? []).filter((s) => !country || s.country === country),
    [data, country])

  // sites affichés sur la carte + dans la liste (pays + recherche + site sélectionné)
  const filtered = useMemo(() => {
    let r = countrySites
    if (siteId) r = r.filter((s) => String(s.id_site) === siteId)
    else if (search) {
      const q = search.toLowerCase()
      r = r.filter((s) => s.site_name.toLowerCase().includes(q)
        || (s.site_number ?? '').toLowerCase().includes(q)
        || (s.country ?? '').toLowerCase().includes(q))
    }
    return r
  }, [countrySites, search, siteId])

  // ── Init carte (une fois Leaflet chargé) → mapReady ──────────────────────────
  useEffect(() => {
    let cancelled = false
    loadLeaflet().then(() => {
      if (cancelled || !mapRef.current) return
      const L = (window as any).L
      if (!mapObj.current) {
        mapObj.current = L.map(mapRef.current, { scrollWheelZoom: true }).setView([46.6, 2.4], 5)
        L.tileLayer(OSM_TILES, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(mapObj.current)
      }
      setMapReady(true)
    }).catch(() => setMapError(true))
    return () => {
      cancelled = true
      if (mapObj.current) { mapObj.current.remove(); mapObj.current = null }
      setMapReady(false)
    }
  }, [])

  // ── (Re)pose des marqueurs — dépend de mapReady (corrige la pastille au retour) ─
  useEffect(() => {
    const L = (window as any).L
    if (!L || !mapReady || !mapObj.current || !data) return
    if (layerRef.current) mapObj.current.removeLayer(layerRef.current)
    markers.current = {}
    const group = L.layerGroup()
    const pts: [number, number][] = []
    filtered.forEach((s) => {
      pts.push([s.latitude, s.longitude])
      const m = L.circleMarker([s.latitude, s.longitude], {
        radius: 9, color: '#fff', weight: 2, fillColor: COLORS[siteColor(s)], fillOpacity: 0.9,
      }).bindPopup(
        `<b>${s.site_name}</b>${s.site_number ? ` (${s.site_number})` : ''}` +
        `${s.country ? `<br>${s.country}` : ''}` +
        `<br>${s.players_online}/${s.players_total} en ligne` +
        (s.players_offline ? `<br>${s.players_offline} hors ligne` : ''),
      )
      m.addTo(group)
      markers.current[s.id_site] = m
    })
    group.addTo(mapObj.current)
    layerRef.current = group
    if (siteId && filtered.length === 1) {
      const s = filtered[0]
      mapObj.current.setView([s.latitude, s.longitude], 14)
      markers.current[s.id_site]?.openPopup()
    } else if (pts.length) {
      try { mapObj.current.fitBounds(pts, { padding: [40, 40], maxZoom: 13 }) } catch { /* */ }
    }
  }, [data, mapReady, filtered, siteId])

  const inp = 'px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface text-gray-700'
  const legend = [
    { c: COLORS.online, k: 'geo_all_online' },
    { c: COLORS.warning, k: 'geo_warning' },
    { c: COLORS.offline, k: 'geo_offline' },
    { c: COLORS.empty, k: 'geo_no_player' },
  ]

  return (
    <>
      <Topbar title={t('geo_title')}>
        <BackButton />
      </Topbar>
      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-8 space-y-4">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <p className="text-sm text-gray-400 max-w-xl">{t('geo_hint')}</p>
            <div className="flex items-center gap-3 flex-wrap text-xs text-gray-500">
              {legend.map((l) => (
                <span key={l.k} className="inline-flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: l.c }} />{t(l.k)}
                </span>
              ))}
            </div>
          </div>

          {/* Filtres */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <input value={search} onChange={(e) => { setSearch(e.target.value); setSiteId('') }}
                placeholder={t('geo_search')} className={`w-full pl-9 pr-3 ${inp}`} />
            </div>
            <select value={country} onChange={(e) => { setCountry(e.target.value); setSiteId('') }} className={inp}>
              <option value="">{t('geo_all_countries')}</option>
              {countries.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={siteId} onChange={(e) => setSiteId(e.target.value)} className={inp}>
              <option value="">{t('geo_all_sites')}</option>
              {countrySites.map((s) => (
                <option key={s.id_site} value={s.id_site}>
                  {s.site_number ? `${s.site_number} — ` : ''}{s.site_name}
                </option>
              ))}
            </select>
            {(search || country || siteId) && (
              <button onClick={() => { setSearch(''); setCountry(''); setSiteId('') }}
                className="text-xs text-accent hover:underline">{t('geo_reset')}</button>
            )}
          </div>

          {data && data.unplaced > 0 && (
            <div className="flex items-center gap-2 text-xs text-warning bg-warning/10 rounded px-2.5 py-1.5">
              <AlertCircle className="w-4 h-4 shrink-0" />{t('geo_unplaced', { n: data.unplaced })}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-4">
            {mapError ? (
              <div className="flex flex-col items-center justify-center gap-2 py-16 text-gray-400 bg-surface rounded-lg border border-gray-200 shadow-sf-card">
                <MapPin className="w-8 h-8" /><p className="text-sm">{t('geo_map_error')}</p>
              </div>
            ) : (
              <div ref={mapRef} className="w-full rounded-lg border border-gray-200 overflow-hidden"
                style={{ height: '64vh', minHeight: 420, background: '#e8eef3' }} />
            )}

            {/* Liste des sites / numéros */}
            <div className="bg-surface rounded-lg border border-gray-200 overflow-hidden flex flex-col shadow-sf-card"
              style={{ maxHeight: '64vh' }}>
              <div className="px-3 py-2 border-b border-gray-200 text-xs font-medium text-gray-500">
                {t('geo_site_list', { n: filtered.length })}
              </div>
              <div className="overflow-y-auto divide-y divide-gray-100">
                {filtered.length === 0 && (
                  <p className="text-xs text-gray-400 p-3 text-center">{t('geo_empty')}</p>
                )}
                {filtered.map((s) => (
                  <button key={s.id_site} onClick={() => setSiteId(String(s.id_site))}
                    className="w-full text-left px-3 py-2 hover:bg-gray-50 transition-sf flex items-center gap-2">
                    <Circle className="w-2.5 h-2.5 shrink-0" fill={COLORS[siteColor(s)]}
                      stroke="none" />
                    <div className="min-w-0">
                      <p className="text-sm text-gray-800 truncate">
                        {s.site_number ? <span className="font-mono text-xs text-gray-500">{s.site_number} </span> : null}
                        {s.site_name}
                      </p>
                      <p className="text-[11px] text-gray-400 truncate">
                        {s.country ? `${s.country} · ` : ''}{s.players_online}/{s.players_total} {t('geo_online_short')}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>
    </>
  )
}
