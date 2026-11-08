'use client'

import { useCommitField } from '@/lib/useCommitField'
import Input from '@/components/ui/Input'

/**
 * Champ numérique **unique du produit**. Deux garanties, chacune née d'un défaut vécu :
 *
 * 1. Il s'enregistre **sans dépendre du blur** (débounce + Entrée + flush au démontage)
 *    — cf. `lib/useCommitField`. ⛔ Ne pas revenir à `defaultValue` + `onBlur` : agir sur
 *    les FLÈCHES du spinner sans cliquer dans le champ ne produit aucun blur, donc aucun
 *    enregistrement (retour Ed 2026-07-25).
 *
 * 2. Il laisse **taper librement** : le texte en cours de saisie vit dans le hook, et les
 *    bornes ne s'appliquent qu'au commit. C'est ce qui manquait aux 46 champs corrigés le
 *    2026-08-11 : ils étaient contrôlés ET clampés à CHAQUE frappe, si bien qu'aucun état
 *    intermédiaire n'existait — sur un champ à 3, borné à 6, taper « 1 » produisait « 31 »
 *    donc 6, et l'effacer produisait 3. Le champ écrivait n'importe quoi (retour Ed).
 *    ⚠️ Corollaire : `min`/`max` ne sont PAS décoratifs ici. Sur un `<input>` nu ils ne
 *    bornent que le spinner — une valeur tapée hors bornes partait telle quelle.
 *
 * `null` = champ vide, valeur à part entière (hérite / pas de limite) — n'est autorisé
 * que si `allowEmpty`. Sinon un champ vidé n'envoie rien et revient à la valeur serveur.
 *
 * Avec `label`, le rendu passe par `Input` (label + style du design system) ; sans lui,
 * c'est un `<input>` nu que l'appelant habille — les deux formes partagent le mécanisme.
 */
export default function NumberField({
  value, onCommit, allowEmpty = false, min, max, step, decimals,
  className = '', placeholder, disabled, title, delay, label, hint,
}: {
  value: number | null
  onCommit: (v: number | null) => void
  allowEmpty?: boolean
  min?: number
  max?: number
  step?: number
  /** Conserver les décimales (défaut : déduit de `step` < 1). */
  decimals?: boolean
  className?: string
  placeholder?: string
  disabled?: boolean
  title?: string
  delay?: number
  /** Rend le champ via `Input` (libellé + style). Sans lui : `<input>` nu. */
  label?: string
  hint?: string
}) {
  const keepDecimals = decimals ?? (step !== undefined && step < 1)

  const bind = useCommitField<number | null>({
    external: value,
    toText: (v) => (v === null || v === undefined ? '' : String(v)),
    parse: (raw) => {
      const s = raw.trim()
      if (s === '') return allowEmpty ? null : undefined
      const n = Number(s)
      if (!Number.isFinite(n)) return undefined
      const rounded = keepDecimals ? n : Math.round(n)
      const lo = min !== undefined ? Math.max(min, rounded) : rounded
      return max !== undefined ? Math.min(max, lo) : lo
    },
    commit: onCommit,
    delay,
  })

  const common = {
    type: 'number' as const,
    min, max, step, placeholder, disabled, title,
    ...bind,
  }

  return label !== undefined || hint !== undefined
    ? <Input label={label} hint={hint} className={className} {...common} />
    : <input className={className} {...common} />
}
