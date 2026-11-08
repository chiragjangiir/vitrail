'use client'

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Film, Image as ImageIcon, Music, Rss, Globe, FileText } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import BackButton from '@/components/ui/BackButton'
import api from '@/lib/api'
import { fmtDuration } from '@/components/analytics/DashboardView'

interface ContentRow {
  id_media: number | null; media_name: string | null; media_type: string | null
  plays: number; seconds: number; players: number; sites: number
}
interface ContentResponse {
  from_date: string; until_date: string
  total_plays: number; total_seconds: number; rows: ContentRow[]
}

const PERIODS = [7, 30, 90] as const
const TYPE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  video: Film, image: ImageIcon, audio: Music, feed_display: Rss, url_display: Globe,
}

export default function ContentDashboardPage() {
  const t = useTranslations('reports')
  const [days, setDays] = useState<number>(30)

  const period = useMemo(() => {
    const until = new Date(); const from = new Date()
    from.setDate(from.getDate() - (days - 1))
    return { from: from.toISOString().slice(0, 10), until: until.toISOString().slice(0, 10) }
  }, [days])

  const { data } = useQuery({
    queryKey: ['analytics-content', days],
    queryFn: async () => (await api.get<ContentResponse>('/analytics/content', { params: period })).data,
  })

  const maxPlays = useMemo(
    () => Math.max(1, ...(data?.rows ?? []).map((r) => r.plays)), [data])

  return (
    <>
      <Topbar title={t('content_title')}>
        <BackButton />
      </Topbar>
      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-8 space-y-6">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <p className="text-sm text-gray-400 max-w-2xl">{t('content_hint')}</p>
            <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
              {PERIODS.map((p) => (
                <button key={p} onClick={() => setDays(p)}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition-sf ${
                    days === p ? 'bg-surface text-accent shadow-sm' : 'text-gray-500 hover:text-gray-700'
                  }`}>{t('period_days', { n: p })}</button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div className="bg-surface rounded-lg border border-gray-200 p-4 shadow-sf-card">
              <p className="text-xs text-gray-500 mb-1">{t('content_total_plays')}</p>
              <p className="text-2xl font-semibold text-accent">
                {(data?.total_plays ?? 0).toLocaleString('fr-FR')}
              </p>
            </div>
            <div className="bg-surface rounded-lg border border-gray-200 p-4 shadow-sf-card">
              <p className="text-xs text-gray-500 mb-1">{t('content_total_duration')}</p>
              <p className="text-2xl font-semibold text-accent">{fmtDuration(data?.total_seconds ?? 0)}</p>
            </div>
            <div className="bg-surface rounded-lg border border-gray-200 p-4 shadow-sf-card">
              <p className="text-xs text-gray-500 mb-1">{t('content_distinct')}</p>
              <p className="text-2xl font-semibold text-accent">{data?.rows.length ?? 0}</p>
            </div>
          </div>

          <div className="bg-surface rounded-lg border border-gray-200 overflow-y-auto max-h-[62vh] shadow-sf-card">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide w-10">#</th>
                  {['content_col_name', 'content_col_plays', 'content_col_duration',
                    'content_col_players', 'content_col_sites'].map((k, i) => (
                    <th key={k} className={`px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide ${i === 0 ? 'text-left' : 'text-right'}`}>
                      {t(k)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(data?.rows ?? []).length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-10 text-center text-gray-400">{t('no_data')}</td></tr>
                )}
                {(data?.rows ?? []).map((r, i) => {
                  const Icon = TYPE_ICON[r.media_type ?? ''] ?? FileText
                  return (
                    <tr key={r.id_media ?? i} className="hover:bg-gray-50/50">
                      <td className="px-4 py-2.5 text-xs text-gray-400">{i + 1}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2 mb-1">
                          <Icon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                          <span className="text-gray-800 truncate">{r.media_name ?? `#${r.id_media}`}</span>
                        </div>
                        <div className="h-1 bg-gray-100 rounded-full overflow-hidden max-w-[240px]">
                          <div className="h-full bg-accent rounded-full"
                            style={{ width: `${Math.round((r.plays / maxPlays) * 100)}%` }} />
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-right font-medium text-gray-900">{r.plays.toLocaleString('fr-FR')}</td>
                      <td className="px-4 py-2.5 text-right text-gray-600">{fmtDuration(r.seconds)}</td>
                      <td className="px-4 py-2.5 text-right text-gray-600">{r.players}</td>
                      <td className="px-4 py-2.5 text-right text-gray-600">{r.sites}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </>
  )
}
