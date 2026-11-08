'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { X, Pencil, Download, ChevronLeft, ChevronRight, Globe, Rss, MonitorPlay } from 'lucide-react'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import type { DocumentPagesResult, MediaRead } from '@/types/api'
import { formatSize } from './MediaGrid'
import { downloadMedia, isMediaDownloadable } from '@/lib/mediaDownload'

/**
 * Visionneuse plein écran (retour Ed sur les maquettes MyBox, audit du menu Média
 * 2026-07-28) : le clic sur un contenu VISUEL montre d'abord le contenu, en grand.
 *
 * Avant, le clic ouvrait directement le tiroir d'édition — pratique pour modifier, mais on
 * ne pouvait pas simplement *regarder* un média sans se retrouver dans un formulaire. La
 * visionneuse porte donc un bouton « Modifier » qui ouvre ce tiroir : le geste d'édition
 * n'est pas perdu, il est juste au bon endroit.
 *
 * ⚠️ Réservée aux contenus qui ont quelque chose à MONTRER (image / vidéo / audio /
 * document). Les médias POINTEURS — page web, flux, entrée HDMI — n'ont pas de fichier :
 * pour eux, le clic continue d'ouvrir leur éditeur, seul endroit où il y a quelque chose
 * à voir. C'est `isViewable()` qui tranche, et la page l'utilise avant d'ouvrir.
 */

/**
 * Types que la visionneuse sait MONTRER.
 *
 * Les médias POINTEURS (page web, flux, entrée HDMI) n'ont pas de fichier : ils y entrent
 * quand même depuis le 2026-07-29 (question d'Ed), avec une fiche qui dit ce qu'ils sont —
 * les sauter en silence dans une lecture de playlist donnait l'impression que l'aperçu
 * mentait sur le contenu réel de la boucle. C'est `hasRenderableFile()` qui distingue « il
 * y a un fichier à afficher » de « il y a quelque chose à comprendre ».
 */
export function isViewable(type: string): boolean {
  return hasRenderableFile(type) || isPointerMedia(type)
}

export function hasRenderableFile(type: string): boolean {
  return type === 'image' || type === 'video' || type === 'audio' || type === 'document'
}

export function isPointerMedia(type: string): boolean {
  return type === 'url_display' || type === 'feed_display' || type === 'hdmi_input'
}

/**
 * Forme minimale suffisante pour la visionneuse — `MediaListItem` la satisfait, et un
 * item de PLAYLIST (id_media + nom + type) aussi : le fichier lui-même est de toute
 * façon rechargé par l'API (URL signée du détail), la liste n'apporte que l'identité.
 */
export interface ViewerMedia {
  id_media: number
  media_name: string
  media_type: string
  file_size_bytes?: number | null
  served_size_bytes?: number | null
  page_count?: number | null
}

/**
 * Document PDF/PPTX : on affiche les PAGES CONVERTIES, pas le fichier source.
 *
 * 🔴 Défaut trouvé sur question d'Ed (2026-07-29) : la visionneuse rendait
 * `<img src={cdn_url_signed}>` pour tout ce qui n'était ni vidéo ni audio — donc, pour un
 * document, le `.pptx` ou le `.pdf` lui-même dans une balise `<img>`. Aucun navigateur ne
 * sait faire ça : **carré vide, sans la moindre erreur visible**. Le défaut valait aussi
 * pour `/media` depuis le 28/07 (même composant), et mon audit du menu Média ne l'avait
 * pas vu — comme les vignettes MinIO, c'est un rendu qu'il fallait REGARDER.
 *
 * Les pages existent déjà : le worker convertit chaque page en JPEG à l'upload (§3.2), et
 * `GET /media/{id}/pages` les sert. On feuillette donc le document — ce qu'Ed demandait a
 * minima pour la première page.
 */
function DocumentPages({ item, page, onPageCount }: {
  item: ViewerMedia
  page: number
  onPageCount: (n: number) => void
}) {
  const t = useTranslations('media')
  const { data, isLoading } = useQuery<DocumentPagesResult>({
    queryKey: ['media', 'pages', item.id_media],
    queryFn: () => api.get<DocumentPagesResult>(`/media/${item.id_media}/pages`).then((r) => r.data),
  })

  const pages = data?.pages ?? []
  useEffect(() => { onPageCount(pages.length) }, [pages.length, onPageCount])

  if (isLoading) {
    return <span className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
  }
  // Document non encore converti (worker en cours, ou format refusé) : le dire. L'ancien
  // comportement — un cadre vide — laissait croire à un contenu illisible.
  if (!pages.length) {
    return <p className="text-sm text-gray-400 px-6 py-10 text-center">{t('doc_pages_unavailable')}</p>
  }
  const current = pages[Math.min(page, pages.length - 1)]
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={current.url}
      alt={`${item.media_name} — ${current.page}`}
      className="max-h-[62vh] max-w-full object-contain rounded"
    />
  )
}

/**
 * Média POINTEUR (page web, flux, entrée HDMI) : il n'a pas de fichier, mais il occupe une
 * place réelle dans la boucle. Les sauter dans l'aperçu d'une playlist donnait un déroulé
 * qui ne correspondait pas à ce que diffuse l'écran (question d'Ed, 2026-07-29).
 * On montre donc ce qu'il EST — l'icône de son type et sa nature — plutôt que rien.
 */
function PointerCard({ item }: { item: ViewerMedia }) {
  const t = useTranslations('media')
  const Icon = item.media_type === 'feed_display' ? Rss
    : item.media_type === 'hdmi_input' ? MonitorPlay : Globe
  return (
    <div className="flex flex-col items-center gap-3 px-8 py-12 text-center">
      <span className="w-20 h-20 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
        <Icon className="w-9 h-9 text-accent" />
      </span>
      <p className="text-sm font-medium text-gray-900">{t(`type_${item.media_type}`)}</p>
      <p className="text-xs text-gray-500 max-w-sm">{t('pointer_no_preview')}</p>
    </div>
  )
}

interface Props {
  item: ViewerMedia | null
  onClose: () => void
  /** Bouton « Modifier » — absent = masqué (toutes les surfaces n'ont pas d'éditeur de média). */
  onEdit?: (item: ViewerMedia) => void
  /** Navigation au clavier dans la liste courante (← →). Optionnel. */
  onPrev?: () => void
  onNext?: () => void
  /** Lecture séquentielle (aperçu de playlist) : fin du contenu courant — vidéo/audio
   *  terminé, ou minuterie `holdMs` pour un contenu SANS durée native (image/document). */
  onEnded?: () => void
  holdMs?: number
  /** Empilement face à un Drawer (panneau z-50) : `elevated` passe la visionneuse en
   *  z-[60] — nécessaire pour l'aperçu ouvert DEPUIS un drawer. Par défaut la visionneuse
   *  reste en z-50 et c'est l'ordre DOM qui tranche (comme sur /media). */
  elevated?: boolean
  /** Un drawer est ouvert PAR-DESSUS la visionneuse : le clavier lui appartient. */
  keysDisabled?: boolean
  /** Actions supplémentaires au pied (ex. « Ajouter un média » côté playlist). */
  actions?: React.ReactNode
  /** Position dans la liste parcourue — affichée « 3 / 12 » au pied. */
  position?: { index: number; total: number }
}

export default function MediaViewer({
  item, onClose, onEdit, onPrev, onNext, onEnded, holdMs, elevated, keysDisabled, actions,
  position,
}: Props) {
  const t = useTranslations('media')
  // Page courante d'un document feuilleté (remise à zéro quand on change de contenu).
  const [docPage, setDocPage] = useState(0)
  const [docPageCount, setDocPageCount] = useState(0)
  useEffect(() => { setDocPage(0); setDocPageCount(0) }, [item?.id_media])
  // Portail : `document` n'existe pas au rendu serveur.
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  // Le détail porte l'URL signée du fichier (la liste n'a que la vignette).
  const { data } = useQuery<MediaRead>({
    queryKey: ['media', 'detail', item?.id_media],
    queryFn: () => api.get<MediaRead>(`/media/${item!.id_media}`).then((r) => r.data),
    enabled: !!item,
  })

  useEffect(() => {
    if (!item || keysDisabled) return
    const onKey = (e: KeyboardEvent) => {
      // stopPropagation (phase CAPTURE) : quand la visionneuse est ouverte PAR-DESSUS un
      // drawer (aperçu depuis « Ajouter un média »), Échap ne doit fermer QUE la
      // visionneuse — sans ça, le listener du drawer (bubble, document) fermait les deux.
      if (e.key === 'Escape') { e.stopPropagation(); onClose() }
      if (e.key === 'ArrowLeft') onPrev?.()
      if (e.key === 'ArrowRight') onNext?.()
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [item, keysDisabled, onClose, onPrev, onNext])

  // Lecture séquentielle : un contenu sans durée native (image, document) « se termine »
  // au bout de sa durée d'exposition — celle que le player appliquerait.
  useEffect(() => {
    if (!item || !onEnded || !holdMs) return
    if (item.media_type === 'video' || item.media_type === 'audio') return
    const timer = setTimeout(onEnded, holdMs)
    return () => clearTimeout(timer)
  }, [item, onEnded, holdMs])

  if (!item || !mounted) return null
  const url = data?.cdn_url_signed ?? null

  // 🔑 PORTAIL vers `document.body` — indispensable, pas décoratif. `DashboardShell` place
  // les pages dans un `<div class="relative z-10">` et monte `<DemoTips />` en FRÈRE, après :
  // aucun z-index interne ne sort d'un contexte d'empilement (leçon du plein écran de la
  // carte de gouvernance, 26/07). Sans portail, la bulle d'aide `fixed bottom-20 right-5`
  // recouvrait le pied de la visionneuse — donc « Modifier », « Précédent », « Suivant » et
  // « Ajouter un média » n'étaient PAS cliquables. Mesuré par un test le 2026-07-29 ; le
  // défaut valait aussi pour `/media` depuis le 28/07.
  return createPortal(
    <div
      className={`fixed inset-0 ${elevated ? 'z-[60]' : 'z-50'} bg-black/80 backdrop-blur-sm flex items-center justify-center p-6`}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      data-testid="media-viewer"
    >
      <button
        onClick={onClose}
        className="absolute top-5 right-6 text-white/70 hover:text-white transition-sf"
        title={t('close_viewer')}
      >
        <X className="w-6 h-6" />
      </button>

      {/* Navigation latérale — pastille pleine et non plus un chevron translucide : sur un
          fond noir, `text-white/60` ne se remarquait pas (retour Ed 2026-07-29, qui a
          demandé « des boutons » alors qu'il y en avait déjà). Doublée en bas par des
          boutons libellés : ces flèches-ci sont le geste rapide, pas la découverte. */}
      {onPrev && (
        <button
          onClick={(e) => { e.stopPropagation(); onPrev() }}
          className="absolute left-4 w-11 h-11 rounded-full bg-black/60 hover:bg-black/80 border border-white/15 text-white flex items-center justify-center transition-sf"
          title={t('viewer_prev')}
          aria-label={t('viewer_prev')}
        >
          <ChevronLeft className="w-6 h-6" />
        </button>
      )}
      {onNext && (
        <button
          onClick={(e) => { e.stopPropagation(); onNext() }}
          className="absolute right-4 w-11 h-11 rounded-full bg-black/60 hover:bg-black/80 border border-white/15 text-white flex items-center justify-center transition-sf"
          title={t('viewer_next')}
          aria-label={t('viewer_next')}
        >
          <ChevronRight className="w-6 h-6" />
        </button>
      )}

      <div
        className="sf-panel max-w-5xl w-full max-h-full flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex-1 min-h-0 flex items-center justify-center bg-black/40 p-4">
          {isPointerMedia(item.media_type) ? (
            <PointerCard item={item} />
          ) : item.media_type === 'document' ? (
            <DocumentPages item={item} page={docPage} onPageCount={setDocPageCount} />
          ) : !url ? (
            <span className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          ) : item.media_type === 'video' ? (
            // eslint-disable-next-line jsx-a11y/media-has-caption
            <video src={url} controls autoPlay onEnded={onEnded} className="max-h-[65vh] max-w-full rounded" />
          ) : item.media_type === 'audio' ? (
            // autoPlay comme la vidéo : la visionneuse EST le lecteur (demande Ed 2026-07-29,
            // paniers audio) — sans lui, l'écoute enchaînée d'un panier s'arrêtait à chaque
            // morceau en attendant un clic. Ouverte par un clic ⇒ l'autoplay est permis.
            // eslint-disable-next-line jsx-a11y/media-has-caption
            <audio src={url} controls autoPlay onEnded={onEnded} className="w-full max-w-xl" />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={item.media_name} className="max-h-[65vh] max-w-full object-contain rounded" />
          )}
        </div>

        {/* Document multipage : on feuillette DANS la visionneuse. Les flèches ← → restent
            la navigation entre CONTENUS ; ces boutons-ci naviguent entre PAGES. */}
        {item.media_type === 'document' && docPageCount > 1 && (
          <div className="shrink-0 flex items-center justify-center gap-3 pb-1">
            <button
              onClick={() => setDocPage((p) => Math.max(0, p - 1))}
              disabled={docPage === 0}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-800 hover:bg-white/10 disabled:opacity-30 transition-sf"
              aria-label={t('doc_page_prev')}
              title={t('doc_page_prev')}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-xs text-gray-500 tabular-nums">
              {/* `doc_page_of` préexiste avec le paramètre `page` (et non `n`) : réutiliser
                  une clé impose d'en respecter la signature — sinon le libellé sort vide. */}
              {t('doc_page_of', { page: docPage + 1, total: docPageCount })}
            </span>
            <button
              onClick={() => setDocPage((p) => Math.min(docPageCount - 1, p + 1))}
              disabled={docPage >= docPageCount - 1}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-800 hover:bg-white/10 disabled:opacity-30 transition-sf"
              aria-label={t('doc_page_next')}
              title={t('doc_page_next')}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}

        <div className="shrink-0 px-5 py-4 flex items-end justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <p className="text-base font-semibold text-gray-900 truncate">{item.media_name}</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {t(`type_${item.media_type}`)}
              {formatSize(item.served_size_bytes ?? item.file_size_bytes ?? null) &&
                ` · ${formatSize(item.served_size_bytes ?? item.file_size_bytes ?? null)}`}
              {item.page_count ? ` · ${t('doc_pages', { n: item.page_count })}` : ''}
              {position && ` · ${position.index + 1} / ${position.total}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* Boutons LIBELLÉS de navigation : visibles là où l'œil va (à côté des autres
                actions), contrairement aux flèches posées sur les bords de l'écran. */}
            {(onPrev || onNext) && (
              <div className="flex items-center gap-1 mr-1">
                <Button size="sm" variant="secondary" onClick={onPrev} disabled={!onPrev}
                        data-testid="viewer-prev">
                  <ChevronLeft className="w-3.5 h-3.5" />
                  {t('viewer_prev')}
                </Button>
                <Button size="sm" variant="secondary" onClick={onNext} disabled={!onNext}
                        data-testid="viewer-next">
                  {t('viewer_next')}
                  <ChevronRight className="w-3.5 h-3.5" />
                </Button>
              </div>
            )}
            {actions}
            {isMediaDownloadable(item.media_type) && (
              <Button size="sm" variant="secondary" onClick={() => downloadMedia(item.id_media)}>
                <Download className="w-3.5 h-3.5" />
                {t('download')}
              </Button>
            )}
            {onEdit && (
              <Button size="sm" onClick={() => onEdit(item)}>
                <Pencil className="w-3.5 h-3.5" />
                {t('viewer_edit')}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
