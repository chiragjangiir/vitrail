// Loader Leaflet partagé (CDN unpkg + tuiles OSM) — extrait de /reports/geo (§24.2),
// réutilisé par le map picker du drawer site et le sélecteur de sites du drawer
// campagne (S7 Phase A). Charge le JS/CSS une seule fois, résout quand window.L est prêt.

const LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'

export const OSM_TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
export const OSM_ATTRIBUTION = '© OpenStreetMap'
// Vue par défaut (France entière) quand rien n'est placé.
export const DEFAULT_VIEW: { center: [number, number]; zoom: number } = { center: [46.6, 2.4], zoom: 5 }

export function loadLeaflet(): Promise<void> {
  return new Promise((resolve, reject) => {
    const w = window as unknown as { L?: unknown }
    if (w.L) return resolve()
    if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
      const link = document.createElement('link')
      link.rel = 'stylesheet'; link.href = LEAFLET_CSS
      document.head.appendChild(link)
    }
    const existing = document.querySelector(`script[src="${LEAFLET_JS}"]`)
    if (existing) { existing.addEventListener('load', () => resolve()); return }
    const script = document.createElement('script')
    script.src = LEAFLET_JS
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('leaflet load failed'))
    document.body.appendChild(script)
  })
}

export function getLeaflet(): any {
  return (window as any).L
}
