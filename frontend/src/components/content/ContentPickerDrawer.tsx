'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Eye, FolderTree as FolderTreeIcon, ListVideo, Music, Plus } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import SearchInput from '@/components/ui/SearchInput'
import api from '@/lib/api'
import type { MediaListItem, PlaylistRead } from '@/types/api'
import FolderTree, { type FolderFilter } from '@/app/(dashboard)/media/components/FolderTree'
import MediaViewer, { isViewable } from '@/app/(dashboard)/media/components/MediaViewer'

/**
 * Tiroir de choix de CONTENU — brique partagée (audit des menus Événements/VOD, 2026-07-29).
 *
 * Il n'existait pas moins de QUATRE façons de choisir un contenu dans le produit : le tiroir
 * des playlists (recherche serveur + arbre de dossiers), celui des paniers audio (même
 * patron), et deux menus déroulants plats — Événements et VOD — qui, eux, ne cherchaient
 * rien. Ed : « pas besoin d'avoir différentes façons de le faire ». Ce composant est la
 * façon unique ; les deux menus déroulants disparaissent.
 *
 * 🔴 Ce que les menus déroulants cachaient : ils appelaient l'API SANS paramètre, donc au
 * plafond par défaut du serveur — **50 playlists**, **500 médias** — et **sans recherche**.
 * Au-delà, le contenu était invisible ET introuvable. Ça ne se voit pas à 20 playlists ;
 * ça devient un mur à 200 écrans et quelques centaines de contenus.
 *
 * Trois choses le rendent réutilisable sans le rendre flou :
 *   · `mediaTypes` — une requête PAR type (le serveur ne filtre que sur un type à la fois) ;
 *   · `multiple` — sélection multiple (playlists, paniers, VOD) ou unique (événements) ;
 *   · `withPlaylists` — onglet « Playlists » (demande d'Ed) : un événement diffuse une
 *     playlist entière aussi bien qu'un média isolé.
 *
 * ⚠️ Rendu AU NIVEAU DE LA PAGE, jamais imbriqué dans un autre `Drawer` : le panneau porte
 * un `transform`, qui devient le bloc conteneur de tout `fixed` descendant.
 */

export interface ContentPick {
  medias: number[]
  playlist?: number | null
  /** Choix UNIQUE : nom et durée du contenu retenu.
   *
   * 🔑 Indispensable, pas décoratif : le contenu peut venir d'une RECHERCHE, donc être
   * absent des listes que la page a chargées d'avance — c'est précisément ce que ce tiroir
   * rend possible. Sans ces deux champs, l'appelant afficherait « aucun contenu » et ne
   * saurait pas calculer la durée automatique d'un contenu qu'il vient pourtant de choisir.
   */
  label?: string
  durationMs?: number | null
}

interface Props {
  open: boolean
  onClose: () => void
  /** Types de médias proposés. `[]` = onglet Médias masqué (playlists seules). */
  mediaTypes: string[]
  /** Sélection multiple (défaut) ou choix unique qui valide immédiatement. */
  multiple?: boolean
  /** Ajoute l'onglet « Playlists » (événements). */
  withPlaylists?: boolean
  /** Déjà retenus : montrés cochés-grisés plutôt que cachés. */
  alreadySelected?: Set<number>
  title?: string
  /** Largeur du panneau. Défaut `w-[560px]` = la largeur DOMINANTE du produit (édition
   *  VOD, flux, pages web, import de campagne). Le tiroir de sélection restait au défaut
   *  générique de 480 px et paraissait donc plus étroit que le tiroir d'édition qui
   *  l'ouvre (constat d'Ed, 2026-07-29). Alignée PARTOUT plutôt que page par page : garder
   *  480 ici et 560 là remettrait une divergence dans la brique qu'on vient d'unifier. */
  width?: string
  onPick: (pick: ContentPick) => void
}

const LANDING_PER_TYPE = 12

export default function ContentPickerDrawer({
  open, onClose, mediaTypes, multiple = true, withPlaylists = false,
  alreadySelected, title, width = 'w-[560px]', onPick,
}: Props) {
  const t = useTranslations()
  const [tab, setTab] = useState<'media' | 'playlist'>(mediaTypes.length ? 'media' : 'playlist')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [folder, setFolder] = useState<FolderFilter>('all')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [preview, setPreview] = useState<number | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    if (open) {
      setSearch(''); setFolder('all'); setPicked(new Set()); setPreview(null)
      setTab(mediaTypes.length ? 'media' : 'playlist')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function folderParams(): Record<string, string | number | boolean> {
    if (folder === 'unfiled') return { unfiled: true }
    if (folder !== 'all') return { id_folder: folder }
    return {}
  }
  const isLanding = !debounced && folder === 'all'

  // Une requête PAR TYPE : le serveur ne filtre que sur un `media_type` à la fois, et
  // filtrer côté navigateur reviendrait à réintroduire le défaut qu'on corrige.
  const mediaQueries = useQueries({
    queries: mediaTypes.map((ty) => ({
      queryKey: ['content-picker', 'media', ty, folder, debounced, isLanding],
      queryFn: () => {
        const params: Record<string, string | number | boolean> = {
          media_type: ty, limit: isLanding ? LANDING_PER_TYPE : 200, ...folderParams(),
        }
        if (debounced) params.q = debounced
        return api.get<MediaListItem[]>('/media/', { params }).then((r) => r.data)
      },
      enabled: open && tab === 'media',
    })),
  })
  const medias = useMemo(
    // Dédoublonnage par identifiant : on lance une requête PAR TYPE, et rien ne garantit
    // qu'un même média ne revienne pas de deux d'entre elles (repli serveur, type mal
    // renseigné…). Sans cette garde, l'élément apparaîtrait plusieurs fois dans la liste.
    () => {
      const seen = new Set<number>()
      return mediaQueries.flatMap((q) => q.data ?? []).filter((m) => {
        if (seen.has(m.id_media)) return false
        seen.add(m.id_media)
        return true
      })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mediaQueries.map((q) => q.data?.length ?? -1).join(','), debounced, folder],
  )

  // Playlists : recherche SERVEUR elle aussi (paramètre `q` ajouté le 2026-07-29 — le menu
  // déroulant des événements était plafonné à 50 sans aucun moyen de trouver les autres).
  const { data: playlists = [] } = useQuery<PlaylistRead[]>({
    queryKey: ['content-picker', 'playlists', debounced],
    queryFn: () => api.get<PlaylistRead[]>('/playlists/', {
      params: { limit: 200, ...(debounced ? { q: debounced } : {}) },
    }).then((r) => r.data),
    enabled: open && withPlaylists && tab === 'playlist',
  })

  function toggle(id: number) {
    if (!multiple) {
      const m = medias.find((x) => x.id_media === id)
      onPick({ medias: [id], label: m?.media_name, durationMs: m?.duration_ms ?? null })
      onClose()
      return
    }
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const previewItem = preview !== null ? medias.find((m) => m.id_media === preview) ?? null : null

  return (
    <>
      <Drawer open={open} onClose={onClose} title={title ?? t('content_picker.title')} width={width}>
        {open && (
        <div className="flex flex-col h-full min-h-0 gap-3" data-testid="content-picker">
          {withPlaylists && mediaTypes.length > 0 && (
            <div className="shrink-0 flex rounded overflow-hidden border border-gray-200 text-xs w-max">
              {(['media', 'playlist'] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  data-testid={`content-tab-${k}`}
                  onClick={() => { setTab(k); setPicked(new Set()) }}
                  className={`px-3 py-1 font-medium transition-sf ${
                    tab === k ? 'bg-accent text-white' : 'bg-surface text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {t(`content_picker.tab_${k}`)}
                </button>
              ))}
            </div>
          )}

          <div className="shrink-0">
            <SearchInput
              placeholder={t('content_picker.search')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              wrapperClassName="max-w-none"
            />
          </div>

          {tab === 'media' && (
            <div className="shrink-0 basis-[32%] min-h-[7rem] flex flex-col border border-gray-200 rounded overflow-hidden">
              <div className="flex items-center justify-between w-full px-3 py-2 text-sm text-gray-600 shrink-0">
                <span className="flex items-center gap-2">
                  <FolderTreeIcon className="w-4 h-4 text-gray-400" />
                  {t('media.folders')}
                </span>
                {folder !== 'all' && (
                  <button type="button" onClick={() => setFolder('all')}
                          className="text-xs text-accent hover:underline">
                    {folder === 'unfiled' ? t('media.folder_unfiled') : t('media.folder_filtered')}
                  </button>
                )}
              </div>
              <div className="border-t border-gray-100 p-2 flex-1 min-h-0">
                <FolderTree selected={folder} onSelect={setFolder} fill />
              </div>
            </div>
          )}

          <div className="flex-1 min-h-0 overflow-y-auto space-y-1" data-testid="content-picker-list">
            {tab === 'media' ? (
              medias.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-8">{t('media.no_results')}</p>
              ) : medias.map((m) => {
                const already = alreadySelected?.has(m.id_media) ?? false
                const checked = already || picked.has(m.id_media)
                return (
                  <button
                    key={m.id_media}
                    type="button"
                    disabled={already}
                    onClick={() => { if (!already) toggle(m.id_media) }}
                    aria-pressed={checked}
                    data-testid={`content-media-${m.id_media}`}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded text-left transition-sf border ${
                      already ? 'border-transparent opacity-50'
                        : checked ? 'border-accent bg-accent/5' : 'border-transparent hover:bg-gray-50'
                    }`}
                  >
                    {multiple && (
                      <input type="checkbox" checked={checked} readOnly tabIndex={-1}
                             className="accent-accent w-4 h-4 shrink-0 pointer-events-none" />
                    )}
                    <span className="w-8 h-8 rounded bg-gray-100 shrink-0 overflow-hidden flex items-center justify-center">
                      {m.thumbnail_url
                        // eslint-disable-next-line @next/next/no-img-element
                        ? <img src={m.thumbnail_url} alt="" className="w-full h-full object-cover" />
                        : <Music className="w-4 h-4 text-gray-400" />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-800 truncate">{m.media_name}</p>
                      <p className="text-xs text-gray-400">
                        {m.media_type}
                        {m.duration_ms != null && <> · {Math.round(m.duration_ms / 1000)}s</>}
                        {already && <> · {t('content_picker.already')}</>}
                      </p>
                    </div>
                    {isViewable(m.media_type) && (
                      <span
                        role="button"
                        tabIndex={0}
                        onClick={(e) => { e.stopPropagation(); setPreview(m.id_media) }}
                        onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); setPreview(m.id_media) } }}
                        title={t('content_picker.preview')}
                        className="text-gray-300 hover:text-accent transition-sf shrink-0 p-1"
                      >
                        <Eye className="w-4 h-4" />
                      </span>
                    )}
                  </button>
                )
              })
            ) : (
              playlists.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-8">{t('media.no_results')}</p>
              ) : playlists.map((pl) => (
                <button
                  key={pl.id_playlist}
                  type="button"
                  data-testid={`content-playlist-${pl.id_playlist}`}
                  onClick={() => {
                    onPick({
                      medias: [], playlist: pl.id_playlist,
                      label: pl.playlist_name, durationMs: pl.total_duration_ms ?? null,
                    })
                    onClose()
                  }}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded text-left transition-sf border border-transparent hover:bg-gray-50 hover:border-accent/30"
                >
                  <ListVideo className="w-4 h-4 text-gray-300 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-800 truncate">{pl.playlist_name}</p>
                    <p className="text-xs text-gray-400">
                      {t('content_picker.playlist_meta', {
                        s: Math.round((pl.total_duration_ms ?? 0) / 1000),
                      })}
                    </p>
                  </div>
                </button>
              ))
            )}

            {isLanding && tab === 'media' && medias.length > 0 && (
              <p className="text-xs text-gray-500 text-center pt-3">
                {t('content_picker.landing_hint')}
              </p>
            )}
          </div>

          {multiple && tab === 'media' && (
            <div className="shrink-0 flex items-center justify-between gap-3 border-t border-gray-100 pt-3">
              <span className="text-xs text-gray-500">
                {t('content_picker.selected', { count: picked.size })}
              </span>
              <Button
                size="sm"
                data-testid="content-picker-add"
                onClick={() => { onPick({ medias: Array.from(picked) }); onClose() }}
                disabled={picked.size === 0}
              >
                <Plus className="w-3.5 h-3.5 mr-1" />
                {t('content_picker.add', { count: picked.size })}
              </Button>
            </div>
          )}
        </div>
        )}
      </Drawer>

      {/* Pré-écoute / aperçu par-dessus le tiroir (portail + z-60, Échap ne ferme que lui) */}
      <MediaViewer
        item={previewItem ? {
          id_media: previewItem.id_media,
          media_name: previewItem.media_name,
          media_type: previewItem.media_type,
          file_size_bytes: previewItem.file_size_bytes,
          served_size_bytes: previewItem.served_size_bytes,
        } : null}
        onClose={() => setPreview(null)}
        elevated
      />
    </>
  )
}
