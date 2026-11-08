'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Globe, Plus, Search, Trash2 } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import api from '@/lib/api'
import type { UrlDisplayRead } from '@/types/api'
import UrlDisplayDrawer from '../media/components/UrlDisplayDrawer'
import DeleteMediaDialog from '../media/components/DeleteMediaDialog'

export default function UrlDisplayPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [drawer, setDrawer] = useState<{ open: boolean; editId: number | null }>({ open: false, editId: null })
  const [del, setDel] = useState<{ id: number; name: string } | null>(null)

  const { data: items = [], isLoading } = useQuery<UrlDisplayRead[]>({
    queryKey: ['url-display'],
    queryFn: () => api.get<UrlDisplayRead[]>('/url-display').then((r) => r.data),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/url-display/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['url-display'] })
      qc.invalidateQueries({ queryKey: ['media'] })  // url_display = média → médiathèque
      setDel(null)
    },
  })

  const filtered = items.filter(
    (it) => !search ||
      it.name.toLowerCase().includes(search.toLowerCase()) ||
      it.url.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <>
      <Topbar title={t('url_display.title')}>
        <Can perm="media:create">
          <Button size="sm" onClick={() => setDrawer({ open: true, editId: null })}>
            <Plus className="w-4 h-4 mr-1" />{t('url_display.new')}
          </Button>
        </Can>
      </Topbar>

      <main className="flex-1 overflow-y-auto">
        <div className="px-6 py-8 space-y-6">
          <p className="text-sm text-gray-500">{t('url_display.intro')}</p>

          <div className="relative max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <input
              type="search" value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder={t('common.search')}
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
            />
          </div>

          {isLoading ? (
            <p className="text-sm text-gray-400">{t('common.loading')}</p>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400">
              <Globe className="w-10 h-10" />
              <p className="text-sm">{t('url_display.empty')}</p>
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
              {filtered.map((it) => (
                <div
                  key={it.id_media}
                  role="button" tabIndex={0}
                  onClick={() => setDrawer({ open: true, editId: it.id_media })}
                  onKeyDown={(e) => { if (e.key === 'Enter') setDrawer({ open: true, editId: it.id_media }) }}
                  className="group relative bg-surface border border-gray-200 rounded-lg p-4 cursor-pointer transition-sf hover:border-accent shadow-sf-card"
                >
                  <Can perm="media:delete">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setDel({ id: it.id_media, name: it.name }) }}
                      title={t('common.delete')}
                      className="absolute top-2 right-2 p-1.5 rounded text-gray-300 opacity-0 group-hover:opacity-100 hover:text-danger hover:bg-gray-50 transition-sf"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </Can>
                  <div className="flex items-center gap-2 min-w-0 pr-6">
                    <Globe className="w-4 h-4 text-accent shrink-0" />
                    <span className="text-sm font-medium text-gray-900 truncate" title={it.name}>{it.name}</span>
                  </div>
                  <p className="text-xs text-gray-400 truncate mt-1" title={it.url}>{it.url}</p>
                  {it.config.refresh_interval_s > 0 && (
                    <p className="text-[11px] text-gray-500 mt-2">↻ {it.config.refresh_interval_s}s</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      <UrlDisplayDrawer
        open={drawer.open}
        editId={drawer.editId}
        onClose={() => setDrawer({ open: false, editId: null })}
      />

      <Drawer open={del !== null} onClose={() => setDel(null)} title={t('media.delete_title')}>
        {del && (
          <DeleteMediaDialog
            name={del.name}
            impactUrl={`/url-display/${del.id}/deletion-impact`}
            queryKey={['url-display-deletion-impact', del.id]}
            isPending={deleteMutation.isPending}
            onConfirm={() => deleteMutation.mutate(del.id)}
            onCancel={() => setDel(null)}
          />
        )}
      </Drawer>
    </>
  )
}
