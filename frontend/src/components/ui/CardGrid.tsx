'use client'

import { clsx } from 'clsx'

/**
 * Grille de cartes responsive partagée (playlists, events, players…).
 * Par défaut : 1 colonne mobile → 2 (sm) → 3 (lg). Style aligné sur /audio-baskets.
 *
 * `minItemWidth` (px) : passe en grille auto-fill `minmax(minItemWidth, 1fr)` →
 * le nombre de colonnes s'adapte automatiquement à la largeur disponible
 * (utile pour les cartes compactes, ex. players : ~4/ligne en standard, plus sur écran large).
 *
 * `maxItemWidth` (px) : borne la largeur d'une piste au lieu du `1fr` qui étire. Les cartes
 * gardent alors une largeur LISIBLE et la grille se CENTRE dans l'espace restant — c'est ce
 * qu'il faut pour des panneaux de formulaire (retour Ed 2026-07-26 : en 34" ultrawide et en 4K,
 * une colonne unique étirée laissait « un grand vide »). Sans cette borne, passer en grille
 * réglerait le vide en fabriquant des cartes de 2 000 px de large.
 */
export function CardGrid({
  children, className, minItemWidth, maxItemWidth,
}: {
  children: React.ReactNode
  className?: string
  minItemWidth?: number
  maxItemWidth?: number
}) {
  if (minItemWidth) {
    const track = maxItemWidth ? `${maxItemWidth}px` : '1fr'
    // ⚠️ `min(100%, …)` et pas `minItemWidth` nu : une piste dont le MINIMUM dépasse le
    // conteneur déborde — et avec `justify-center` elle déborde des DEUX côtés, si bien que
    // la carte passe sous la colonne voisine. Vu sur la page Gouvernance en 1280 px : les
    // panneaux glissaient sous l'arbre et devenaient inatteignables. `min(100%, …)` laisse la
    // piste rétrécir quand il n'y a pas la place, sans rien changer aux cas larges.
    return (
      <div
        className={clsx('grid gap-4', maxItemWidth && 'justify-center', className)}
        style={{
          gridTemplateColumns:
            `repeat(auto-fill, minmax(min(100%, ${minItemWidth}px), ${track}))`,
        }}
      >
        {children}
      </div>
    )
  }
  return (
    <div className={clsx('grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4', className)}>
      {children}
    </div>
  )
}

/**
 * Coquille de carte d'entité avec zones optionnelles :
 *  - `media`    : visuel 16:9 en haut (screenshot player, vignette…)
 *  - `title` / `subtitle`
 *  - `actions`  : boutons en haut à droite (le caller gère stopPropagation)
 *  - `badges`   : ligne de pastilles sous le titre
 *  - `footer`   : ligne de méta en bas
 * `onClick` rend la carte cliquable.
 */
export function EntityCard({
  onClick, media, title, subtitle, actions, badges, footer, titleTitle,
}: {
  onClick?: () => void
  media?: React.ReactNode
  title: React.ReactNode
  titleTitle?: string
  subtitle?: React.ReactNode
  actions?: React.ReactNode
  badges?: React.ReactNode
  footer?: React.ReactNode
}) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        'bg-surface rounded-xl border border-white/5 shadow-sf-card overflow-hidden hover:border-accent-hover/40 hover:shadow-sf-card-hover transition-sf',
        onClick && 'cursor-pointer',
      )}
    >
      {media && <div className="aspect-video bg-gray-50 relative overflow-hidden">{media}</div>}
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="min-w-0">
            <p className="font-medium text-gray-900 text-sm truncate" title={titleTitle}>{title}</p>
            {subtitle && <p className="text-xs text-gray-400 truncate mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-1 shrink-0">{actions}</div>}
        </div>
        {badges && <div className="flex items-center gap-1.5 flex-wrap mb-2">{badges}</div>}
        {footer && <div className="text-xs text-gray-500">{footer}</div>}
      </div>
    </div>
  )
}
