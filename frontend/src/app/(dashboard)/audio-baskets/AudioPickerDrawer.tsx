'use client'

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { FolderTree as FolderTreeIcon, Headphones, Music, Plus } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import SearchInput from '@/components/ui/SearchInput'
import api from '@/lib/api'
import type { AudioBasket, BasketItem, MediaListItem } from '@/types/api'
import FolderTree, { type FolderFilter } from '../media/components/FolderTree'
import MediaViewer from '../media/components/MediaViewer'

/**
 * Drawer de sélection de contenus AUDIO pour un panier — à l'image du drawer « Ajouter un
 * média » des playlists (demande Ed 2026-07-29) : recherche RÉSOLUE PAR LE SERVEUR,
 * arbre de dossiers, multi-sélection, et PRÉ-ÉCOUTE d'un morceau avant de l'ajouter.
 *
 * L'ancien picker chargeait `/media/?media_type=audio` en une requête plate SANS recherche :
 * depuis la pagination server-side de la médiathèque (08/07), il ne montrait que la première
 * page — un morceau existant pouvait être introuvable, sans message. Même classe de défaut
 * que le picker des playlists corrigé le 20/07.
 *
 * ⚠️ Rendu AU NIVEAU DE LA PAGE, jamais imbriqué dans un autre Drawer : le panneau du
 * Drawer porte un `transform` (translate), qui devient le bloc conteneur de tout `fixed`
 * descendant — un Drawer imbriqué serait découpé dans le panneau parent.
 */

interface Props {
  /** Panier destinataire (null = fermé). */
  basket: AudioBasket | null
  onClose: () => void
}

export default function AudioPickerDrawer({ basket, onClose }: Props) {
  const t = useTranslations()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [folder, setFolder] = useState<FolderFilter>('all')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  // Pré-écoute : index dans la liste courante (la visionneuse passe au-dessus du drawer).
  const [preview, setPreview] = useState<number | null>(null)

  const open = basket !== null

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(timer)
  }, [search])

  // Réouverture pour un autre panier → état neuf.
  useEffect(() => {
    if (open) { setSearch(''); setFolder('all'); setPicked(new Set()); setPreview(null) }
  }, [open, basket?.id_basket])

  // Items déjà présents : on les montre cochés-grisés plutôt que de les cacher — les
  // cacher ferait croire que le morceau n'existe pas dans la médiathèque.
  const { data: existing = [] } = useQuery<BasketItem[]>({
    queryKey: ['basket-items', basket?.id_basket],
    queryFn: () => api.get<BasketItem[]>(`/audio-baskets/${basket!.id_basket}/items`).then((r) => r.data),
    enabled: open,
  })
  const existingIds = new Set(existing.map((i) => i.id_media))

  const { data: stats } = useQuery<{ total: number; by_type: Record<string, number> }>({
    queryKey: ['media', 'stats', 'audio-picker'],
    queryFn: () => api.get('/media/stats').then((r) => r.data),
    enabled: open,
  })
  const audioTotal = stats?.by_type?.audio ?? 0

  // Vue d'accueil (ni recherche ni dossier) : les derniers audio seulement — on ne
  // déverse pas toute l'audiothèque (même contrat que le picker des playlists).
  const isLanding = !debounced && folder === 'all'

  function folderParams(): Record<string, string | number | boolean> {
    if (folder === 'unfiled') return { unfiled: true }
    if (folder !== 'all') return { id_folder: folder }
    return {}
  }

  const { data: results = [] } = useQuery<MediaListItem[]>({
    queryKey: ['media', 'audio-picker', folder, debounced, isLanding],
    queryFn: () => {
      const params: Record<string, string | number | boolean> = {
        media_type: 'audio',
        limit: isLanding ? 15 : 200,
        ...folderParams(),
      }
      if (debounced) params.q = debounced
      return api.get<MediaListItem[]>('/media/', { params }).then((r) => r.data)
    },
    enabled: open,
  })

  const addMutation = useMutation({
    mutationFn: (ids: number[]) =>
      api.post(`/audio-baskets/${basket!.id_basket}/items/bulk`, { id_medias: ids }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['basket-items', basket?.id_basket] })
      qc.invalidateQueries({ queryKey: ['audio-baskets'] })
      setPicked(new Set())
      onClose()
    },
  })

  function togglePick(id: number) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const previewItem = preview !== null ? results[preview] ?? null : null

  return (
    <>
      <Drawer open={open} onClose={onClose} title={t('ab.picker_title')}>
        {/* Contenu démonté à la fermeture : le Drawer garde ses enfants translatés hors
            écran, et un contenu monté continuerait ses requêtes et « existerait » pour
            les tests — démonter rend l'état fermé observable. */}
        {open && (
        <div className="flex flex-col h-full min-h-0 gap-4">
          <div className="shrink-0">
            <SearchInput
              placeholder={t('ab.picker_search')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              wrapperClassName="max-w-none"
            />
          </div>

          {/* Arbre de dossiers — proportionnel au drawer, arbre défilant à l'intérieur */}
          <div className="shrink-0 basis-[34%] min-h-[8rem] flex flex-col border border-gray-200 rounded overflow-hidden">
            <div className="flex items-center justify-between w-full px-3 py-2 text-sm text-gray-600 shrink-0">
              <span className="flex items-center gap-2">
                <FolderTreeIcon className="w-4 h-4 text-gray-400" />
                {t('media.folders')}
              </span>
              {folder !== 'all' && (
                <button
                  type="button"
                  onClick={() => setFolder('all')}
                  className="text-xs text-accent hover:underline"
                >
                  {folder === 'unfiled' ? t('media.folder_unfiled') : t('media.folder_filtered')}
                </button>
              )}
            </div>
            <div className="border-t border-gray-100 p-2 flex-1 min-h-0">
              <FolderTree selected={folder} onSelect={setFolder} fill />
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto space-y-1" data-testid="audio-picker-list">
            {results.map((m, idx) => {
              const already = existingIds.has(m.id_media)
              const checked = already || picked.has(m.id_media)
              return (
                <button
                  key={m.id_media}
                  type="button"
                  onClick={() => { if (!already) togglePick(m.id_media) }}
                  aria-pressed={checked}
                  disabled={already}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded text-left transition-sf border ${
                    already ? 'border-transparent opacity-50'
                      : checked ? 'border-accent bg-accent/5' : 'border-transparent hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    readOnly
                    tabIndex={-1}
                    className="accent-accent w-4 h-4 shrink-0 pointer-events-none"
                  />
                  <span className="w-8 h-8 rounded bg-gray-100 shrink-0 flex items-center justify-center">
                    <Music className="w-4 h-4 text-gray-400" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-800 truncate">{m.media_name}</p>
                    <p className="text-xs text-gray-400">
                      {m.duration_ms != null
                        ? `${Math.round(m.duration_ms / 1000)}s`
                        : t('media.type_audio')}
                      {already && <> · {t('ab.picker_already')}</>}
                    </p>
                  </div>
                  {/* Pré-écoute SANS quitter le drawer : la visionneuse passe au-dessus
                      (elevated) et Échap ne referme qu'elle. Pas un <button> — la ligne
                      entière en est déjà un. */}
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => { e.stopPropagation(); setPreview(idx) }}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter') return
                      e.stopPropagation()
                      setPreview(idx)
                    }}
                    title={t('ab.listen')}
                    className="text-gray-300 hover:text-accent transition-sf shrink-0 p-1"
                    data-testid={`audio-preview-${m.id_media}`}
                  >
                    <Headphones className="w-4 h-4" />
                  </span>
                </button>
              )
            })}
            {results.length === 0 && (
              <p className="text-sm text-gray-400 text-center py-8">{t('media.no_results')}</p>
            )}
            {isLanding && results.length > 0 && audioTotal > results.length && (
              <p className="text-xs text-gray-500 text-center pt-3">
                {t('ab.picker_landing_hint', { total: audioTotal })}
              </p>
            )}
          </div>

          {/* Pied : ajout en lot des morceaux cochés */}
          <div className="shrink-0 flex items-center justify-between gap-3 border-t border-gray-100 pt-3">
            <span className="text-xs text-gray-500">
              {t('ab.picker_selected', { count: picked.size })}
            </span>
            <Button
              size="sm"
              onClick={() => addMutation.mutate(Array.from(picked))}
              disabled={picked.size === 0 || addMutation.isPending}
              data-write-action
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              {t('ab.picker_add', { count: picked.size })}
            </Button>
          </div>
        </div>
        )}
      </Drawer>

      {/* Pré-écoute par-dessus le drawer (portail + z-60, Échap ne ferme qu'elle) */}
      <MediaViewer
        item={previewItem ? {
          id_media: previewItem.id_media,
          media_name: previewItem.media_name,
          media_type: previewItem.media_type,
          file_size_bytes: previewItem.file_size_bytes,
          served_size_bytes: previewItem.served_size_bytes,
        } : null}
        onClose={() => setPreview(null)}
        onPrev={preview !== null && preview > 0 ? () => setPreview((p) => (p ?? 1) - 1) : undefined}
        onNext={preview !== null && preview < results.length - 1 ? () => setPreview((p) => (p ?? 0) + 1) : undefined}
        position={preview !== null && results.length > 1 ? { index: preview, total: results.length } : undefined}
        elevated
      />
    </>
  )
}
