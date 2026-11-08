'use client'

import { useRef } from 'react'
import { RotateCw } from 'lucide-react'
import PromoPreview, { type PromoInputs, type PromoTemplate, type PromoLayer } from './PromoPreview'

/**
 * Éditeur canvas des calques libres (Phase B) : superpose un overlay interactif à l'aperçu
 * (PromoPreview). Chaque calque se déplace (drag), se redimensionne (poignée bas-droite, centre
 * fixe, compensée par la rotation) et pivote (poignée haute). Coordonnées en % de la toile.
 */
type Drag =
  | { mode: 'move'; id: string; sx: number; sy: number; x0: number; y0: number }
  | { mode: 'resize'; id: string; sx: number; sy: number; w0: number; h0: number
      x0: number; y0: number; rot: number }
  | { mode: 'rotate'; id: string; cx: number; cy: number }

export default function PromoCanvasEditor({
  template, format, inputs, backgroundUrl, productUrl, fontFamilies, layers, mediaThumbs,
  selectedId, onSelect, onChange,
}: {
  template: PromoTemplate | undefined
  format: string
  inputs: PromoInputs
  backgroundUrl?: string
  productUrl?: string
  fontFamilies?: Record<string, string>
  layers: PromoLayer[]
  mediaThumbs?: Record<number, string>
  selectedId: string | null
  onSelect: (id: string | null) => void
  onChange: (id: string, patch: Partial<PromoLayer>) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)
  const r1 = (n: number) => Math.round(n * 10) / 10

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d || !ref.current) return
    const r = ref.current.getBoundingClientRect()
    if (d.mode === 'move') {
      const dx = ((e.clientX - d.sx) / r.width) * 100
      const dy = ((e.clientY - d.sy) / r.height) * 100
      onChange(d.id, { x: r1(d.x0 + dx), y: r1(d.y0 + dy) })
    } else if (d.mode === 'resize') {
      const dxp = e.clientX - d.sx, dyp = e.clientY - d.sy
      const th = (-d.rot * Math.PI) / 180
      const ldx = dxp * Math.cos(th) - dyp * Math.sin(th)
      const ldy = dxp * Math.sin(th) + dyp * Math.cos(th)
      const w = Math.max(2, d.w0 + (ldx / r.width) * 100 * 2)
      const h = Math.max(2, d.h0 + (ldy / r.height) * 100 * 2)
      const cx = d.x0 + d.w0 / 2, cy = d.y0 + d.h0 / 2
      onChange(d.id, { w: r1(w), h: r1(h), x: r1(cx - w / 2), y: r1(cy - h / 2) })
    } else {
      const px = e.clientX - r.left, py = e.clientY - r.top
      onChange(d.id, { rotation: Math.round(Math.atan2(py - d.cy, px - d.cx) * 180 / Math.PI + 90) })
    }
  }

  const end = () => { drag.current = null }
  const capture = (e: React.PointerEvent) =>
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId)

  const startMove = (e: React.PointerEvent, ly: PromoLayer) => {
    e.stopPropagation(); onSelect(ly.id); capture(e)
    drag.current = { mode: 'move', id: ly.id, sx: e.clientX, sy: e.clientY, x0: ly.x, y0: ly.y }
  }
  const startResize = (e: React.PointerEvent, ly: PromoLayer) => {
    e.stopPropagation(); capture(e)
    drag.current = { mode: 'resize', id: ly.id, sx: e.clientX, sy: e.clientY,
      w0: ly.w, h0: ly.h, x0: ly.x, y0: ly.y, rot: ly.rotation ?? 0 }
  }
  const startRotate = (e: React.PointerEvent, ly: PromoLayer) => {
    e.stopPropagation(); capture(e)
    const r = ref.current!.getBoundingClientRect()
    drag.current = { mode: 'rotate', id: ly.id,
      cx: ((ly.x + ly.w / 2) / 100) * r.width, cy: ((ly.y + ly.h / 2) / 100) * r.height }
  }

  return (
    <div ref={ref} className="relative select-none" style={{ touchAction: 'none' }}
      onPointerMove={onPointerMove} onPointerUp={end}
      onPointerDown={() => onSelect(null)}>
      <PromoPreview template={template} format={format} inputs={inputs}
        backgroundUrl={backgroundUrl} productUrl={productUrl} fontFamilies={fontFamilies}
        layers={layers} mediaThumbs={mediaThumbs} />
      <div className="absolute inset-0" style={{ zIndex: 500 }}>
        {layers.map((ly) => {
          const sel = ly.id === selectedId
          return (
            <div key={ly.id} onPointerDown={(e) => startMove(e, ly)} className="absolute cursor-move"
              style={{
                left: `${ly.x}%`, top: `${ly.y}%`, width: `${ly.w}%`, height: `${ly.h}%`,
                transform: `rotate(${ly.rotation ?? 0}deg)`, transformOrigin: 'center',
                outline: sel ? '2px solid #4875B4' : '1px dashed rgba(72,117,180,.45)',
                background: sel ? 'rgba(72,117,180,.06)' : 'transparent',
              }}>
              {sel && (
                <>
                  <div onPointerDown={(e) => startResize(e, ly)}
                    className="absolute h-3 w-3 rounded-full border border-white bg-accent shadow"
                    style={{ right: -6, bottom: -6, cursor: 'nwse-resize' }} />
                  <div onPointerDown={(e) => startRotate(e, ly)}
                    className="absolute flex h-4 w-4 items-center justify-center rounded-full border border-white bg-accent text-white shadow"
                    style={{ left: '50%', top: -22, marginLeft: -8, cursor: 'grab' }}>
                    <RotateCw className="h-2.5 w-2.5" />
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
