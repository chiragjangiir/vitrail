'use client'

// S7 B2 — rapport d'une campagne dans le portail annonceur : réutilise
// CampaignReportView (mêmes chiffres que le retailer, scope B1 = 404 si la
// campagne n'appartient pas à l'annonceur du compte) + export PDF white-label.

import { use } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import Button from '@/components/ui/Button'
import CampaignReportView, {
  PdfLevelButton, type CampaignReport, type PdfLevel,
} from '@/components/campaigns/CampaignReportView'
import api from '@/lib/api'

export default function PortalCampaignReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const t = useTranslations('campaigns')
  const tp = useTranslations('portal')
  const router = useRouter()

  const { data: report, isLoading, isError } = useQuery<CampaignReport>({
    queryKey: ['portal-campaign-report', id],
    queryFn: () => api.get<CampaignReport>(`/campaigns/${id}/report`).then((r) => r.data),
    retry: false,
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
      a.download = `campaign_report_${id}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    },
  })

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <Button size="sm" variant="secondary" onClick={() => router.push('/portal')}>
            <ArrowLeft className="w-3.5 h-3.5 mr-1" />{tp('back_to_campaigns')}
          </Button>
          <h1 className="text-lg font-semibold text-gray-900 truncate">
            {report?.campaign.campaign_name ?? ''}
          </h1>
        </div>
        <PdfLevelButton report={report} loading={downloadPdf.isPending} t={t}
                        onDownload={(level) => downloadPdf.mutate(level)} />
      </div>

      {isLoading && <p className="text-sm text-gray-400">…</p>}
      {isError && <p className="text-sm text-danger">{tp('report_not_found')}</p>}
      {report && <CampaignReportView report={report} t={t} />}
    </div>
  )
}
