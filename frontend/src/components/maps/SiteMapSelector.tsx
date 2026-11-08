'use client'

// S7 Phase A — sélection de sites cibles sur la CARTE de l'org (drawer campagne) :
// marqueurs des sites placés (accent = sélectionné, gris = non), clic = toggle.
// Les sites sans coordonnées restent sélectionnables via les dropdowns classiques.
//
// 2026-07-21 (retour Ed) : recherche par nom + recentrage. Un champ optionnel
// (`searchable`) liste les sites correspondants ; cliquer un résultat recentre la
// carte dessus (setView) et remonte `onFocusSite` au parent (pour, ex., déplier la
// sélection par écran de ce site).

import { useEffect, useMemo, useRef, useState } from 'react'
import { Search, X, MapPin, MapPinOff, Layers } from 'lucide-react'
import { DEFAULT_VIEW, getLeaflet, loadLeaflet, OSM_ATTRIBUTION, OSM_TILES } from '@/lib/leaflet'

/** Groupe de sites cherchable sur la carte (optionnel — les campagnes n'en passent pas). */
export interface MapSiteGroup {
  id: number
  name: string
  site_ids: number[]
}

export interface MapSite {
  id_site: number
  site_name: string
  latitude: number | null
  longitude: number | null
  // Nb d'écrans vendables (portail — affiché dans le tooltip du marqueur, Ed #4)
  screen_count?: number
  // Exclusion concurrentielle #10 (portail) : site fermé à CET annonceur —
  // marqueur grisé, non cliquable.
  excluded?: boolean
  // Sélection par écran (0089, portail) : players vendables du site — présents
  // seulement si le réglage org l'autorise.
  players?: { id_player: number; player_name: string }[]
}

const SELECTED_COLOR = '#2563EB'   // accent Mission Control
const UNSELECTED_COLOR = '#9CA3AF'
// Site couvert par un GROUPE rattaché : ni « choisi à la main », ni « libre ». Il doit se
// distinguer des deux — sinon on croit avoir oublié un magasin qui est en réalité gouverné
// par son groupe (gouvernance §XVIII, retour Ed 2026-07-26).
const COVERED_COLOR = '#10B981'
const FOCUS_ZOOM = 15

export default function SiteMapSelector({
  sites, selected, onToggle, heightClass = 'h-[420px]',
  searchable = false, onFocusSite, searchPlaceholder = 'Search a site…',
  covered, groups, onPickGroup,
}: {
  sites: MapSite[]
  selected: Set<number>
  onToggle: (id_site: number) => void
  heightClass?: string
  /** Affiche un champ de recherche par nom + recentrage au clic (retour Ed). */
  searchable?: boolean
  /** Appelé quand un site est choisi dans la recherche (après recentrage). */
  onFocusSite?: (id_site: number) => void
  /** Placeholder du champ de recherche (i18n — le portail est multilingue). */
  searchPlaceholder?: string
  /** Sites couverts INDIRECTEMENT (par un groupe rattaché) : marqueur distinct, non
   *  basculable — les retirer se fait en détachant le groupe, pas site par site. */
  covered?: Set<number>
  /** Groupes de sites cherchables : taper leur nom les trouve et cadre leurs sites. */
  groups?: MapSiteGroup[]
  onPickGroup?: (id: number) => void
}) {
  const mapRef = useRef<HTMLDivElement>(null)
  const mapObj = useRef<any>(null)
  const layerRef = useRef<any>(null)
  const onToggleRef = useRef(onToggle)
  onToggleRef.current = onToggle
  const [ready, setReady] = useState(false)
  const [error, setError] = useState(false)

  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)

  const placed = sites.filter((s) => s.latitude != null && s.longitude != null)

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return sites.filter((s) => s.site_name.toLowerCase().includes(q)).slice(0, 20)
  }, [query, sites])

  // Les GROUPES sont cherchables aussi : taper « Governance - IDF » ne trouvait rien alors
  // que le groupe existe (retour Ed 2026-07-26). Ils sortent en tête des résultats — on
  // cherche un ensemble, pas un site parmi d'autres.
  const groupMatches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q || !groups) return []
    return groups.filter((g) => g.name.toLowerCase().includes(q)).slice(0, 10)
  }, [query, groups])

  function focusGroup(g: MapSiteGroup) {
    const pts = sites
      .filter((s) => g.site_ids.includes(s.id_site) && s.latitude != null && s.longitude != null)
      .map((s) => [s.latitude!, s.longitude!] as [number, number])
    if (pts.length && mapObj.current) {
      try { mapObj.current.fitBounds(pts, { padding: [40, 40], maxZoom: 13 }) } catch { /* */ }
    }
    onPickGroup?.(g.id)
    setOpen(false)
    setQuery(g.name)
  }

  function focusSite(s: MapSite) {
    if (s.latitude != null && s.longitude != null && mapObj.current) {
      mapObj.current.setView([s.latitude, s.longitude], FOCUS_ZOOM, { animate: true })
    }
    onFocusSite?.(s.id_site)
    setOpen(false)
    setQuery(s.site_name)
  }

  useEffect(() => {
    let cancelled = false
    loadLeaflet().then(() => {
      if (cancelled || !mapRef.current || mapObj.current) return
      const L = getLeaflet()
      mapObj.current = L.map(mapRef.current, { scrollWheelZoom: true })
        .setView(DEFAULT_VIEW.center, DEFAULT_VIEW.zoom)
      // Zoom en HAUT À DROITE : libère le coin haut-gauche pour la barre de recherche
      // (sinon les boutons +/- masquaient le début du champ — retour Ed 21/07).
      try { mapObj.current.zoomControl?.setPosition('topright') } catch { /* */ }
      L.tileLayer(OSM_TILES, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(mapObj.current)
      setReady(true)
      setTimeout(() => mapObj.current?.invalidateSize(), 150)
    }).catch(() => setError(true))
    return () => {
      cancelled = true
      if (mapObj.current) { mapObj.current.remove(); mapObj.current = null }
      setReady(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // (Re)pose des marqueurs à chaque changement de sélection.
  useEffect(() => {
    const L = getLeaflet()
    if (!L || !ready || !mapObj.current) return
    const hadLayer = layerRef.current !== null
    if (layerRef.current) mapObj.current.removeLayer(layerRef.current)
    const group = L.layerGroup()
    const pts: [number, number][] = []
    placed.forEach((s) => {
      const isSel = selected.has(s.id_site)
      const isCovered = !isSel && !!covered?.has(s.id_site)
      pts.push([s.latitude!, s.longitude!])
      const m = L.circleMarker([s.latitude!, s.longitude!], {
        radius: isSel || isCovered ? 11 : 9,
        color: '#fff', weight: 2,
        fillColor: isSel ? SELECTED_COLOR : isCovered ? COVERED_COLOR : UNSELECTED_COLOR,
        fillOpacity: s.excluded ? 0.4 : 0.95,
      }).bindTooltip(
        s.excluded
          ? `${s.site_name} — ✕`
          : s.screen_count != null ? `${s.site_name} — ${s.screen_count} 📺` : s.site_name,
        { direction: 'top', offset: [0, -8] })
      // Un site couvert par un groupe n'est pas décochable ici : on détache le GROUPE.
      if (!s.excluded && !isCovered) m.on('click', () => onToggleRef.current(s.id_site))
      m.addTo(group)
    })
    group.addTo(mapObj.current)
    layerRef.current = group
    // fitBounds au premier rendu seulement (pas à chaque clic — la vue ne doit pas sauter)
    if (!hadLayer && pts.length) {
      try { mapObj.current.fitBounds(pts, { padding: [40, 40], maxZoom: 13 }) } catch { /* */ }
    }
  }, [ready, placed, selected, covered])

  if (error) return null
  return (
    <div className={`relative w-full ${heightClass}`}>
      {searchable && (
        // z au-dessus des panes Leaflet (~400/600). Positionné dans le coin haut-gauche.
        <div className="absolute top-2 left-2 right-2 z-[1000] max-w-xs">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
            <input
              type="search"
              value={query}
              onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
              onFocus={() => setOpen(true)}
              placeholder={searchPlaceholder}
              className="w-full pl-8 pr-7 py-1.5 text-sm rounded-lg border border-gray-200 bg-surface shadow-sf-card focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
            {query && (
              <button
                type="button"
                onClick={() => { setQuery(''); setOpen(false) }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          {open && (matches.length > 0 || groupMatches.length > 0) && (
            <div className="mt-1 max-h-56 overflow-y-auto rounded-lg border border-gray-200 bg-surface shadow-sf-card divide-y divide-gray-100">
              {groupMatches.map((g) => (
                <button
                  key={`g-${g.id}`}
                  type="button"
                  onClick={() => focusGroup(g)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-sf"
                >
                  <Layers className="w-3.5 h-3.5 text-accent shrink-0" />
                  <span className="truncate flex-1">{g.name}</span>
                  <span className="text-[10px] text-gray-400 shrink-0">{g.site_ids.length}</span>
                </button>
              ))}
              {matches.map((s) => {
                const hasCoords = s.latitude != null && s.longitude != null
                return (
                  <button
                    key={s.id_site}
                    type="button"
                    onClick={() => focusSite(s)}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-sf"
                  >
                    {hasCoords
                      ? <MapPin className="w-3.5 h-3.5 text-accent shrink-0" />
                      : <MapPinOff className="w-3.5 h-3.5 text-gray-300 shrink-0" />}
                    <span className="truncate flex-1">{s.site_name}</span>
                    {selected.has(s.id_site) && (
                      <span className="text-[10px] text-accent shrink-0">✓</span>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}
      <div
        ref={mapRef}
        data-testid="site-map-selector"
        className="w-full h-full rounded-lg border border-gray-200 overflow-hidden"
        style={{ background: '#e8eef3' }}
      />
    </div>
  )
}
