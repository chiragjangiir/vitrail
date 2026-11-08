import type { MediaRead } from '@/types/api'

/**
 * Conformité & sync-readiness d'un média (passthrough §XVI.2). Miroir léger côté
 * front du verdict produit par backend/app/services/media_conformance.py — le
 * rapport détaillé est dans `media.media_metadata.conformance`.
 */

export type ConformanceStatus = 'ready' | 'playable' | 'nonconform'

export interface ConformanceCheck {
  ok?: boolean | null
  value?: unknown
  value_kbps?: number | null
  ceiling_kbps?: number | null
  max_gop_sec?: number | null
  [k: string]: unknown
}

export interface ConformanceReport {
  status: ConformanceStatus
  checks?: Partial<Record<CheckKey, ConformanceCheck>>
  reasons?: string[]
  gop_max_sec?: number
}

export const CHECK_KEYS = ['codec', 'bitrate', 'cfr', 'gop', 'faststart'] as const
export type CheckKey = (typeof CHECK_KEYS)[number]

/** Statut StatusBadge (icône+couleur) correspondant à un verdict de conformité. */
export function conformanceBadge(
  status: ConformanceStatus | null | undefined,
): 'done' | 'warning' | 'error' | 'pending' {
  switch (status) {
    case 'ready':
      return 'done'
    case 'playable':
      return 'warning'
    case 'nonconform':
      return 'error'
    default:
      return 'pending'
  }
}

/** Extrait le rapport de conformité de media_metadata (probe enrichi par le worker). */
export function conformanceReport(media: MediaRead): ConformanceReport | null {
  const meta = media.media_metadata as Record<string, unknown> | undefined
  const conf = meta?.conformance as ConformanceReport | undefined
  return conf ?? null
}

/** Détail lisible d'un check (valeur/seuil), localisable car purement numérique. */
export function checkDetail(key: CheckKey, c: ConformanceCheck | undefined): string | null {
  if (!c) return null
  switch (key) {
    case 'codec':
      return typeof c.value === 'string' ? c.value.toUpperCase() : null
    case 'bitrate':
      return c.value_kbps ? `${c.value_kbps}${c.ceiling_kbps ? ` / ${c.ceiling_kbps}` : ''} kbps` : null
    case 'gop':
      return c.max_gop_sec != null ? `${c.max_gop_sec}s` : null
    default:
      return null
  }
}
