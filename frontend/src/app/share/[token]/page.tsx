'use client'

import { use, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import {
  DashboardView, fmtEur, type ExecutiveDashboard, type RoiEstimate,
} from '@/components/analytics/DashboardView'
import CampaignReportView, { type CampaignReport } from '@/components/campaigns/CampaignReportView'

interface PublicShareView {
  org_name: string
  primary_color: string
  report_title: string | null
  report_subtitle: string | null
  logo_url: string | null
  report_type?: 'executive' | 'campaign'
  dashboard: ExecutiveDashboard | null
  roi: RoiEstimate | null
  campaign_report: CampaignReport | null
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

class ShareAuthError extends Error {
  code: string
  constructor(code: string) { super(code); this.code = code }
}

export default function PublicSharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params)
  const t = useTranslations('reports')
  const tCamp = useTranslations('campaigns')
  // Mot de passe soumis (jamais persisté — RAM only, re-demandé au refresh).
  const [password, setPassword] = useState<string | null>(null)
  const [pwInput, setPwInput] = useState('')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['public-share', token, password],
    queryFn: async (): Promise<PublicShareView> => {
      const res = await fetch(`${API_BASE}/api/v1/public/share/${token}`, {
        headers: password ? { 'X-Share-Password': password } : undefined,
      })
      if (res.status === 401 || res.status === 403) {
        let detail = ''
        try { detail = (await res.json())?.detail ?? '' } catch { /* corps non-JSON */ }
        throw new ShareAuthError(detail || 'password_required')
      }
      if (!res.ok) throw new Error('not found')
      return res.json()
    },
    retry: false,
    refetchInterval: 120000,
  })

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }
  if (isError && error instanceof ShareAuthError) {
    const wrong = error.code === 'invalid_password'
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-canvas px-6">
        <div className="w-full max-w-sm bg-surface rounded-lg border border-gray-200 p-6 space-y-4 shadow-sf-card">
          <div className="flex items-center gap-2">
            <Lock className="w-4 h-4 text-accent" />
            <h1 className="text-sm font-semibold text-gray-900">{t('share_pw_title')}</h1>
          </div>
          <p className="text-xs text-gray-500">{t('share_pw_hint')}</p>
          <form
            className="space-y-3"
            onSubmit={(e) => { e.preventDefault(); if (pwInput) setPassword(pwInput) }}
          >
            <input
              type="password"
              autoFocus
              value={pwInput}
              onChange={(e) => setPwInput(e.target.value)}
              placeholder={t('share_pw_placeholder')}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
            {wrong && <p className="text-xs text-danger">{t('share_pw_wrong')}</p>}
            <button
              type="submit"
              disabled={!pwInput}
              className="w-full py-2 text-sm font-medium text-white bg-accent rounded-md disabled:opacity-50"
            >
              {t('share_pw_submit')}
            </button>
          </form>
        </div>
      </div>
    )
  }
  if (isError || !data) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-2 bg-canvas text-gray-400">
        <p className="text-lg font-medium text-gray-600">{t('share_invalid_title')}</p>
        <p className="text-sm">{t('share_invalid_hint')}</p>
      </div>
    )
  }

  // ── Lien « campagne » (Retail Media S4) : rapport annonceur white-label ──
  if (data.report_type === 'campaign' && data.campaign_report) {
    const cr = data.campaign_report
    return (
      <div className="min-h-screen bg-canvas">
        <div className="h-1.5 w-full" style={{ background: data.primary_color }} />
        <header className="w-full px-6 py-6 border-b border-gray-200 bg-surface">
          <div className="flex items-center gap-4 flex-wrap">
            {data.logo_url && (
              <img src={data.logo_url} alt="" className="h-10 max-w-[160px] object-contain" />
            )}
            <div className="min-w-0">
              <h1 className="text-lg font-semibold text-gray-900 truncate">
                {tCamp('report_title')} — {cr.campaign.campaign_name}
              </h1>
              <p className="text-xs text-gray-400">
                {cr.campaign.advertiser_name ? `${cr.campaign.advertiser_name} · ` : ''}
                {data.org_name}
                {' · '}{cr.period.from} → {cr.period.until}
              </p>
            </div>
          </div>
        </header>
        <main className="w-full px-6 py-8 space-y-6">
          <CampaignReportView report={cr} t={tCamp} />
          <p className="text-center text-xs text-gray-400 pt-2">
            {t('share_watermark', { org: data.org_name })}
          </p>
        </main>
      </div>
    )
  }

  if (!data.dashboard || !data.roi) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-2 bg-canvas text-gray-400">
        <p className="text-lg font-medium text-gray-600">{t('share_invalid_title')}</p>
        <p className="text-sm">{t('share_invalid_hint')}</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-canvas">
      <div className="h-1.5 w-full" style={{ background: data.primary_color }} />
      <header className="w-full px-6 py-6 border-b border-gray-200 bg-surface">
        <div className="flex items-center gap-4 flex-wrap">
          {data.logo_url && (
            <img src={data.logo_url} alt="" className="h-10 max-w-[160px] object-contain" />
          )}
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-gray-900 truncate">
              {data.report_title || t('exec_title')}
            </h1>
            <p className="text-xs text-gray-400">
              {data.report_subtitle || data.org_name}
              {' · '}{data.dashboard.from_date} → {data.dashboard.until_date}
            </p>
          </div>
        </div>
      </header>

      <main className="w-full px-6 py-8 space-y-6">
        <DashboardView data={data.dashboard} t={t} />

        {/* ROI */}
        <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">{t('roi_title')}</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <RoiTile label={t('roi_impressions')} value={data.roi.impressions.toLocaleString('fr-FR')} />
            <RoiTile label={t('roi_network_value')} value={fmtEur(data.roi.network_value_eur)} />
            <RoiTile label={t('roi_paper_savings')} value={fmtEur(data.roi.paper_savings_eur)} />
            <RoiTile label={t('roi_total')} value={fmtEur(data.roi.total_roi_eur)} accent />
          </div>
        </div>

        <p className="text-center text-xs text-gray-400 pt-2">
          {t('share_watermark', { org: data.org_name })}
        </p>
      </main>
    </div>
  )
}

function RoiTile({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-xl font-semibold ${accent ? 'text-accent' : 'text-gray-900'}`}>{value}</p>
    </div>
  )
}
