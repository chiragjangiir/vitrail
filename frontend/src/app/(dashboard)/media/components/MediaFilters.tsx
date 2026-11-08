'use client'

import { useTranslations } from 'next-intl'
import { SlidersHorizontal, X } from 'lucide-react'

/**
 * Panneau de filtres latéral (retour Ed sur les maquettes MyBox, audit du menu Média
 * 2026-07-28).
 *
 * Il ne REMPLACE pas les pastilles de type au-dessus de la grille : celles-ci restent le
 * geste rapide « je veux voir les vidéos ». Le panneau sert au filtrage COMBINÉ — plusieurs
 * types à la fois, plus l'état de préparation — ce que des pastilles à choix unique ne
 * savent pas exprimer.
 *
 * ⚠️ Le filtre multi-types est appliqué CÔTÉ CLIENT sur la page chargée, car l'API ne prend
 * qu'un seul `media_type`. C'est assumé et signalé à l'écran : sur une médiathèque paginée,
 * un filtre client ne voit que ce qui est chargé. Un filtre serveur multi-valeurs serait la
 * bonne réponse le jour où ça gêne — le dire vaut mieux que de laisser croire à un filtrage
 * exhaustif (c'est la leçon du drawer « Ajouter un média », qui filtrait 200 éléments
 * chargés en laissant croire qu'il cherchait dans toute la médiathèque).
 */

export interface FilterState {
  types: Set<string>
  status: Set<string>   // done | processing | error
  onlyEmbargo: boolean
  onlyBlocked: boolean
}

export const EMPTY_FILTERS: FilterState = {
  types: new Set(), status: new Set(), onlyEmbargo: false, onlyBlocked: false,
}

export function countActive(f: FilterState): number {
  return f.types.size + f.status.size + (f.onlyEmbargo ? 1 : 0) + (f.onlyBlocked ? 1 : 0)
}

export function applyFilters<T extends {
  media_type: string; transcode_status: string; not_before_utc: string | null; is_blocked?: boolean
}>(items: T[], f: FilterState): T[] {
  return items.filter((m) => {
    if (f.types.size && !f.types.has(m.media_type)) return false
    if (f.status.size && !f.status.has(m.transcode_status)) return false
    if (f.onlyEmbargo && !m.not_before_utc) return false
    if (f.onlyBlocked && !m.is_blocked) return false
    return true
  })
}

interface Props {
  open: boolean
  onClose: () => void
  value: FilterState
  onChange: (f: FilterState) => void
  /** Types réellement présents dans la médiathèque, avec leur compte. */
  availableTypes: { key: string; label: string; count: number }[]
  /** Vrai si la liste affichée est partielle (pagination) — on le DIT. */
  partial: boolean
}

function Check({ checked, label, count, onToggle }: {
  checked: boolean; label: string; count?: number; onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      className="flex items-center gap-2.5 w-full px-1 py-1.5 rounded text-sm text-gray-700 hover:text-gray-900 transition-sf"
    >
      <span className={`w-4 h-4 rounded border shrink-0 flex items-center justify-center ${
        checked ? 'bg-accent border-accent' : 'border-gray-400'
      }`}>
        {checked && <span className="block w-2 h-2 bg-white rounded-[2px]" />}
      </span>
      <span className="flex-1 text-left truncate">{label}</span>
      {count != null && <span className="text-xs text-gray-500 tabular-nums">{count}</span>}
    </button>
  )
}

export default function MediaFilters({
  open, onClose, value, onChange, availableTypes, partial,
}: Props) {
  const t = useTranslations('media')
  if (!open) return null

  const toggleIn = (set: Set<string>, key: string) => {
    const next = new Set(set)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  }

  const STATUSES = [
    { key: 'done', label: t('status_done') },
    { key: 'processing', label: t('status_processing') },
    // Décision requise : filtrable, sinon retrouver les médias en attente dans une grosse
    // médiathèque relèverait de la chance — or « il attend, visible et compté » (décision
    // Ed) suppose qu'on puisse les RETROUVER.
    { key: 'awaiting_decision', label: t('status_awaiting_decision') },
    { key: 'error', label: t('status_error') },
  ]

  return (
    <aside data-testid="media-filters" className="w-56 shrink-0 flex flex-col min-h-0 border-l border-white/5 pl-4">
      <div className="flex items-center justify-between shrink-0 mb-3">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">
          <SlidersHorizontal className="w-3.5 h-3.5" />
          {t('filters')}
        </span>
        <div className="flex items-center gap-1">
          {countActive(value) > 0 && (
            <button
              onClick={() => onChange({ ...EMPTY_FILTERS, types: new Set(), status: new Set() })}
              className="text-[11px] text-accent-hover hover:underline"
            >
              {t('filters_clear')}
            </button>
          )}
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700" title={t('filters_hide')}>
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

        {/* ⚠️ Gouttière basse : la bulle d'aide (`DemoTips`) est en position fixe
            `bottom-20 right-5` et RECOUVRE le bas d'un panneau collé au bord droit — les
            derniers filtres deviennent inatteignables, et en mode démo la bulle n'a pas de
            croix pour la fermer. Défaut mesuré par le test (2026-07-31), même famille que
            la bulle qui bloquait le pied des tiroirs le 29/07. */}
      <div className="flex-1 min-h-0 overflow-y-auto space-y-4 pb-40">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('filter_type')}</p>
          {availableTypes.map((ty) => (
            <Check
              key={ty.key}
              checked={value.types.has(ty.key)}
              label={ty.label}
              count={ty.count}
              onToggle={() => onChange({ ...value, types: toggleIn(value.types, ty.key) })}
            />
          ))}
        </div>

        <div>
          <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('filter_state')}</p>
          {STATUSES.map((s) => (
            <Check
              key={s.key}
              checked={value.status.has(s.key)}
              label={s.label}
              onToggle={() => onChange({ ...value, status: toggleIn(value.status, s.key) })}
            />
          ))}
          <Check
            checked={value.onlyEmbargo}
            label={t('filter_embargo')}
            onToggle={() => onChange({ ...value, onlyEmbargo: !value.onlyEmbargo })}
          />
          <Check
            checked={value.onlyBlocked}
            label={t('filter_blocked')}
            onToggle={() => onChange({ ...value, onlyBlocked: !value.onlyBlocked })}
          />
        </div>

        {/* Ne jamais laisser croire à un filtrage exhaustif quand il ne l'est pas. */}
        {partial && countActive(value) > 0 && (
          <p className="text-[11px] text-warning bg-warning/10 border border-warning/25 rounded px-2 py-1.5">
            {t('filters_partial')}
          </p>
        )}
      </div>
    </aside>
  )
}
