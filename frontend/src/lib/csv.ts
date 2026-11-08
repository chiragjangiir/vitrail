/**
 * Génère un CSV depuis un tableau de lignes et déclenche son téléchargement.
 * Échappe les guillemets/points-virgules ; séparateur `;` (compatibilité Excel FR).
 * BOM UTF-8 en tête pour que les accents s'affichent correctement dans Excel.
 */
export function downloadCsv(filename: string, rows: (string | number)[][]): void {
  const escape = (v: string | number) => {
    const s = String(v ?? '')
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csv = rows.map((r) => r.map(escape).join(';')).join('\r\n')
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/* ═══════════════════════════════════════════════════════════════════════════════════════════
   LECTURE — mode série du générateur promo (2026-08-10).

   Le produit ne faisait qu'ÉCRIRE du CSV ; c'est la première fois qu'il en lit. Écrit à la main
   plutôt qu'avec une dépendance : le besoin tient en quelques dizaines de lignes, et une
   dépendance de plus se paie à chaque chargement de page.

   ⚠️ Ce qu'un fichier réel apporte et qu'un parseur naïf casse :
     · le **point-virgule** — Excel en français sépare avec `;` (c'est d'ailleurs ce qu'écrit
       `downloadCsv` ci-dessus, donc un export Vitrail doit pouvoir être relu tel quel) ;
     · la **BOM UTF-8** — sans la retirer, le 1er en-tête devient `﻿nom` et n'est plus reconnu ;
     · les **guillemets** — un slogan contenant le séparateur, avec `""` pour un guillemet ;
     · les fins de ligne **CRLF** et une ligne vide finale.
   ═══════════════════════════════════════════════════════════════════════════════════════════ */

/** Séparateur du fichier, détecté sur la 1re ligne non vide, **hors guillemets** — sinon un
 *  slogan « Frais, local et de saison » ferait croire à des virgules séparatrices. */
export function detectSeparator(text: string): ';' | ',' | '\t' {
  // ⚠️ On s'arrête au premier saut de ligne **HORS GUILLEMETS**, pas au premier `\n` du texte :
  // un champ multiligne (`"deux\nlignes";c`) ferait sinon regarder `"deux` seul, où aucun
  // séparateur n'apparaît — on retombait sur la virgule et le fichier entier devenait
  // une colonne unique. Trouvé par le test, pas à la relecture.
  const src = text.replace(/^﻿/, '')
  let inQuotes = false
  const n = { ';': 0, ',': 0, '\t': 0 }
  for (const ch of src) {
    if (ch === '"') { inQuotes = !inQuotes; continue }
    if (inQuotes) continue
    if (ch === '\n') { if (n[';'] || n[','] || n['\t']) break; else continue }
    if (ch === ';' || ch === ',' || ch === '\t') n[ch]++
  }
  if (n[';'] > 0 && n[';'] >= n[','] && n[';'] >= n['\t']) return ';'
  if (n['\t'] > 0 && n['\t'] > n[',']) return '\t'
  return ','
}

/** Lignes du CSV, guillemets résolus, lignes entièrement vides écartées. */
export function parseCsv(text: string, sep?: string): string[][] {
  const src = text.replace(/^﻿/, '')
  const s = sep ?? detectSeparator(src)
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false

  for (let i = 0; i < src.length; i++) {
    const ch = src[i]
    if (inQuotes) {
      if (ch === '"') {
        if (src[i + 1] === '"') { field += '"'; i++ }   // `""` = un guillemet littéral
        else inQuotes = false
      } else field += ch
      continue
    }
    if (ch === '"') { inQuotes = true; continue }
    if (ch === s) { row.push(field); field = ''; continue }
    if (ch === '\r') continue
    if (ch === '\n') { row.push(field); rows.push(row); row = []; field = ''; continue }
    field += ch
  }
  row.push(field)
  rows.push(row)
  return rows.map((r) => r.map((c) => c.trim())).filter((r) => r.some((c) => c !== ''))
}

/** Une ligne de série : uniquement ce qui VARIE d'un visuel à l'autre. */
export interface SerieCsvLine {
  slogan?: string
  price?: string
  original_price?: string
  discount_pct?: string
}

/** Sans accents, minuscules, sans ponctuation — pour reconnaître « Prix barré » ≈ `prix_barre`. */
const normHeader = (s: string) =>
  s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '')

const HEADER_ALIASES: Record<keyof SerieCsvLine, string[]> = {
  slogan: ['slogan', 'nom', 'produit', 'libelle', 'name', 'product', 'title', 'titre',
           'nombre', 'produto', 'bezeichnung', 'artikel'],
  price: ['prix', 'price', 'prixpromo', 'precio', 'preco', 'preis', 'tarif'],
  original_price: ['prixbarre', 'ancienprix', 'prixinitial', 'originalprice', 'was',
                   'preciotachado', 'precoriscado', 'streichpreis', 'alterpreis'],
  discount_pct: ['remise', 'discount', 'reduction', 'descuento', 'desconto', 'rabatt'],
}

export interface SerieCsvResult {
  lines: SerieCsvLine[]
  /** Colonnes retenues, dans l'ordre du fichier — pour que l'écran puisse les MONTRER. */
  mapped: (keyof SerieCsvLine | null)[]
  /** `true` si la 1re ligne a été lue comme des en-têtes. */
  hasHeader: boolean
}

/**
 * Transforme un CSV en lignes de série.
 *
 * 🔑 **Sans en-tête reconnu, on ne devine pas EN SILENCE** : les colonnes sont lues dans l'ordre
 * (slogan, prix, prix barré, remise) et `hasHeader=false` permet à l'écran de le DIRE. Deviner
 * sans le dire produirait des visuels avec le prix dans le mauvais champ — ce qui ne se voit
 * qu'une fois le visuel à l'antenne.
 */
export function parseSerieCsv(text: string): SerieCsvResult {
  const rows = parseCsv(text)
  if (rows.length === 0) return { lines: [], mapped: [], hasHeader: false }

  const mapped: (keyof SerieCsvLine | null)[] = rows[0].map((cell) => {
    const h = normHeader(cell)
    for (const key of Object.keys(HEADER_ALIASES) as (keyof SerieCsvLine)[]) {
      if (HEADER_ALIASES[key].includes(h)) return key
    }
    return null
  })
  const hasHeader = mapped.some((m) => m !== null)
  const order: (keyof SerieCsvLine | null)[] = hasHeader
    ? mapped
    : ['slogan', 'price', 'original_price', 'discount_pct']

  const lines = (hasHeader ? rows.slice(1) : rows).map((r) => {
    const line: SerieCsvLine = {}
    order.forEach((key, i) => {
      const v = (r[i] ?? '').trim()
      if (key && v) line[key] = v
    })
    return line
  }).filter((l) => Object.keys(l).length > 0)

  return { lines, mapped: order, hasHeader }
}
