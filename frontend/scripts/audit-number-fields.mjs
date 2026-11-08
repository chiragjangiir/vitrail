#!/usr/bin/env node
/**
 * Audit des champs numériques de l'UI.
 *
 * Cherche le défaut signalé par Ed le 2026-08-11 sur le tiroir des feeds :
 * un `<input type="number">` CONTRÔLÉ dont le `onChange` CLAMPE ou remplace la
 * saisie à chaque frappe. Conséquence : il n'existe aucun état intermédiaire de
 * saisie — on ne peut ni vider le champ ni taper un nombre à deux chiffres.
 *
 *   value=3, on tape « 1 »  -> la chaîne devient « 31 » -> Math.min(6, 31) = 6
 *   on efface               -> parseInt('') = NaN       -> NaN || 3       = 3
 *
 * Classement (du plus grave au plus bénin) :
 *   BLOQUANT  contrôlé + plafond bas  -> un 2e chiffre clampe TOUJOURS : valeur inatteignable
 *   CLAMP     contrôlé + clamp/défaut -> vider est impossible, le champ se remplit tout seul
 *   ZERO      contrôlé sans repli     -> vider écrit 0 en silence
 *   BLUR      non contrôlé (defaultValue) -> saisie perdue si aucun blur (règle CLAUDE.md)
 *   OK        NumberField / range / lecture seule
 */
import { readFileSync } from 'node:fs'
import { execSync } from 'node:child_process'

// Liste des fichiers via git (rapide, et sans node_modules). Racine résolue par git
// plutôt qu'en dur : le script doit tourner en CI comme sur n'importe quel poste.
const REPO = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim()
const files = execSync('git ls-files "frontend/src/**/*.tsx"', {
  cwd: REPO, encoding: 'utf8',
}).trim().split('\n').filter(Boolean)

/** Découpe le fichier en éléments JSX <input .../> ou <Input .../> (auto-fermants). */
function extractElements(src) {
  const out = []
  const re = /<(input|Input|NumberField)\b/g
  let m
  while ((m = re.exec(src)) !== null) {
    // Avancer jusqu'au '>' de fermeture en respectant les accolades JSX imbriquées.
    let i = re.lastIndex, depth = 0, inStr = null
    while (i < src.length) {
      const c = src[i]
      if (inStr) { if (c === inStr && src[i - 1] !== '\\') inStr = null }
      else if (c === '"' || c === "'" || c === '`') inStr = c
      else if (c === '{') depth++
      else if (c === '}') depth--
      else if (c === '>' && depth === 0) break
      i++
    }
    const text = src.slice(m.index, i + 1)
    const line = src.slice(0, m.index).split('\n').length
    out.push({ tag: m[1], text, line })
  }
  return out
}

const findings = []

for (const rel of files) {
  const abs = REPO + '/' + rel
  let src
  try { src = readFileSync(abs, 'utf8') } catch { continue }
  if (!src.includes('type="number"') && !src.includes('NumberField')) continue

  for (const el of extractElements(src)) {
    if (el.tag === 'NumberField') { findings.push({ rel, line: el.line, kind: 'OK', why: 'NumberField', text: '' }); continue }
    if (!/type="number"/.test(el.text)) continue          // range / text / checkbox : hors sujet
    if (/readOnly|disabled={true}/.test(el.text)) continue

    const controlled = /\bvalue=\{/.test(el.text)
    const onChange = (el.text.match(/onChange=\{([\s\S]*)\}/) || [])[1] || ''
    const maxMatch = el.text.match(/\bmax=[{"]?(\d+)/)
    const max = maxMatch ? Number(maxMatch[1]) : null

    let kind = 'OK', why = ''
    if (!controlled && /defaultValue=/.test(el.text)) { kind = 'BLUR'; why = 'defaultValue + onBlur' }
    else if (controlled) {
      const clamps = /Math\.(min|max)/.test(onChange)
      const fallback = /\|\|\s*\d/.test(onChange)
      const bare = /(parseInt|parseFloat|Number)\(e\.target\.value/.test(onChange) && !fallback
      if (clamps && max !== null && max < 10) { kind = 'BLOQUANT'; why = `clampé à chaque frappe, max=${max}` }
      else if (clamps || fallback) { kind = 'CLAMP'; why = 'clampé / repli à chaque frappe' }
      else if (bare) { kind = 'ZERO'; why = 'vider écrit 0' }
    }
    {
      const label = (el.text.match(/label=\{?t\('([^']+)'\)/) || el.text.match(/label="([^"]+)"/) || [])[1] || ''
      findings.push({ rel, line: el.line, kind, why, label })
    }
  }
}

// ⚠️ Tout genre doit figurer ici : un genre absent donne `undefined - n` = NaN, le
// comparateur devient incohérent et le tri ne s'applique PAS (défaut vécu au 1er jet).
const ORDER = { BLOQUANT: 0, CLAMP: 1, ZERO: 2, BLUR: 3, OK: 4 }
for (const f of findings) if (!(f.kind in ORDER)) throw new Error(`genre non classé : ${f.kind}`)
findings.sort((a, b) => (ORDER[a.kind] - ORDER[b.kind]) || a.rel.localeCompare(b.rel) || a.line - b.line)

const counts = {}
for (const f of findings) counts[f.kind] = (counts[f.kind] || 0) + 1

console.log('=== CHAMPS NUMÉRIQUES À CORRIGER ===\n')
let cur = null
for (const f of findings) {
  if (f.kind !== cur) { cur = f.kind; console.log(`\n--- ${f.kind} (${counts[f.kind]}) ---`) }
  console.log(`${f.rel}:${f.line}  ${f.label ? `[${f.label}] ` : ''}${f.why}`)
}
console.log('\n=== TOTAL ===')
console.log(JSON.stringify(counts, null, 2))
