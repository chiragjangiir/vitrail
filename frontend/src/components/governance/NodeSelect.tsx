'use client'

import { useId, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Lock, Network } from 'lucide-react'
import api from '@/lib/api'
import { useCan } from '@/components/auth/Can'
import type { GovernanceNode } from '@/types/api'

/**
 * Contenu gouverné §XVIII (D6/D9) — brique partagée playlists + médias.
 *
 * Une playlist / un média peut appartenir à un NŒUD de gouvernance au lieu de
 * l'organisation : l'écriture est alors réservée aux administrateurs de ce nœud
 * (ou d'un de ses ancêtres), et la lecture est filtrée (un nœud frère est
 * invisible — 404 côté serveur). Le contenu SANS nœud (null) reste le contenu
 * d'organisation : aucun changement de comportement.
 *
 * ⚠️ Confort d'affichage, jamais une sécurité : l'autorisation réelle est
 * `governance_access.user_can_edit_node` côté serveur. On n'offre que les nœuds
 * `can_edit` parce qu'un choix qui finit systématiquement en 403 est un défaut
 * de produit.
 */

/** Nœuds de l'org — requête partagée (la liste est petite, un seul cache pour tout le CMS). */
export function useGovernanceNodes() {
  // Sans `governance:read`, l'appel partirait en 403 : on ne le lance pas et le
  // sélecteur se masque (un Designer ne rattache rien à un nœud de toute façon).
  const canRead = useCan('governance:read')
  return useQuery<GovernanceNode[]>({
    queryKey: ['gov-nodes'],
    queryFn: () => api.get<GovernanceNode[]>('/governance/nodes').then((r) => r.data),
    enabled: canRead,
    staleTime: 60_000,
  })
}

/** Nom lisible d'un nœud (pour les badges) — `null` tant que la liste n'est pas chargée. */
export function useNodeName(idNode: number | null | undefined): string | null {
  const { data: nodes = [] } = useGovernanceNodes()
  if (idNode == null) return null
  return nodes.find((n) => n.id_node === idNode)?.node_name ?? null
}

/**
 * Sélecteur de nœud propriétaire. Ne s'affiche PAS si l'org n'a aucun nœud de
 * gouvernance (cas de la très grande majorité des installations) — inutile de
 * montrer un champ qui n'a qu'une seule valeur possible.
 */
export default function NodeSelect({
  value,
  onChange,
  disabled = false,
  label,
  hint,
  className = '',
}: {
  value: number | null
  onChange: (id: number | null) => void
  disabled?: boolean
  label?: string
  hint?: string
  className?: string
}) {
  const t = useTranslations('governance')
  const { data: nodes = [] } = useGovernanceNodes()
  // Le libellé doit être RATTACHÉ au select (id/htmlFor) : sans ça il n'est qu'un
  // texte voisin — pas de lecture correcte au lecteur d'écran.
  const selectId = useId()

  // Ordre d'arbre : le backend trie déjà par `path` matérialisé, on indente au niveau.
  const options = useMemo(
    () => nodes.map((n) => ({
      ...n,
      // Le nœud COURANT reste sélectionnable même non éditable : sinon un contenu
      // gouverné affiché en lecture seule perdrait son libellé dans la liste.
      selectable: n.can_edit !== false || n.id_node === value,
    })),
    [nodes, value],
  )

  if (nodes.length === 0) return null

  return (
    <div className={className}>
      <label htmlFor={selectId} className="mb-1 block text-xs text-gray-400">
        {label ?? t('content_node_label')}
      </label>
      <select
        id={selectId}
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        className="w-full rounded-lg border border-gray-200 bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none disabled:opacity-50"
      >
        <option value="">{t('content_node_org')}</option>
        {options.map((n) => (
          <option key={n.id_node} value={n.id_node} disabled={!n.selectable}>
            {'  '.repeat(n.node_level)}
            {n.node_name}
            {n.can_edit === false ? ` (${t('content_node_readonly_suffix')})` : ''}
          </option>
        ))}
      </select>
      <p className="mt-1 text-[11px] text-gray-400">{hint ?? t('content_node_hint')}</p>
    </div>
  )
}

/** Pastille « contenu gouverné » (liste playlists / médias). */
export function GovernedBadge({
  idNode,
  readonly = false,
}: {
  idNode: number | null | undefined
  readonly?: boolean
}) {
  const t = useTranslations('governance')
  const name = useNodeName(idNode)
  if (idNode == null) return null
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
        readonly ? 'bg-gray-100 text-gray-500' : 'bg-accent/10 text-accent'
      }`}
      title={readonly ? t('content_readonly_hint') : t('content_governed_hint')}
    >
      {readonly ? <Lock className="w-3 h-3" /> : <Network className="w-3 h-3" />}
      {name ?? t('content_governed')}
    </span>
  )
}
