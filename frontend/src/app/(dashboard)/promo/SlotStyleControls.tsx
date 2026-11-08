'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { Type, AlignLeft, AlignCenter, AlignRight, X } from 'lucide-react'
import type { SlotStyle } from './PromoPreview'
import NumberField from '@/components/ui/NumberField'

export interface FontItem {
  id: string; label: string; family: string; weights: number[]
  category?: string                              // 'sans'|'serif'|… ou 'custom'
  files?: { id_font: number; weight: number }[]  // custom : fichiers à charger (FontFace API)
}

const DEFAULT_WEIGHTS = [400, 500, 600, 700, 800, 900]

/**
 * Contrôles de style d'un slot texte promo (Phase A) : police, couleur, graisse, taille,
 * alignement. Repliable. Écrit un patch partiel dans `inputs.style_overrides[slot]`.
 * Toutes les valeurs sont re-validées côté serveur (anti-injection CSS).
 */
export default function SlotStyleControls({
  value, onChange, fonts,
}: {
  value?: SlotStyle
  onChange: (patch: SlotStyle) => void
  fonts: FontItem[]
}) {
  const t = useTranslations()
  const [open, setOpen] = useState(false)

  const weights = (value?.font && fonts.find((f) => f.id === value.font)?.weights) || DEFAULT_WEIGHTS
  const hasStyle = !!value && Object.values(value).some((v) => v != null && v !== '')

  const sel = 'rounded border border-gray-200 bg-surface px-1.5 py-1 text-xs'

  return (
    <div className="mt-1">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className={`inline-flex items-center gap-1 text-[11px] transition-sf ${
          hasStyle ? 'font-medium text-accent' : 'text-gray-400 hover:text-gray-600'}`}>
        <Type className="h-3 w-3" />{t('promo.style_title')}{hasStyle ? ' •' : ''}
      </button>

      {open && (
        <div className="mt-1.5 grid grid-cols-2 gap-1.5 rounded-lg border border-gray-200 p-2 sm:grid-cols-4">
          {/* Police */}
          <label className="col-span-2 flex flex-col gap-0.5 sm:col-span-2">
            <span className="text-[10px] text-gray-500">{t('promo.style_font')}</span>
            <select className={sel} value={value?.font ?? ''}
              onChange={(e) => onChange({ font: e.target.value || undefined })}>
              <option value="">{t('promo.style_default')}</option>
              {fonts.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </label>

          {/* Graisse */}
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-gray-500">{t('promo.style_weight')}</span>
            <select className={sel} value={value?.weight ?? ''}
              onChange={(e) => onChange({ weight: e.target.value ? Number(e.target.value) : undefined })}>
              <option value="">{t('promo.style_default')}</option>
              {weights.map((w) => <option key={w} value={w}>{w}</option>)}
            </select>
          </label>

          {/* Couleur */}
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-gray-500">{t('promo.style_color')}</span>
            <div className="flex items-center gap-1">
              <input type="color" className="h-[26px] w-8 rounded border border-gray-200 bg-surface"
                value={value?.color && /^#[0-9a-fA-F]{6}$/.test(value.color) ? value.color : '#1d2b3a'}
                onChange={(e) => onChange({ color: e.target.value })} />
              {value?.color && (
                <button type="button" onClick={() => onChange({ color: undefined })}
                  className="text-gray-400 hover:text-danger" aria-label={t('promo.style_reset')}>
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </label>

          {/* Alignement */}
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] text-gray-500">{t('promo.style_align')}</span>
            <div className="flex gap-0.5">
              {([['left', AlignLeft], ['center', AlignCenter], ['right', AlignRight]] as const).map(
                ([a, Icon]) => (
                  <button key={a} type="button"
                    onClick={() => onChange({ align: value?.align === a ? undefined : a })}
                    className={`rounded border p-1 transition-sf ${
                      value?.align === a ? 'border-accent bg-accent/10 text-accent'
                        : 'border-gray-200 text-gray-500 hover:bg-gray-50'}`}>
                    <Icon className="h-3.5 w-3.5" />
                  </button>
                ))}
            </div>
          </div>

          {/* Taille */}
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-gray-500">{t('promo.style_size')}</span>
            <NumberField min={1} max={40} step={0.5} className={sel} allowEmpty
              placeholder={t('promo.style_auto')} value={value?.size_vh ?? null}
              onCommit={(v) => onChange({ size_vh: v ?? undefined })} />
          </label>
        </div>
      )}
    </div>
  )
}
