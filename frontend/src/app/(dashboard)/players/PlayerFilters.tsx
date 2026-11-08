'use client'

import { useTranslations } from 'next-intl'
import { SlidersHorizontal, X } from 'lucide-react'
import type { PlayerRead } from '@/types/api'

/**
 * Panneau de filtres latéral du parc (demande d'Ed, audit du menu Players 2026-07-31 —
 * même patron que `MediaFilters`, livré à l'audit du menu Média).
 *
 * Il ne remplace pas les onglets (Tous / Groupes / Sync LAN / Alertes), qui sont des VUES.
 * Il sert au filtrage COMBINÉ à l'intérieur d'une vue : « les écrans Linux du site Lyon qui
 * ne sont pas en ligne » — ce qu'une barre de recherche textuelle ne sait pas exprimer.
 *
 * ✅ Contrairement à la médiathèque, le filtrage est **exhaustif** : `GET /players/` rend
 * tout le parc visible d'un coup (pas de pagination serveur), donc filtrer côté client ne
 * cache rien. Pas de bandeau « résultats partiels » à afficher ici — et si la liste devenait
 * paginée un jour, il faudrait en ajouter un (leçon du drawer « Ajouter un média »).
 */

export interface PlayerFilterState {
  status: Set<string>     // online | warning | offline | critical | maintenance
  os: Set<string>
  sites: Set<number>
  onlyLanSync: boolean
  onlyAlerts: boolean
}

export const EMPTY_PLAYER_FILTERS: PlayerFilterState = {
  status: new Set(), os: new Set(), sites: new Set(),
  onlyLanSync: false, onlyAlerts: false,
}

export function countActivePlayerFilters(f: PlayerFilterState): number {
  return f.status.size + f.os.size + f.sites.size
    + (f.onlyLanSync ? 1 : 0) + (f.onlyAlerts ? 1 : 0)
}

export function applyPlayerFilters(items: PlayerRead[], f: PlayerFilterState): PlayerRead[] {
  return items.filter((p) => {
    if (f.status.size && !f.status.has(p.status)) return false
    if (f.os.size && !f.os.has(p.player_os ?? '')) return false
    if (f.sites.size && (p.id_site == null || !f.sites.has(p.id_site))) return false
    if (f.onlyLanSync && !p.display_config?.lan_sync_enabled) return false
    // « Avec alerte » = ce que la vue Alertes retient, exprimable ici en combinaison.
    if (f.onlyAlerts && !['warning', 'critical', 'offline'].includes(p.status)) return false
    return true
  })
}

interface Props {
  open: boolean
  onClose: () => void
  value: PlayerFilterState
  onChange: (f: PlayerFilterState) => void
  /** Parc COMPLET (pas la liste filtrée) : les compteurs doivent rester stables quand on
   *  coche — sinon une option disparaît au moment où on la sélectionne. */
  players: PlayerRead[]
  sites: { id_site: number; site_name: string }[]
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

export default function PlayerFilters({
  open, onClose, value, onChange, players, sites,
}: Props) {
  const t = useTranslations('players')
  const tm = useTranslations('media')
  if (!open) return null

  const toggleStr = (set: Set<string>, key: string) => {
    const next = new Set(set)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  }
  const toggleNum = (set: Set<number>, key: number) => {
    const next = new Set(set)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  }

  const countBy = <K,>(pick: (p: PlayerRead) => K | null) => {
    const m = new Map<K, number>()
    players.forEach((p) => {
      const k = pick(p)
      if (k !== null && k !== undefined) m.set(k, (m.get(k) ?? 0) + 1)
    })
    return m
  }
  const byStatus = countBy((p) => p.status)
  const byOs = countBy((p) => p.player_os || null)
  const bySite = countBy((p) => p.id_site)

  // Le type de `status` est une union : on la reprend telle quelle plutôt que des chaînes
  // libres, sinon la carte de comptage (typée par le modèle) refuse la lecture.
  const STATUSES = (['online', 'warning', 'offline', 'critical', 'maintenance'] as const)
    .filter((s) => byStatus.has(s))

  return (
    <aside
      data-testid="player-filters"
      className="w-56 shrink-0 flex flex-col min-h-0 border-l border-white/5 pl-4"
    >
      <div className="flex items-center justify-between shrink-0 mb-3">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">
          <SlidersHorizontal className="w-3.5 h-3.5" />
          {tm('filters')}
        </span>
        <div className="flex items-center gap-1">
          {countActivePlayerFilters(value) > 0 && (
            <button
              onClick={() => onChange({
                status: new Set(), os: new Set(), sites: new Set(),
                onlyLanSync: false, onlyAlerts: false,
              })}
              className="text-[11px] text-accent-hover hover:underline"
            >
              {tm('filters_clear')}
            </button>
          )}
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700" title={tm('filters_hide')}>
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
          <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('filter_status')}</p>
          {STATUSES.map((s) => (
            <Check
              key={s}
              checked={value.status.has(s)}
              label={t(`status_${s}`)}
              count={byStatus.get(s)}
              onToggle={() => onChange({ ...value, status: toggleStr(value.status, s) })}
            />
          ))}
        </div>

        {byOs.size > 0 && (
          <div>
            <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('filter_os')}</p>
            {[...byOs.keys()].sort().map((os) => (
              <Check
                key={os}
                checked={value.os.has(os)}
                label={os}
                count={byOs.get(os)}
                onToggle={() => onChange({ ...value, os: toggleStr(value.os, os) })}
              />
            ))}
          </div>
        )}

        {sites.length > 0 && (
          <div>
            <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('filter_site')}</p>
            {sites.map((s) => (
              <Check
                key={s.id_site}
                checked={value.sites.has(s.id_site)}
                label={s.site_name}
                count={bySite.get(s.id_site) ?? 0}
                onToggle={() => onChange({ ...value, sites: toggleNum(value.sites, s.id_site) })}
              />
            ))}
          </div>
        )}

        <div>
          <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{t('filter_other')}</p>
          <Check
            checked={value.onlyLanSync}
            label={t('filter_lansync')}
            onToggle={() => onChange({ ...value, onlyLanSync: !value.onlyLanSync })}
          />
          <Check
            checked={value.onlyAlerts}
            label={t('filter_alerts')}
            onToggle={() => onChange({ ...value, onlyAlerts: !value.onlyAlerts })}
          />
        </div>
      </div>
    </aside>
  )
}
