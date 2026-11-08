'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { ListVideo, Trash2, Play } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import SearchInput from '@/components/ui/SearchInput'
import { CardGrid, EntityCard } from '@/components/ui/CardGrid'
import SyncBadge from './SyncBadge'
import PlaylistPlayer from './PlaylistPlayer'
import NodeSelect, { GovernedBadge } from '@/components/governance/NodeSelect'
import api from '@/lib/api'
import { formatMs } from '@/lib/formatMs'
import { useCreateShortcut } from '@/lib/useCreateShortcut'
import type { PlaylistRead } from '@/types/api'

export default function PlaylistsPage() {
  const t = useTranslations()
  const router = useRouter()
  const qc = useQueryClient()
  const [drawerOpen, setDrawerOpen] = useState(false)
  useCreateShortcut(() => setDrawerOpen(true))
  const [search, setSearch] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  // Contenu gouverné §XVIII : nœud propriétaire choisi à la création (null = org).
  const [govNode, setGovNode] = useState<number | null>(null)
  // Lecture d'une playlist depuis sa carte, sans quitter la liste.
  const [playingId, setPlayingId] = useState<number | null>(null)

  const { data: playlists = [], isLoading } = useQuery<PlaylistRead[]>({
    queryKey: ['playlists'],
    queryFn: () => api.get<PlaylistRead[]>('/playlists/').then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post<PlaylistRead>('/playlists', {
        playlist_name: name,
        description: description || null,
        id_governance_node: govNode,
      }),
    onSuccess: ({ data }) => {
      qc.invalidateQueries({ queryKey: ['playlists'] })
      setDrawerOpen(false)
      setName('')
      setDescription('')
      setGovNode(null)
      setCreateError(null)
      router.push(`/playlists/${data.id_playlist}`)
    },
    onError: () => setCreateError(t('common.error')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/playlists/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playlists'] }),
  })

  return (
    <>
      <Topbar title={t('playlists.title')}>
        <Can perm="playlists:create">
          <Button size="sm" onClick={() => setDrawerOpen(true)}>
            {t('playlists.new')}
          </Button>
        </Can>
      </Topbar>

      {/* Page verrouillée au viewport : recherche fixe, seules les vignettes défilent
          (la grille reste responsive : nb de colonnes selon la résolution). */}
      <main className="flex-1 flex flex-col min-h-0 px-6">
          {isLoading ? (
            <div className="flex justify-center py-16">
              <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : playlists.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3 text-gray-400">
              <ListVideo className="w-10 h-10" />
              <p className="text-sm">{t('playlists.no_playlists')}</p>
            </div>
          ) : (
            <>
              <div className="shrink-0 pt-8 pb-4">
                <SearchInput
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('common.search')}
                />
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto pb-8">
              <CardGrid minItemWidth={300}>
                {playlists
                  .filter((pl) => !search || pl.playlist_name.toLowerCase().includes(search.toLowerCase()) || (pl.description ?? '').toLowerCase().includes(search.toLowerCase()))
                  .map((pl) => (
                    <EntityCard
                      key={pl.id_playlist}
                      onClick={() => router.push(`/playlists/${pl.id_playlist}`)}
                      title={pl.playlist_name}
                      titleTitle={pl.playlist_name}
                      subtitle={pl.description || undefined}
                      actions={
                        <>
                        {/* Lecture de la playlist sans quitter la liste (demande d'Ed
                            2026-07-29). Pas de <Can> : regarder n'est pas modifier —
                            un rôle en lecture seule y a droit comme les autres. */}
                        <button
                          onClick={(e) => { e.stopPropagation(); setPlayingId(pl.id_playlist) }}
                          className="p-1 rounded text-gray-400 hover:text-accent hover:bg-accent/10 transition-sf"
                          title={t('playlists.play_preview')}
                        >
                          <Play className="w-4 h-4" />
                        </button>
                        {/* Gouvernance D6 : une playlist d'un nœud qu'on n'administre pas
                            est visible mais intouchable — la poubelle finirait en 403. */}
                        <Can perm="playlists:delete">
                          {pl.governed_readonly ? null : <button
                            onClick={(e) => {
                              e.stopPropagation()
                              if (confirm(t('playlists.delete_playlist_confirm'))) deleteMutation.mutate(pl.id_playlist)
                            }}
                            className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf"
                            title={t('common.delete')}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>}
                        </Can>
                        </>
                      }
                      badges={
                        <>
                          <SyncBadge pl={pl} t={t} />
                          <GovernedBadge idNode={pl.id_governance_node} readonly={pl.governed_readonly} />
                          {(pl.rotation_mode === 'one_sequential' || pl.rotation_mode === 'one_random') && (
                            <span
                              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent"
                              title={t('playlists.rotation_hint')}
                            >
                              <ListVideo className="w-3 h-3" />
                              {t('playlists.rotation_badge', { k: pl.items_per_turn ?? 1 })}
                            </span>
                          )}
                        </>
                      }
                      footer={
                        <div className="flex items-center justify-between gap-2">
                          {/* Contenu de la boucle : nb d'items + durée totale (calcul
                              serveur, même repli 10 s que le wall-clock du player). */}
                          <span className="text-gray-400 truncate">
                            {t('playlists.items_summary', { count: pl.item_count ?? 0 })}
                            {(pl.item_count ?? 0) > 0 && pl.total_duration_ms != null && (
                              <> · {formatMs(pl.total_duration_ms)}</>
                            )}
                          </span>
                          <span className="text-gray-400 shrink-0">{new Date(pl.created_at).toLocaleDateString()}</span>
                        </div>
                      }
                    />
                  ))}
              </CardGrid>
              </div>
            </>
          )}
      </main>

      {/* Lecture de la playlist choisie (rendue avant le drawer : à z égal, l'ordre DOM
          laisse un drawer ouvert passer devant). */}
      <PlaylistPlayer idPlaylist={playingId} onClose={() => setPlayingId(null)} />

      <Drawer open={drawerOpen} onClose={() => { setDrawerOpen(false); setCreateError(null) }} title={t('playlists.new')}>
        <div className="space-y-5">
          <Input
            label={t('playlists.name_label')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <Input
            label={t('playlists.description_label')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          {/* Contenu gouverné §XVIII : ne s'affiche que si l'org a des nœuds. */}
          <NodeSelect value={govNode} onChange={setGovNode} />
          {createError && (
            <p className="text-sm text-danger">{createError}</p>
          )}
          <Button
            onClick={() => createMutation.mutate()}
            loading={createMutation.isPending}
            disabled={!name.trim()}
            className="w-full"
          >
            {t('common.create')}
          </Button>
        </div>
      </Drawer>
    </>
  )
}
