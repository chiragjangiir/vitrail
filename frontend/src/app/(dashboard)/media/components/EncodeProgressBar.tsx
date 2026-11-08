'use client'

import { useTranslations } from 'next-intl'
import type { EncodeProgress } from '@/types/api'

/** Signature minimale d'un `t` de next-intl — suffisante ici et sans dépendance au
 *  paramétrage de types du namespace (ces helpers sont appelés depuis 3 surfaces). */
type Translate = (key: string, values?: Record<string, string | number>) => string

/**
 * Avancement d'un encodage — définition UNIQUE, partagée par la grille, la vue liste et le
 * tiroir. Trois surfaces montrent la même chose ; trois implémentations finiraient par
 * afficher trois pourcentages différents pour le même encodage.
 *
 * 🔑 Deux états bien distincts, et c'est le point :
 *   - `pct` connu    → barre déterminée, avec le temps restant estimé ;
 *   - `pct` inconnu  → barre INDÉTERMINÉE (source sans durée sondable, ou phase de
 *     finalisation). On montre qu'il se passe quelque chose, on n'invente pas de chiffre.
 */

/** « 45 s », « 4 min », « 1 h 12 » — jamais « 4523 secondes ». */
export function formatEta(seconds: number, t: Translate): string {
  if (seconds < 60) return t('enc_eta_sec', { n: Math.max(1, Math.round(seconds)) })
  if (seconds < 3600) return t('enc_eta_min', { n: Math.round(seconds / 60) })
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return m > 0 ? t('enc_eta_hm', { h, m }) : t('enc_eta_h', { h })
}

export function encodeLabel(
  p: EncodeProgress,
  t: Translate,
): string {
  if (p.phase === 'download') return t('enc_downloading')
  if (p.phase === 'finalize') return t('enc_finalizing')
  if (p.phase === 'rendition') return t('enc_rendition', { profile: p.profile ?? '' })
  return t('enc_encoding')
}

export default function EncodeProgressBar({
  progress,
  compact = false,
  className = '',
}: {
  progress?: EncodeProgress | null
  /** Vignette : barre seule, sans libellé (la place manque). */
  compact?: boolean
  className?: string
}) {
  const t = useTranslations('media')
  if (!progress) return null

  const pct = progress.pct
  const determinate = typeof pct === 'number'
  const label = encodeLabel(progress, t)

  return (
    <div className={className} data-testid="encode-progress">
      {!compact && (
        <div className="flex items-baseline justify-between gap-2 mb-1">
          <span className="text-[11px] text-gray-600">{label}</span>
          <span className="text-[11px] tabular-nums text-gray-500">
            {determinate ? `${Math.round(pct!)} %` : ''}
            {typeof progress.eta_s === 'number' && progress.eta_s > 0 && (
              <> · {t('enc_eta', { time: formatEta(progress.eta_s, t) })}</>
            )}
          </span>
        </div>
      )}
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-white/10"
        role="progressbar"
        aria-label={label}
        {...(determinate
          ? { 'aria-valuenow': Math.round(pct!), 'aria-valuemin': 0, 'aria-valuemax': 100 }
          : {})}
      >
        <div
          className={
            determinate
              ? 'h-full rounded-full bg-accent transition-[width] duration-500 ease-out'
              : 'h-full w-1/3 rounded-full bg-accent motion-safe:animate-[sf-indeterminate_1.4s_ease-in-out_infinite]'
          }
          style={determinate ? { width: `${pct}%` } : undefined}
        />
      </div>
    </div>
  )
}
