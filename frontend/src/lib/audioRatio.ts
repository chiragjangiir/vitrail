/**
 * Auto-équilibrage des ratios de mix audio (§XIX, option C).
 *
 * Quand l'utilisateur fixe un panier à `newValue`, les AUTRES paniers (music/ambiance)
 * sont rééquilibrés au prorata pour que le total fasse 100 %, chacun borné à [min, max]
 * (water-filling). Best-effort si les bornes rendent 100 % infaisable.
 */
export interface RatioItem {
  id: number
  ratio: number
  min: number
  max: number
}

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v))

export function rebalanceRatios(
  items: RatioItem[],
  changedId: number,
  newValue: number,
): Record<number, number> {
  const result: Record<number, number> = {}
  const ch = items.find((i) => i.id === changedId)
  if (!ch) {
    items.forEach((i) => (result[i.id] = i.ratio))
    return result
  }
  const chVal = clamp(Math.round(newValue), ch.min, ch.max)
  result[ch.id] = chVal

  const others = items.filter((i) => i.id !== changedId).map((i) => ({ ...i }))
  if (others.length === 0) {
    result[ch.id] = clamp(100, ch.min, ch.max)
    return result
  }

  let remaining = 100 - chVal
  let free = others.slice()
  let guard = 0
  while (free.length && guard++ < 30) {
    const wsum = free.reduce((s, i) => s + Math.max(0.001, i.ratio), 0)
    let clampedAny = false
    for (const i of [...free]) {
      const share = remaining * (Math.max(0.001, i.ratio) / wsum)
      if (share < i.min) {
        result[i.id] = i.min; remaining -= i.min; free = free.filter((x) => x.id !== i.id); clampedAny = true
      } else if (share > i.max) {
        result[i.id] = i.max; remaining -= i.max; free = free.filter((x) => x.id !== i.id); clampedAny = true
      }
    }
    if (!clampedAny) {
      const wsum2 = free.reduce((s, i) => s + Math.max(0.001, i.ratio), 0)
      let acc = 0
      free.forEach((i, idx) => {
        const v = idx === free.length - 1
          ? Math.max(0, Math.round(remaining - acc))
          : Math.round(remaining * (Math.max(0.001, i.ratio) / wsum2))
        result[i.id] = v
        acc += v
      })
      free = []
    }
  }
  // Sécurité : tout panier non assigné garde sa valeur clampée
  others.forEach((i) => { if (result[i.id] === undefined) result[i.id] = clamp(i.ratio, i.min, i.max) })
  return result
}
