'use client'

import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Server, Cpu, HardDrive, Gauge, AlertTriangle, Zap } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import api from '@/lib/api'
import EncodeProgressBar from '@/app/(dashboard)/media/components/EncodeProgressBar'
import type { EncodeProgress, EncodeDecision } from '@/types/api'

/**
 * Page « Serveur » — ce que cette machine sait faire, et ce qu'elle est en train de faire.
 *
 * Elle existe parce qu'une question revenait sans réponse : « pourquoi cet encodage est-il
 * si long ? ». La réponse tient dans trois chiffres qui n'étaient visibles nulle part —
 * l'encodeur réellement utilisé (matériel ou logiciel), le débit constaté sur cette
 * machine, et ce qui occupe la file.
 *
 * Réservée à l'EXPLOITANT du serveur (`require_server_operator`) : super-admin, ou
 * org-admin d'un serveur sans super-admin. Conséquence voulue sur un serveur mutualisé :
 * un org-admin d'organisation ne voit pas la file d'encodage des autres.
 */
type Worker = {
  hostname: string
  hw_encoders: string[]
  encoder_h264: string
  encoder_hevc: string
  cpu_count: number | null
  ffmpeg_threads: number | null
  ffmpeg_version: string | null
  work_dir: string
  disk_total_bytes: number
  disk_free_bytes: number
  at: number
}
type ServerStatus = {
  version: string
  workers: Worker[]
  queue: {
    id_media: number; media_name: string; id_org: number; transcode_status: string
    encode_progress: EncodeProgress | null; encode_decision: EncodeDecision | null
  }[]
  throughput: { encoder: string; samples: number; avg_speed: number }[]
  media: { count: number; total_bytes: number }
  encode_bands: { auto_below_s: number; refuse_above_s: number }
}

const gb = (b: number) => `${(b / 1e9).toFixed(1)} Go`
const mins = (s: number) => Math.round(s / 60)

function Panel({ icon: Icon, title, children }: {
  icon: React.ComponentType<{ className?: string }>; title: string; children: React.ReactNode
}) {
  return (
    <section className="sf-panel p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-800 mb-3">
        <Icon className="w-4 h-4 text-accent" />{title}
      </h2>
      {children}
    </section>
  )
}

export default function ServerPage() {
  const t = useTranslations('server')
  const { data, isLoading, error } = useQuery<ServerStatus>({
    queryKey: ['server-status'],
    queryFn: async () => (await api.get('/meta/server')).data,
    // La file bouge : on rafraîchit, mais sans marteler — la page reste ouverte longtemps.
    refetchInterval: 10_000,
    // Un 403 est un état stable (on ne devient pas porteur en réessayant) : réessayer
    // ferait clignoter la page et marteler le serveur pour rien.
    retry: (count, e) =>
      (e as { response?: { status?: number } })?.response?.status === 403 ? false : count < 2,
  })

  const notHolder = (error as { response?: { status?: number } } | null)?.response?.status === 403

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <Topbar title={t('title')} />
      <main className="flex-1 min-h-0 overflow-y-auto p-6">
        <div className="mx-auto w-full max-w-5xl space-y-4">
          {isLoading && <p className="text-sm text-gray-500">{t('loading')}</p>}

          {/* Non-porteur : ce n'est PAS une erreur. Un org-admin de marque sur un serveur
              d'intégrateur n'a rien fait de mal — le serveur est simplement exploité par
              quelqu'un d'autre. Même traitement visuel que la page Licence (retour d'Ed,
              2026-08-03) : un panneau qui explique, pas une phrase rouge qui accuse.
              Une VRAIE panne (réseau, backend à terre) garde, elle, un ton d'erreur. */}
          {notHolder && (
            <Panel icon={Server} title={t('title')}>
              <p className="text-sm text-gray-600">{t('managed_by_provider')}</p>
              <p className="mt-2 text-sm text-gray-500">{t('managed_hint')}</p>
            </Panel>
          )}
          {error && !notHolder && (
            <Panel icon={AlertTriangle} title={t('title')}>
              <p className="text-sm text-danger">{t('load_failed')}</p>
            </Panel>
          )}

          {data && (
            <>
              <Panel icon={Cpu} title={t('capacity')}>
                {data.workers.length === 0 ? (
                  // Silence explicite : sans worker, la page ne doit PAS afficher les
                  // capacités d'une machine éteinte.
                  <p className="flex items-center gap-2 text-sm text-warning">
                    <AlertTriangle className="w-4 h-4" />{t('no_worker')}
                  </p>
                ) : data.workers.map((w) => (
                  <div key={w.hostname} className="space-y-2 text-sm">
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-gray-600">
                      <span className="font-medium text-gray-800">{w.hostname}</span>
                      {w.cpu_count && <span>{t('cores', { n: w.cpu_count })}</span>}
                      {w.ffmpeg_version && <span>ffmpeg {w.ffmpeg_version}</span>}
                    </div>
                    {/* Le point le plus utile de la page : matériel ou logiciel. C'est ce
                        qui sépare « quelques minutes » de « plusieurs heures ». */}
                    <p className={w.hw_encoders.length ? 'text-success' : 'text-warning'}>
                      <Zap className="inline w-3.5 h-3.5 mr-1" />
                      {w.hw_encoders.length
                        ? t('hw_yes', { list: w.hw_encoders.join(', ') })
                        : t('hw_no')}
                    </p>
                    <p className="text-gray-600">
                      {t('encoders_used', { h264: w.encoder_h264, hevc: w.encoder_hevc })}
                    </p>
                    <p className="flex items-center gap-1.5 text-gray-600">
                      <HardDrive className="w-3.5 h-3.5" />
                      {t('workdir', {
                        dir: w.work_dir, free: gb(w.disk_free_bytes), total: gb(w.disk_total_bytes),
                      })}
                    </p>
                  </div>
                ))}
              </Panel>

              <Panel icon={Gauge} title={t('throughput')}>
                {data.throughput.length === 0 ? (
                  <p className="text-sm text-gray-500">{t('no_throughput')}</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead><tr>
                      <th className="text-left">{t('col_encoder')}</th>
                      <th className="text-right">{t('col_speed')}</th>
                      <th className="text-right">{t('col_samples')}</th>
                    </tr></thead>
                    <tbody>
                      {data.throughput.map((r) => (
                        <tr key={r.encoder} className="border-t border-white/5">
                          <td className="py-1.5 text-gray-700">{r.encoder}</td>
                          <td className="py-1.5 text-right tabular-nums text-gray-700">
                            {r.avg_speed}×
                          </td>
                          <td className="py-1.5 text-right tabular-nums text-gray-500">
                            {r.samples}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="mt-3 text-[11px] text-gray-500">
                  {t('bands_hint', {
                    auto: mins(data.encode_bands.auto_below_s),
                    refuse: Math.round(data.encode_bands.refuse_above_s / 3600),
                  })}
                </p>
              </Panel>

              <Panel icon={Server} title={t('queue', { n: data.queue.length })}>
                {data.queue.length === 0 ? (
                  <p className="text-sm text-gray-500">{t('queue_empty')}</p>
                ) : (
                  <ul className="space-y-2">
                    {data.queue.map((q) => (
                      <li key={q.id_media} className="text-sm">
                        <div className="flex items-center justify-between gap-3">
                          <span className="truncate text-gray-700">{q.media_name}</span>
                          <span className="shrink-0 text-[11px] text-gray-500">
                            {t(`st_${q.transcode_status}`)}
                          </span>
                        </div>
                        {q.encode_progress && (
                          <EncodeProgressBar progress={q.encode_progress} className="mt-1" />
                        )}
                        {q.encode_decision && (
                          <p className="mt-0.5 text-[11px] text-warning">
                            {t('needs_decision', { min: mins(q.encode_decision.estimate_s) })}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel icon={HardDrive} title={t('storage')}>
                <p className="text-sm text-gray-600">
                  {t('media_total', {
                    n: data.media.count, size: gb(data.media.total_bytes),
                  })}
                </p>
              </Panel>
            </>
          )}
        </div>
      </main>
    </div>
  )
}
