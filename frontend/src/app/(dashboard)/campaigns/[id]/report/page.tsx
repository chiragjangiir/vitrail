'use client'

// Retail Media §2.8 S4 — page rapport annonceur d'une campagne (interne).
// PDF white-label + création de liens annonceur (page /share publique, protections §24.4).
import { use, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Copy, Share2, Trash2 } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import StatusBadge from '@/components/ui/StatusBadge'
import CampaignReportView, {
  PdfLevelButton, type CampaignReport, type PdfLevel,
} from '@/components/campaigns/CampaignReportView'
import api from '@/lib/api'

interface ShareLink {
  id_share: number
  token: string
  url: string
  label: string | null
  revoked: boolean
  access_count: number
  has_password: boolean
  expires_at: string | null
  created_at: string
}

const BADGE: Record<string, 'online' | 'info' | 'pending' | 'warning' | 'done' | 'offline'> = {
  live: 'online', scheduled: 'info', draft: 'pending',
  paused: 'warning', completed: 'done', cancelled: 'offline',
}

export default function CampaignReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const t = useTranslations('campaigns')
  const tc = useTranslations('common')
  const router = useRouter()
  const qc = useQueryClient()
  const [shareOpen, setShareOpen] = useState(false)
  const [sharePw, setSharePw] = useState('')
  const [shareDays, setShareDays] = useState('')
  const [copiedToken, setCopiedToken] = useState<string | null>(null)

  const { data: report, isLoading } = useQuery<CampaignReport>({
    queryKey: ['campaign-report', id],
    queryFn: () => api.get<CampaignReport>(`/campaigns/${id}/report`).then((r) => r.data),
  })
  const { data: shares = [] } = useQuery<ShareLink[]>({
    queryKey: ['campaign-shares', id],
    queryFn: () => api.get<ShareLink[]>(`/campaigns/${id}/shares`).then((r) => r.data),
    enabled: shareOpen,
  })

  // PDF avec granularité (Ed #3) : écran / site / groupe de sites
  const downloadPdf = useMutation({
    mutationFn: async (level: PdfLevel) => {
      const res = await api.get(`/campaigns/${id}/report.pdf`, {
        params: { level }, responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `rapport_campagne_${id}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    },
  })

  const createShare = useMutation({
    mutationFn: () => api.post<ShareLink>(`/campaigns/${id}/share`, {
      password: sharePw || null,
      expires_in_days: shareDays ? Number(shareDays) : null,
    }).then((r) => r.data),
    onSuccess: () => {
      setSharePw('')
      setShareDays('')
      qc.invalidateQueries({ queryKey: ['campaign-shares', id] })
    },
  })

  const revokeShare = useMutation({
    mutationFn: (idShare: number) => api.delete(`/analytics/shares/${idShare}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaign-shares', id] }),
  })

  const copyUrl = (s: ShareLink) => {
    const url = `${window.location.origin}${s.url}`
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(url).catch(() => {})
    } else {
      const ta = document.createElement('textarea')
      ta.value = url
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopiedToken(s.token)
    setTimeout(() => setCopiedToken(null), 2000)
  }

  return (
    <>
      <Topbar title={report ? `${t('report_title')} — ${report.campaign.campaign_name}` : t('report_title')}>
        <Button size="sm" variant="secondary" onClick={() => router.push('/campaigns')}>
          <ArrowLeft className="w-3.5 h-3.5 mr-1" />{tc('back')}
        </Button>
        <PdfLevelButton report={report} loading={downloadPdf.isPending} t={t}
                        onDownload={(level) => downloadPdf.mutate(level)} />
        <Button size="sm" onClick={() => setShareOpen(!shareOpen)}>
          <Share2 className="w-3.5 h-3.5 mr-1" />{t('report_share')}
        </Button>
      </Topbar>

      <main className="flex-1 overflow-y-auto">
        <div className="px-6 py-6 space-y-6">
          {isLoading || !report ? (
            <div className="flex justify-center py-16">
              <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3 flex-wrap text-sm text-gray-500">
                {report.campaign.advertiser_name && (
                  <span className="font-medium text-gray-800">{report.campaign.advertiser_name}</span>
                )}
                <StatusBadge status={BADGE[report.campaign.status] ?? 'pending'}
                             label={t(`st_${report.campaign.status}`)} />
                <span>
                  {t('report_period')} : {report.period.from} → {report.period.until}
                </span>
              </div>

              {shareOpen && (
                <div className="bg-surface rounded-lg border border-gray-200 p-5 space-y-4 shadow-sf-card">
                  <div>
                    <h2 className="text-sm font-semibold text-gray-900">{t('report_share_title')}</h2>
                    <p className="text-xs text-gray-400 mt-0.5">{t('report_share_hint')}</p>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-[1fr_140px_auto] gap-3 items-end">
                    <Input label={t('report_share_password')} type="password"
                           value={sharePw} onChange={(e) => setSharePw(e.target.value)}
                           placeholder="••••" />
                    <Input label={t('report_share_expiry')} type="number" min={1}
                           value={shareDays} onChange={(e) => setShareDays(e.target.value)} />
                    <Button size="sm" onClick={() => createShare.mutate()}
                            loading={createShare.isPending}>
                      {t('report_share_create')}
                    </Button>
                  </div>
                  {shares.filter((s) => !s.revoked).length > 0 && (
                    <ul className="space-y-2">
                      {shares.filter((s) => !s.revoked).map((s) => (
                        <li key={s.id_share}
                            className="flex items-center gap-3 rounded-lg border border-gray-200 px-3 py-2 text-sm">
                          <code className="flex-1 truncate text-xs text-gray-600">
                            {typeof window !== 'undefined' ? window.location.origin : ''}{s.url}
                          </code>
                          {s.has_password && <span className="text-xs text-gray-400">🔒</span>}
                          <span className="text-xs text-gray-400">
                            {t('report_share_visits', { n: s.access_count })}
                          </span>
                          <Button size="sm" variant="secondary" onClick={() => copyUrl(s)}>
                            <Copy className="w-3.5 h-3.5 mr-1" />
                            {copiedToken === s.token ? t('report_share_copied') : t('report_share_copy')}
                          </Button>
                          <button type="button"
                                  onClick={() => revokeShare.mutate(s.id_share)}
                                  className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf"
                                  title={t('report_share_revoke')}>
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <CampaignReportView report={report} t={t} />
            </>
          )}
        </div>
      </main>
    </>
  )
}
