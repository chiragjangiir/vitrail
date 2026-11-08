'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Maximize2, Crosshair, MapPin } from 'lucide-react'
import { loadLeaflet, OSM_ATTRIBUTION, OSM_TILES } from '@/lib/leaflet'

export interface GeoSite {
  id_site: number
  site_name: string
  country: string | null
  site_number: string | null
  latitude: number
  longitude: number
  players_total: number
  players_online: number
  players_warning: number
  players_offline: number
  players_maintenance: number
}

type StatusKey = 'online' | 'warning' | 'offline' | 'maintenance'

const STATUS_COLOR: Record<StatusKey, string> = {
  online: '#10B981', warning: '#F59E0B', offline: '#EF4444', maintenance: '#3B82F6',
}
const EMPTY_COLOR = '#8B949E'
// Priorité de la couleur d'un site (pire état d'abord).
const PRIORITY: StatusKey[] = ['offline', 'warning', 'maintenance', 'online']

function siteCount(s: GeoSite, k: StatusKey): number {
  return s[`players_${k}` as const]
}
function worstColor(s: GeoSite): string {
  if (s.players_total === 0) return EMPTY_COLOR
  for (const k of PRIORITY) if (siteCount(s, k) > 0) return STATUS_COLOR[k]
  return EMPTY_COLOR
}

interface FleetMapProps {
  sites: GeoSite[]
  /** Compteurs de players par statut (NOC) pour la légende. */
  counts: { online?: number; warning?: number; offline?: number; maintenance?: number }
  /** Demande de centrage externe (clic sur un site dans la table Players). Le `nonce`
   *  change à chaque clic pour re-déclencher le centrage même sur le même site. */
  focus?: { id_site: number; nonce: number } | null
}

/**
 * État du parc — carte monde Leaflet interactive (pan/zoom, reset), filtre par statut
 * et centrage cyclique : un clic sur la cible d'un statut zoome sur le 1er site concerné,
 * le clic suivant sur le 2e, etc. Tuiles OSM assombries (thème dark, cf. globals.css).
 */
export default function FleetMap({ sites, counts, focus }: FleetMapProps) {
  const t = useTranslations()
  const mapRef = useRef<HTMLDivElement>(null)
  const mapObj = useRef<any>(null)
  const layerRef = useRef<any>(null)
  const markers = useRef<Record<number, any>>({})
  const cycle = useRef<Record<StatusKey, number>>({ online: 0, warning: 0, offline: 0, maintenance: 0 })
  const [ready, setReady] = useState(false)
  const [error, setError] = useState(false)
  const [filter, setFilter] = useState<StatusKey | null>(null)

  const placed = useMemo(() => sites.filter((s) => s.latitude != null && s.longitude != null), [sites])
  const shown = useMemo(
    () => (filter ? placed.filter((s) => siteCount(s, filter) > 0) : placed),
    [placed, filter],
  )

  // ── Init carte ──────────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    loadLeaflet().then(() => {
      if (cancelled || !mapRef.current) return
      const L = (window as any).L
      if (!mapObj.current) {
        mapObj.current = L.map(mapRef.current, { scrollWheelZoom: true, worldCopyJump: true })
          .setView([25, 10], 2)
        L.tileLayer(OSM_TILES, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(mapObj.current)
      }
      setReady(true)
      setTimeout(() => mapObj.current?.invalidateSize(), 100)
    }).catch(() => setError(true))
    return () => {
      cancelled = true
      if (mapObj.current) { mapObj.current.remove(); mapObj.current = null }
      setReady(false)
    }
  }, [])

  // ── (Re)pose des marqueurs ────────────────────────────────────────────────────
  useEffect(() => {
    const L = (window as any).L
    if (!L || !ready || !mapObj.current) return
    if (layerRef.current) mapObj.current.removeLayer(layerRef.current)
    markers.current = {}
    const group = L.layerGroup()
    shown.forEach((s) => {
      const color = worstColor(s)
      const m = L.circleMarker([s.latitude, s.longitude], {
        radius: 7, color: '#0B0C10', weight: 1.5, fillColor: color, fillOpacity: 0.95,
      }).bindPopup(
        `<b>${s.site_name}</b>${s.site_number ? ` (${s.site_number})` : ''}` +
        `${s.country ? `<br>${s.country}` : ''}` +
        `<br>${s.players_online}/${s.players_total} online` +
        (s.players_offline ? `<br>${s.players_offline} offline` : '') +
        (s.players_warning ? `<br>${s.players_warning} warning` : ''),
      )
      m.addTo(group)
      markers.current[s.id_site] = m
    })
    group.addTo(mapObj.current)
    layerRef.current = group
  }, [shown, ready])

  // Centrage externe : un clic sur le nom de site dans la table Players demande de zoomer
  // dessus. On lève d'abord un éventuel filtre de statut qui le masquerait (l'effet re-tourne
  // après repose des marqueurs), puis on centre + ouvre la popup.
  useEffect(() => {
    if (!focus || !ready || !mapObj.current) return
    const site = placed.find((s) => s.id_site === focus.id_site)
    if (!site) return
    if (filter && siteCount(site, filter) === 0) { setFilter(null); return }
    mapObj.current.setView([site.latitude, site.longitude], 13, { animate: true })
    markers.current[site.id_site]?.openPopup()
  }, [focus, ready, shown, placed, filter])

  function resetView() {
    const map = mapObj.current
    if (!map) return
    if (placed.length) {
      try { map.fitBounds(placed.map((s) => [s.latitude, s.longitude]), { padding: [30, 30], maxZoom: 12 }) } catch { /* */ }
    } else {
      map.setView([25, 10], 2)
    }
  }

  // Centrage cyclique sur les sites d'un statut.
  function cycleStatus(k: StatusKey) {
    const map = mapObj.current
    if (!map) return
    const list = placed.filter((s) => siteCount(s, k) > 0).sort((a, b) => a.site_name.localeCompare(b.site_name))
    if (list.length === 0) return
    const idx = cycle.current[k] % list.length
    const s = list[idx]
    cycle.current[k] = idx + 1
    map.setView([s.latitude, s.longitude], 13, { animate: true })
    markers.current[s.id_site]?.openPopup()
  }

  const LEGEND: { k: StatusKey; label: string }[] = [
    { k: 'online', label: t('players.status_online') },
    { k: 'offline', label: t('players.status_offline') },
    { k: 'warning', label: t('players.status_warning') },
    { k: 'maintenance', label: t('players.status_maintenance') },
  ]

  return (
    <div className="flex gap-4 flex-1 min-h-0">
      {/* Légende + filtres + cibles */}
      <div className="shrink-0 w-48 space-y-1.5 py-1">
        {LEGEND.map(({ k, label }) => {
          const active = filter === k
          const nSites = placed.filter((s) => siteCount(s, k) > 0).length
          return (
            <div
              key={k}
              className={`group flex items-center gap-2 rounded-lg px-2 py-1.5 cursor-pointer transition-sf ${active ? 'bg-white/10' : 'hover:bg-white/5'}`}
              onClick={() => setFilter(active ? null : k)}
              title={active ? t('dashboard.fleet_filter_clear') : t('dashboard.fleet_filter', { s: label })}
            >
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: STATUS_COLOR[k], boxShadow: `0 0 6px ${STATUS_COLOR[k]}` }} />
              <span className="text-base font-semibold text-gray-900 tabular-nums min-w-[2.5rem]">{counts[k] ?? '—'}</span>
              <span className="text-xs text-gray-500 flex-1 truncate">{label}</span>
              <button
                onClick={(e) => { e.stopPropagation(); cycleStatus(k) }}
                disabled={nSites === 0}
                title={t('dashboard.fleet_center', { s: label })}
                className="shrink-0 p-1 rounded text-gray-500 hover:text-accent-hover hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-sf"
              >
                <Crosshair className="w-3.5 h-3.5" />
              </button>
            </div>
          )
        })}
        {filter && (
          <button onClick={() => setFilter(null)} className="text-[11px] text-accent-hover hover:underline pl-2 pt-1">
            {t('dashboard.fleet_filter_clear')}
          </button>
        )}
      </div>

      {/* Carte */}
      <div className="relative flex-1 rounded-lg border border-white/5 overflow-hidden min-h-[240px]">
        {error ? (
          <div className="sf-dotted absolute inset-0 bg-black/20 flex flex-col items-center justify-center gap-2 text-gray-500">
            <MapPin className="w-6 h-6" />
            <p className="text-xs">{t('dashboard.fleet_map_error')}</p>
          </div>
        ) : (
          <>
            <div ref={mapRef} className="sf-fleet-map w-full h-full min-h-[240px]" />
            <button
              onClick={resetView}
              title={t('dashboard.fleet_reset')}
              className="absolute top-2 right-2 z-[400] p-1.5 rounded-lg bg-surface border border-white/10 text-gray-400 hover:text-gray-900 hover:bg-surface-hover shadow-sf-card transition-sf"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
            {placed.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <p className="text-xs text-gray-500 bg-canvas/70 rounded px-2 py-1">{t('dashboard.fleet_no_geo')}</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
