'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import NumberField from '@/components/ui/NumberField'
import api from '@/lib/api'
import { isDemoBlocked } from '@/lib/demo'
import type { UrlDisplayConfig, UrlDisplayRead } from '@/types/api'
import MediaTagsEditor from './MediaTagsEditor'
import DeleteMediaDialog from './DeleteMediaDialog'
import QuarantineSection from './QuarantineSection'

const DEFAULT_CONFIG: UrlDisplayConfig = {
  render_mode: 'webview',
  refresh_interval_s: 0,
  zoom: 1,
  scroll_mode: 'none',
  scroll_speed_px_s: 50,
  interaction_blocked: true,
  custom_css: '',
  hide_selectors: [],
  reachability_enabled: true,
  reachability_timeout_s: 8,
}

/** Drawer de création / édition d'une « Page Web » (url_display = média sans fichier).
 *  editId=null → création ; editId=<id> → édition (l'item est rechargé). */
export default function UrlDisplayDrawer({
  open, editId, onClose,
}: { open: boolean; editId: number | null; onClose: () => void }) {
  const t = useTranslations()
  const qc = useQueryClient()

  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [config, setConfig] = useState<UrlDisplayConfig>(DEFAULT_CONFIG)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [mutateError, setMutateError] = useState<string | null>(null)
  const [showDelete, setShowDelete] = useState(false)

  const { data: item } = useQuery<UrlDisplayRead>({
    queryKey: ['url-display', editId],
    queryFn: () => api.get<UrlDisplayRead>(`/url-display/${editId}`).then((r) => r.data),
    enabled: open && editId !== null,
  })

  useEffect(() => {
    if (!open) return
    setOptionsOpen(false); setMutateError(null); setShowDelete(false)
    if (editId === null) { setName(''); setUrl(''); setConfig(DEFAULT_CONFIG) }
    else if (item) { setName(item.name); setUrl(item.url); setConfig({ ...DEFAULT_CONFIG, ...item.config }) }
  }, [open, editId, item])

  function setCfg<K extends keyof UrlDisplayConfig>(k: K, v: UrlDisplayConfig[K]) {
    setConfig((prev) => ({ ...prev, [k]: v }))
  }

  const httpsOk = url.trim().toLowerCase().startsWith('https://')
  const canSave = !!name.trim() && httpsOk

  function invalidate() {
    qc.invalidateQueries({ queryKey: ['url-display'] })
    qc.invalidateQueries({ queryKey: ['media'] })  // url_display = média → rafraîchit la médiathèque
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = { name, url: url.trim(), config }
      if (editId === null) await api.post('/url-display', body)
      else await api.put(`/url-display/${editId}`, body)
    },
    onSuccess: () => { invalidate(); onClose() },
    onError: (e: unknown) => {
      if (isDemoBlocked(e)) return  // toast global démo → pas de message dans le drawer
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMutateError(typeof detail === 'string' ? detail : t('common.error'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/url-display/${id}`),
    onSuccess: () => { invalidate(); onClose() },
  })

  if (showDelete && editId !== null) {
    return (
      <Drawer open={open} onClose={onClose} title={t('media.delete_title')} width="w-[560px]">
        <DeleteMediaDialog
          name={name}
          impactUrl={`/url-display/${editId}/deletion-impact`}
          queryKey={['url-display-deletion-impact', editId]}
          isPending={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(editId)}
          onCancel={() => setShowDelete(false)}
        />
      </Drawer>
    )
  }

  return (
    <Drawer open={open} onClose={onClose} title={editId !== null ? t('url_display.edit') : t('url_display.new')} width="w-[560px]">
      {/* Nudge lecture-seule : édition = media:edit, création = media:create (backend url_display.py). */}
      <div className="space-y-5" data-write-perm={editId !== null ? 'media:edit' : 'media:create'}>
        <Input label={t('url_display.name_label')} value={name} onChange={(e) => setName(e.target.value)} />
        <div>
          <Input
            label={t('url_display.url_label')} value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t('url_display.url_placeholder')}
          />
          {url.trim() !== '' && !httpsOk && (
            <p className="text-xs text-danger mt-1">{t('url_display.https_only')}</p>
          )}
        </div>

        {/* Mode de rendu : webview (iframe) vs capture serveur (image Playwright) */}
        <div>
          <label className="text-sm font-medium text-gray-800">{t('url_display.render_mode_label')}</label>
          <select
            value={config.render_mode}
            onChange={(e) => setCfg('render_mode', e.target.value as UrlDisplayConfig['render_mode'])}
            className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
          >
            <option value="webview">{t('url_display.render_webview')}</option>
            <option value="screenshot_server">{t('url_display.render_screenshot')}</option>
          </select>
          <p className="text-xs text-gray-400 mt-1">
            {config.render_mode === 'screenshot_server'
              ? t('url_display.render_screenshot_hint')
              : t('url_display.render_webview_hint')}
          </p>
        </div>

        {/* Options d'affichage — repliable */}
        <div className="space-y-2">
          <button type="button" onClick={() => setOptionsOpen((v) => !v)}
            className="flex items-center gap-1.5 w-full text-left text-sm font-medium text-gray-700">
            {optionsOpen ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
            {t('url_display.options')}
          </button>
          {optionsOpen && (
            <div className="space-y-3 pl-1">
              <NumberField
                label={t('url_display.refresh_label')} min={0}
                value={config.refresh_interval_s ?? 0}
                onCommit={(v) => setCfg('refresh_interval_s', v ?? 0)}
              />
              <NumberField
                label={t('url_display.zoom_label')} min={0.1} step={0.1}
                value={config.zoom ?? 1}
                onCommit={(v) => setCfg('zoom', v ?? 1)}
              />
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={config.interaction_blocked}
                  onChange={(e) => setCfg('interaction_blocked', e.target.checked)}
                  className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                {t('url_display.interaction_label')}
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={config.reachability_enabled}
                  onChange={(e) => setCfg('reachability_enabled', e.target.checked)}
                  className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                {t('url_display.reachability_label')}
              </label>
              {config.reachability_enabled && (
                <NumberField
                  label={t('url_display.reachability_timeout_label')} min={1}
                  value={config.reachability_timeout_s ?? 8}
                  onCommit={(v) => setCfg('reachability_timeout_s', v ?? 8)}
                />
              )}
            </div>
          )}
        </div>

        {/* Tags (§XVII) — un url_display est un média → tags natifs (sur une page déjà créée). */}
        {editId !== null && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">{t('media.tags')}</label>
            <MediaTagsEditor idMedia={editId} mediaType="url_display" />
          </div>
        )}

        {/* Quarantaine / kill-switch (§ Q5) — url_display = média → mêmes règles */}
        {editId !== null && (
          <QuarantineSection idMedia={editId} />
        )}

        <p className="text-xs text-gray-400">{t('url_display.schedule_hint')}</p>
        {mutateError && <p className="text-sm text-danger">{mutateError}</p>}
        <div className="flex items-center justify-between">
          <div className="flex gap-2">
            <Button data-write-action onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !canSave}>
              {saveMutation.isPending ? t('common.saving') : t('common.save')}
            </Button>
            <Button variant="secondary" onClick={onClose}>{t('common.cancel')}</Button>
          </div>
          {editId !== null && (
            <Can perm="media:delete">
              <button
                onClick={() => setShowDelete(true)}
                className="p-2 text-gray-300 hover:text-danger transition-sf" title={t('common.delete')}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </Can>
          )}
        </div>
      </div>
    </Drawer>
  )
}
