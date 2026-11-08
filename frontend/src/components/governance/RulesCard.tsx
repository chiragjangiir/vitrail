'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation } from '@tanstack/react-query'
import { Gauge } from 'lucide-react'
import NumberField from '@/components/ui/NumberField'
import api from '@/lib/api'
import type { DelegationRule, GovernanceNodeDetail, RuleFamily } from '@/types/api'

const DOW = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

/**
 * Paramètres de diffusion du nœud — les 4 familles, **toujours affichées**.
 *
 * 🔑 Décision Ed 2026-07-26 : « les paramètres sont toujours affichés, en lecture seule
 * quand ils ne sont pas délégués, avec la mention de qui décide ». L'écran précédent
 * masquait purement et simplement ce que le niveau supérieur avait posé : l'admin local
 * ne pouvait pas voir la règle qui le contraignait, et croyait la boucle libre.
 *
 * Conséquence d'ergonomie : il n'y a plus de formulaire « ajouter une règle » avec un
 * sélecteur de type. Chaque paramètre est une ligne ; le vider **supprime** la règle
 * (= « aucune contrainte »), le renseigner la crée. Une règle n'est plus un objet qu'on
 * gère, c'est un réglage qui vaut quelque chose ou rien.
 */
export default function RulesCard({
  node, onChange,
}: {
  node: GovernanceNodeDetail
  onChange: () => void
}) {
  const t = useTranslations('governance')
  const td = useTranslations('schedules')   // libellés de jours (day_mon…)
  const [error, setError] = useState<string | null>(null)

  const byType = new Map(node.rules.map((r) => [r.rule_type, r]))
  const canEdit = (f: RuleFamily) => (node.can_edit_rule_types ?? {})[f] ?? false

  const fail = (e: unknown) => {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setError(typeof msg === 'string' && msg ? msg : t('rule_add_error'))
  }
  const done = () => { setError(null); onChange() }

  // Créer / mettre à jour / supprimer selon l'existant : l'appelant décrit le RÉGLAGE VOULU,
  // pas l'opération CRUD à faire.
  const write = useMutation({
    mutationFn: async ({ type, params, soft_cut }: {
      type: RuleFamily
      params: Record<string, unknown> | null
      soft_cut?: boolean
    }) => {
      const existing = byType.get(type)
      if (params === null) {
        if (existing) await api.delete(`/governance/rules/${existing.id_rule}`)
        return
      }
      if (existing) {
        await api.put(`/governance/rules/${existing.id_rule}`, {
          params, ...(soft_cut === undefined ? {} : { soft_cut }), is_active: true,
        })
      } else {
        await api.post(`/governance/nodes/${node.id_node}/rules`, {
          rule_type: type, params, soft_cut: soft_cut ?? true,
        })
      }
    },
    onSuccess: done,
    onError: fail,
  })

  const params = <T,>(r: DelegationRule | undefined): T => ((r?.params ?? {}) as T)

  const ic = params<{ max_per_cycle?: number; mode?: string }>(byType.get('item_count'))
  const tb = params<{ sec_per_cycle?: number }>(byType.get('time_budget'))
  const tw = params<{ days?: number[]; start?: string; end?: string }>(byType.get('time_window'))

  const field = 'border border-gray-300 rounded-md px-2 py-1 text-sm bg-surface'

  return (
    <section className="sf-panel p-5 space-y-4" data-testid="gov-rules">
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
          <Gauge className="w-3.5 h-3.5" />{t('rules')}
        </p>
        <p className="text-[11px] text-gray-400 mt-1">{t('rules_phase2')}</p>
      </div>

      {/* ── Contenus par tour ── */}
      <RuleRow title={t('rule_item_count')} hint={t('rule_item_count_hint')}
               editable={canEdit('item_count')} t={t}>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={ic.mode === 'one_random' ? 'one_random' : 'one_sequential'}
            disabled={!canEdit('item_count') || byType.get('item_count') === undefined}
            onChange={(e) => write.mutate({
              type: 'item_count',
              params: { max_per_cycle: ic.max_per_cycle ?? 1, mode: e.target.value },
            })}
            className={field}
          >
            <option value="one_sequential">{t('rot_sequential')}</option>
            <option value="one_random">{t('rot_random')}</option>
          </select>
          <NumberField
            value={ic.max_per_cycle ?? null}
            allowEmpty
            min={1}
            max={node.inherited_max_per_turn ?? undefined}
            disabled={!canEdit('item_count')}
            placeholder={t('rot_all')}
            className={`${field} w-20`}
            onCommit={(v) => write.mutate({
              type: 'item_count',
              params: v === null ? null : { max_per_cycle: v, mode: ic.mode ?? 'one_sequential' },
            })}
          />
          <span className="text-xs text-gray-500">{t('rot_per_turn')}</span>
          {node.inherited_max_per_turn != null && (
            <span className="text-[11px] text-gray-400">
              {t('rot_inherited_max', { n: node.inherited_max_per_turn })}
            </span>
          )}
        </div>
        {ic.max_per_cycle == null && (
          <p className="text-[11px] text-gray-400 mt-1">{t('rot_all_hint')}</p>
        )}
      </RuleRow>

      {/* ── Budget temps ── */}
      <RuleRow title={t('rule_time_budget')} hint={t('rule_time_budget_hint')}
               editable={canEdit('time_budget')} t={t}>
        <div className="flex flex-wrap items-center gap-2">
          <NumberField
            value={tb.sec_per_cycle ?? null}
            allowEmpty
            min={1}
            disabled={!canEdit('time_budget')}
            placeholder={t('budget_none')}
            className={`${field} w-24`}
            onCommit={(v) => write.mutate({
              type: 'time_budget',
              params: v === null ? null : { sec_per_cycle: v },
            })}
          />
          <span className="text-xs text-gray-500">{t('budget_unit')}</span>
          {byType.get('time_budget') && (
            <label className="flex items-center gap-1.5 text-xs text-gray-600">
              <input
                type="checkbox"
                checked={byType.get('time_budget')!.soft_cut}
                disabled={!canEdit('time_budget')}
                onChange={(e) => write.mutate({
                  type: 'time_budget',
                  params: { sec_per_cycle: tb.sec_per_cycle ?? 0 },
                  soft_cut: e.target.checked,
                })}
                className="accent-accent"
              />
              {t('soft_cut')}
            </label>
          )}
        </div>
      </RuleRow>

      {/* ── Plage horaire ── */}
      <RuleRow title={t('rule_time_window')} hint={t('rule_time_window_hint')}
               editable={canEdit('time_window')} t={t}>
        <TimeWindowRow
          days={tw.days ?? []}
          start={tw.start ?? ''}
          end={tw.end ?? ''}
          disabled={!canEdit('time_window')}
          field={field}
          td={td}
          t={t}
          onApply={(days, start, end) => write.mutate({
            type: 'time_window',
            params: days.length === 0 && !(start && end)
              ? null
              : {
                ...(days.length ? { days: [...days].sort((a, b) => a - b) } : {}),
                ...(start ? { start } : {}),
                ...(end ? { end } : {}),
              },
          })}
        />
      </RuleRow>

      {/* ── Préemption ── */}
      <RuleRow title={t('rule_preemptive')} hint={t('rule_preemptive_hint')}
               editable={canEdit('preemptive')} t={t}>
        <label className="flex items-center gap-2 text-xs text-gray-600">
          <input
            type="checkbox"
            checked={byType.has('preemptive')}
            disabled={!canEdit('preemptive')}
            onChange={(e) => write.mutate({
              type: 'preemptive', params: e.target.checked ? {} : null,
            })}
            className="accent-accent"
          />
          {t('preemptive_on')}
        </label>
      </RuleRow>

      {error && <p className="text-[11px] text-danger">{error}</p>}
    </section>
  )
}

function RuleRow({
  title, hint, editable, t, children,
}: {
  title: string
  hint: string
  editable: boolean
  t: ReturnType<typeof useTranslations>
  children: React.ReactNode
}) {
  return (
    <div className="border-t border-gray-100 pt-3 first:border-t-0 first:pt-0">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="text-sm font-medium text-gray-800">{title}</span>
        {!editable && (
          // « Avec la mention de qui décide » : sans elle, un champ grisé passe pour un bug.
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
            {t('decided_above')}
          </span>
        )}
      </div>
      <p className="text-[11px] text-gray-400 mb-1.5">{hint}</p>
      {children}
    </div>
  )
}

function TimeWindowRow({
  days, start, end, disabled, field, td, t, onApply,
}: {
  days: number[]
  start: string
  end: string
  disabled: boolean
  field: string
  td: ReturnType<typeof useTranslations>
  t: ReturnType<typeof useTranslations>
  onApply: (days: number[], start: string, end: string) => void
}) {
  // Les heures sont saisies à deux mains (début PUIS fin) : on ne pousse au serveur qu'une
  // paire complète, sinon un `start` seul écraserait la plage par une valeur inutilisable.
  const [s, setS] = useState(start)
  const [e, setE] = useState(end)

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex gap-1 flex-wrap">
        {DOW.map((d, i) => (
          <button
            key={d}
            type="button"
            disabled={disabled}
            onClick={() => onApply(
              days.includes(i) ? days.filter((x) => x !== i) : [...days, i], s, e,
            )}
            className={`text-[11px] px-1.5 py-1 rounded border transition-sf ${
              days.includes(i) ? 'bg-accent/10 border-accent text-accent' : 'border-gray-300 text-gray-500'
            } ${disabled ? 'opacity-50' : ''}`}
          >
            {td(`day_${d}`)}
          </button>
        ))}
      </div>
      {/* ⚠️ `onBlur` est légitime ICI, contrairement à la règle générale : un `input[type=time]`
          n'expose pas de flèches manipulables sans focus (ses segments exigent le focus), et
          committer à chaque `change` enverrait les états intermédiaires de frappe (« 01:00 »
          en tapant « 10:00 »). Les champs numériques, eux, passent par `NumberField`. */}
      <input type="time" value={s} disabled={disabled}
             onChange={(ev) => setS(ev.target.value)}
             onBlur={() => onApply(days, s, e)} className={field} />
      <span className="text-xs text-gray-400">→</span>
      <input type="time" value={e} disabled={disabled}
             onChange={(ev) => setE(ev.target.value)}
             onBlur={() => onApply(days, s, e)} className={field} />
      {days.length === 0 && !start && !end && (
        <span className="text-[11px] text-gray-400">{t('tw_always')}</span>
      )}
    </div>
  )
}
