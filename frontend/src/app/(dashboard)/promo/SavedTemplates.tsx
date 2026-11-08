'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, Loader2, Trash2, Check, X } from 'lucide-react'
import api from '@/lib/api'

interface SavedItem { id_promo_template: number; name: string; updated_at: string }

/**
 * Modèles promo réutilisables (Phase C) : charger un instantané enregistré de l'éditeur, en
 * enregistrer un nouveau, mettre à jour ou supprimer le modèle chargé. `currentConfig()` capture
 * l'état courant au moment de l'enregistrement ; `onLoad(config)` restaure l'éditeur.
 */
export default function SavedTemplates({
  currentConfig, onLoad,
}: {
  currentConfig: () => Record<string, unknown>
  onLoad: (config: Record<string, unknown>) => void
}) {
  const t = useTranslations()
  const qc = useQueryClient()
  const [loadedId, setLoadedId] = useState<number | null>(null)
  const [naming, setNaming] = useState(false)
  const [nameInput, setNameInput] = useState('')

  const { data: saved = [] } = useQuery<SavedItem[]>({
    queryKey: ['promo-saved'],
    queryFn: () => api.get<SavedItem[]>('/promo/saved').then((r) => r.data),
  })
  const invalidate = () => qc.invalidateQueries({ queryKey: ['promo-saved'] })

  const load = useMutation({
    mutationFn: (id: number) => api.get<{ config: Record<string, unknown> }>(`/promo/saved/${id}`).then((r) => r.data),
    onSuccess: (d, id) => { onLoad(d.config || {}); setLoadedId(id) },
  })
  const create = useMutation({
    mutationFn: () => api.post<SavedItem>('/promo/saved',
      { name: nameInput.trim(), config: currentConfig() }).then((r) => r.data),
    onSuccess: (d) => { invalidate(); setLoadedId(d.id_promo_template); setNaming(false); setNameInput('') },
  })
  const update = useMutation({
    mutationFn: () => api.put(`/promo/saved/${loadedId}`, { config: currentConfig() }),
    onSuccess: invalidate,
  })
  const del = useMutation({
    mutationFn: () => api.delete(`/promo/saved/${loadedId}`),
    onSuccess: () => { invalidate(); setLoadedId(null) },
  })

  const btn = 'inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] transition-sf'

  return (
    <div className="rounded-lg border border-gray-200 p-2 space-y-1.5">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
        <Save className="h-3.5 w-3.5 text-accent" />{t('promo.saved_title')}
      </p>

      <select className="w-full rounded border border-gray-200 bg-surface px-1.5 py-1 text-xs"
        value={loadedId ?? ''} onChange={(e) => e.target.value && load.mutate(Number(e.target.value))}>
        <option value="">{saved.length ? t('promo.saved_load') : t('promo.saved_none')}</option>
        {saved.map((s) => <option key={s.id_promo_template} value={s.id_promo_template}>{s.name}</option>)}
      </select>

      {naming ? (
        <div className="flex gap-1">
          <input autoFocus value={nameInput} onChange={(e) => setNameInput(e.target.value)}
            placeholder={t('promo.saved_name_ph')}
            onKeyDown={(e) => { if (e.key === 'Enter' && nameInput.trim()) create.mutate() }}
            className="flex-1 rounded border border-gray-200 bg-surface px-1.5 py-1 text-xs" />
          <button type="button" disabled={!nameInput.trim() || create.isPending} onClick={() => create.mutate()}
            className={`${btn} border-accent/40 text-accent hover:bg-accent/10 disabled:opacity-50`}>
            {create.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
          </button>
          <button type="button" onClick={() => { setNaming(false); setNameInput('') }}
            className={`${btn} border-gray-200 text-gray-500`}><X className="h-3 w-3" /></button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-1">
          <button type="button" onClick={() => setNaming(true)}
            className={`${btn} border-accent/40 text-accent hover:bg-accent/10`}>
            <Save className="h-3 w-3" />{t('promo.saved_save')}
          </button>
          {loadedId && (
            <>
              <button type="button" disabled={update.isPending} onClick={() => update.mutate()}
                className={`${btn} border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50`}>
                {update.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}{t('promo.saved_update')}
              </button>
              <button type="button" onClick={() => del.mutate()}
                className={`${btn} border-gray-200 text-gray-500 hover:border-danger hover:text-danger`}>
                <Trash2 className="h-3 w-3" />
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
