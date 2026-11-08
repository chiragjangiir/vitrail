import type { PlayerRead } from '@/types/api'

/**
 * Synthèse de l'état de décodage vidéo d'un player, calculée côté front depuis
 * `player.capabilities` (remonté par le player). Miroir de
 * backend/app/services/player_capabilities.py::decode_health — gardé volontairement
 * en TS pour que les libellés restent localisés (next-intl) au lieu d'afficher les
 * messages serveur en français.
 */

export type DecodeEffective = 'hardware' | 'software' | 'unknown'
export type DecodeSeverity = 'ok' | 'warning' | 'unknown'

export interface DecodeHealth {
  effective: DecodeEffective
  /** méthode HW effective : vaapi | v4l2 | d3d11 | mediacodec — sinon null */
  method: string | null
  severity: DecodeSeverity
  /** true si un GPU compatible a été détecté mais le décodage HW n'est pas actif */
  capableButInactive: boolean
}

const VALID_HW_METHODS = ['vaapi', 'v4l2', 'd3d11', 'mediacodec']
// Plateformes à décodage natif transparent (ChromeOS) : matériel par construction,
// sans drapeau hw_decode_active. Miroir de player_capabilities._NATIVE_HW_METHODS.
const NATIVE_HW_METHODS = ['chromium-native']
const ALL_HW_METHODS = [...VALID_HW_METHODS, ...NATIVE_HW_METHODS]

export function decodeHealth(player: PlayerRead): DecodeHealth {
  const caps = player.capabilities
  if (!caps || Object.keys(caps).length === 0) {
    return { effective: 'unknown', method: null, severity: 'unknown', capableButInactive: false }
  }
  const method = caps.hw_decode ?? null
  const validMethod = method && ALL_HW_METHODS.includes(method) ? method : null

  if (caps.sf_hw_decode === 'off') {
    return { effective: 'software', method: validMethod, severity: 'warning', capableButInactive: false }
  }
  if (method && NATIVE_HW_METHODS.includes(method)) {
    // ChromeOS : décodage natif HW, pas de hw_decode_active attendu.
    return { effective: 'hardware', method: validMethod, severity: 'ok', capableButInactive: false }
  }
  if (caps.hw_decode_active === true && validMethod) {
    return { effective: 'hardware', method: validMethod, severity: 'ok', capableButInactive: false }
  }
  if (caps.hw_decode_active === false) {
    return {
      effective: 'software',
      method: validMethod,
      severity: 'warning',
      capableButInactive: Boolean(validMethod),
    }
  }
  return { effective: 'unknown', method: null, severity: 'unknown', capableButInactive: false }
}
