'use client'

import { useTranslations } from 'next-intl'
import {
  Type, Image as ImageIcon, Square, Circle, Minus, Trash2, ChevronUp, ChevronDown,
  AlignLeft, AlignCenter, AlignRight,
} from 'lucide-react'
import ReferencePicker from '../media/components/ReferencePicker'
import type { PromoLayer } from './PromoPreview'
import type { FontItem } from './SlotStyleControls'
import NumberField from '@/components/ui/NumberField'

const DEFAULT_WEIGHTS = [400, 500, 600, 700, 800, 900]
const inp = 'rounded border border-gray-200 bg-surface px-1.5 py-1 text-xs'
const lbl = 'text-[10px] text-gray-500'

/** Barre d'insertion + liste des calques (rail gauche). */
export function LayerToolbar({
  layers, selectedId, onAdd, onSelect, onDelete, onMoveZ,
}: {
  layers: PromoLayer[]
  selectedId: string | null
  onAdd: (partial: Partial<PromoLayer> & { type: PromoLayer['type'] }) => void
  onSelect: (id: string | null) => void
  onDelete: (id: string) => void
  onMoveZ: (id: string, dir: 1 | -1) => void
}) {
  const t = useTranslations()
  const addBtns: [PromoLayer['type'], Partial<PromoLayer>, typeof Type, string][] = [
    ['text', { text: t('promo.layer_text_ph'), size_vh: 8, color: '#1D2B3A', weight: 700, align: 'center' }, Type, t('promo.layer_add_text')],
    ['image', {}, ImageIcon, t('promo.layer_add_image')],
    ['shape', { shape: 'rect', fill: '#4875B4', radius: 8 }, Square, t('promo.layer_add_rect')],
    ['shape', { shape: 'ellipse', fill: '#E4572E' }, Circle, t('promo.layer_add_ellipse')],
    ['shape', { shape: 'line', h: 2, stroke: '#1D2B3A', stroke_width: 0.6 }, Minus, t('promo.layer_add_line')],
  ]
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {addBtns.map(([type, partial, Icon, label], i) => (
          <button key={i} type="button" onClick={() => onAdd({ type, ...partial })} title={label}
            className="inline-flex flex-1 items-center justify-center gap-1 rounded border border-gray-200 px-1.5 py-1.5 text-gray-600 hover:border-accent hover:text-accent">
            <Icon className="h-4 w-4" />
          </button>
        ))}
      </div>
      {layers.length === 0 ? (
        <p className="text-[11px] text-gray-400">{t('promo.layer_none')}</p>
      ) : (
        <ul className="space-y-0.5">
          {[...layers].sort((a, b) => (b.z ?? 0) - (a.z ?? 0)).map((ly) => (
            <li key={ly.id}>
              <div className={`flex items-center gap-1 rounded px-1.5 py-1 text-xs ${
                ly.id === selectedId ? 'bg-accent/10 text-accent' : 'hover:bg-gray-50'}`}>
                <button type="button" onClick={() => onSelect(ly.id)} className="flex-1 truncate text-left">
                  {ly.type === 'text' ? `T · ${ly.text || ''}`
                    : ly.type === 'image' ? t('promo.layer_image') : `${ly.shape}`}
                </button>
                <button type="button" onClick={() => onMoveZ(ly.id, 1)} title={t('promo.layer_front')}
                  className="text-gray-400 hover:text-gray-700"><ChevronUp className="h-3.5 w-3.5" /></button>
                <button type="button" onClick={() => onMoveZ(ly.id, -1)} title={t('promo.layer_back')}
                  className="text-gray-400 hover:text-gray-700"><ChevronDown className="h-3.5 w-3.5" /></button>
                <button type="button" onClick={() => onDelete(ly.id)} title={t('promo.layer_del')}
                  className="text-gray-400 hover:text-danger"><Trash2 className="h-3.5 w-3.5" /></button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Propriétés du calque sélectionné (rail droit — inspecteur contextuel). */
export function LayerProps({
  layer, fonts, onUpdate,
}: {
  layer: PromoLayer
  fonts: FontItem[]
  onUpdate: (id: string, patch: Partial<PromoLayer>) => void
}) {
  const t = useTranslations()
  const upd = (patch: Partial<PromoLayer>) => onUpdate(layer.id, patch)
  const hex = (v?: string) => (v && /^#[0-9a-fA-F]{6}$/.test(v) ? v : '#4875b4')
  const weights = (layer.font && fonts.find((f) => f.id === layer.font)?.weights) || DEFAULT_WEIGHTS

  return (
    <div className="grid grid-cols-2 gap-1.5">
      {layer.type === 'text' && (
        <>
          <label className="col-span-2 flex flex-col gap-0.5">
            <span className={lbl}>{t('promo.layer_text_ph')}</span>
            <input className={inp} value={layer.text ?? ''} onChange={(e) => upd({ text: e.target.value })} />
          </label>
          <label className="col-span-2 flex flex-col gap-0.5">
            <span className={lbl}>{t('promo.style_font')}</span>
            <select className={inp} value={layer.font ?? ''} onChange={(e) => upd({ font: e.target.value || undefined })}>
              <option value="">{t('promo.style_default')}</option>
              {fonts.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className={lbl}>{t('promo.style_size')}</span>
            <NumberField min={1} max={60} step={0.5} className={inp}
              value={layer.size_vh ?? 6} onCommit={(v) => upd({ size_vh: v ?? 6 })} />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className={lbl}>{t('promo.style_weight')}</span>
            <select className={inp} value={layer.weight ?? 600} onChange={(e) => upd({ weight: Number(e.target.value) })}>
              {weights.map((w) => <option key={w} value={w}>{w}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className={lbl}>{t('promo.style_color')}</span>
            <input type="color" className="h-[26px] w-full rounded border border-gray-200"
              value={hex(layer.color)} onChange={(e) => upd({ color: e.target.value })} />
          </label>
          <div className="flex flex-col gap-0.5">
            <span className={lbl}>{t('promo.style_align')}</span>
            <div className="flex gap-0.5">
              {([['left', AlignLeft], ['center', AlignCenter], ['right', AlignRight]] as const).map(([a, Ic]) => (
                <button key={a} type="button" onClick={() => upd({ align: a })}
                  className={`rounded border p-1 ${layer.align === a ? 'border-accent text-accent' : 'border-gray-200 text-gray-500'}`}>
                  <Ic className="h-3 w-3" />
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {layer.type === 'image' && (
        <>
          <div className="col-span-2">
            <ReferencePicker value={layer.media_id ? [layer.media_id] : []} maxRefs={1}
              onChange={(ids) => upd({ media_id: ids[0] })} />
          </div>
          <div className="col-span-2 flex gap-1">
            {(['contain', 'cover'] as const).map((f) => (
              <button key={f} type="button" onClick={() => upd({ fit: f })}
                className={`rounded border px-2 py-1 text-[11px] ${
                  (layer.fit ?? 'contain') === f ? 'border-accent text-accent' : 'border-gray-200 text-gray-500'}`}>
                {t(`promo.layer_fit_${f}`)}
              </button>
            ))}
          </div>
        </>
      )}

      {layer.type === 'shape' && (
        <>
          {layer.shape !== 'line' && (
            <label className="flex flex-col gap-0.5">
              <span className={lbl}>{t('promo.layer_fill')}</span>
              <div className="flex items-center gap-1">
                <input type="color" className="h-[26px] w-8 rounded border border-gray-200"
                  value={hex(layer.fill)} onChange={(e) => upd({ fill: e.target.value })} />
                <button type="button" onClick={() => upd({ fill: 'none' })}
                  className="text-[10px] text-gray-400 hover:text-danger">{t('promo.layer_no_fill')}</button>
              </div>
            </label>
          )}
          <label className="flex flex-col gap-0.5">
            <span className={lbl}>{t('promo.layer_stroke')}</span>
            <input type="color" className="h-[26px] w-full rounded border border-gray-200"
              value={hex(layer.stroke)} onChange={(e) => upd({ stroke: e.target.value })} />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className={lbl}>{t('promo.layer_stroke_w')}</span>
            <NumberField min={0} max={20} step={0.2} className={inp}
              value={layer.stroke_width ?? 0} onCommit={(v) => upd({ stroke_width: v ?? 0 })} />
          </label>
          {layer.shape === 'rect' && (
            <label className="flex flex-col gap-0.5">
              <span className={lbl}>{t('promo.layer_radius')}</span>
              <NumberField min={0} max={50} step={1} className={inp}
                value={layer.radius ?? 0} onCommit={(v) => upd({ radius: v ?? 0 })} />
            </label>
          )}
        </>
      )}

      <label className="flex flex-col gap-0.5">
        <span className={lbl}>{t('promo.layer_rotation')}</span>
        <NumberField step={1} className={inp}
          value={Math.round(layer.rotation ?? 0)} onCommit={(v) => upd({ rotation: v ?? 0 })} />
      </label>
      <label className="flex flex-col gap-0.5">
        <span className={lbl}>{t('promo.layer_opacity')}</span>
        <input type="range" min={0} max={1} step={0.05}
          value={layer.opacity ?? 1} onChange={(e) => upd({ opacity: Number(e.target.value) })} />
      </label>
    </div>
  )
}
