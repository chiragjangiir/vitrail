'use client'

import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { TagNamespace, TagValue } from '@/types/api'

/** Hook partagé : taxonomie de tags de l'org (namespaces + valeurs). */
export function useTagNamespaces() {
  return useQuery<TagNamespace[]>({
    queryKey: ['tag-namespaces'],
    queryFn: () => api.get<TagNamespace[]>('/tags/namespaces').then((r) => r.data),
    staleTime: 60_000,
  })
}

/** Index id_tag → {value, namespace} pour le rendu des badges. */
export function indexTags(namespaces: TagNamespace[]) {
  const map = new Map<number, { value: TagValue; ns: TagNamespace }>()
  for (const ns of namespaces) for (const v of ns.values) map.set(v.id_tag, { value: v, ns })
  return map
}

function badgeStyle(color: string | null): React.CSSProperties {
  if (!color) return {}
  return { backgroundColor: `${color}1A`, color, borderColor: `${color}55` }
}

/** Badges colorés pour une liste d'id_tags (groupés implicitement par leur couleur de namespace). */
export function TagBadges({
  ids, namespaces, max,
}: {
  ids: number[]
  namespaces: TagNamespace[]
  max?: number
}) {
  const idx = indexTags(namespaces)
  const resolved = ids.map((id) => idx.get(id)).filter(Boolean) as { value: TagValue; ns: TagNamespace }[]
  if (resolved.length === 0) return null
  const shown = max ? resolved.slice(0, max) : resolved
  const extra = resolved.length - shown.length
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map(({ value }) => (
        <span
          key={value.id_tag}
          className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border bg-gray-100 text-gray-600 border-gray-200"
          style={badgeStyle(value.color)}
          title={value.label ?? value.tag_value}
        >
          {value.label ?? value.tag_value}
        </span>
      ))}
      {extra > 0 && <span className="text-[10px] text-gray-400">+{extra}</span>}
    </div>
  )
}

/** Sélecteur multi-tags groupé par namespace (médias, filtres player, items). */
export function TagPicker({
  namespaces, selected, onToggle, emptyLabel,
}: {
  namespaces: TagNamespace[]
  selected: Set<number>
  onToggle: (id: number) => void
  emptyLabel?: string
}) {
  const active = namespaces.filter((ns) => ns.is_active && ns.values.length > 0)
  if (active.length === 0) {
    return <p className="text-xs text-gray-400">{emptyLabel ?? 'No tag namespaces configured.'}</p>
  }
  return (
    <div className="space-y-3">
      {active.map((ns) => (
        <div key={ns.id_namespace}>
          <p className="text-[11px] font-medium text-gray-500 mb-1">{ns.label ?? ns.namespace_key}</p>
          <div className="flex flex-wrap gap-1.5">
            {ns.values.map((v) => {
              const on = selected.has(v.id_tag)
              return (
                <button
                  key={v.id_tag}
                  type="button"
                  onClick={() => onToggle(v.id_tag)}
                  className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium border transition-sf ${
                    on ? 'border-transparent text-white' : 'bg-surface text-gray-600 border-gray-300 hover:bg-gray-50'
                  }`}
                  style={on && v.color ? { backgroundColor: v.color } : undefined}
                >
                  {v.label ?? v.tag_value}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
