'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation } from '@tanstack/react-query'
import { CalendarClock, ExternalLink, ListVideo, Plus } from 'lucide-react'
import MarqueeText from '@/components/ui/MarqueeText'
import api from '@/lib/api'
import type { PlaylistRead, ScheduleRead } from '@/types/api'

type NodeCoverage = {
  id_node: number
  perimeter_count: number
  schedules: {
    id_schedule: number
    schedule_name: string
    is_active: boolean
    target_count: number
    resolved_count: number
  }[]
  uncovered: { id_player: number; player_name: string | null }[]
}

/**
 * « Contenu de ce nœud » — l'espace de travail manquant (demande Ed 2026-07-26, point ⑥ de
 * sa liste du 25/07).
 *
 * Avant, monter une gouvernance imposait Playlists → Schedules → Governance avec des
 * allers-retours et un re-dépliage de l'arbre à chaque passage. Ici, on voit ce que le nœud
 * porte et on le crée sur place, **déjà rattaché**.
 *
 * 🔑 Deux notions volontairement SÉPARÉES à l'écran, parce que les confondre a réellement
 * coûté une recherche à l'aveugle le 25/07 : une **playlist** rattachée au nœud décide QUI
 * l'édite et si elle est modérée — elle ne diffuse rien. C'est le **programme** rattaché au
 * même nœud qui met le contenu à l'antenne.
 */
export default function NodeWorkspaceCard({
  nodeId, canEdit, onChange,
}: {
  nodeId: number
  canEdit: boolean
  onChange: () => void
}) {
  const t = useTranslations('governance')
  const [error, setError] = useState<string | null>(null)

  const { data: playlists = [] } = useQuery<PlaylistRead[]>({
    queryKey: ['gov-node-playlists', nodeId],
    queryFn: () => api.get<PlaylistRead[]>('/playlists/', {
      params: { id_governance_node: nodeId, limit: 200 },
    }).then((r) => r.data),
  })
  const { data: schedules = [] } = useQuery<ScheduleRead[]>({
    queryKey: ['gov-node-schedules', nodeId],
    queryFn: () => api.get<ScheduleRead[]>('/schedules', {
      params: { id_governance_node: nodeId, limit: 200 },
    }).then((r) => r.data),
  })
  // D-b : « qui reçoit quoi » dans ce nœud. Deux réponses en une lecture — les écrans
  // retenus par chaque programme (ses cibles restreignent le périmètre), et ceux qu'aucune
  // couche LOCALE ne vise. Ce second compteur est la contrepartie assumée de D1 : un écran
  // installé et oublié dans son groupe ne reçoit que l'héritage, sans que rien ne le dise.
  const { data: coverage } = useQuery<NodeCoverage>({
    queryKey: ['gov-node-coverage', nodeId],
    queryFn: () => api.get<NodeCoverage>(`/governance/nodes/${nodeId}/coverage`).then((r) => r.data),
  })
  const scopeOf = (id: number) => coverage?.schedules.find((s) => s.id_schedule === id)

  const fail = (e: unknown) => {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setError(typeof msg === 'string' && msg ? msg : t('workspace_error'))
  }

  // Création PRÉ-RATTACHÉE au nœud : c'est tout l'intérêt: on ne peut pas oublier le
  // rattachement, qui est justement ce qu'on oubliait en passant par les autres pages.
  const newPlaylist = useMutation({
    mutationFn: () => api.post<PlaylistRead>('/playlists', {
      playlist_name: t('workspace_new_playlist_name'),
      id_governance_node: nodeId,
    }).then((r) => r.data),
    onSuccess: (pl) => { setError(null); onChange(); window.location.href = `/playlists/${pl.id_playlist}` },
    onError: fail,
  })
  // ⚠️ Deux gardes du modèle, appliquées ICI plutôt que subies plus tard :
  //  · un programme « contenu » EXIGE une playlist (422 sinon) ;
  //  · un programme SANS règle horaire n'est JAMAIS actif. C'est la cause `no_rule` que
  //    l'aperçu doit nommer (R10) ; en créer un vide reviendrait à fabriquer le piège.
  //    On pose donc une règle `always`, que l'utilisateur restreindra s'il le veut.
  //  · aucune CIBLE n'est posée : sans cible, le programme couvre TOUT le nœud (D0). Pour
  //    n'en viser qu'une partie (« entrée » vs « boucherie »), on ajoute des cibles depuis
  //    /schedules — elles ne peuvent que RESTREINDRE le périmètre du nœud (D-b).
  //
  // 🔑 L'ORDRE DU GESTE suit celui de l'utilisateur (retour Ed 2026-07-26) : « je n'ai pas de
  // programme, j'en crée un ; si j'ai déjà une playlist je la choisis, sinon je la crée ».
  // Un sélecteur posé en permanence sous la liste demandait de RE-choisir une playlist déjà
  // visible juste au-dessus, sans qu'on comprenne pourquoi. Il n'apparaît donc qu'après le
  // clic, et seulement s'il y a un vrai choix à faire — avec une seule playlist, on ne pose
  // pas la question.
  const [choosing, setChoosing] = useState(false)
  const newSchedule = useMutation({
    mutationFn: (id_playlist: number) => api.post<ScheduleRead>('/schedules', {
      schedule_name: t('workspace_new_schedule_name'),
      schedule_kind: 'content',
      id_playlist,
      id_governance_node: nodeId,
      rules: [{ rule_type: 'always' }],
      targets: [],
    }).then((r) => r.data),
    onSuccess: () => { setError(null); setChoosing(false); onChange() },
    onError: fail,
  })

  const startSchedule = () => {
    if (playlists.length === 1) newSchedule.mutate(playlists[0].id_playlist)
    else setChoosing(true)
  }

  return (
    <section className="sf-panel p-5 space-y-4" data-testid="gov-workspace">
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          {t('workspace_title')}
        </p>
        <p className="text-[11px] text-gray-400 mt-1">{t('workspace_hint')}</p>
      </div>

      <Block
        icon={<ListVideo className="w-3.5 h-3.5" />}
        label={t('workspace_playlists')}
        hint={t('workspace_playlists_hint')}
        empty={t('workspace_no_playlist')}
        addLabel={t('workspace_add_playlist')}
        canEdit={canEdit}
        pending={newPlaylist.isPending}
        onAdd={() => newPlaylist.mutate()}
        rows={playlists.map((pl) => ({
          key: pl.id_playlist,
          name: pl.playlist_name,
          href: `/playlists/${pl.id_playlist}`,
          note: pl.has_draft_changes ? t('workspace_draft') : null,
        }))}
      />

      <Block
        icon={<CalendarClock className="w-3.5 h-3.5" />}
        label={t('workspace_schedules')}
        hint={t('workspace_schedules_hint')}
        // Un nœud SANS programme est la cause n°1 de « rien ne s'affiche » : on le dit ici,
        // pas seulement dans l'aperçu du programme compilé où on arrive déjà perplexe.
        empty={t('workspace_no_schedule')}
        addLabel={t('workspace_add_schedule')}
        canEdit={canEdit}
        addDisabled={playlists.length === 0}
        pending={newSchedule.isPending}
        onAdd={startSchedule}
        rows={schedules.map((sc) => {
          const sp = scopeOf(sc.id_schedule)
          return {
            key: sc.id_schedule,
            name: sc.schedule_name,
            href: '/schedules',
            note: !sc.is_active ? t('workspace_inactive')
              // Toujours afficher le RÉSULTAT résolu (D3) : « tous » vs « N sur M ».
              : sp && sp.target_count > 0
                ? t('workspace_scope_partial',
                    { count: sp.resolved_count, total: coverage?.perimeter_count ?? 0 })
                : sp ? t('workspace_scope_all', { count: sp.resolved_count }) : null,
          }
        })}
        // Le compteur parle DANS LES DEUX CAS. N'afficher que l'alerte laissait croire que
        // rien n'est mesuré tant que tout va bien — or c'est justement la ligne qui dit
        // « le périmètre est couvert », et qui rend l'alerte crédible quand elle apparaît.
        footer={coverage && coverage.perimeter_count > 0 ? (
          coverage.uncovered.length > 0 ? (
            <p className="text-[11px] text-amber-600 dark:text-amber-300 mt-1.5"
               data-testid="gov-uncovered">
              {t('workspace_uncovered', {
                count: coverage.uncovered.length,
                names: coverage.uncovered
                  .map((u) => u.player_name ?? `#${u.id_player}`).slice(0, 4).join(', '),
              })}
            </p>
          ) : (
            <p className="text-[11px] text-gray-400 mt-1.5" data-testid="gov-covered">
              {t('workspace_all_covered', { count: coverage.perimeter_count })}
            </p>
          )
        ) : null}
        extra={canEdit && playlists.length === 0 ? (
          // Le bouton reste VISIBLE mais désactivé : un bouton qui disparaît ne s'explique
          // pas. La phrase dit quoi faire — créer la playlist d'abord.
          <p className="text-[11px] text-amber-600 dark:text-amber-300 mt-1.5">
            {t('workspace_schedule_needs_playlist')}
          </p>
        ) : choosing ? (
          <div className="mt-1.5 space-y-1">
            <p className="text-[11px] text-gray-400">{t('workspace_pick_playlist_hint')}</p>
            <select
              autoFocus
              defaultValue=""
              onChange={(e) => { if (e.target.value) newSchedule.mutate(Number(e.target.value)) }}
              className="w-full border border-gray-300 rounded-md px-2 py-1 text-xs bg-surface"
            >
              <option value="">{t('workspace_pick_playlist')}</option>
              {playlists.map((pl) => (
                <option key={pl.id_playlist} value={pl.id_playlist}>{pl.playlist_name}</option>
              ))}
            </select>
            <button onClick={() => setChoosing(false)}
                    className="text-[11px] text-gray-400 hover:text-gray-600">
              {t('cancel_action')}
            </button>
          </div>
        ) : null}
      />

      {error && <p className="text-[11px] text-danger">{error}</p>}
    </section>
  )
}

function Block({
  icon, label, hint, empty, addLabel, canEdit, pending, onAdd, rows, extra, addDisabled, footer,
}: {
  icon: React.ReactNode
  label: string
  hint: string
  empty: string
  addLabel: string
  canEdit: boolean
  pending: boolean
  onAdd: () => void
  rows: { key: number; name: string; href: string; note: string | null }[]
  extra?: React.ReactNode
  addDisabled?: boolean
  footer?: React.ReactNode
}) {
  return (
    <div className="border-t border-gray-100 pt-3 first:border-t-0 first:pt-0">
      <div className="flex items-center gap-1.5">
        <span className="text-gray-400">{icon}</span>
        <span className="text-sm font-medium text-gray-800 flex-1">{label}</span>
        <span className="text-[11px] text-gray-400">{rows.length}</span>
      </div>
      <p className="text-[11px] text-gray-400 mb-1.5">{hint}</p>

      {rows.length === 0 ? (
        <p className="text-xs text-gray-400">{empty}</p>
      ) : (
        <div className="space-y-1">
          {rows.map((r) => (
            <a
              key={r.key}
              href={r.href}
              className="flex items-center gap-2 text-sm text-gray-700 hover:text-accent transition-sf group"
            >
              <MarqueeText text={r.name} className="flex-1 min-w-0" />
              {r.note && <span className="text-[10px] text-gray-400 shrink-0">{r.note}</span>}
              <ExternalLink className="w-3 h-3 shrink-0 opacity-0 group-hover:opacity-100" />
            </a>
          ))}
        </div>
      )}

      {footer}
      {extra}
      {canEdit && (
        <button
          onClick={onAdd}
          disabled={pending || addDisabled}
          className="mt-1.5 inline-flex items-center gap-1 text-xs text-accent hover:underline disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />{addLabel}
        </button>
      )}
    </div>
  )
}
