'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import NumberField from '@/components/ui/NumberField'
import api from '@/lib/api'
import { RULE_FAMILIES, type GovernanceNodeDetail, type RuleFamily } from '@/types/api'

/**
 * « Ce que ce nœud laisse décider en dessous » — toutes les cases de gouvernance au même
 * endroit, avec la même polarité.
 *
 * 🔑 Décision de modèle Ed 2026-07-26 : **tout est une RESTRICTION cochée par défaut**, qui
 * se propage vers le bas et ne se lève que depuis un niveau supérieur. Le produit portait
 * jusqu'ici deux polarités opposées côte à côte (`requires_approval` = restriction cochée,
 * `rules_delegated` = permission décochée) : deux cases voisines dont l'une cochait pour
 * interdire et l'autre pour autoriser.
 *
 * Les **plafonds** sont ici et non dans le formulaire de règle : ils décrivent le droit des
 * descendants, pas la diffusion de ce nœud. Effet de bord résolu au passage — poser un
 * plafond n'oblige plus à créer une règle `item_count` dont le nœud n'a aucun besoin.
 */
export default function RestrictionsCard({
  node, onChange,
}: {
  node: GovernanceNodeDetail
  onChange: () => void
}) {
  const t = useTranslations('governance')
  const [error, setError] = useState<string | null>(null)

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.put(`/governance/nodes/${node.id_node}`, body),
    onSuccess: () => { setError(null); onChange() },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof msg === 'string' ? msg : t('restriction_error'))
    },
  })

  const canSetLocks = node.can_set_rules_delegation ?? false
  const canEditNode = node.can_edit ?? true
  const lockedAbove = node.rules_locked_above ?? {}
  const effective = node.rules_locked_effective ?? {}

  const moderationLocked = node.requires_approval ?? true
  const canLiftModeration = node.can_disable_moderation ?? false

  return (
    <section className="sf-panel p-5 space-y-4" data-testid="gov-restrictions">
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
          <Lock className="w-3.5 h-3.5" />{t('restrictions_title')}
        </p>
        <p className="text-[11px] text-gray-400 mt-1">{t('restrictions_hint')}</p>
      </div>

      {/* Contenu — la seule case qui ne porte pas sur un paramètre de diffusion mais sur la
          publication (§XXI). Elle vit ici parce qu'elle obéit exactement à la même règle. */}
      <RestrictionRow
        label={t('moderation_label')}
        hint={t('moderation_hint')}
        checked={moderationLocked}
        // Décocher est réservé à un ancêtre ; recocher (durcir) reste ouvert.
        disabled={moderationLocked && !canLiftModeration}
        lockedAbove={false}
        note={moderationLocked && !canLiftModeration ? t('moderation_locked') : null}
        onChange={(v) => patch.mutate({ requires_approval: v })}
      />

      <div className="border-t border-gray-100 pt-3 space-y-3">
        {RULE_FAMILIES.map((f: RuleFamily) => {
          const above = !!lockedAbove[f]
          // ⚠️ Clé absente = RESTREINTE, exactement comme côté serveur (migr 0110). Un `??
          // false` afficherait « délégué » sur un nœud qui ne l'est pas — le pire sens pour
          // une valeur par défaut sur un écran de droits.
          const isLocked = effective[f] ?? true
          return (
            <RestrictionRow
              key={f}
              label={t(`lock_${f}`)}
              hint={t(`lock_${f}_hint`)}
              checked={isLocked}
              // Rien à décider ici si un ancêtre a déjà posé la restriction : la case
              // locale serait sans effet, et une case cliquable sans effet ment.
              disabled={above || (isLocked && !canSetLocks)}
              lockedAbove={above}
              note={
                above ? t('lock_from_above')
                  : isLocked && !canSetLocks ? t('lock_needs_ancestor')
                    : null
              }
              onChange={(v) => patch.mutate({ rules_locked: { [f]: v } })}
            />
          )
        })}
      </div>

      {/* Plafonds : ils bornent ce que les niveaux INFÉRIEURS peuvent se donner. */}
      <div className="border-t border-gray-100 pt-3 space-y-2">
        <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">
          {t('caps_title')}
        </p>
        <CapRow
          label={t('cap_children')}
          value={node.max_for_children ?? null}
          inherited={node.inherited_max_per_turn ?? null}
          disabled={!canEditNode}
          onCommit={(v) => patch.mutate({ max_for_children: v })}
          t={t}
        />
        <CapRow
          label={t('cap_item_sec')}
          value={node.max_item_sec ?? null}
          inherited={node.inherited_max_item_sec ?? null}
          disabled={!canEditNode}
          onCommit={(v) => patch.mutate({ max_item_sec: v })}
          t={t}
        />
        <p className="text-[11px] text-gray-400">{t('caps_hint')}</p>
      </div>

      {error && <p className="text-[11px] text-danger">{error}</p>}
    </section>
  )
}

function RestrictionRow({
  label, hint, checked, disabled, lockedAbove, note, onChange,
}: {
  label: string
  hint: string
  checked: boolean
  disabled: boolean
  lockedAbove: boolean
  note: string | null
  onChange: (v: boolean) => void
}) {
  return (
    <div>
      <label className={`flex items-start gap-2 ${disabled ? '' : 'cursor-pointer'}`}>
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="accent-accent mt-0.5"
        />
        <span className="text-sm text-gray-700">
          {label}
          <span className="block text-[11px] text-gray-400">{hint}</span>
        </span>
      </label>
      {note && (
        <p className={`text-[11px] mt-0.5 ml-6 ${lockedAbove ? 'text-amber-600 dark:text-amber-300' : 'text-gray-400'}`}>
          {note}
        </p>
      )}
    </div>
  )
}

function CapRow({
  label, value, inherited, disabled, onCommit, t,
}: {
  label: string
  value: number | null
  inherited: number | null
  disabled: boolean
  onCommit: (v: number | null) => void
  t: ReturnType<typeof useTranslations>
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-gray-600">
      <span className="flex-1">{label}</span>
      {inherited != null && (
        <span className="text-[11px] text-gray-400">{t('cap_inherited', { n: inherited })}</span>
      )}
      <NumberField
        value={value}
        onCommit={onCommit}
        allowEmpty
        min={1}
        max={inherited ?? undefined}
        disabled={disabled}
        placeholder="—"
        className="border border-gray-300 rounded-md px-2 py-1 text-sm bg-surface w-20"
      />
    </label>
  )
}
