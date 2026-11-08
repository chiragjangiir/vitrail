'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { AlertTriangle, Trash2, PauseCircle, Link2Off } from 'lucide-react'

import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import api from '@/lib/api'

/**
 * Ce qui retient une suppression, NOMMÉ — organisations et comptes (P3.3).
 *
 * Le produit savait déjà dire ce qu'une suppression emporterait, mais seulement PAR ENTITÉ
 * (médias, templates, paniers, flux). Rien pour une organisation ni pour un compte.
 *
 * Deux principes, et ils viennent d'Ed :
 *  · « quand on efface, on efface » — on supprime FRANCHEMENT, ou on refuse en expliquant ;
 *    jamais un `is_deleted` qui laisse la ligne invisible et irrécupérable ;
 *  · jamais un bouton qui ne peut QU'échouer — quand la porte est fermée par construction
 *    (sa propre organisation, son propre compte, le dernier administrateur), le bouton est
 *    grisé ET la raison est écrite à côté.
 *
 * 🔑 Le tiroir montre les TROIS natures de lien, pas seulement « bloqué ». Sur une
 * organisation, une trentaine de tables partiraient en CASCADE : ne montrer que ce qui
 * bloque cacherait précisément ce qu'un opérateur doit voir avant de trancher.
 */

interface Reference {
  table: string
  column: string
  count: number
  kind: 'blocking' | 'cascade' | 'detach'
}

export interface DeletionImpact {
  can_delete: boolean
  blocking: Reference[]
  cascade: Reference[]
  detach: Reference[]
  blocking_total: number
  cascade_total: number
  detach_total: number
  closed_reason: string | null
  /** Alternative RÉVERSIBLE proposée quand la suppression est refusée. */
  suspend_available?: boolean
  deactivate_available?: boolean
}

interface Props {
  open: boolean
  onClose: () => void
  /** Ce qu'on s'apprête à supprimer, tel qu'il s'affiche (email, nom d'organisation). */
  label: string
  /** Endpoint du rapport d'impact, ex. `/users/12/deletion-impact`. */
  impactUrl: string
  /** Suppression réelle. */
  onPurge: () => Promise<unknown>
  /** Alternative réversible (désactiver un compte / suspendre une organisation). */
  onSoftAction?: () => Promise<unknown>
  softActionLabel?: string
  /** Clés à invalider après un geste réussi. */
  invalidate: string[]
}

function RefList({ refs, tone }: { refs: Reference[]; tone: string }) {
  return (
    <ul className="mt-1.5 space-y-0.5">
      {refs.map((r) => (
        <li key={`${r.table}.${r.column}`} className="flex justify-between gap-3 text-xs">
          {/* Le nom de table est technique ET c'est exactement ce qui rend l'information
              actionnable : « 14 dans cms_media » se règle, « c'est référencé » non. */}
          <span className="font-mono text-gray-600">{r.table}</span>
          <span className={`tabular-nums font-medium ${tone}`}>{r.count}</span>
        </li>
      ))}
    </ul>
  )
}

export default function DeletionImpactDrawer({
  open, onClose, label, impactUrl, onPurge, onSoftAction, softActionLabel, invalidate,
}: Props) {
  const t = useTranslations('admin_delete')
  const qc = useQueryClient()

  const { data, isLoading } = useQuery<DeletionImpact>({
    queryKey: ['deletion-impact', impactUrl],
    queryFn: () => api.get<DeletionImpact>(impactUrl).then((r) => r.data),
    enabled: open,
    // Jamais de cache : entre l'ouverture du tiroir et le clic, quelqu'un peut avoir fait
    // le ménage — ou l'inverse.
    staleTime: 0,
  })

  const done = () => {
    invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
    qc.invalidateQueries({ queryKey: ['deletion-impact', impactUrl] })
    onClose()
  }
  const purge = useMutation({ mutationFn: onPurge, onSuccess: done })
  const soft = useMutation({ mutationFn: () => onSoftAction!(), onSuccess: done })

  const canDelete = !!data?.can_delete
  const reason = data?.closed_reason
  const softAvailable = data?.suspend_available ?? data?.deactivate_available ?? false

  return (
    <Drawer open={open} onClose={onClose} title={t('title', { label })} width="w-[560px]">
      {isLoading || !data ? (
        <p className="text-sm text-gray-500">{t('loading')}</p>
      ) : (
        <div className="space-y-5">
          {/* Porte fermée par construction : on l'écrit, on ne laisse pas deviner. */}
          {reason && (
            <div className="flex gap-2 rounded-lg bg-orange-500/15 p-3 text-sm text-orange-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{t(`closed.${reason}`)}</span>
            </div>
          )}

          {data.blocking.length > 0 && (
            <section data-testid="impact-blocking">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
                <Trash2 className="h-4 w-4 text-danger" />
                {t('blocking_title', { total: data.blocking_total })}
              </h3>
              <p className="mt-1 text-xs text-gray-500">{t('blocking_hint')}</p>
              <RefList refs={data.blocking} tone="text-danger" />
            </section>
          )}

          {/* Le point que « bloqué » seul cacherait : ce qui disparaîtrait AVEC la cible. */}
          {data.cascade.length > 0 && (
            <section data-testid="impact-cascade">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
                <AlertTriangle className="h-4 w-4 text-warning" />
                {t('cascade_title', { total: data.cascade_total })}
              </h3>
              <p className="mt-1 text-xs text-gray-500">{t('cascade_hint')}</p>
              <RefList refs={data.cascade} tone="text-warning" />
            </section>
          )}

          {data.detach.length > 0 && (
            <section data-testid="impact-detach">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
                <Link2Off className="h-4 w-4 text-gray-500" />
                {t('detach_title', { total: data.detach_total })}
              </h3>
              <p className="mt-1 text-xs text-gray-500">{t('detach_hint')}</p>
              <RefList refs={data.detach} tone="text-gray-600" />
            </section>
          )}

          {canDelete && data.blocking.length === 0 && data.cascade.length === 0
            && data.detach.length === 0 && (
            <p className="text-sm text-gray-500">{t('nothing_holds')}</p>
          )}

          <div className="flex flex-col gap-2 border-t border-white/5 pt-4">
            <Button
              variant="danger"
              disabled={!canDelete || purge.isPending}
              onClick={() => purge.mutate()}
              data-testid="purge-btn"
            >
              <Trash2 className="mr-1.5 h-4 w-4" />
              {t('purge')}
            </Button>
            {/* Le bouton grisé n'explique rien tout seul : la raison est écrite dessous. */}
            {!canDelete && (
              <p className="text-xs text-gray-500" data-testid="purge-blocked-reason">
                {reason ? t(`closed.${reason}`) : t('blocked_hint')}
              </p>
            )}
            {onSoftAction && softAvailable && (
              <Button
                variant="secondary"
                disabled={soft.isPending}
                onClick={() => soft.mutate()}
                data-testid="soft-btn"
              >
                <PauseCircle className="mr-1.5 h-4 w-4" />
                {softActionLabel ?? t('soft_default')}
              </Button>
            )}
          </div>
        </div>
      )}
    </Drawer>
  )
}
