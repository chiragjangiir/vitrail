'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Upload, X, Image as ImageIcon, Loader2 } from 'lucide-react'
import api from '@/lib/api'
import type { MediaListItem, MediaRead } from '@/types/api'

/** Sélecteur d'image(s) de référence (image→image / image→vidéo) : médiathèque + upload. */
export default function ReferencePicker({
  value,
  onChange,
  maxRefs,
}: {
  value: number[]
  onChange: (ids: number[]) => void
  maxRefs: number
}) {
  const t = useTranslations()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  // Aperçu local des images fraîchement uploadées (la vignette serveur n'existe qu'après transcode).
  const [previews, setPreviews] = useState<Record<number, string>>({})

  // Grille dynamique : nb de colonnes selon la largeur (comme /media), hauteur = exactement 2 lignes.
  const gridRef = useRef<HTMLDivElement>(null)
  const [cols, setCols] = useState(5)
  const [twoRowH, setTwoRowH] = useState<number | null>(null)
  useEffect(() => {
    const el = gridRef.current
    if (!el) return
    const TILE = 96, GAP = 6, PAD = 16 // p-2 (8px ×2)
    const compute = () => {
      const w = el.clientWidth - PAD
      if (w <= 0) return
      const c = Math.max(1, Math.floor((w + GAP) / (TILE + GAP)))
      setCols(c)
      const tile = (w - (c - 1) * GAP) / c
      setTwoRowH(Math.round(2 * tile + GAP + PAD)) // 2 lignes + gap inter-ligne + padding vertical
    }
    compute()
    const ro = new ResizeObserver(compute)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const { data: images = [], isLoading } = useQuery<MediaListItem[]>({
    queryKey: ['media', 'images-ref'],
    queryFn: () => api.get<MediaListItem[]>('/media/?media_type=image').then((r) => r.data),
  })

  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return api
        .post<MediaRead>('/media/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
        .then((r) => r.data)
    },
    onSuccess: (m, file) => {
      setPreviews((p) => ({ ...p, [m.id_media]: URL.createObjectURL(file) }))
      qc.invalidateQueries({ queryKey: ['media', 'images-ref'] })
      // En sélection unique, un nouvel upload remplace ; sinon on ajoute tant qu'il reste de la place.
      if (maxRefs === 1) onChange([m.id_media])
      else if (value.length < maxRefs) onChange([...value, m.id_media])
    },
  })

  const toggle = (id: number) => {
    if (value.includes(id)) onChange(value.filter((x) => x !== id))
    // En sélection unique, cliquer une autre image REMPLACE la sélection courante.
    else if (maxRefs === 1) onChange([id])
    else if (value.length < maxRefs) onChange([...value, id])
  }

  const byId = new Map(images.map((m) => [m.id_media, m]))

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-gray-700">
          {t('generation.reference')} {maxRefs > 1 ? `(${value.length}/${maxRefs})` : ''}
        </label>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
        >
          {upload.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
          {t('generation.reference_upload')}
        </button>
        <input
          ref={fileRef} type="file" accept="image/*" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = '' }}
        />
      </div>

      {/* Sélection courante */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((id) => {
            const m = byId.get(id)
            return (
              // NB: pas d'overflow-hidden sur le conteneur relatif — sinon le bouton en négatif est rogné.
              <div key={id} className="relative h-14 w-14">
                <div className="h-full w-full overflow-hidden rounded border border-accent bg-gray-100">
                  {(m?.thumbnail_url || previews[id])
                    ? <img src={m?.thumbnail_url || previews[id]} alt="" className="h-full w-full object-contain" />
                    : <ImageIcon className="h-5 w-5 m-auto mt-4 text-gray-400" />}
                </div>
                <button
                  type="button" onClick={() => toggle(id)} aria-label={t('common.delete')}
                  className="absolute -top-2 -right-2 rounded-full bg-danger p-1 text-white shadow ring-2 ring-surface transition-sf hover:bg-danger/90"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Médiathèque (images) — colonnes dynamiques (largeur) + hauteur = 2 lignes, scroll au-delà. */}
      <div
        ref={gridRef}
        className="max-h-40 overflow-y-auto rounded border border-gray-200 p-2"
        style={twoRowH ? { maxHeight: twoRowH } : undefined}
      >
        {isLoading ? (
          <p className="text-xs text-gray-400">{t('common.loading')}</p>
        ) : images.length === 0 ? (
          <p className="text-xs text-gray-400">{t('generation.reference_empty')}</p>
        ) : (
          <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
            {images.map((m) => {
              const sel = value.includes(m.id_media)
              return (
                <button
                  key={m.id_media} type="button" onClick={() => toggle(m.id_media)}
                  title={m.media_name}
                  className={`relative aspect-square rounded overflow-hidden border-2 bg-gray-50 transition-sf ${
                    sel ? 'border-accent' : 'border-transparent hover:border-gray-300'
                  }`}
                >
                  {(m.thumbnail_url || previews[m.id_media])
                    ? <img src={m.thumbnail_url || previews[m.id_media]} alt="" className="h-full w-full object-contain" />
                    : <span className="flex h-full w-full items-center justify-center bg-gray-100"><ImageIcon className="w-4 h-4 text-gray-400" /></span>}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
