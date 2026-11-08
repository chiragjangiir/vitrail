'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { X, Globe, Rss, MonitorPlay, FileQuestion, Maximize2, Minimize2 } from 'lucide-react'
import api from '@/lib/api'
import type { DocumentPagesResult, MediaRead, PlaylistItemRead, TemplateRead } from '@/types/api'
import { itemHoldMs, selectedPages } from './loopTiming'

/**
 * Scène MULTI-ZONES de l'aperçu : compose une playlist **comme le fait un écran** quand sa
 * playlist pointe un template à plusieurs zones (constat d'Ed 2026-08-08 — le lecteur ne
 * montrait qu'une liste plate, donc autre chose que ce qui allait diffuser).
 *
 * 🔑 Ce qui est copié du player, et pourquoi ça ne s'invente pas :
 *  - **positions en % du canevas** — `left = x / canvas_width` (`player.js:1550`) : c'est ce
 *    qui rend un template indépendant de la résolution de l'écran (FHD ↔ 4K, même ratio) ;
 *  - **`object-fit: contain` sur fond noir** — mesuré identique sur les 8 chemins de rendu du
 *    player (`player.js:306, 336, 832, 861, 949, 1706, 1741, 1778`). Un `cover` ici montrerait
 *    un cadrage que l'écran ne fera pas, sur l'écran même où l'on vient vérifier le cadrage ;
 *  - **un minuteur PAR ZONE, piloté par `duration_ms`** — jamais par la fin de la vidéo : en
 *    zone, le player met `loop = true` et fait avancer la zone sur son timer (`player.js:1703`).
 *
 * ⛔ Ce que la scène ne rejoue PAS, et qu'elle DIT (bandeau de pied) : rotation « N par tour »,
 * spots de campagne et recouvrement plein écran (injectés **par player**, un aperçu n'en a
 * pas), filtrage par tags. Un aperçu qui diverge sans le dire est pire qu'une absence
 * d'aperçu — c'est la règle qu'on applique déjà aux couleurs de la charte de marque (P3.4).
 */

export type ZoneDef = TemplateRead['layout']['zones'][number]

/** Part de la hauteur de fenêtre occupée par la scène au repos — la valeur de la
 *  visionneuse (`max-h-[65vh]`), pour que les deux lecteurs aient le même poids visuel. */
const MAX_STAGE_VH = 0.65

/** Types qu'une zone ne rend pas ici : ils sont PRODUITS sur l'écran, à la diffusion.
 *  (Les 8 modes de rendu des feeds vivent dans `player.js` ; les réimplémenter en React
 *  serait un second moteur de rendu, qui divergerait dès la première évolution.) */
function pointerIcon(type: string | null | undefined) {
  if (type === 'feed_display') return Rss
  if (type === 'hdmi_input') return MonitorPlay
  if (type === 'url_display') return Globe
  return FileQuestion
}

function isRenderedInStage(type: string | null | undefined): boolean {
  return type === 'image' || type === 'video' || type === 'document'
}

/** Document : le serveur le déroule en N items IMAGE (`_document_page_items`, §3.2). On
 *  fait tourner les pages DANS la zone au rythme de `duration_ms` — le total retombe donc
 *  sur `itemHoldMs`, qui est aussi ce que la zone attend avant d'avancer. */
function DocumentInZone({ item }: { item: PlaylistItemRead }) {
  const [page, setPage] = useState(0)
  const { data } = useQuery<DocumentPagesResult>({
    queryKey: ['media', 'pages', item.id_media],
    queryFn: () => api.get<DocumentPagesResult>(`/media/${item.id_media}/pages`).then((r) => r.data),
    enabled: !!item.id_media,
  })

  const all = data?.pages ?? []
  // Sélection "2-5,8" honorée : c'est ce que l'écran diffuse, et l'ordre de saisie compte.
  const wanted = selectedPages(item.doc_pages, all.length)
  const shown = wanted.map((n) => all.find((p) => p.page === n)).filter(Boolean) as typeof all

  useEffect(() => { setPage(0) }, [item.id_item])
  useEffect(() => {
    if (shown.length <= 1) return
    const timer = setTimeout(() => setPage((p) => (p + 1) % shown.length), item.duration_ms || 10000)
    return () => clearTimeout(timer)
  }, [page, shown.length, item.duration_ms])

  const current = shown[Math.min(page, Math.max(0, shown.length - 1))]
  if (!current) return null
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={current.url} alt="" className="w-full h-full object-contain bg-black" />
}

/** Contenu courant d'une zone. Le détail porte l'URL signée (la même clé de cache que la
 *  visionneuse : ouvrir un contenu puis la scène ne refait pas l'appel). */
function ZoneContent({ item }: { item: PlaylistItemRead }) {
  const t = useTranslations()
  const { data } = useQuery<MediaRead>({
    queryKey: ['media', 'detail', item.id_media],
    queryFn: () => api.get<MediaRead>(`/media/${item.id_media}`).then((r) => r.data),
    enabled: !!item.id_media && isRenderedInStage(item.media_type),
  })

  if (!isRenderedInStage(item.media_type)) {
    const Icon = pointerIcon(item.media_type)
    return (
      <div className="w-full h-full flex flex-col items-center justify-center gap-1.5 bg-black px-2 text-center">
        <Icon className="w-6 h-6 text-accent shrink-0" />
        <p className="text-[11px] font-medium text-gray-800 truncate max-w-full">
          {item.media_name ?? ''}
        </p>
        <p className="text-[10px] text-gray-500 leading-tight">
          {item.media_type ? t(`media.type_${item.media_type}`) : ''} · {t('playlists.stage_not_rendered')}
        </p>
      </div>
    )
  }

  if (item.media_type === 'document') return <DocumentInZone item={item} />

  const url = data?.cdn_url_signed
  if (!url) return null

  if (item.media_type === 'video') {
    // `loop` + `muted` : en zone le player boucle la vidéo et laisse le TIMER décider de
    // l'avance (`player.js:1703`). Muet ici par choix d'aperçu — N zones sonores en même
    // temps seraient inaudibles ; c'est dit dans le bandeau.
    // eslint-disable-next-line jsx-a11y/media-has-caption
    return <video src={url} autoPlay loop muted playsInline className="w-full h-full object-contain bg-black" />
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={item.media_name ?? ''} className="w-full h-full object-contain bg-black" />
}

function Zone({ def, items, canvasWidth, canvasHeight }: {
  def: ZoneDef
  items: PlaylistItemRead[]
  canvasWidth: number
  canvasHeight: number
}) {
  const t = useTranslations('playlists')
  const [index, setIndex] = useState(0)

  useEffect(() => { setIndex(0) }, [items])

  const item = items.length ? items[index % items.length] : undefined

  // 🔑 UN MINUTEUR PAR ZONE. Un minuteur global ferait avancer toutes les zones au même
  // rythme — l'aperçu aurait l'air de marcher tout en étant faux. Chaque zone du player a
  // le sien (`_mzScheduleAdvance`), c'est même la raison pour laquelle les zones ne sont
  // jamais suspendues pendant un takeover (leur wall-clock doit rester vrai, §P3.6).
  useEffect(() => {
    if (!item || items.length <= 1) return
    const timer = setTimeout(
      () => setIndex((i) => (i + 1) % items.length),
      itemHoldMs(item) ?? 10000,
    )
    return () => clearTimeout(timer)
  }, [item, index, items.length])

  return (
    <div
      className="absolute overflow-hidden bg-black ring-1 ring-white/10"
      data-testid={`stage-zone-${def.index}`}
      data-item-name={item?.media_name ?? ''}
      style={{
        left: `${(def.x / canvasWidth) * 100}%`,
        top: `${(def.y / canvasHeight) * 100}%`,
        width: `${(def.w / canvasWidth) * 100}%`,
        height: `${(def.h / canvasHeight) * 100}%`,
      }}
    >
      {item ? (
        <ZoneContent key={item.id_item} item={item} />
      ) : (
        // Zone sans contenu : le player laisse un rectangle noir. On le dit, sinon on
        // cherche une panne d'aperçu là où il n'y a simplement rien d'affecté à la zone.
        <div className="w-full h-full flex items-center justify-center px-2 text-center">
          <p className="text-[10px] text-gray-500">{t('stage_zone_empty')}</p>
        </div>
      )}
    </div>
  )
}

interface Props {
  playlistName: string
  templateName: string | null
  canvasWidth: number
  canvasHeight: number
  zones: ZoneDef[]
  /** Items de la boucle rattachés à leur zone EFFECTIVE (sous-playlists déjà dépliées). */
  itemsByZone: Map<number, PlaylistItemRead[]>
  onClose: () => void
  elevated?: boolean
}

export default function TemplateStage({
  playlistName, templateName, canvasWidth, canvasHeight, zones, itemsByZone, onClose, elevated,
}: Props) {
  const t = useTranslations()
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  /**
   * Taille de la scène : le canevas garde SON ratio et tient dans la place disponible.
   *
   * Callback ref (et pas `useRef` + `useEffect([])`) : le nœud n'existe pas au premier
   * rendu, l'observateur ne se brancherait jamais — piège déjà payé deux fois (éditeur de
   * templates, grille /media).
   *
   * 🔑 Au repos, la HAUTEUR ne vient pas du cadre mais de la fenêtre (65 %), et le cadre
   * épouse ensuite le canevas. Un cadre à hauteur fixe laissait une bande noire morte
   * au-dessus et en dessous dès que le canevas était contraint par la LARGEUR — ce qui est
   * le cas courant d'un 16:9 dans un panneau de 1024 px (vu sur une capture, pas dans le
   * code). La visionneuse, elle, épouse son média : les deux lecteurs se ressemblent enfin.
   */
  // Plein écran : déclaré ICI parce que le calcul de la taille du canevas en dépend
  // (au repos la hauteur vient de la fenêtre, en plein écran du cadre). Le reste du
  // mécanisme est plus bas.
  const panelRef = useRef<HTMLDivElement | null>(null)
  const [expanded, setExpanded] = useState(false)

  const [box, setBox] = useState<{ w: number; h: number } | null>(null)
  // Un seul point de démontage : l'observateur ET l'écouteur de fenêtre. La ref est
  // rappelée à chaque bascule plein écran — sans ce nettoyage, un écouteur de plus à
  // chaque clic.
  const teardownRef = useRef<(() => void) | null>(null)
  const frameRef = useCallback((node: HTMLDivElement | null) => {
    teardownRef.current?.()
    teardownRef.current = null
    if (!node) return
    const apply = () => {
      const cs = getComputedStyle(node)
      const r = node.getBoundingClientRect()
      const availW = r.width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
      const availH = expanded
        ? r.height - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
        : window.innerHeight * MAX_STAGE_VH
      if (availW <= 0 || availH <= 0) return
      const scale = Math.min(availW / canvasWidth, availH / canvasHeight)
      const w = Math.round(canvasWidth * scale)
      const h = Math.round(canvasHeight * scale)
      // ⚠️ Sans cette garde, boucle infinie : au repos le cadre est dimensionné PAR le
      // canevas, donc le poser fait re-mesurer le cadre, qui repose le canevas…
      setBox((prev) => (prev && prev.w === w && prev.h === h ? prev : { w, h }))
    }
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(node)
    // Au repos la hauteur vient de la FENÊTRE : l'observateur du cadre ne la voit pas
    // changer tant que la largeur ne bouge pas.
    window.addEventListener('resize', apply)
    teardownRef.current = () => {
      ro.disconnect()
      window.removeEventListener('resize', apply)
    }
  }, [canvasWidth, canvasHeight, expanded])
  useEffect(() => () => { teardownRef.current?.(); teardownRef.current = null }, [])

  /**
   * Plein écran (retour d'Ed 2026-08-13 : la scène s'ouvrait à la taille de la fenêtre,
   * alors que le lecteur des autres playlists est un panneau posé au centre).
   *
   * 🔑 **L'agrandissement est porté par le CSS, pas par l'API navigateur** : celle-ci peut
   * échouer (iframe sans `allowfullscreen`, refus faute de geste utilisateur) et le bouton
   * serait alors mort. On agrandit donc toujours, et on DEMANDE en plus le vrai plein écran
   * — qui, lui, retire le cadre du navigateur.
   *
   * (`expanded` est déclaré plus haut : le calcul de la taille du canevas en dépend.)
   */
  const toggleExpanded = useCallback(() => {
    if (expanded) {
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
      setExpanded(false)
      return
    }
    setExpanded(true)
    panelRef.current?.requestFullscreen?.().catch(() => {})
  }, [expanded])

  // L'utilisateur peut sortir du plein écran par le navigateur (Échap, F11, barre) : on
  // se recale sur lui, sinon le panneau resterait agrandi avec un bouton « réduire » qui
  // ne correspond plus à rien.
  useEffect(() => {
    const onFsChange = () => { if (!document.fullscreenElement) setExpanded(false) }
    document.addEventListener('fullscreenchange', onFsChange)
    return () => document.removeEventListener('fullscreenchange', onFsChange)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Phase capture + stopPropagation, comme la visionneuse : ouverte par-dessus un
      // drawer, Échap ne doit fermer QUE la scène.
      if (e.key !== 'Escape') return
      e.stopPropagation()
      // En plein écran NATIF, Échap appartient au navigateur : il réduit, et fermer la
      // scène en plus ferait disparaître l'aperçu sur un geste qui ne demandait que ça.
      if (document.fullscreenElement) return
      if (expanded) { setExpanded(false); return }
      onClose()
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [onClose, expanded])

  if (!mounted) return null

  // Portail vers `document.body` : `DashboardShell` monte la bulle d'aide en FRÈRE du
  // conteneur des pages, et aucun z-index interne ne sort d'un contexte d'empilement —
  // sans portail elle recouvrirait le pied de la scène (leçon de la visionneuse, 29/07).
  return createPortal(
    <div
      className={`fixed inset-0 ${elevated ? 'z-[60]' : 'z-50'} bg-black/85 backdrop-blur-sm flex items-center justify-center ${expanded ? 'p-0' : 'p-6'}`}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      data-testid="template-stage"
      data-expanded={expanded ? '1' : '0'}
    >
      {/* Au repos : MÊME gabarit que la visionneuse des autres playlists (panneau centré
          `max-w-5xl`, zone de rendu plafonnée à 65vh) — la scène occupait toute la fenêtre
          et écrasait tout le reste. Le plein écran est un GESTE, pas le défaut. */}
      <div
        ref={panelRef}
        className={`sf-panel flex flex-col overflow-hidden ${
          expanded ? 'w-full h-full max-w-none rounded-none' : 'w-full max-w-5xl max-h-full'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="shrink-0 px-5 py-3 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-base font-semibold text-gray-900 truncate">{playlistName}</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {templateName ? `${templateName} · ` : ''}
              {t('templates.zone_count', { count: zones.length })} · {canvasWidth}×{canvasHeight}
            </p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={toggleExpanded}
              className="text-gray-400 hover:text-gray-800 transition-sf p-1"
              title={expanded ? t('playlists.stage_reduce') : t('playlists.stage_fullscreen')}
              aria-label={expanded ? t('playlists.stage_reduce') : t('playlists.stage_fullscreen')}
              data-testid="stage-fullscreen"
            >
              {expanded ? <Minimize2 className="w-5 h-5" /> : <Maximize2 className="w-5 h-5" />}
            </button>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-800 transition-sf p-1"
              title={t('media.close_viewer')}
              aria-label={t('media.close_viewer')}
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Au repos, AUCUNE hauteur : le cadre épouse le canevas (dont la taille vient de
            `MAX_STAGE_VH` et de la largeur disponible). En plein écran, c'est lui qui
            commande et le canevas s'y inscrit. */}
        <div
          ref={frameRef}
          className={`flex items-center justify-center bg-black/40 p-4 ${
            expanded ? 'flex-1 min-h-0' : ''
          }`}
        >
          {box && (
            <div className="relative bg-black" style={{ width: box.w, height: box.h }} data-testid="stage-canvas">
              {zones.map((z) => (
                <Zone
                  key={z.index}
                  def={z}
                  items={itemsByZone.get(z.index) ?? []}
                  canvasWidth={canvasWidth}
                  canvasHeight={canvasHeight}
                />
              ))}
            </div>
          )}
        </div>

        {/* Ce que la scène ne rejoue pas — écrit, pas sous-entendu. */}
        <p className="shrink-0 px-5 py-3 text-xs text-gray-500">{t('playlists.stage_note')}</p>
      </div>
    </div>,
    document.body,
  )
}
