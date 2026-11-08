'use client'

/**
 * Aperçu WYSIWYG côté client d'un visuel promo. Rend les mêmes slots (%/vh) que le serveur,
 * en unités CSS `cqh` (= 1% de la hauteur du conteneur → équivalent vh de la toile serveur).
 * Approximatif (police de secours, pas d'auto-fit) : la source de vérité reste le rendu
 * serveur (Playwright). Un débordement visible ici aide juste l'utilisateur à raccourcir.
 */

export interface PromoTheme {
  accent: string; ink: string; paper: string; badge_bg: string; badge_ink: string; font: string
}
export interface Slot {
  left: number; top: number; width: number; height?: number; align?: string
  font_vh: number; min_vh: number; color?: string; weight?: number; max_chars?: number
}
export type Layout = Record<string, Slot>
export interface PromoTemplate {
  id: string; label: string; formats: string[]; theme: PromoTheme
  layouts: Record<string, Layout>
}
export interface SlotStyle {
  font?: string; size_vh?: number; color?: string; weight?: number; align?: string
}
export interface PromoLayer {
  id: string
  type: 'text' | 'image' | 'shape'
  x: number; y: number; w: number; h: number
  rotation?: number; z?: number; opacity?: number
  text?: string; font?: string; size_vh?: number; color?: string; weight?: number; align?: string
  media_id?: number; fit?: 'contain' | 'cover'
  shape?: 'rect' | 'ellipse' | 'line'
  fill?: string; stroke?: string; stroke_width?: number; radius?: number
}
export interface PromoInputs {
  slogan?: string; price?: string; original_price?: string
  discount_pct?: string; currency?: string; mentions?: string
  style_overrides?: Record<string, SlotStyle>
  layers?: PromoLayer[]
}

const SYM: Record<string, string> = { EUR: '€', USD: '$', GBP: '£' }

function num(v?: string): number | null {
  if (v == null || v === '') return null
  const n = Number(String(v).replace(',', '.').replace(/\s/g, ''))
  return Number.isFinite(n) ? n : null
}
export function formatPrice(v?: string, currency = 'EUR'): string | null {
  const n = num(v)
  if (n == null) return null
  return `${n.toFixed(2).replace('.', ',')} ${SYM[(currency || 'EUR').toUpperCase()] ?? currency}`
}
export function discountPct(price?: string, original?: string, explicit?: string): number | null {
  if (explicit != null && explicit !== '') {
    const e = Number(String(explicit).replace('%', '').trim())
    return Number.isFinite(e) ? Math.round(e) : null
  }
  const p = num(price), o = num(original)
  if (p != null && o != null && o > 0 && o > p) return Math.round((1 - p / o) * 100)
  return null
}

function color(theme: PromoTheme, ref?: string): string {
  if (ref && ref in theme) return (theme as unknown as Record<string, string>)[ref]
  return ref || theme.ink
}

/** Style CSS d'un calque libre (mêmes règles que le renderer serveur, en unités cqh). */
function layerStyle(ly: PromoLayer, theme: PromoTheme, fam?: string): React.CSSProperties {
  const common: React.CSSProperties = {
    position: 'absolute', left: `${ly.x}%`, top: `${ly.y}%`, width: `${ly.w}%`, height: `${ly.h}%`,
    transform: `rotate(${ly.rotation ?? 0}deg)`, transformOrigin: 'center', boxSizing: 'border-box',
    zIndex: 100 + (ly.z ?? 0), opacity: ly.opacity ?? 1, overflow: 'hidden',
  }
  if (ly.type === 'text') return {
    ...common, fontFamily: fam ? `'${fam}', ${theme.font}, sans-serif` : undefined,
    fontSize: `${ly.size_vh ?? 6}cqh`, color: color(theme, ly.color), fontWeight: ly.weight ?? 600,
    textAlign: (ly.align ?? 'left') as 'left' | 'center' | 'right', lineHeight: 1.06,
    overflowWrap: 'break-word', wordBreak: 'break-word',
  }
  if (ly.type === 'image') return common
  if (ly.shape === 'line') return {
    ...common, height: `${ly.stroke_width || 0.5}cqh`,
    background: ly.stroke && ly.stroke !== 'none' ? ly.stroke : ly.fill,
  }
  return {
    ...common, background: ly.fill === 'none' ? 'transparent' : (ly.fill ?? '#4875B4'),
    border: ly.stroke && ly.stroke !== 'none' && ly.stroke_width
      ? `${ly.stroke_width}cqh solid ${ly.stroke}` : undefined,
    borderRadius: ly.shape === 'ellipse' ? '50%' : `${ly.radius ?? 0}%`,
  }
}

export default function PromoPreview({
  template, format, inputs, backgroundUrl, productUrl, fontFamilies, layers, mediaThumbs,
}: {
  template: PromoTemplate | undefined
  format: string
  inputs: PromoInputs
  backgroundUrl?: string
  productUrl?: string
  /** id de police → nom de famille CSS (catalogue /promo/fonts) — pour rendre l'aperçu fidèle. */
  fontFamilies?: Record<string, string>
  layers?: PromoLayer[]                        // calques libres (Phase B)
  mediaThumbs?: Record<number, string>         // id média → vignette (calques image)
}) {
  if (!template || !template.layouts[format]) {
    return <div className="aspect-video rounded-lg border border-dashed border-gray-300" />
  }
  const layout = template.layouts[format]
  const theme = template.theme
  const pct = discountPct(inputs.price, inputs.original_price, inputs.discount_pct)
  const price = formatPrice(inputs.price, inputs.currency)
  const original = pct ? formatPrice(inputs.original_price, inputs.currency) : null

  const texts: { name: string; text: string; strike?: boolean; nowrap?: boolean }[] = []
  if (inputs.slogan?.trim() && layout.slogan)
    texts.push({ name: 'slogan', text: inputs.slogan.trim() })
  if (original && layout.original_price)
    texts.push({ name: 'original_price', text: original, strike: true, nowrap: true })
  if (price && layout.price) texts.push({ name: 'price', text: price, nowrap: true })
  if (inputs.mentions?.trim() && layout.mentions)
    texts.push({ name: 'mentions', text: inputs.mentions.trim() })

  const box: React.CSSProperties = {
    aspectRatio: format === '9:16' ? '9 / 16' : '16 / 9',
    containerType: 'size',
    background: theme.paper,
    fontFamily: `${theme.font}, 'Segoe UI', Roboto, sans-serif`,
  }

  return (
    <div data-testid="promo-preview"
         className="relative w-full overflow-hidden rounded-lg border border-gray-200 shadow-sm"
         style={box}>
      {backgroundUrl && (
        <img src={backgroundUrl} alt="" className="absolute inset-0 h-full w-full object-cover" />
      )}
      {productUrl && layout.product && (
        <img src={productUrl} alt="" className="absolute object-contain" style={{
          left: `${layout.product.left}%`, top: `${layout.product.top}%`,
          width: `${layout.product.width}%`, height: `${layout.product.height}%`,
        }} />
      )}
      {texts.map(({ name, text, strike, nowrap }) => {
        const s = layout[name]
        const ov = inputs.style_overrides?.[name]
        const fam = ov?.font ? fontFamilies?.[ov.font] : undefined
        return (
          <div key={name} className="absolute overflow-hidden" style={{
            left: `${s.left}%`, top: `${s.top}%`, width: `${s.width}%`,
            height: s.height ? `${s.height}%` : undefined,
            fontSize: `${ov?.size_vh ?? s.font_vh}cqh`, lineHeight: 1.06,
            fontWeight: ov?.weight ?? s.weight ?? 600,
            fontFamily: fam ? `'${fam}', ${theme.font}, sans-serif` : undefined,
            color: color(theme, ov?.color ?? s.color),
            textAlign: (ov?.align ?? s.align ?? 'left') as 'left' | 'center' | 'right',
            textDecoration: strike ? 'line-through' : undefined, opacity: strike ? 0.7 : undefined,
            whiteSpace: nowrap ? 'nowrap' : 'normal',
            overflowWrap: 'break-word', wordBreak: 'break-word',
          }}>{text}</div>
        )
      })}
      {pct != null && layout.discount && (
        <div className="absolute flex items-center justify-center rounded-full text-center" style={{
          left: `${layout.discount.left}%`, top: `${layout.discount.top}%`,
          width: `${layout.discount.width}%`, height: `${layout.discount.height}%`,
          background: theme.badge_bg, color: theme.badge_ink,
          fontSize: `${layout.discount.font_vh}cqh`, fontWeight: layout.discount.weight ?? 900,
          transform: 'rotate(-8deg)', boxShadow: '0 0.6cqh 1.6cqh rgba(0,0,0,.25)',
        }}>{`-${pct}%`}</div>
      )}
      {[...(layers ?? [])].sort((a, b) => (a.z ?? 0) - (b.z ?? 0)).map((ly) => {
        const fam = ly.type === 'text' && ly.font ? fontFamilies?.[ly.font] : undefined
        const url = ly.type === 'image' && ly.media_id ? mediaThumbs?.[ly.media_id] : undefined
        return (
          <div key={ly.id} style={layerStyle(ly, theme, fam)}>
            {ly.type === 'text' && ly.text}
            {url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={url} alt="" style={{
                width: '100%', height: '100%',
                objectFit: ly.fit === 'cover' ? 'cover' : 'contain',
              }} />
            )}
          </div>
        )
      })}
    </div>
  )
}
