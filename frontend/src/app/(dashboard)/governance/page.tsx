'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Network, Plus, Trash2, Monitor, Users, Building2, ShieldCheck, Map,
} from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import NodeTree from '@/components/governance/NodeTree'
import RestrictionsCard from '@/components/governance/RestrictionsCard'
import RulesCard from '@/components/governance/RulesCard'
import CompiledProgramPanel from '@/components/governance/CompiledProgramPanel'
import PerimeterMapModal from '@/components/governance/PerimeterMapModal'
import NodeWorkspaceCard from '@/components/governance/NodeWorkspaceCard'
import NewNodeAdminDrawer from '@/components/governance/NewNodeAdminDrawer'
import { CardGrid } from '@/components/ui/CardGrid'
import MarqueeText from '@/components/ui/MarqueeText'
import api from '@/lib/api'
import { isDemoBlocked } from '@/lib/demo'
import { roleLabel } from '@/lib/roleLabel'
import type {
  GovernanceNode, GovernanceNodeDetail, PlayerGroupRead, Site, SiteGroupRead,
} from '@/types/api'

/** Écran proposable au rattachement (G1/G2) — `orphan` = encore hors gouvernance. */
type AttachablePlayer = {
  id_player: number
  player_name: string
  id_site: number | null
  orphan: boolean
}

/** Candidat administrateur de nœud + verdict de son rôle (R8/R9). */
type AdminCandidate = {
  id_user: number
  email: string
  full_name: string | null
  roles: string[]
  can_program: boolean          // a-t-il de quoi éditer un programme ?
  bypasses_governance: boolean  // org-admin : le nommer est un no-op
}

const NODE_TYPES = ['international', 'national', 'regional', 'department', 'store', 'custom']

/**
 * Gouvernance §XVIII — **mise en page A** (choix d'Ed, 2026-07-26) : arbre à gauche,
 * configuration au centre, programme compilé à droite.
 *
 * ⚠️ Page **verrouillée au viewport** : `DashboardShell` fournit déjà `h-screen
 * overflow-hidden`, chaque colonne défile pour son compte. L'ancienne page violait notre
 * propre règle (`<main flex-1 overflow-y-auto>` + arbre `h-fit`) : l'arbre partait vers le
 * haut dès qu'on descendait dans la configuration.
 *
 * Le nœud sélectionné vit dans l'**URL** (`?node=14`) : une configuration de gouvernance
 * se partage (« regarde le réglage du département Nord ») et survit à un rechargement.
 * Lecture via `window.location` et non `useSearchParams` — même raison que
 * `useSearchPrefill` : ce dernier impose un Suspense au build.
 */
export default function GovernancePage() {
  const t = useTranslations('governance')
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: nodes = [] } = useQuery<GovernanceNode[]>({
    queryKey: ['gov-nodes'],
    queryFn: () => api.get<GovernanceNode[]>('/governance/nodes').then((r) => r.data),
  })

  // Sélection initiale : ?node= si présent (et existant), sinon rien.
  const [urlRead, setUrlRead] = useState(false)
  useEffect(() => {
    if (urlRead || nodes.length === 0) return
    const raw = new URLSearchParams(window.location.search).get('node')
    const id = raw ? Number(raw) : NaN
    if (Number.isFinite(id) && nodes.some((n) => n.id_node === id)) setSelectedId(id)
    setUrlRead(true)
  }, [nodes, urlRead])

  // `replaceState` plutôt que `router.replace` : changer de nœud ne doit ni empiler une
  // entrée d'historique ni re-rendre l'arbre.
  const select = (id: number | null) => {
    setSelectedId(id)
    if (typeof window === 'undefined') return
    const url = new URL(window.location.href)
    if (id == null) url.searchParams.delete('node')
    else url.searchParams.set('node', String(id))
    window.history.replaceState(null, '', url.toString())
  }

  // R1 (revue du 2026-07-23) : le bouton créait le nœud IMMÉDIATEMENT, avec un nom par
  // défaut — et pour une racine ce nom était « Nouvelle région », alors qu'une racine est le
  // niveau le PLUS HAUT (national, voire international) : le premier clic poussait à
  // modéliser à l'envers. On passe par un drawer, comme partout ailleurs dans le produit
  // (règle « +Nouveau ouvre le drawer de création de la cible », 2026-07-18).
  const [createFor, setCreateFor] = useState<{ parent_id: number | null } | null>(null)

  const createNode = useMutation({
    mutationFn: (body: { node_name: string; node_type: string | null; parent_id: number | null }) =>
      api.post<GovernanceNode>('/governance/nodes', body).then((r) => r.data),
    onSuccess: (node) => {
      qc.invalidateQueries({ queryKey: ['gov-nodes'] })
      setCreateFor(null)
      select(node.id_node)
    },
  })

  return (
    <>
      <Topbar title={t('title')}>
        {/* N1 : créer un nœud RACINE est un acte d'org-admin (le serveur refuse en 403) —
            un gestionnaire de gouvernance ne crée que SOUS les nœuds qu'il administre. */}
        <Can admin>
          <Button size="sm" onClick={() => setCreateFor({ parent_id: null })}>
            <Plus className="w-3.5 h-3.5 mr-1" />{t('new_root')}
          </Button>
        </Can>
      </Topbar>

      {nodes.length === 0 ? (
        <main className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-400">
          <Network className="w-10 h-10" />
          <p className="text-sm">{t('empty')}</p>
        </main>
      ) : (
        <main className="flex-1 flex min-h-0">
          {/* ── Colonne 1 : arbre ── */}
          <aside className="w-[280px] shrink-0 border-r border-gray-100 overflow-y-auto">
            <NodeTree nodes={nodes} selectedId={selectedId} onSelect={select} />
          </aside>

          {/* ── Colonne 2 : configuration du nœud ── */}
          <section className="flex-1 min-w-0 overflow-y-auto px-5 py-4">
            {selectedId !== null ? (
              <NodeDetailPanel
                key={selectedId}
                nodeId={selectedId}
                t={t}
                onDeleted={() => select(null)}
                onAddChild={(id) => setCreateFor({ parent_id: id })}
              />
            ) : (
              <p className="text-sm text-gray-400">{t('select_node')}</p>
            )}
          </section>

          {/* ── Colonne 3 : programme compilé ── */}
          <aside className="w-[400px] shrink-0 border-l border-gray-100 min-h-0">
            {selectedId !== null && <CompiledProgramPanel key={selectedId} nodeId={selectedId} />}
          </aside>
        </main>
      )}

      {createFor && (
        <NodeCreateDrawer
          parentId={createFor.parent_id}
          parentName={nodes.find((n) => n.id_node === createFor.parent_id)?.node_name ?? null}
          t={t}
          pending={createNode.isPending}
          onClose={() => setCreateFor(null)}
          onCreate={(body) => createNode.mutate({ ...body, parent_id: createFor.parent_id })}
        />
      )}
    </>
  )
}

/**
 * R1 — création d'un nœud par formulaire. Le nom est OBLIGATOIRE (plus de nom par défaut
 * trompeur) et le niveau créé est annoncé : à la racine, on crée le niveau le PLUS HAUT,
 * ce que « Nouvelle région » laissait croire l'inverse.
 */
function NodeCreateDrawer({
  parentId, parentName, t, pending, onClose, onCreate,
}: {
  parentId: number | null
  parentName: string | null
  t: ReturnType<typeof useTranslations>
  pending: boolean
  onClose: () => void
  onCreate: (body: { node_name: string; node_type: string | null }) => void
}) {
  const [name, setName] = useState('')
  const [type, setType] = useState(parentId === null ? 'national' : 'store')

  return (
    <Drawer
      open
      onClose={onClose}
      title={parentId === null ? t('new_root') : t('add_child')}
      width="w-[420px]"
    >
      <div className="space-y-4" data-write-perm="governance:edit">
        <p className="text-xs text-gray-400">
          {parentId === null
            ? t('create_root_hint')
            : t('create_child_hint', { parent: parentName ?? '—' })}
        </p>
        <div>
          <label className="mb-1 block text-xs text-gray-400">{t('node_name')}</label>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) onCreate({ node_name: name.trim(), node_type: type || null }) }}
            className="w-full rounded-lg border border-gray-200 bg-surface px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-400">{t('node_type')}</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-surface px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none"
          >
            <option value="">—</option>
            {NODE_TYPES.map((nt) => <option key={nt} value={nt}>{t(`type_${nt}`)}</option>)}
          </select>
        </div>
        <Button
          data-write-action
          className="w-full"
          disabled={!name.trim()}
          loading={pending}
          onClick={() => onCreate({ node_name: name.trim(), node_type: type || null })}
        >
          {t('create')}
        </Button>
      </div>
    </Drawer>
  )
}

function NodeDetailPanel({
  nodeId, t, onDeleted, onAddChild,
}: {
  nodeId: number
  t: ReturnType<typeof useTranslations>
  onDeleted: () => void
  onAddChild: (parentId: number) => void
}) {
  const qc = useQueryClient()
  const { data } = useQuery<GovernanceNodeDetail>({
    queryKey: ['gov-node', nodeId],
    queryFn: () => api.get<GovernanceNodeDetail>(`/governance/nodes/${nodeId}`).then((r) => r.data),
  })

  const [name, setName] = useState('')
  const [type, setType] = useState('')
  const [editInit, setEditInit] = useState<number | null>(null)
  if (data && editInit !== data.id_node) {
    setName(data.node_name)
    setType(data.node_type ?? '')
    setEditInit(data.id_node)
  }

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['gov-nodes'] })
    qc.invalidateQueries({ queryKey: ['gov-node', nodeId] })
    // L'aperçu du programme compilé dépend des règles/assignations → le rafraîchir aussi.
    qc.invalidateQueries({ queryKey: ['compiled-schedule'] })
    qc.invalidateQueries({ queryKey: ['gov-node-players', nodeId] })
    qc.invalidateQueries({ queryKey: ['gov-node-playlists', nodeId] })
    qc.invalidateQueries({ queryKey: ['gov-node-schedules', nodeId] })
    qc.invalidateQueries({ queryKey: ['gov-node-coverage', nodeId] })
  }

  const save = useMutation({
    mutationFn: () => api.put(`/governance/nodes/${nodeId}`, { node_name: name, node_type: type || null }),
    onSuccess: invalidate,
  })
  const del = useMutation({
    mutationFn: () => api.delete(`/governance/nodes/${nodeId}`),
    onSuccess: () => { invalidate(); onDeleted() },
    onError: (e: unknown) => {
      if (isDemoBlocked(e)) return  // toast global démo → pas d'alerte moche
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(msg ?? t('delete_error'))
    },
  })

  if (!data) return <div className="sf-panel p-8" />

  const field = 'border border-gray-300 rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface'

  return (
    // Retour Ed 2026-07-26 : en FHD la colonne unique est juste, mais en 34" ultrawide et en 4K
    // elle laissait « un grand vide ». Grille CONTAINER-based (comme les vignettes de médias) :
    // le nombre de colonnes suit la largeur RÉELLEMENT disponible — pas un point de rupture de
    // viewport, qui se tromperait ici puisque l'arbre et l'aperçu mangent 680 px fixes.
    // `maxItemWidth` borne la piste : les panneaux gardent une largeur lisible et se CENTRENT,
    // au lieu de s'étirer sur 2 000 px pour remplir l'espace.
    <CardGrid
      minItemWidth={620}
      maxItemWidth={760}
      className="mx-auto w-full max-w-[1560px]"
    >
      {/* Identité du nœud : pleine largeur, elle ne se met pas « à côté » de sa configuration. */}
      <section className="sf-panel p-5 space-y-3 col-span-full">
        <div className="flex items-end gap-2 flex-wrap">
          <div className="flex-1 min-w-[160px]">
            <label className="block text-xs text-gray-400 mb-1">{t('node_name')}</label>
            <input value={name} onChange={(e) => setName(e.target.value)} disabled={!(data.can_edit ?? true)} className={`${field} w-full`} />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">{t('node_type')}</label>
            <select value={type} onChange={(e) => setType(e.target.value)} disabled={!(data.can_edit ?? true)} className={field}>
              <option value="">—</option>
              {NODE_TYPES.map((nt) => <option key={nt} value={nt}>{t(`type_${nt}`)}</option>)}
            </select>
          </div>
          {(data.can_edit ?? true) && (
            <Button size="sm" onClick={() => save.mutate()} loading={save.isPending}>{t('save')}</Button>
          )}
        </div>
        {/* R2 : le NIVEAU est la seule donnée qui fixe l'ordre national→local dans la
            compilation des couches — et il n'était affiché nulle part. L'arbre montrait le
            type, qui lui est purement décoratif. */}
        <p className="text-[11px] text-gray-400" data-testid="node-level">
          {t('node_level_hint', { level: data.node_level })}
        </p>
        {/* N1 : ces actes de STRUCTURE sont désormais refusés (403) hors du sous-arbre
            administré — on ne montre pas des boutons qui mènent toujours à un refus. */}
        {(data.can_edit ?? true) && (
          <div className="flex items-center justify-between pt-1">
            <button
              onClick={() => onAddChild(nodeId)}
              className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
            >
              <Plus className="w-3.5 h-3.5" />{t('add_child')}
            </button>
            <button
              onClick={() => { if (confirm(t('delete_confirm'))) del.mutate() }}
              className="inline-flex items-center gap-1 text-xs text-danger hover:underline"
            >
              <Trash2 className="w-3.5 h-3.5" />{t('delete_node')}
            </button>
          </div>
        )}
      </section>

      <RestrictionsCard node={data} onChange={invalidate} />
      <RulesCard node={data} onChange={invalidate} />
      <NodeWorkspaceCard nodeId={nodeId} canEdit={data.can_edit ?? true} onChange={invalidate} />
      {/* Cibles ET administrateurs dans UN panneau (retour Ed) : « qui reçoit » et « qui
          administre » sont les deux faces de l'accès au nœud, et ça donne une grille 2×2
          pleine plutôt qu'une carte orpheline en dernière ligne. */}
      <section className="sf-panel p-5 space-y-4">
        <AssignmentsCard
          nodeId={nodeId}
          assignments={data.assignments}
          canEdit={data.can_edit ?? true}
          t={t}
          onChange={invalidate}
        />
        <AdminsCard
          nodeId={nodeId}
          nodeName={data.node_name}
          admins={data.admins}
          canEdit={data.can_edit ?? true}
          t={t}
          onChange={invalidate}
        />
      </section>
    </CardGrid>
  )
}

function AssignmentsCard({
  nodeId, assignments, canEdit, t, onChange,
}: {
  nodeId: number
  assignments: GovernanceNodeDetail['assignments']
  canEdit: boolean
  t: ReturnType<typeof useTranslations>
  onChange: () => void
}) {
  const [mapOpen, setMapOpen] = useState(false)
  // R4 : la sélection se fait côté SERVEUR (drawer de recherche), plus dans quatre listes
  // déroulantes qui chargeaient tout le parc à chaque ouverture d'un nœud.
  const [pickerOpen, setPickerOpen] = useState(false)
  // G1/G2 : source DÉDIÉE — `/players/` est désormais filtré par le périmètre (N8), ce qui
  // viderait ce sélecteur pour l'usage même auquel il sert ; `attachable-players` rend le
  // sous-arbre + les écrans orphelins si l'utilisateur administre une racine (étiquetés).

  const remove = useMutation({
    mutationFn: (b: { target_type: string; target_id: number }) =>
      api.request({ method: 'DELETE', url: `/governance/nodes/${nodeId}/assignments`, data: b }),
    onSuccess: onChange,
  })

  const icon = (tt: string) =>
    tt === 'player' ? <Monitor className="w-3.5 h-3.5" />
      : tt === 'group' ? <Users className="w-3.5 h-3.5" />
        : tt === 'site_group' ? <Map className="w-3.5 h-3.5" />
          : <Building2 className="w-3.5 h-3.5" />

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{t('assignments')}</p>
        {/* Carte 1 : à l'échelle d'un réseau, on ne compose pas un périmètre de 100 magasins
            dans une liste déroulante. La carte reste un RACCOURCI — les sélecteurs ci-dessous
            restent la voie complète (players, groupes de players). */}
        {canEdit && (
          <button
            onClick={() => setMapOpen(true)}
            className="text-xs text-accent hover:underline inline-flex items-center gap-1"
          >
            <Map className="w-3.5 h-3.5" />{t('pick_on_map')}
          </button>
        )}
      </div>
      {mapOpen && (
        <PerimeterMapModal
          nodeId={nodeId}
          assignments={assignments}
          onClose={() => setMapOpen(false)}
          onChanged={onChange}
        />
      )}

      {assignments.length === 0 ? (
        <p className="text-xs text-gray-400">{t('no_assignments')}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {assignments.map((a) => (
            <span key={`${a.target_type}-${a.target_id}`} className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded max-w-[220px]">
              {icon(a.target_type)}
              <MarqueeText text={a.target_name ?? `#${a.target_id}`} className="min-w-0" />
              {canEdit && (
                <button onClick={() => remove.mutate({ target_type: a.target_type, target_id: a.target_id })} className="text-gray-400 hover:text-danger ml-0.5">×</button>
              )}
            </span>
          ))}
        </div>
      )}

      {canEdit && (
        <button
          onClick={() => setPickerOpen(true)}
          data-testid="gov-add-targets"
          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs text-accent hover:bg-surface-hover"
        >
          <Plus className="w-3.5 h-3.5" />{t('add_targets')}
        </button>
      )}
      {pickerOpen && (
        <TargetPickerDrawer
          nodeId={nodeId}
          assignments={assignments}
          t={t}
          onClose={() => setPickerOpen(false)}
          onAdded={() => { setPickerOpen(false); onChange() }}
        />
      )}
    </div>
  )
}

/** Résultat uniforme de `/governance/targets/search` (R4). */
type TargetHit = {
  target_type: string
  target_id: number
  name: string
  subtitle: string | null
  player_count: number
  /** G2 : écran encore rattaché à AUCUN nœud — le rattacher le fait entrer en gouvernance. */
  orphan: boolean
}

const TARGET_KINDS = ['player', 'group', 'site', 'site_group'] as const

/**
 * R4 — sélection de cibles à l'échelle. Remplace les quatre listes déroulantes qui
 * chargeaient TOUT le parc à chaque ouverture d'un nœud (2000 `<option>` natives à 2000
 * écrans) et n'ajoutaient qu'une cible à la fois.
 *
 * Même patron que le picker de créatifs refondu le 2026-07-10 (validé par Ed) : pastilles
 * par type, recherche débouncée **côté serveur**, multi-sélection, « Ajouter (n) » en un
 * seul appel. Le **nombre d'écrans résolus** est affiché par ligne : dès qu'on mêle
 * groupes, sites et groupes de sites, on ne sait plus ce qu'on vient de sélectionner.
 */
function TargetPickerDrawer({
  nodeId, assignments, t, onClose, onAdded,
}: {
  nodeId: number
  assignments: GovernanceNodeDetail['assignments']
  t: ReturnType<typeof useTranslations>
  onClose: () => void
  onAdded: () => void
}) {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [kinds, setKinds] = useState<string[]>([...TARGET_KINDS])
  const [picked, setPicked] = useState<TargetHit[]>([])
  const [error, setError] = useState<string | null>(null)

  // Débounce : une frappe = une requête serveur, pas une par caractère.
  useEffect(() => {
    const id = setTimeout(() => setDebounced(q), 250)
    return () => clearTimeout(id)
  }, [q])

  const { data: hits = [], isFetching } = useQuery<TargetHit[]>({
    queryKey: ['gov-target-search', debounced, kinds.join(',')],
    queryFn: () => api.get<TargetHit[]>('/governance/targets/search', {
      params: { q: debounced, types: kinds.join(',') },
    }).then((r) => r.data),
    enabled: kinds.length > 0,
  })

  const already = (h: TargetHit) =>
    assignments.some((a) => a.target_type === h.target_type && a.target_id === h.target_id)
  const isPicked = (h: TargetHit) =>
    picked.some((x) => x.target_type === h.target_type && x.target_id === h.target_id)

  const addAll = useMutation({
    mutationFn: () => api.post(
      `/governance/nodes/${nodeId}/assignments/batch`,
      picked.map((h) => ({ target_type: h.target_type, target_id: h.target_id })),
    ),
    onSuccess: onAdded,
    // Le serveur refuse une cible hors périmètre EN LA NOMMANT : ce message doit
    // remonter tel quel, un « erreur » générique ne dirait pas quel écran pose problème.
    onError: (e: unknown) => setError(
      (e as { response?: { data?: { detail?: string } }; message?: string })
        .response?.data?.detail ?? (e as { message?: string }).message ?? null,
    ),
  })

  const totalScreens = picked.reduce((n, h) => n + h.player_count, 0)

  return (
    <Drawer open onClose={onClose} title={t('add_targets')} width="w-[520px]">
      <div className="space-y-3" data-write-perm="governance:edit">
        <div className="flex flex-wrap gap-1.5">
          {TARGET_KINDS.map((k) => (
            <button
              key={k}
              onClick={() => setKinds((prev) =>
                prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k])}
              className={`rounded-full border px-2.5 py-1 text-xs ${
                kinds.includes(k)
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-gray-200 text-gray-400'
              }`}
            >
              {t(`target_kind_${k}`)}
            </button>
          ))}
        </div>

        <input
          autoFocus
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('target_search_placeholder')}
          className="w-full rounded-lg border border-gray-200 bg-surface px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none"
        />

        <div className="max-h-[45vh] space-y-1 overflow-y-auto" data-testid="gov-target-hits">
          {hits.length === 0 && !isFetching && (
            <p className="text-xs text-gray-400">{t('target_no_result')}</p>
          )}
          {hits.map((h) => {
            const done = already(h)
            return (
              <button
                key={`${h.target_type}-${h.target_id}`}
                disabled={done}
                onClick={() => setPicked((prev) => isPicked(h)
                  ? prev.filter((x) => !(x.target_type === h.target_type && x.target_id === h.target_id))
                  : [...prev, h])}
                className={`flex w-full items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-left text-sm ${
                  done ? 'border-gray-100 opacity-50'
                    : isPicked(h) ? 'border-accent bg-accent/10' : 'border-gray-200 hover:bg-surface-hover'
                }`}
              >
                <span className="min-w-0">
                  <span className="block truncate">{h.name}</span>
                  <span className="block text-[11px] text-gray-400">
                    {t(`target_kind_${h.target_type}`)}
                    {h.subtitle ? ` · ${h.subtitle}` : ''}
                    {h.orphan ? ` · ${t('orphan_suffix')}` : ''}
                    {done ? ` · ${t('target_already')}` : ''}
                  </span>
                </span>
                {/* Le nombre d'écrans RÉSOLUS : c'est la seule donnée qui dise ce qu'on
                    vient réellement de sélectionner quand on mêle les natures de cible. */}
                <span className="shrink-0 text-[11px] text-gray-400">
                  {t('target_screens', { count: h.player_count })}
                </span>
              </button>
            )
          })}
        </div>

        {error && <p className="text-xs text-danger">{error}</p>}

        <Button
          data-write-action
          className="w-full"
          disabled={picked.length === 0}
          loading={addAll.isPending}
          onClick={() => { setError(null); addAll.mutate() }}
        >
          {t('target_add_n', { count: picked.length, screens: totalScreens })}
        </Button>
      </div>
    </Drawer>
  )
}

// ── Administrateurs de nœud (immutabilité §18.4) ─────────────────────────────
// Un user affecté ici peut créer/éditer/supprimer les programmes rattachés à ce
// nœud ET à son sous-arbre (national édite tout en dessous). L'org-admin contourne.
function AdminsCard({
  nodeId, nodeName, admins, canEdit, t, onChange,
}: {
  nodeId: number
  nodeName: string
  admins: GovernanceNodeDetail['admins']
  canEdit: boolean
  t: ReturnType<typeof useTranslations>
  onChange: () => void
}) {
  const [creating, setCreating] = useState(false)
  const tRoot = useTranslations()  // roleLabel lit `iam.role_labels.*` (hors namespace governance)
  // R8/R9 : le rôle est DÉTERMINANT et n'était affiché nulle part — c'est précisément son
  // absence qui a fait douter Ed (« un approbateur, ça marcherait ? » → non : nommer
  // quelqu'un sans `schedules:edit` fabrique un admin de nœud sans aucun pouvoir, en
  // silence ; et nommer un org-admin est un no-op, il contourne déjà la gouvernance).
  const { data: candidates = [] } = useQuery<AdminCandidate[]>({
    queryKey: ['gov-admin-candidates'],
    queryFn: () => api.get<AdminCandidate[]>('/governance/admin-candidates').then((r) => r.data),
  })

  const add = useMutation({
    mutationFn: (id_user: number) => api.post(`/governance/nodes/${nodeId}/admins`, { id_user }),
    onSuccess: onChange,
  })
  const remove = useMutation({
    mutationFn: (id_user: number) =>
      api.request({ method: 'DELETE', url: `/governance/nodes/${nodeId}/admins`, data: { id_user } }),
    onSuccess: onChange,
  })

  const hasAdmin = (id: number) => admins.some((a) => a.id_user === id)

  return (
    <div className="space-y-3 border-t border-gray-100 pt-4">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
        <ShieldCheck className="w-3.5 h-3.5" />{t('admins')}
      </p>
      <p className="text-[11px] text-gray-400">{t('admins_hint')}</p>

      {admins.length === 0 ? (
        <p className="text-xs text-gray-400">{t('no_admins')}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {admins.map((a) => (
            <span key={a.id_user} className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded max-w-[220px]">
              <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
              <MarqueeText text={a.full_name || a.email} className="min-w-0" />
              <button onClick={() => remove.mutate(a.id_user)} className="text-gray-400 hover:text-danger ml-0.5">×</button>
            </span>
          ))}
        </div>
      )}

      {/* R8 : les deux nominations qui ne servent à rien, dites À L'ÉCRAN. Elles sont
          silencieuses par construction — « admin de nœud » ne fait que RESTREINDRE
          par-dessus le RBAC, il n'accorde jamais rien. */}
      {admins.map((a) => {
        const c = candidates.find((u) => u.id_user === a.id_user)
        if (!c) return null
        const who = a.full_name || a.email
        if (c.bypasses_governance) {
          return (
            <p key={`w-${a.id_user}`} className="text-[11px] text-amber-600 dark:text-amber-300"
               data-testid="admin-warning">
              {t('admin_bypasses', { who })}
            </p>
          )
        }
        if (!c.can_program) {
          return (
            <p key={`w-${a.id_user}`} className="text-[11px] text-amber-600 dark:text-amber-300"
               data-testid="admin-warning">
              {t('admin_cannot_program', { who })}
            </p>
          )
        }
        return null
      })}

      <div className="flex flex-wrap items-center gap-2">
        <select
          value=""
          onChange={(e) => { const id = Number(e.target.value); if (id) add.mutate(id) }}
          className="border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-surface max-w-full"
        >
          <option value="">+ {t('add_admin')}</option>
          {candidates.filter((u) => !hasAdmin(u.id_user)).map((u) => (
            // Le rôle est DANS l'option : c'est la seule façon de choisir en connaissance
            // de cause au moment du geste (un libellé après coup arriverait trop tard).
            <option key={u.id_user} value={u.id_user}>
              {(u.full_name || u.email)
                + (u.roles.length
                  ? ` — ${u.roles.map((r) => roleLabel({ role_key: r, label: r }, tRoot)).join(', ')}`
                  : ` — ${t('admin_no_role')}`)}
            </option>
          ))}
        </select>
        {/* Rattacher quelqu'un qui existe déjà VS créer le compte : deux gestes distincts,
            le second évitait jusqu'ici trois pages d'aller-retour (demande Ed 26/07). */}
        {canEdit && (
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
          >
            <Plus className="w-3.5 h-3.5" />{t('admin_create_open')}
          </button>
        )}
      </div>
      {creating && (
        <NewNodeAdminDrawer
          nodeId={nodeId}
          nodeName={nodeName}
          onClose={() => setCreating(false)}
          onCreated={onChange}
        />
      )}
    </div>
  )
}
