'use client'

import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

/**
 * Section repliable (utilisée dans le drawer player : blocs de config).
 * En-tête cliquable = icône + titre + pastille colorée optionnelle (si configuré/actif) + chevron.
 * Fermée par défaut (gain de place) ; `defaultOpen` pour l'ouvrir d'entrée.
 */
export default function Collapsible({
  title,
  icon,
  active = false,
  activeColor = 'bg-accent',
  defaultOpen = false,
  className = '',
  children,
}: {
  title: string
  icon?: React.ReactNode
  active?: boolean
  activeColor?: string
  defaultOpen?: boolean
  className?: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`border-t border-gray-100 pt-3 ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 text-left group"
      >
        {icon && <span className="text-gray-400 shrink-0">{icon}</span>}
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide flex-1 group-hover:text-gray-700 transition-sf">
          {title}
        </span>
        {active && <span className={`w-2 h-2 rounded-full ${activeColor} shrink-0`} />}
        <ChevronDown
          className={`w-4 h-4 text-gray-400 shrink-0 transition-transform ${open ? '' : '-rotate-90'}`}
        />
      </button>
      {open && <div className="mt-3 space-y-4">{children}</div>}
    </div>
  )
}
