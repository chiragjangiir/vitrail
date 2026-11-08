'use client'

import { clsx } from 'clsx'
import { Search } from 'lucide-react'
import type { InputHTMLAttributes } from 'react'

interface SearchInputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Classes du CONTENEUR (largeur, marges). L'input lui-même reste standard. */
  wrapperClassName?: string
}

/**
 * Barre de recherche canonique de l'UI.
 *
 * **Largeur : fluide, plafonnée à `max-w-md` (28rem)** — décision Ed 2026-07-20.
 * Elle suit la largeur disponible sur écran étroit et en FHD, mais ne s'étire
 * jamais absurdement sur un ultrawide 3440.
 *
 * Avant ce composant, sept pages utilisaient six stratégies de largeur
 * différentes (`w-64`, `max-w-sm`, `max-w-xs`, `flex-1 min-w-[220px]`, et trois
 * `mb-4` pleine largeur manifestement involontaires). Toute nouvelle barre de
 * recherche doit passer par ici plutôt que de recopier un `<input>` + icône.
 */
export default function SearchInput({ wrapperClassName, className, ...props }: SearchInputProps) {
  return (
    <div className={clsx('relative w-full max-w-md', wrapperClassName)}>
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
      <input
        type="search"
        {...props}
        className={clsx(
          'w-full pl-9 pr-3 py-2 text-sm rounded-lg border bg-surface text-gray-900 placeholder-gray-400',
          'border-gray-200 hover:border-gray-400 transition-sf',
          'focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent',
          className
        )}
      />
    </div>
  )
}
