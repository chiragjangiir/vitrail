'use client'

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Users, Info } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import BackButton from '@/components/ui/BackButton'
import api from '@/lib/api'

interface AudienceSiteRow {
  id_site: number | null; site_name: string | null; plays: number; seconds: number; est_impressions: number
}
interface AudienceHourRow { hour: number; plays: number; est_impressions: number }
interface AudienceResponse {
  from_date: string; until_date: string; contacts_per_hour: number
  total_est_impressions: number; by_site: AudienceSiteRow[]; by_hour: AudienceHourRow[]
}

const PERIODS = [7, 30, 90] as const

function fmtNum(n: number): string { return n.toLocaleString('fr-FR') }

export default function AudienceDashboardPage() {
  const t = useTranslations('reports')
  const [days, setDays] = useState<number>(30)

  const period = useMemo(() => {
    const until = new Date(); const from = new Date()
    from.setDate(from.getDate() - (days - 1))
    return { from: from.toISOString().slice(0, 10), until: until.toISOString().slice(0, 10) }
  }, [days])

  const { data } = useQuery({
    queryKey: ['analytics-audience', days],
    queryFn: async () => (await api.get<AudienceResponse>('/analytics/audience', { params: period })).data,
  })

  const hourMax = useMemo(
    () => Math.max(1, ...(data?.by_hour ?? []).map((h) => h.est_impressions)), [data])
  const siteMax = useMemo(
    () => Math.max(1, ...(data?.by_site ?? []).map((s) => s.est_impressions)), [data])

  return (
    <>
      <Topbar title={t('aud_title')}>
        <BackButton />
      </Topbar>
      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-8 space-y-6">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <p className="text-sm text-gray-400 max-w-2xl">{t('aud_hint')}</p>
            <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
              {PERIODS.map((p) => (
                <button key={p} onClick={() => setDays(p)}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition-sf ${
                    days === p ? 'bg-surface text-accent shadow-sm' : 'text-gray-500 hover:text-gray-700'
                  }`}>{t('period_days', { n: p })}</button>
              ))}
            </div>
          </div>

          <div className="flex items-start gap-2 text-xs text-gray-500 bg-gray-50 rounded px-3 py-2">
            <Info className="w-4 h-4 shrink-0 text-accent mt-0.5" />
            <span>{t('aud_method', { cph: data?.contacts_per_hour ?? 0 })}</span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div className="bg-surface rounded-lg border border-gray-200 p-4 shadow-sf-card">
              <div className="flex items-center gap-2 text-gray-500 mb-2">
                <Users className="w-4 h-4 text-accent" /><span className="text-xs">{t('aud_total')}</span>
              </div>
              <p className="text-2xl font-semibold text-accent">{fmtNum(data?.total_est_impressions ?? 0)}</p>
            </div>
            <div className="bg-surface rounded-lg border border-gray-200 p-4 shadow-sf-card">
              <p className="text-xs text-gray-500 mb-1">{t('aud_sites')}</p>
              <p className="text-2xl font-semibold text-gray-900">{(data?.by_site ?? []).filter((s) => s.id_site).length}</p>
            </div>
            <div className="bg-surface rounded-lg border border-gray-200 p-4 shadow-sf-card">
              <p className="text-xs text-gray-500 mb-1">{t('aud_cph')}</p>
              <p className="text-2xl font-semibold text-gray-900">{data?.contacts_per_hour ?? 0}</p>
            </div>
          </div>

          {/* Par heure de la journée */}
          <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">{t('aud_by_hour')}</h2>
            <div className="flex items-end gap-0.5 h-40">
              {(data?.by_hour ?? []).map((h) => (
                <div key={h.hour} className="flex-1 flex flex-col justify-end items-center"
                  title={`${h.hour}h — ${fmtNum(h.est_impressions)} ${t('aud_contacts')}`}>
                  <div className="w-full bg-accent/70 rounded-t"
                    style={{ height: `${Math.max(2, Math.round((h.est_impressions / hourMax) * 100))}%` }} />
                </div>
              ))}
            </div>
            <div className="flex justify-between text-[10px] text-gray-400 mt-1">
              <span>0h</span><span>6h</span><span>12h</span><span>18h</span><span>23h</span>
            </div>
          </div>

          {/* Par site */}
          <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">{t('aud_by_site')}</h2>
            {(data?.by_site ?? []).length === 0 ? (
              <p className="text-sm text-gray-400 py-6 text-center">{t('no_data')}</p>
            ) : (
              <div className="space-y-3">
                {(data?.by_site ?? []).map((s, i) => (
                  <div key={s.id_site ?? i} className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-sm text-gray-700 truncate">{s.site_name ?? t('aud_no_site')}</span>
                        <span className="text-xs text-gray-500 shrink-0">
                          {fmtNum(s.est_impressions)} {t('aud_contacts')}
                        </span>
                      </div>
                      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-accent rounded-full"
                          style={{ width: `${Math.round((s.est_impressions / siteMax) * 100)}%` }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  )
}
