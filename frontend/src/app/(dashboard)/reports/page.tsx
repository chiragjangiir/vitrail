'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation } from '@tanstack/react-query'
import { FileText, Download, Music } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import type { RightsReportResponse } from '@/types/api'

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}
function firstOfMonthISO(): string {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10)
}
function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`
}

const RIGHTS_ORGS = ['SACEM', 'SOCAN', 'ASCAP', 'BMI', 'PRS', 'GEMA', 'SIAE']

export default function ReportsPage() {
  const t = useTranslations('reports')
  const [from, setFrom] = useState(firstOfMonthISO())
  const [until, setUntil] = useState(todayISO())
  const [rightsOrg, setRightsOrg] = useState('')
  const [downloading, setDownloading] = useState(false)

  const report = useMutation({
    mutationFn: () =>
      api
        .get<RightsReportResponse>('/reports/rights', {
          params: { from, until, ...(rightsOrg && { rights_org: rightsOrg }) },
        })
        .then((r) => r.data),
  })

  const downloadCsv = async () => {
    setDownloading(true)
    try {
      const res = await api.get('/reports/rights', {
        params: { from, until, format: 'csv', ...(rightsOrg && { rights_org: rightsOrg }) },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `rights_${from}_${until}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setDownloading(false)
    }
  }

  const data = report.data
  const inputCls =
    'border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface'

  return (
    <>
      <Topbar title={t('title')} />
      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-8 space-y-6">
          <div className="bg-surface rounded-lg border border-gray-200 p-5 space-y-4 shadow-sf-card">
            <div className="flex items-center gap-2">
              <Music className="w-4 h-4 text-accent" />
              <h2 className="text-sm font-semibold text-gray-900">{t('rights_title')}</h2>
            </div>
            <p className="text-xs text-gray-400">{t('rights_hint')}</p>

            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('from')}</label>
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inputCls} />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('until')}</label>
                <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className={inputCls} />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('rights_org')}</label>
                <select value={rightsOrg} onChange={(e) => setRightsOrg(e.target.value)} className={inputCls}>
                  <option value="">{t('all_orgs')}</option>
                  {RIGHTS_ORGS.map((o) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </select>
              </div>
              <Button size="sm" onClick={() => report.mutate()} loading={report.isPending}>
                {t('generate')}
              </Button>
              {data && data.rows.length > 0 && (
                <Button size="sm" variant="secondary" onClick={downloadCsv} loading={downloading}>
                  <Download className="w-3.5 h-3.5 mr-1.5" />
                  {t('export_csv')}
                </Button>
              )}
            </div>
          </div>

          {data && (
            <div className="bg-surface rounded-lg border border-gray-200 overflow-hidden shadow-sf-card">
              <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50 text-xs text-gray-500">
                <span>{t('summary', { plays: data.total_plays, sec: fmtDuration(data.total_sec), works: data.rows.length })}</span>
              </div>
              {data.rows.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400">
                  <FileText className="w-10 h-10" />
                  <p className="text-sm">{t('no_data')}</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr>
                        {['col_isrc', 'col_title', 'col_composer', 'col_org', 'col_plays', 'col_duration', 'col_players', 'col_sites'].map((k) => (
                          <th key={k} className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
                            {t(k)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {data.rows.map((r) => (
                        <tr key={r.id_media} className="hover:bg-gray-50">
                          <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{r.isrc ?? '—'}</td>
                          <td className="px-4 py-2.5 font-medium text-gray-800">{r.title}</td>
                          <td className="px-4 py-2.5 text-gray-600">{r.composer ?? '—'}</td>
                          <td className="px-4 py-2.5 text-gray-600">{r.rights_org ?? '—'}</td>
                          <td className="px-4 py-2.5 text-gray-800">{r.plays}</td>
                          <td className="px-4 py-2.5 text-gray-600">{fmtDuration(r.total_sec)}</td>
                          <td className="px-4 py-2.5 text-gray-600">{r.players}</td>
                          <td className="px-4 py-2.5 text-gray-600">{r.sites}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </>
  )
}
