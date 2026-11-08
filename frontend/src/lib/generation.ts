// Catalogue de génération IA + estimatif de coût — partagé GenerateDialog + Studio.
// MIROIR de backend services/generation/catalog.py (mêmes constantes/règles).

export type ParamSpec = {
  key: string
  control: 'select' | 'number' | 'text'
  label: string
  default?: string | number | null
  options?: { value: string; label?: string; label_literal?: string }[]
  min?: number
  max?: number
  step?: number
  unit?: string
  optional?: boolean
  affects_cost?: 'seconds' | 'megapixels'
}

export type ModelSpec = {
  id: string
  kind: 'image' | 'video' | 'music' | 'voice'
  provider: 'fal' | 'elevenlabs'
  label: string
  tier: 'low' | 'moderate' | 'high'
  pricing: { mode: string; usd: number }
  params: ParamSpec[]
  /** 'image' = image→image / image→vidéo : exige une ou des image(s) de référence. */
  input?: 'text' | 'image'
  ref_multi?: boolean
  max_refs?: number
  /** Le modèle accepte un negative prompt (pilote l'affichage du champ + l'assistant). */
  supports_negative_prompt?: boolean
  /** 'edit' = retouche d'une image existante (détourage, édition par instruction). */
  op?: string
  /** Modèle d'édition sans prompt requis (ex. détourage). */
  prompt_optional?: boolean
}

export type GenerationCatalog = { providers: string[]; models: ModelSpec[] }

export const RATIO_DIMS: Record<string, [number, number]> = {
  '1:1': [1024, 1024], '16:9': [1344, 768], '9:16': [768, 1344], '4:3': [1152, 896], '3:4': [896, 1152],
}
export const RES_SCALE: Record<string, number> = { standard: 1.0, high: 1.5 }

export function megapixels(params: Record<string, unknown>): number {
  const ratio = (params.aspect_ratio as string) || '16:9'
  const [w, h] = RATIO_DIMS[ratio] || RATIO_DIMS['16:9']
  const s = RES_SCALE[(params.resolution as string) || 'standard'] || 1
  return (w * h * s * s) / 1_000_000
}

function seconds(model: ModelSpec, params: Record<string, unknown>): number {
  const p = model.params.find((x) => x.affects_cost === 'seconds')
  if (!p) return 0
  const v = Number(params[p.key] ?? p.default)
  return Number.isFinite(v) ? v : 0
}

/** Coût USD estimé d'UNE génération (mêmes modes que le backend). */
export function estimateCost(
  model: ModelSpec | undefined, params: Record<string, unknown>, text: string,
): number {
  if (!model) return 0
  const { mode, usd } = model.pricing
  if (mode === 'flat' || mode === 'per_image' || mode === 'per_video') return usd
  if (mode === 'per_megapixel') return usd * megapixels(params)
  if (mode === 'per_second') return usd * Math.max(seconds(model, params), 1)
  if (mode === 'per_1k_chars') return (usd * Math.max(text.trim().length, 1)) / 1000
  return usd
}

/** Format court d'un coût (≥ 1¢ → 2 décimales, sinon 4). */
export function fmtCost(cost: number): string {
  return cost >= 0.01 ? `$${cost.toFixed(2)}` : `$${cost.toFixed(4)}`
}
