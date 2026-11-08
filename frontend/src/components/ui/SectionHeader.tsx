'use client'

import { ChevronDown } from 'lucide-react'

interface SectionHeaderProps {
  title: string
  open: boolean
  onToggle: () => void
  /** Infobulle quand la section est ouverte (« Replier »). */
  collapseLabel?: string
  /** Infobulle quand la section est repliée (« Déplier »). */
  expandLabel?: string
}

/**
 * En-tête de section repliable : chevron + libellé capitales + filet horizontal.
 *
 * Source unique — ce composant était dupliqué à l'identique dans le dashboard
 * CMS et l'accueil du portail. Les deux copies ne différaient que par le
 * NAMESPACE i18n de l'infobulle (`dashboard.section_collapse` vs
 * `section_collapse`), d'où le passage des libellés en props plutôt qu'un `t`
 * imposé : le composant n'a pas à connaître le namespace de son appelant.
 *
 * À utiliser avec `useCollapse` (lib/useCollapse) pour un état persisté.
 */
export default function SectionHeader({
  title,
  open,
  onToggle,
  collapseLabel,
  expandLabel,
}: SectionHeaderProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      title={open ? collapseLabel : expandLabel}
      className="group flex items-center gap-2 w-full text-left"
    >
      <ChevronDown
        className={`w-4 h-4 text-gray-500 group-hover:text-gray-800 transition-sf ${open ? '' : '-rotate-90'}`}
      />
      <span className="text-[11px] uppercase tracking-wide text-gray-400 font-semibold group-hover:text-gray-700">
        {title}
      </span>
      <span className="flex-1 h-px bg-white/5" />
    </button>
  )
}
