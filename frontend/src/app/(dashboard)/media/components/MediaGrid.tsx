'use client'

import { useState } from 'react'
import Image from 'next/image'
import { clsx } from 'clsx'
import { FileVideo, AudioLines, FileImage, FileText, Globe, Rss, Trash2, Lock, Check, ShieldAlert, Layers, Download, MonitorPlay, Pencil } from 'lucide-react'
import { useTranslations } from 'next-intl'
import StatusBadge from '@/components/ui/StatusBadge'
import type { MediaListItem } from '@/types/api'
import { TagBadges, useTagNamespaces } from '@/components/tags/TagControls'
import { GovernedBadge } from '@/components/governance/NodeSelect'
import { downloadMedia, isMediaDownloadable } from '@/lib/mediaDownload'
import MediaUsageHint from './MediaUsageHint'
import EncodeProgressBar from './EncodeProgressBar'

interface MediaGridProps {
  items: MediaListItem[]
  onSelect: (item: MediaListItem) => void
  /** Raccourci d'édition (demande d'Ed) : depuis que le clic ouvre la VISIONNEUSE, il
      fallait deux gestes pour éditer. Ce bouton rouvre le tiroir directement. */
  onEdit?: (item: MediaListItem) => void
  onDelete: (item: MediaListItem) => void
  onEditEmbargo: (item: MediaListItem) => void
  /** Résumé de diffusion chargé en lot par la page (une requête pour tout l'écran). */
  usage?: Record<string, { playlists: number; screens: number }>
  selectMode?: boolean
  selectedIds?: Set<number>
}

export function MediaPlaceholder({ type }: { type: string }) {
  // Vignette audio plus avenante : panneau dégradé + onde sonore en accent,
  // plutôt qu'une petite note grise terne.
  if (type === 'audio') {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-accent/15 via-accent/5 to-transparent">
        <AudioLines className="w-10 h-10 text-accent/70" strokeWidth={1.75} />
      </div>
    )
  }
  // Page Web (url_display) : panneau accent + globe (en attendant la vignette de capture Playwright).
  if (type === 'url_display') {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-accent/15 via-accent/5 to-transparent">
        <Globe className="w-10 h-10 text-accent/70" strokeWidth={1.75} />
      </div>
    )
  }
  // Feed (feed_display) : panneau accent + icône RSS.
  if (type === 'feed_display') {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-accent/15 via-accent/5 to-transparent">
        <Rss className="w-10 h-10 text-accent/70" strokeWidth={1.75} />
      </div>
    )
  }
  // Entrée HDMI (hdmi_input) : panneau accent + écran-lecture (média pointeur BrightSign).
  if (type === 'hdmi_input') {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-accent/15 via-accent/5 to-transparent">
        <MonitorPlay className="w-10 h-10 text-accent/70" strokeWidth={1.75} />
      </div>
    )
  }
  // Document (PDF/PPT/PPTX…) sans vignette de page rendue : panneau accent + icône fichier,
  // homogène avec audio/feed/URL (demande Ed 18/07 — plus de note grise terne).
  if (type === 'document') {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-accent/15 via-accent/5 to-transparent">
        <FileText className="w-10 h-10 text-accent/70" strokeWidth={1.75} />
      </div>
    )
  }
  if (type === 'video') return <FileVideo className="w-8 h-8 text-gray-300" />
  if (type === 'html_package') return <Globe className="w-8 h-8 text-gray-300" />
  return <FileImage className="w-8 h-8 text-gray-300" />
}

export function TranscodeStatusBadge({ status }: { status: MediaListItem['transcode_status'] }) {
  const t = useTranslations('media')
  const map = {
    pending:    { status: 'pending'    as const, label: t('status_pending')    },
    processing: { status: 'processing' as const, label: t('status_processing') },
    done:       { status: 'done'       as const, label: t('status_done')       },
    error:      { status: 'error'      as const, label: t('status_error')      },
    // Étalonnage : encodage trop long, rien ne part sans un geste humain. En `warning`
    // et non `pending` — ce n'est pas une file d'attente qui se videra toute seule.
    awaiting_decision: { status: 'warning' as const, label: t('status_awaiting_decision') },
  }
  // Repli explicite : un statut inconnu (serveur plus récent que ce build) doit s'afficher,
  // pas faire planter la grille sur un déstructurage d'`undefined`.
  const entry = map[status] ?? { status: 'info' as const, label: status }
  return <StatusBadge status={entry.status} label={entry.label} />
}

export function formatSize(bytes: number | null) {
  if (!bytes) return null
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export default function MediaGrid({
  items, onSelect, onEdit, onDelete, onEditEmbargo, usage, selectMode = false, selectedIds,
}: MediaGridProps) {
  const t = useTranslations('media')
  const { data: namespaces = [] } = useTagNamespaces()
  // Survol d'une VIGNETTE → « diffusé sur N écrans » (même mécanique que la vue liste :
  // la requête ne part qu'après un court délai, jamais au rendu).
  const [hovered, setHovered] = useState<number | null>(null)

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400">
        <FileImage className="w-10 h-10 mb-3 opacity-30" />
        <p className="text-sm">{t('no_media')}</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
      {items.map((item) => {
        const selected = selectedIds?.has(item.id_media) ?? false
        return (
        <div
          key={item.id_media}
          className={clsx(
            'group relative bg-surface rounded-lg border overflow-hidden hover:shadow-sm transition-sf cursor-pointer',
            selected ? 'border-accent ring-2 ring-accent' : 'border-gray-200 hover:border-accent'
          )}
          onClick={() => onSelect(item)}
          onMouseEnter={() => setHovered(item.id_media)}
          onMouseLeave={() => setHovered((h) => (h === item.id_media ? null : h))}
        >
          {/* Thumbnail */}
          <div className="aspect-video bg-gray-50 flex items-center justify-center relative overflow-hidden">
            {item.thumbnail_url ? (
              <Image
                src={item.thumbnail_url}
                alt={item.media_name}
                fill
                className="object-cover"
                sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 20vw"
                unoptimized
              />
            ) : (
              <MediaPlaceholder type={item.media_type} />
            )}
          </div>

          {/* Selection checkbox (top-left, select mode only) */}
          {selectMode && (
            <div className="absolute top-2 left-2">
              <span className={clsx(
                'flex items-center justify-center w-5 h-5 rounded border shadow-sm',
                selected ? 'bg-accent border-accent text-white' : 'bg-black/60 border-gray-300'
              )}>
                {selected && <Check className="w-3.5 h-3.5" />}
              </span>
            </div>
          )}

          {/* Action buttons (top-right, appear on hover) */}
          <div className={clsx(
            'absolute top-2 right-2 flex gap-1',
            'opacity-0 group-hover:opacity-100 transition-sf',
            selectMode && 'hidden'
          )}>
            {isMediaDownloadable(item.media_type) && (
              <button
                onClick={(e) => { e.stopPropagation(); void downloadMedia(item.id_media) }}
                className="p-1.5 rounded bg-black/60 text-gray-400 hover:text-accent hover:bg-accent/10 shadow-sm"
                title={t('download')}
                aria-label={t('download')}
              >
                <Download className="w-3.5 h-3.5" />
              </button>
            )}
            {/* Gouvernance §XVIII (D9) : un média d'un nœud qu'on n'administre pas ne
                s'édite ni ne se supprime — le serveur répond 403, on n'affiche donc
                ni l'embargo ni la poubelle. Le téléchargement reste offert (lecture). */}
            {!item.governed_readonly && (
              <>
                {onEdit && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onEdit(item) }}
                    className="p-1.5 rounded bg-black/60 text-gray-400 hover:text-accent hover:bg-accent/10 shadow-sm"
                    title={t('viewer_edit')}
                    aria-label={t('viewer_edit')}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); onEditEmbargo(item) }}
                  className="p-1.5 rounded bg-black/60 text-orange-400 hover:text-orange-300 hover:bg-orange-500/15 shadow-sm"
                  title="Edit embargo"
                >
                  <Lock className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); onDelete(item) }}
                  className="p-1.5 rounded bg-black/60 text-gray-400 hover:text-danger hover:bg-red-500/10 shadow-sm"
                  aria-label={`Delete ${item.media_name}`}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </>
            )}
          </div>

          {/* Pastilles coin haut-gauche — empilées : embargo puis gouvernance (§XVIII D9),
              sinon les deux se superposeraient sur un média national sous embargo. */}
          {!selectMode && (item.not_before_utc || item.embargo_event_id || item.id_governance_node != null) && (
            <div className="absolute top-2 left-2 z-10 flex flex-col items-start gap-1">
              {(item.not_before_utc || item.embargo_event_id) && (
                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-100 dark:bg-orange-500/20 text-orange-700 dark:text-orange-300 shadow-sm">
                  <Lock className="w-2.5 h-2.5" />
                  {item.embargo_event_name ?? new Date(item.not_before_utc!).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                </span>
              )}
              <GovernedBadge idNode={item.id_governance_node} readonly={item.governed_readonly} />
            </div>
          )}

          {/* Document multipage : badge « N pages » — coin bas-gauche de la vignette */}
          {item.media_type === 'document' && (item.page_count ?? 0) > 0 && (
            <div className="absolute top-[calc(56.25%-1.5rem)] left-2 z-10">
              <span
                className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/90 text-white shadow-sm"
                title={t('doc_pages_badge_title')}
              >
                <FileText className="w-2.5 h-2.5" />
                {t('doc_pages_badge', { count: item.page_count ?? 0 })}
              </span>
            </div>
          )}

          {/* Renditions badge (artefacts adaptatifs) — coin bas-droit de la vignette */}
          {item.has_renditions && (
            <div className="absolute top-[calc(56.25%-1.5rem)] right-2 z-10">
              <span
                className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/90 text-white shadow-sm"
                title={t('renditions_badge_title')}
              >
                <Layers className="w-2.5 h-2.5" />
                {t('renditions_badge')}
              </span>
            </div>
          )}

          {/* Quarantaine badge (§ Q5) — prioritaire, en bas */}
          {item.is_blocked && (
            <div className="absolute bottom-[3.2rem] left-2 z-10">
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-600 text-white shadow-sm">
                <ShieldAlert className="w-2.5 h-2.5" />
                {t('quarantine_badge')}
              </span>
            </div>
          )}

          {/* Info */}
          <div className="p-2.5">
            <p className="text-xs font-medium text-gray-800 truncate" title={item.media_name}>
              {item.media_name}
            </p>
            <div className="flex items-center justify-between mt-1.5 gap-1 flex-wrap">
              <TranscodeStatusBadge status={item.transcode_status} />
              {formatSize(item.served_size_bytes ?? item.file_size_bytes) && (
                <span className="text-xs text-gray-400">
                  {formatSize(item.served_size_bytes ?? item.file_size_bytes)}
                </span>
              )}
            </div>
            {/* Vignette : barre seule (la place manque pour un libellé) — le détail chiffré
                est dans la vue liste et le tiroir. */}
            <EncodeProgressBar progress={item.encode_progress} compact className="mt-1.5" />
            <MediaUsageHint
                      idMedia={item.id_media}
                      hovered={hovered === item.id_media}
                      summary={usage?.[String(item.id_media)]}
                    />
            {item.tags && item.tags.length > 0 && (
              <div className="mt-1.5">
                <TagBadges ids={item.tags} namespaces={namespaces} max={4} />
              </div>
            )}
          </div>
        </div>
        )
      })}
    </div>
  )
}
