'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import api from '@/lib/api'
import type { TagNamespace, TagValue } from '@/types/api'
import { indexTags, useTagNamespaces } from '@/components/tags/TagControls'

function tagBadgeStyle(color: string | null): React.CSSProperties {
  if (!color) return {}
  return { backgroundColor: `${color}1A`, color, borderColor: `${color}55` }
}

/** Un namespace s'applique au média si applies_to est vide (= tous) ou contient son type. */
function appliesToType(ns: TagNamespace, mediaType: string) {
  return !ns.applies_to || ns.applies_to.length === 0 || ns.applies_to.includes(mediaType)
}

/** Éditeur de tags (§XVII) réutilisable pour n'importe quel média (id + type). Utilisé par le
 *  drawer média générique ET le drawer Page Web (url_display = média → tags natifs).
 *  Endpoints `GET/PUT /media/{id}/tags`, dropdown filtré par type, pastilles. */
export default function MediaTagsEditor({ idMedia, mediaType }: { idMedia: number; mediaType: string }) {
  const t = useTranslations('media')
  const qc = useQueryClient()
  const { data: namespaces = [] } = useTagNamespaces()
  const { data: current = [] } = useQuery<number[]>({
    queryKey: ['media-tags', idMedia],
    queryFn: () => api.get<number[]>(`/media/${idMedia}/tags`).then((r) => r.data),
  })
  const [sel, setSel] = useState<Set<number> | null>(null)
  const selected = sel ?? new Set(current)

  const save = useMutation({
    mutationFn: (ids: number[]) => api.put(`/media/${idMedia}/tags`, { id_tags: ids }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['media-tags', idMedia] })
      qc.invalidateQueries({ queryKey: ['media'] })
      setSel(null)
    },
  })

  const add = (id: number) => { const next = new Set(selected); next.add(id); setSel(next) }
  const remove = (id: number) => { const next = new Set(selected); next.delete(id); setSel(next) }
  const dirty = sel !== null && (sel.size !== current.length || Array.from(sel).some((id) => !current.includes(id)))

  const idx = indexTags(namespaces)
  const applicable = namespaces.filter(
    (ns) => ns.is_active && ns.values.length > 0 && appliesToType(ns, mediaType),
  )
  const selectedResolved = Array.from(selected)
    .map((id) => idx.get(id))
    .filter(Boolean) as { value: TagValue; ns: TagNamespace }[]

  return (
    <div className="space-y-3" data-write-perm="media:edit">
      {selectedResolved.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {selectedResolved.map(({ value }) => (
            <span
              key={value.id_tag}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border bg-gray-100 text-gray-600 border-gray-200"
              style={tagBadgeStyle(value.color)}
            >
              {value.label ?? value.tag_value}
              <button type="button" data-write-action onClick={() => remove(value.id_tag)} className="hover:opacity-70" aria-label={t('tags_clear')}>
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-400">{t('tags_none_selected')}</p>
      )}

      {applicable.length > 0 ? (
        <select
          value=""
          onChange={(e) => { const id = Number(e.target.value); if (id) add(id) }}
          className="w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
        >
          <option value="">{t('tags_add_placeholder')}</option>
          {applicable.map((ns) => {
            const opts = ns.values.filter((v) => !selected.has(v.id_tag))
            if (opts.length === 0) return null
            return (
              <optgroup key={ns.id_namespace} label={ns.label ?? ns.namespace_key}>
                {opts.map((v) => (
                  <option key={v.id_tag} value={v.id_tag}>{v.label ?? v.tag_value}</option>
                ))}
              </optgroup>
            )
          })}
        </select>
      ) : (
        <p className="text-xs text-gray-400">{t('tags_empty')}</p>
      )}

      {dirty && (
        <button
          data-write-action
          onClick={() => save.mutate(Array.from(selected))}
          disabled={save.isPending}
          className="w-full py-1.5 bg-accent text-white text-sm rounded-md hover:bg-accent/90 disabled:opacity-50"
        >
          {save.isPending ? t('tags_saving') : t('tags_save')}
        </button>
      )}
    </div>
  )
}
