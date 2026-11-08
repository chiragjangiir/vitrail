'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { LayoutTemplate, Trash2 } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import SearchInput from '@/components/ui/SearchInput'
import api from '@/lib/api'
import NodeSelect, { GovernedBadge } from '@/components/governance/NodeSelect'
import { useCreateShortcut } from '@/lib/useCreateShortcut'
import { useSearchPrefill } from '@/lib/useSearchPrefill'
import type { TemplateRead } from '@/types/api'

type LayoutType = 'full' | 'split_h' | 'split_v' | 'sidebar_r'

const LAYOUTS: { value: LayoutType; zones: TemplateRead['layout']['zones'] }[] = [
  {
    value: 'full',
    zones: [{ index: 0, x: 0, y: 0, w: 1920, h: 1080, label: 'Main' }],
  },
  {
    value: 'split_h',
    zones: [
      { index: 0, x: 0, y: 0, w: 1920, h: 540, label: 'Top' },
      { index: 1, x: 0, y: 540, w: 1920, h: 540, label: 'Bottom' },
    ],
  },
  {
    value: 'split_v',
    zones: [
      { index: 0, x: 0, y: 0, w: 960, h: 1080, label: 'Left' },
      { index: 1, x: 960, y: 0, w: 960, h: 1080, label: 'Right' },
    ],
  },
  {
    value: 'sidebar_r',
    zones: [
      { index: 0, x: 0, y: 0, w: 1440, h: 1080, label: 'Main' },
      { index: 1, x: 1440, y: 0, w: 480, h: 1080, label: 'Sidebar' },
    ],
  },
]

const ZONE_COLORS = ['bg-accent/20 border-accent', 'bg-emerald-400/20 border-emerald-400 dark:border-emerald-500/50']

// Aperçu au RATIO réel du canvas (FHD/4K/portrait/LED) → hauteur fixe, largeur dérivée.
function CanvasPreview({ layout, height = 120 }: { layout: TemplateRead['layout']; height?: number }) {
  const cw = layout.canvas_width || 1920
  const ch = layout.canvas_height || 1080
  return (
    <div className="flex justify-center w-full" style={{ height }}>
      <div
        className="relative bg-canvas-dark rounded overflow-hidden h-full max-w-full"
        style={{ aspectRatio: `${cw} / ${ch}` }}
      >
        {layout.zones.map((zone) => (
          <div
            key={zone.index}
            className={`absolute border ${ZONE_COLORS[zone.index % ZONE_COLORS.length]} flex items-center justify-center`}
            style={{
              left: `${(zone.x / cw) * 100}%`,
              top: `${(zone.y / ch) * 100}%`,
              width: `${(zone.w / cw) * 100}%`,
              height: `${(zone.h / ch) * 100}%`,
            }}
          >
            <span className="text-[9px] text-white/60">{zone.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function TemplatesPage() {
  const t = useTranslations()
  const router = useRouter()
  const qc = useQueryClient()
  const [drawerOpen, setDrawerOpen] = useState(false)
  useCreateShortcut(() => setDrawerOpen(true))
  const [search, setSearch] = useState('')
  useSearchPrefill(setSearch)
  const [name, setName] = useState('')
  const [layoutType, setLayoutType] = useState<LayoutType>('full')
  const [govNode, setGovNode] = useState<number | null>(null)

  const { data: templates = [], isLoading } = useQuery<TemplateRead[]>({
    queryKey: ['templates'],
    queryFn: () => api.get<TemplateRead[]>('/templates').then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: () => {
      const preset = LAYOUTS.find((l) => l.value === layoutType)!
      return api.post<TemplateRead>('/templates', {
        template_name: name,
        layout: { layout_type: layoutType, zones: preset.zones },
        // Gouvernance §XVIII (migr 0112) : nœud propriétaire — null = template d'org,
        // partagé comme avant. Rattaché, seul l'admin du nœud (ou d'un ancêtre) l'édite.
        id_governance_node: govNode,
      })
    },
    onSuccess: ({ data }) => {
      qc.invalidateQueries({ queryKey: ['templates'] })
      setDrawerOpen(false)
      setName('')
      setGovNode(null)
      router.push(`/templates/${data.id_template}/edit`)
    },
  })

  // « Quand on efface, on efface » (décision d'Ed, 2026-07-28) : la suppression est
  // désormais RÉELLE côté serveur. On ne peut donc plus la demander à l'aveugle — on
  // montre d'abord ce qu'elle emporte, et on ne force qu'après une confirmation NOMMÉE.
  const deleteMutation = useMutation({
    mutationFn: ({ id, force }: { id: number; force?: boolean }) =>
      api.delete(`/templates/${id}${force ? '?force=true' : ''}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['templates'] }),
  })

  async function askDelete(tmpl: TemplateRead) {
    let impact: { playlists: { playlist_name: string }[] } | null = null
    try {
      impact = (await api.get(`/templates/${tmpl.id_template}/deletion-impact`)).data
    } catch {
      // L'impact est un CONFORT : s'il échoue, on retombe sur la confirmation simple
      // plutôt que d'empêcher une suppression légitime.
    }
    const used = impact?.playlists ?? []
    const message = used.length
      ? t('templates.delete_confirm_used', {
          name: tmpl.template_name,
          playlists: used.map((p) => p.playlist_name).join(', '),
        })
      : t('templates.delete_confirm_final', { name: tmpl.template_name })
    if (!confirm(message)) return
    deleteMutation.mutate({ id: tmpl.id_template, force: used.length > 0 })
  }

  const layoutLabel = (type: string) => {
    const map: Record<string, string> = {
      full: t('templates.layout_full'),
      split_h: t('templates.layout_split_h'),
      split_v: t('templates.layout_split_v'),
      sidebar_r: t('templates.layout_sidebar_r'),
    }
    return map[type] ?? type
  }

  return (
    <>
      <Topbar title={t('templates.title')}>
        <Can perm="templates:create">
          <Button size="sm" onClick={() => setDrawerOpen(true)}>
            {t('templates.new')}
          </Button>
        </Can>
      </Topbar>

      {/* Page verrouillée au viewport : recherche fixe, seules les vignettes défilent. */}
      <main className="flex-1 flex flex-col min-h-0 px-6">
          {isLoading ? (
            <div className="flex justify-center py-16">
              <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : templates.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3 text-gray-400">
              <LayoutTemplate className="w-10 h-10" />
              <p className="text-sm">{t('templates.no_templates')}</p>
            </div>
          ) : (
            <>
              <div className="shrink-0 pt-8 pb-4">
                <SearchInput
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('common.search')}
                />
              </div>
            {/* Conteneur de défilement SÉPARÉ de la grille : mélanger `grid` et
                `overflow-y-auto` sur le même nœud empêchait le défilement.
                Colonnes à largeur FIXE (300px) et non `minmax(300px,1fr)` : le `1fr`
                étirait les vignettes au lieu de garder leur taille et de changer
                seulement leur nombre par ligne (retour Ed 2026-07-20). */}
            <div className="flex-1 min-h-0 overflow-y-auto pb-8">
            <div className="grid content-start justify-start grid-cols-[repeat(auto-fill,300px)] gap-4">
              {templates.filter((tmpl) => !search || tmpl.template_name.toLowerCase().includes(search.toLowerCase())).map((tmpl) => (
                <div
                  key={tmpl.id_template}
                  className="bg-surface rounded-lg border border-gray-200 overflow-hidden hover:border-accent transition-sf cursor-pointer shadow-sf-card"
                  onClick={() => router.push(`/templates/${tmpl.id_template}/edit`)}
                >
                  <div className="p-4 flex justify-center bg-gray-50 border-b border-gray-100">
                    <CanvasPreview layout={tmpl.layout} />
                  </div>
                  <div className="p-4 flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{tmpl.template_name}</p>
                      {/* Pastille « gouverné » : un template national doit se distinguer
                          d'un template d'organisation avant qu'on essaie de l'éditer. */}
                      <GovernedBadge idNode={tmpl.id_governance_node} />
                      <p className="text-xs text-gray-400 mt-0.5">
                        {layoutLabel(tmpl.layout.layout_type)}
                        <span className="mx-1 text-gray-300">·</span>
                        {(tmpl.layout.canvas_width || 1920)}×{(tmpl.layout.canvas_height || 1080)}
                      </p>
                    </div>
                    <Can perm="templates:delete">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          void askDelete(tmpl)
                        }}
                        className="text-gray-300 hover:text-danger transition-sf shrink-0"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </Can>
                  </div>
                </div>
              ))}
            </div>
            </div>
            </>
          )}
      </main>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title={t('templates.new')}>
        <div className="space-y-5" data-write-perm="templates:create">
          <Input
            label={t('templates.col_name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />

          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-700">{t('templates.col_layout')}</p>
            <div className="grid grid-cols-2 gap-2">
              {LAYOUTS.map((l) => (
                <div
                  key={l.value}
                  role="button"
                  tabIndex={0}
                  onClick={() => setLayoutType(l.value)}
                  onKeyDown={(e) => e.key === 'Enter' && setLayoutType(l.value)}
                  className={`p-3 rounded-lg border text-xs font-medium transition-sf flex flex-col items-center gap-2 cursor-pointer ${
                    layoutType === l.value
                      ? 'border-accent bg-accent/5 text-accent'
                      : 'border-gray-200 text-gray-600 hover:border-accent hover:text-accent'
                  }`}
                >
                  <CanvasPreview layout={{ layout_type: l.value, zones: l.zones }} height={56} />
                  {layoutLabel(l.value)}
                </div>
              ))}
            </div>
          </div>

          {/* Gouvernance §XVIII : masqué si l'org n'a aucun nœud. Un template rattaché
              n'est plus modifiable par les autres branches (défaut N3 de l'audit). */}
          <NodeSelect value={govNode} onChange={setGovNode} />

          <Button
            data-write-action
            onClick={() => createMutation.mutate()}
            loading={createMutation.isPending}
            disabled={!name.trim()}
            className="w-full"
          >
            {t('common.create')}
          </Button>
        </div>
      </Drawer>
    </>
  )
}
