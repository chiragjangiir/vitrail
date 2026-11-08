'use client'

import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import api from '@/lib/api'
import type { PlaylistDetail, PlaylistItemRead, TemplateRead } from '@/types/api'
import MediaViewer, { isViewable, type ViewerMedia } from '../media/components/MediaViewer'
import TemplateStage from './TemplateStage'
import { itemHoldMs, selectedPageCount, selectedPages } from './loopTiming'

/**
 * Lecture d'une playlist dans la visionneuse — utilisable depuis n'importe où (retour Ed
 * 2026-07-29 : « pourrait-on ajouter sur la vignette et dans la page d'édition une
 * visualisation d'une playlist ? »).
 *
 * Deux usages aujourd'hui : le bouton lecture d'une carte de la liste `/playlists`, et
 * celui d'un item SOUS-PLAYLIST dans l'éditeur — ce dernier cas étant celui où l'on
 * devait auparavant ouvrir la playlist enfant dans une autre page pour voir ce qu'elle
 * contenait.
 *
 * Le composant charge le détail lui-même : les deux appelants n'ont que l'identifiant, et
 * les items ne sont pas dans les listes.
 */

/** Contenus visualisables d'une liste d'items, dans l'ordre.
 *
 * ⚠️ Les items SOUS-PLAYLIST n'en font pas partie : ils n'ont pas de média propre. Ce n'est
 * pas pour autant qu'on les ignore — `PlaylistPlayer` charge leur contenu et les DÉROULE à
 * leur place dans la lecture (question d'Ed 2026-07-29 : « il saute la playlist intégrée »).
 * Les appelants qui ne travaillent que sur les items déjà en main (l'éditeur, pour la
 * navigation dans SA liste) utilisent cette fonction telle quelle.
 */
export function viewableItems(items: PlaylistItemRead[]): PlaylistItemRead[] {
  return items.filter(
    (it) => it.item_type !== 'sub_playlist' && it.id_media && it.media_type && isViewable(it.media_type)
  )
}

/** Items sous-playlist d'une playlist (pour charger leur contenu). */
function subPlaylistIds(items: PlaylistItemRead[]): number[] {
  return Array.from(new Set(
    items.filter((it) => it.item_type === 'sub_playlist' && it.id_child_playlist)
         .map((it) => it.id_child_playlist as number)
  ))
}

export function toViewerMedia(it: PlaylistItemRead): ViewerMedia {
  return {
    id_media: it.id_media!,
    media_name: it.media_name ?? `#${it.id_media}`,
    media_type: it.media_type!,
    page_count: it.media_page_count ?? null,
  }
}

/**
 * Durées de la boucle : la définition vit dans `loopTiming.ts` depuis le 2026-08-13 — la
 * scène multi-zones en a besoin, et l'importer d'ici aurait créé un cycle (ce module monte
 * la scène). Ré-exportées pour les appelants existants (l'éditeur de playlist).
 */
export { itemHoldMs, selectedPageCount, selectedPages }

interface Props {
  /** Playlist à lire (null = fermé). */
  idPlaylist: number | null
  onClose: () => void
  /** Empilement au-dessus d'un Drawer déjà ouvert (cf. MediaViewer). */
  elevated?: boolean
}

export default function PlaylistPlayer({ idPlaylist, onClose, elevated }: Props) {
  const t = useTranslations()
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)

  const { data, isLoading } = useQuery<PlaylistDetail>({
    queryKey: ['playlist', String(idPlaylist)],
    queryFn: () => api.get<PlaylistDetail>(`/playlists/${idPlaylist}`).then((r) => r.data),
    enabled: idPlaylist !== null,
  })

  // Nouvelle playlist demandée → on repart de son premier contenu.
  useEffect(() => { setIndex(0); setPlaying(true) }, [idPlaylist])

  // Sous-playlists imbriquées : on charge leur contenu pour les DÉROULER à leur place.
  // Un seul niveau d'imbrication est possible (garde serveur `validate_child_for_nesting`),
  // donc pas de récursion à prévoir ici.
  const childIds = subPlaylistIds(data?.items ?? [])
  const childQueries = useQueries({
    queries: childIds.map((cid) => ({
      queryKey: ['playlist', String(cid)],
      queryFn: () => api.get<PlaylistDetail>(`/playlists/${cid}`).then((r) => r.data),
      enabled: idPlaylist !== null,
    })),
  })
  const childItems = useMemo(() => {
    const map = new Map<number, PlaylistItemRead[]>()
    childIds.forEach((cid, i) => {
      const d = childQueries[i]?.data
      if (d) map.set(cid, viewableItems(d.items))
    })
    return map
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [childIds.join(','), childQueries.map((q) => q.data?.id_playlist ?? 0).join(',')])

  /**
   * Déroulé final : les items de la playlist DANS L'ORDRE, chaque sous-playlist remplacée
   * par ses propres contenus, **et chacun rattaché à sa zone effective**.
   *
   * 🔑 Une sous-playlist n'a pas de zone à elle : ses contenus prennent celle du **slot
   * parent** — c'est exactement ce que fait le serveur (`_compile_item(..., zone_override=
   * item.zone_index)`, `ws.py:2792`). L'oublier renverrait tout le contenu imbriqué en
   * zone 0, c'est-à-dire au bon endroit une fois sur deux et sans le moindre signe.
   *
   * ⚠️ UN SEUL parcours pour les deux surfaces (liste plate et scène) : deux traversées de
   * la même liste finiraient par ne plus retenir les mêmes contenus, et l'une dirait
   * « rien à montrer » pendant que l'autre diffuse.
   *
   * ⚠️ On ne rejoue pas ici la ROTATION du serveur (« N par tour ») : l'aperçu montre tout
   * ce que la sous-playlist peut diffuser, pas le tirage d'un tour donné — c'est
   * `/compiled-schedule` qui fait foi sur le déroulé réel.
   */
  const unrolled = useMemo(() => {
    const out: { zone: number; item: PlaylistItemRead }[] = []
    for (const it of data?.items ?? []) {
      if (it.item_type === 'sub_playlist') {
        for (const child of childItems.get(it.id_child_playlist as number) ?? []) {
          out.push({ zone: it.zone_index, item: child })
        }
      } else if (it.id_media && it.media_type && isViewable(it.media_type)) {
        out.push({ zone: it.zone_index, item: it })
      }
    }
    return out
  }, [data?.items, childItems])

  const items = useMemo(() => unrolled.map((u) => u.item), [unrolled])

  // §25.4 — modèle de mise en page de la playlist. On ne charge que s'il y en a un : la
  // très grande majorité des playlists n'en a pas, et la scène ne sert qu'au-delà d'UNE zone
  // (même seuil que le serveur : `_build_template_block` n'émet rien à zones <= 1, donc le
  // player garde son chemin mono-zone — celui que ce composant rend déjà).
  const idTemplate = data?.id_template ?? null
  const { data: template, isError: templateError } = useQuery<TemplateRead>({
    queryKey: ['template', String(idTemplate)],
    queryFn: () => api.get<TemplateRead>(`/templates/${idTemplate}`).then((r) => r.data),
    enabled: idTemplate !== null,
  })
  const zones = template?.layout?.zones ?? []
  const multiZone = zones.length > 1

  /** Le même déroulé, regroupé par zone — c'est ce que la scène place sur le canevas. */
  const itemsByZone = useMemo(() => {
    const map = new Map<number, PlaylistItemRead[]>()
    for (const { zone, item } of unrolled) {
      const list = map.get(zone)
      if (list) list.push(item)
      else map.set(zone, [item])
    }
    return map
  }, [unrolled])

  const current = items[index]

  // Playlist chargée mais sans aucun contenu visualisable (que des pointeurs, ou vide) :
  // le dire, plutôt que fermer sans un mot — l'utilisateur croirait à un clic manqué.
  const emptyMessage = idPlaylist !== null && !isLoading && data && items.length === 0

  if (idPlaylist === null) return null

  // Un template est attendu mais pas encore chargé : on ne montre RIEN plutôt que la liste
  // plate, qui serait remplacée une fraction de seconde plus tard par la scène — un aperçu
  // qui clignote sur un rendu faux. En cas d'ERREUR de chargement on repart sur la liste
  // plate : dégradé, mais jamais bloqué (le lecteur doit s'ouvrir).
  if (idTemplate !== null && !template && !templateError) return null

  if (multiZone && !emptyMessage) {
    return (
      <TemplateStage
        playlistName={data?.playlist_name ?? ''}
        templateName={template?.template_name ?? null}
        canvasWidth={template?.layout?.canvas_width || 1920}
        canvasHeight={template?.layout?.canvas_height || 1080}
        zones={zones}
        itemsByZone={itemsByZone}
        onClose={onClose}
        elevated={elevated}
      />
    )
  }

  if (emptyMessage) {
    // Portail, pour la même raison que la visionneuse : la bulle d'aide de DashboardShell
    // est montée hors du conteneur des pages et recouvrirait ce panneau.
    if (typeof document === 'undefined') return null
    return createPortal(
      <div
        className={`fixed inset-0 ${elevated ? 'z-[60]' : 'z-50'} bg-black/80 backdrop-blur-sm flex items-center justify-center p-6`}
        onClick={onClose}
        role="dialog"
        aria-modal="true"
        data-testid="playlist-player-empty"
      >
        <div className="sf-panel px-6 py-5 max-w-md text-center" onClick={(e) => e.stopPropagation()}>
          <p className="text-sm text-gray-700">{t('playlists.preview_nothing_to_show')}</p>
        </div>
      </div>,
      document.body,
    )
  }

  return (
    <MediaViewer
      item={current ? toViewerMedia(current) : null}
      onClose={onClose}
      onPrev={index > 0 ? () => { setPlaying(false); setIndex((i) => i - 1) } : undefined}
      onNext={index < items.length - 1 ? () => { setPlaying(false); setIndex((i) => i + 1) } : undefined}
      onEnded={playing
        ? () => (index < items.length - 1 ? setIndex((i) => i + 1) : onClose())
        : undefined}
      holdMs={playing ? itemHoldMs(current) : undefined}
      position={items.length > 1 ? { index, total: items.length } : undefined}
      elevated={elevated}
    />
  )
}
