'use client'

// S7 Phase A — mini-carte de placement d'un site : clic (ou drag du marqueur) →
// remplit latitude/longitude du formulaire. Résorbe le reste §24 « saisir les
// coordonnées des sites » (avant : 2 champs texte à la main).

import { useEffect, useRef, useState } from 'react'
import { DEFAULT_VIEW, getLeaflet, loadLeaflet, OSM_ATTRIBUTION, OSM_TILES } from '@/lib/leaflet'

function parseCoord(v: string): number | null {
  const n = Number(v.trim())
  return v.trim() !== '' && Number.isFinite(n) ? n : null
}

export default function LatLngPicker({
  lat, lng, onChange, heightClass = 'h-56',
}: {
  lat: string
  lng: string
  onChange: (lat: string, lng: string) => void
  heightClass?: string
}) {
  const mapRef = useRef<HTMLDivElement>(null)
  const mapObj = useRef<any>(null)
  const markerRef = useRef<any>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const [error, setError] = useState(false)

  // Init (une fois) — centre sur les coords existantes sinon vue par défaut.
  useEffect(() => {
    let cancelled = false
    loadLeaflet().then(() => {
      if (cancelled || !mapRef.current || mapObj.current) return
      const L = getLeaflet()
      const la = parseCoord(lat)
      const lo = parseCoord(lng)
      const placed = la !== null && lo !== null
      const map = L.map(mapRef.current, { scrollWheelZoom: true })
        .setView(placed ? [la, lo] : DEFAULT_VIEW.center, placed ? 13 : DEFAULT_VIEW.zoom)
      L.tileLayer(OSM_TILES, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(map)

      const setMarker = (pos: [number, number]) => {
        if (markerRef.current) {
          markerRef.current.setLatLng(pos)
        } else {
          markerRef.current = L.marker(pos, { draggable: true }).addTo(map)
          markerRef.current.on('dragend', () => {
            const p = markerRef.current.getLatLng()
            onChangeRef.current(p.lat.toFixed(6), p.lng.toFixed(6))
          })
        }
      }
      if (placed) setMarker([la!, lo!])
      map.on('click', (e: any) => {
        setMarker([e.latlng.lat, e.latlng.lng])
        onChangeRef.current(e.latlng.lat.toFixed(6), e.latlng.lng.toFixed(6))
      })
      mapObj.current = map
      // Le drawer vient de s'ouvrir/déplier : recalcule la taille du canvas.
      setTimeout(() => map.invalidateSize(), 150)
    }).catch(() => setError(true))
    return () => {
      cancelled = true
      if (mapObj.current) { mapObj.current.remove(); mapObj.current = null; markerRef.current = null }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Suit les éditions MANUELLES des champs lat/lng (marqueur re-synchronisé).
  useEffect(() => {
    const L = getLeaflet()
    if (!L || !mapObj.current) return
    const la = parseCoord(lat)
    const lo = parseCoord(lng)
    if (la === null || lo === null) return
    const cur = markerRef.current?.getLatLng()
    if (cur && Math.abs(cur.lat - la) < 1e-6 && Math.abs(cur.lng - lo) < 1e-6) return
    if (markerRef.current) {
      markerRef.current.setLatLng([la, lo])
    } else {
      markerRef.current = L.marker([la, lo], { draggable: true }).addTo(mapObj.current)
      markerRef.current.on('dragend', () => {
        const p = markerRef.current.getLatLng()
        onChangeRef.current(p.lat.toFixed(6), p.lng.toFixed(6))
      })
    }
    mapObj.current.setView([la, lo], Math.max(mapObj.current.getZoom(), 12))
  }, [lat, lng])

  if (error) return null
  return (
    <div
      ref={mapRef}
      data-testid="latlng-picker-map"
      className={`w-full ${heightClass} rounded-lg border border-gray-200 overflow-hidden`}
      style={{ background: '#e8eef3' }}
    />
  )
}
