'use client'

import { useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, Trash2, Loader2, Type } from 'lucide-react'
import api from '@/lib/api'
import type { FontItem } from './SlotStyleControls'

const WEIGHTS = [300, 400, 500, 600, 700, 800, 900]

/**
 * Gestion des polices personnalisées de l'organisation (§12.7, org-admin). Upload (avec
 * attestation de licence obligatoire) + liste + suppression. Les polices apparaissent ensuite
 * dans le sélecteur de police des slots. 1 fichier = (famille, graisse).
 */
export default function OrgFontsManager({ customFonts }: { customFonts: FontItem[] }) {
  const t = useTranslations()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [family, setFamily] = useState('')
  const [weight, setWeight] = useState(400)
  const [ack, setAck] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const invalidate = () => qc.invalidateQueries({ queryKey: ['promo-fonts'] })

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append('file', file!)
      fd.append('family', family.trim())
      fd.append('weight', String(weight))
      fd.append('license_ack', String(ack))
      return api.post('/promo/fonts/upload', fd,
        { headers: { 'Content-Type': 'multipart/form-data' } })
    },
    onSuccess: () => {
      setErr(null); setFile(null); setFamily(''); setAck(false)
      if (fileRef.current) fileRef.current.value = ''
      invalidate()
    },
    onError: (e) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErr(typeof msg === 'string' ? msg : t('common.error'))
    },
  })

  const del = useMutation({
    mutationFn: (idFont: number) => api.delete(`/promo/fonts/${idFont}`),
    onSuccess: invalidate,
  })

  const canUpload = !!file && family.trim().length > 0 && ack && !upload.isPending

  return (
    <div className="rounded-lg border border-gray-200 p-2">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 text-xs font-semibold text-gray-700">
        <Type className="h-3.5 w-3.5 text-accent" />{t('promo.fonts_manage_title')}
        {customFonts.length > 0 ? ` (${customFonts.length})` : ''}
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          {/* Liste des polices custom */}
          {customFonts.length === 0 ? (
            <p className="text-[11px] text-gray-400">{t('promo.fonts_none')}</p>
          ) : (
            <ul className="space-y-1">
              {customFonts.map((f) => (
                <li key={f.id} className="flex items-center justify-between gap-2 rounded bg-gray-50 dark:bg-surface px-2 py-1">
                  <span className="truncate text-xs text-gray-700" style={{ fontFamily: `'${f.family}', sans-serif` }}>
                    {f.family}
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    {(f.files ?? []).map((file2) => (
                      <button key={file2.id_font} type="button" onClick={() => del.mutate(file2.id_font)}
                        title={t('promo.fonts_delete')}
                        className="inline-flex items-center gap-0.5 rounded border border-gray-200 px-1 py-0.5 text-[10px] text-gray-500 hover:border-danger hover:text-danger">
                        {file2.weight}<Trash2 className="h-2.5 w-2.5" />
                      </button>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {/* Formulaire d'upload */}
          <div className="space-y-1.5 border-t border-gray-100 pt-2">
            <div className="grid grid-cols-2 gap-1.5">
              <input value={family} onChange={(e) => setFamily(e.target.value)}
                placeholder={t('promo.fonts_family')}
                className="rounded border border-gray-200 bg-surface px-1.5 py-1 text-xs" />
              <select value={weight} onChange={(e) => setWeight(Number(e.target.value))}
                className="rounded border border-gray-200 bg-surface px-1.5 py-1 text-xs">
                {WEIGHTS.map((w) => <option key={w} value={w}>{t('promo.style_weight')} {w}</option>)}
              </select>
            </div>
            <button type="button" onClick={() => fileRef.current?.click()}
              className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
              <Upload className="h-3 w-3" />{file ? file.name : t('promo.fonts_file')}
            </button>
            <input ref={fileRef} type="file" accept=".woff2,.woff,.ttf,.otf,font/*" className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <label className="flex items-start gap-1.5 text-[11px] text-gray-500">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" />
              <span>{t('promo.fonts_license')}</span>
            </label>
            {err && <p className="text-[11px] text-danger">{err}</p>}
            <button type="button" onClick={() => upload.mutate()} disabled={!canUpload}
              className="inline-flex items-center gap-1.5 rounded-lg border border-accent/40 px-2.5 py-1 text-xs text-accent transition-sf hover:bg-accent/10 disabled:opacity-50">
              {upload.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              {t('promo.fonts_add')}
            </button>
            <p className="text-[11px] text-gray-400">{t('promo.fonts_hint')}</p>
          </div>
        </div>
      )}
    </div>
  )
}
