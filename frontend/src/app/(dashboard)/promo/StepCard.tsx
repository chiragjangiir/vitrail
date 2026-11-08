'use client'

import { ChevronDown, ChevronRight, Check } from 'lucide-react'

/**
 * Une étape du parcours de création d'un visuel promo (proposition A, 2026-08-10).
 *
 * 🔴 CE QU'ELLE CORRIGE. La page présentait une vingtaine de contrôles simultanés répartis en
 * sept cartes titrées — rien n'était faux, mais rien ne disait par où commencer (constat d'Ed :
 * « génial, mais pas du tout intuitif ; un user tout neuf risque d'être complètement perdu »).
 *
 * 🔑 LE POINT QUI FAIT TOUT LE TRAVAIL EST LA VALEUR REPLIÉE. Une étape fermée n'est pas un
 * tiroir vide : elle AFFICHE ce qu'elle contient (« Brightwell », « Éclat · 16:9 · FHD »). L'écran
 * se lit donc en cinq lignes au lieu de vingt contrôles, et on retrouve d'un coup d'œil pour
 * quelle marque et dans quel format on travaille. Sans ça, replier reviendrait à cacher.
 *
 * ⛔ Ce n'est PAS un assistant modal : toutes les étapes restent ouvrables à tout moment, dans
 * n'importe quel ordre. Le numéro guide la première fois ; il n'enferme jamais. Refaire un
 * visuel pour changer un prix doit coûter un clic, pas six écrans.
 */
export default function StepCard({
  n, label, value, done = false, open, onToggle, children, testId,
}: {
  n: number
  label: string
  /** Valeur résolue, montrée quand l'étape est repliée. `null` = rien de choisi. */
  value?: string | null
  /** Étape renseignée — pastille verte plutôt que numéro. */
  done?: boolean
  open: boolean
  onToggle: () => void
  children: React.ReactNode
  testId?: string
}) {
  const bulletCls = done
    ? 'border-green-500/40 bg-green-500/15 text-green-600 dark:text-green-400'
    : open
      ? 'border-accent/40 bg-accent/15 text-accent'
      : 'border-gray-200 bg-gray-100 dark:bg-white/5 text-gray-400'

  return (
    <div
      data-testid={testId}
      data-open={open ? 'true' : 'false'}
      data-done={done ? 'true' : 'false'}
      className={`overflow-hidden rounded-lg border transition-sf ${
        open ? 'border-accent/40' : 'border-gray-200'}`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left transition-sf hover:bg-gray-50 dark:hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
      >
        <span className={`grid h-[19px] w-[19px] flex-none place-items-center rounded-full border text-[10px] font-bold ${bulletCls}`}>
          {done ? <Check className="h-3 w-3" /> : n}
        </span>
        <span className="text-[11.5px] font-semibold text-gray-700">{label}</span>
        {/* La valeur ne s'affiche QUE replié : ouverte, l'étape la montre déjà en entier. */}
        {!open && (
          <span
            data-testid={testId ? `${testId}-value` : undefined}
            className={`ml-auto max-w-[164px] truncate text-[10.5px] ${
              value ? 'text-gray-500' : 'text-gray-400'}`}
          >
            {value || ''}
          </span>
        )}
        <span className={`flex-none text-gray-400 ${open ? '' : 'ml-1'}`}>
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>
      </button>
      {open && <div className="space-y-2 px-2.5 pb-2.5 pl-[38px]">{children}</div>}
    </div>
  )
}
