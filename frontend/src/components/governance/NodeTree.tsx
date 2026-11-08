'use client'

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { ChevronDown, ChevronRight, Network } from 'lucide-react'
import MarqueeText from '@/components/ui/MarqueeText'
import type { GovernanceNode } from '@/types/api'

/**
 * Arbre de gouvernance — colonne de gauche de la mise en page A (validée Ed 2026-07-26).
 *
 * Défile pour son compte : la page entière est verrouillée au viewport, seul le contenu
 * de chaque colonne bouge. Un nœud sélectionné force l'ouverture de ses ancêtres, sinon
 * une sélection venue de l'URL pointerait sur une ligne invisible.
 */
export default function NodeTree({
  nodes, selectedId, onSelect,
}: {
  nodes: GovernanceNode[]
  selectedId: number | null
  onSelect: (id: number) => void
}) {
  const t = useTranslations('governance')
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())

  const childrenOf = useMemo(() => {
    const map = new Map<number | null, GovernanceNode[]>()
    for (const n of nodes) {
      const k = n.parent_id
      if (!map.has(k)) map.set(k, [])
      map.get(k)!.push(n)
    }
    return map
  }, [nodes])

  // Ouvert PAR DÉFAUT (on replie explicitement) : à la première visite l'arbre montre la
  // hiérarchie, qui est justement ce que le module raconte. Un arbre tout fermé donnait
  // l'impression d'une organisation à un seul niveau.
  const isOpen = (id: number) => !collapsed.has(id)
  const toggle = (id: number) =>
    setCollapsed((s) => {
      const next = new Set(s)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const render = (parent: number | null, depth: number): React.ReactNode =>
    (childrenOf.get(parent) ?? []).map((n) => {
      const kids = childrenOf.get(n.id_node) ?? []
      const open = isOpen(n.id_node)
      return (
        <div key={n.id_node}>
          <div
            role="button"
            tabIndex={0}
            onClick={() => onSelect(n.id_node)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelect(n.id_node) }}
            data-node-id={n.id_node}
            className={`flex items-center gap-1 px-2 py-1.5 rounded cursor-pointer transition-sf ${
              selectedId === n.id_node ? 'bg-accent/10 text-accent' : 'hover:bg-gray-50 text-gray-700'
            }`}
            style={{ paddingLeft: `${depth * 14 + 8}px` }}
          >
            {kids.length > 0 ? (
              <button
                onClick={(e) => { e.stopPropagation(); toggle(n.id_node) }}
                className="shrink-0"
                aria-label={open ? t('collapse') : t('expand')}
              >
                {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
              </button>
            ) : (
              <span className="w-3.5 shrink-0" />
            )}
            <Network className="w-3.5 h-3.5 shrink-0 opacity-60" />
            <MarqueeText text={n.node_name} className="text-sm flex-1 min-w-0" />
            {kids.length > 0 && (
              <span className="text-[10px] text-gray-400 shrink-0" title={t('child_count')}>
                {kids.length}
              </span>
            )}
          </div>
          {open && render(n.id_node, depth + 1)}
        </div>
      )
    })

  return <div className="py-2 pr-1">{render(null, 0)}</div>
}
