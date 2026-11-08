'use client'

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  FileText, Share2, Settings2, Coins, Copy, Trash2, Upload, X, CalendarClock, Send, Lock,
  Database,
} from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import BackButton from '@/components/ui/BackButton'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import NumberField from '@/components/ui/NumberField'
import api from '@/lib/api'
import type { PlayerGroupRead, Site, SiteGroupRead } from '@/types/api'
import {
  DashboardView, fmtEur, type ExecutiveDashboard,
} from '@/components/analytics/DashboardView'

const PERIODS = [7, 30, 90] as const

interface Branding {
  primary_color: string
  report_title: string | null
  report_subtitle: string | null
  roi_hours_per_day: number
  roi_contacts_hour: number
  roi_cpm_eur: number
  roi_paper_eur: number
  logo_url: string | null
  has_logo: boolean
}
interface ShareLink {
  id_share: number; token: string; url: string; label: string | null
  period_days: number; expires_at: string | null; revoked: boolean
  access_count: number; last_accessed_at: string | null; created_at: string
  has_password: boolean; ip_allowlist: string[] | null
}

function computeRoi(b: Branding, screens: number, uptimePct: number | null, days: number) {
  const up = (uptimePct ?? 100) / 100
  const impressions = Math.round(screens * b.roi_hours_per_day * days * up * b.roi_contacts_hour)
  const network = Math.round((impressions / 1000) * b.roi_cpm_eur)
  const paper = Math.round(screens * b.roi_paper_eur * (days / 30))
  return { impressions, network, paper, total: network + paper }
}

export default function ExecutiveDashboardPage() {
  const t = useTranslations('reports')
  const qc = useQueryClient()
  const [days, setDays] = useState<number>(30)
  const [siteId, setSiteId] = useState<number | null>(null)
  const [groupId, setGroupId] = useState<number | null>(null)
  const [siteGroupId, setSiteGroupId] = useState<number | null>(null)
  const [showShare, setShowShare] = useState(false)
  const [showBranding, setShowBranding] = useState(false)
  const [showSchedule, setShowSchedule] = useState(false)
  const [showBi, setShowBi] = useState(false)
  const [pdfLoading, setPdfLoading] = useState(false)

  const period = useMemo(() => {
    const until = new Date()
    const from = new Date()
    from.setDate(from.getDate() - (days - 1))
    return { from: from.toISOString().slice(0, 10), until: until.toISOString().slice(0, 10) }
  }, [days])
  // Filtres de périmètre (§24.1) — les endpoints les supportaient déjà, l'UI ne les exposait pas.
  const scope = useMemo(() => ({
    ...(siteId ? { id_site: siteId } : {}),
    ...(groupId ? { id_group: groupId } : {}),
    ...(siteGroupId ? { id_site_group: siteGroupId } : {}),
  }), [siteId, groupId, siteGroupId])

  const { data: siteList = [] } = useQuery<Site[]>({
    queryKey: ['sites'],
    queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
  })
  const { data: siteGroupList = [] } = useQuery<SiteGroupRead[]>({
    queryKey: ['site-groups'],
    queryFn: () => api.get<SiteGroupRead[]>('/site-groups/').then((r) => r.data),
  })
  const { data: groupList = [] } = useQuery<PlayerGroupRead[]>({
    queryKey: ['player-groups'],
    queryFn: () => api.get<PlayerGroupRead[]>('/player-groups/').then((r) => r.data),
  })

  const { data } = useQuery({
    queryKey: ['analytics-executive', days, siteId, groupId],
    queryFn: async () =>
      (await api.get<ExecutiveDashboard>('/analytics/executive',
        { params: { ...period, ...scope } })).data,
    refetchInterval: 60000,
  })
  const { data: branding } = useQuery({
    queryKey: ['analytics-branding'],
    queryFn: async () => (await api.get<Branding>('/analytics/branding')).data,
  })

  const roi = useMemo(() => {
    if (!data || !branding) return null
    return computeRoi(branding, data.fleet.total, data.uptime_pct, days)
  }, [data, branding, days])

  async function exportPdf() {
    setPdfLoading(true)
    try {
      const res = await api.get('/analytics/executive/report.pdf', {
        params: { ...period, ...scope }, responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `rapport_executif_${period.from}_${period.until}.pdf`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <>
      <Topbar title={t('exec_title')}>
        <BackButton />
        <div className="flex items-center gap-2">
          {/* Personnalisation/planification/partage/BI = require_org_admin (analytics.py).
              Un lecteur garde l'export PDF (lecture) mais pas ces actions sensibles. */}
          <Can admin>
            <Button size="sm" onClick={() => setShowBranding(true)}>
              <Settings2 className="w-4 h-4" /> {t('customize')}
            </Button>
          </Can>
          <Button size="sm" onClick={exportPdf} disabled={pdfLoading}>
            <FileText className="w-4 h-4" /> {pdfLoading ? t('generating') : t('export_pdf')}
          </Button>
          <Can admin>
            <Button size="sm" onClick={() => setShowSchedule(true)}>
              <CalendarClock className="w-4 h-4" /> {t('schedule')}
            </Button>
            <Button size="sm" onClick={() => setShowShare(true)}>
              <Share2 className="w-4 h-4" /> {t('share')}
            </Button>
            <Button size="sm" onClick={() => setShowBi(true)}>
              <Database className="w-4 h-4" /> {t('bi_title')}
            </Button>
          </Can>
        </div>
      </Topbar>
      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-8 space-y-6">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <p className="text-sm text-gray-400 max-w-2xl">{t('exec_hint')}</p>
            <div className="flex items-center gap-2 flex-wrap">
              {/* Filtres de périmètre : site / groupe (exclusifs, comme Proof of Play) */}
              <select
                value={siteId ?? ''}
                onChange={(e) => {
                  setSiteId(e.target.value ? Number(e.target.value) : null)
                  if (e.target.value) { setGroupId(null); setSiteGroupId(null) }
                }}
                className="border border-gray-200 rounded-md px-2.5 py-1.5 text-sm text-gray-700 bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
              >
                <option value="">{t('exec_all_sites')}</option>
                {siteList.map((s) => (
                  <option key={s.id_site} value={s.id_site}>{s.site_name}</option>
                ))}
              </select>
              <select
                value={groupId ?? ''}
                onChange={(e) => {
                  setGroupId(e.target.value ? Number(e.target.value) : null)
                  if (e.target.value) { setSiteId(null); setSiteGroupId(null) }
                }}
                className="border border-gray-200 rounded-md px-2.5 py-1.5 text-sm text-gray-700 bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
              >
                <option value="">{t('exec_all_groups')}</option>
                {groupList.map((g) => (
                  <option key={g.id_group} value={g.id_group}>{g.group_name}</option>
                ))}
              </select>
              <select
                value={siteGroupId ?? ''}
                onChange={(e) => {
                  setSiteGroupId(e.target.value ? Number(e.target.value) : null)
                  if (e.target.value) { setSiteId(null); setGroupId(null) }
                }}
                className="border border-gray-200 rounded-md px-2.5 py-1.5 text-sm text-gray-700 bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
              >
                <option value="">{t('exec_all_site_groups')}</option>
                {siteGroupList.map((g) => (
                  <option key={g.id_site_group} value={g.id_site_group}>{g.group_name}</option>
                ))}
              </select>
              <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
                {PERIODS.map((p) => (
                  <button key={p} onClick={() => setDays(p)}
                    className={`px-3 py-1.5 rounded-md text-sm font-medium transition-sf ${
                      days === p ? 'bg-surface text-accent shadow-sm' : 'text-gray-500 hover:text-gray-700'
                    }`}>
                    {t('period_days', { n: p })}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {data && <DashboardView data={data} t={t} />}

          {/* ROI estimator */}
          {roi && (
            <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Coins className="w-4 h-4 text-accent" />
                  <h2 className="text-sm font-semibold text-gray-900">{t('roi_title')}</h2>
                </div>
                <Can admin>
                  <button onClick={() => setShowBranding(true)}
                    className="text-xs text-accent hover:underline">{t('roi_edit')}</button>
                </Can>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <RoiTile label={t('roi_impressions')} value={roi.impressions.toLocaleString('fr-FR')} />
                <RoiTile label={t('roi_network_value')} value={fmtEur(roi.network)} />
                <RoiTile label={t('roi_paper_savings')} value={fmtEur(roi.paper)} />
                <RoiTile label={t('roi_total')} value={fmtEur(roi.total)} accent />
              </div>
              <p className="text-xs text-gray-400 mt-3">
                {t('roi_assumptions', {
                  screens: data?.fleet.total ?? 0, hours: branding?.roi_hours_per_day ?? 0,
                  contacts: branding?.roi_contacts_hour ?? 0, cpm: branding?.roi_cpm_eur ?? 0,
                  paper: branding?.roi_paper_eur ?? 0,
                })}
              </p>
            </div>
          )}
        </div>
      </main>

      {showSchedule && <ScheduleModal t={t} onClose={() => setShowSchedule(false)} />}
      {showShare && <ShareModal t={t} onClose={() => setShowShare(false)} />}
      {showBi && <BiModal t={t} onClose={() => setShowBi(false)} />}
      {showBranding && branding && (
        <BrandingModal t={t} branding={branding} onClose={() => setShowBranding(false)}
          onSaved={() => qc.invalidateQueries({ queryKey: ['analytics-branding'] })} />
      )}
    </>
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

// ── Modale de planification (PDF par email) ──────────────────────────────────
interface ReportSchedule {
  id_schedule: number; label: string | null; frequency: string
  send_hour: number; send_dow: number; send_dom: number; period_days: number
  language: string; recipients: string[]; include_roi: boolean; enabled: boolean
  last_run_at: string | null; next_run_at: string | null; created_at: string
}
interface ReportHistory {
  id_history: number; period_from: string | null; period_until: string | null
  recipients: string[]; status: string; detail: string | null; created_at: string
}
const DOW = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']

function ScheduleModal({ t, onClose }: { t: (k: string, v?: Record<string, string | number>) => string; onClose: () => void }) {
  const qc = useQueryClient()
  const [freq, setFreq] = useState<'weekly' | 'monthly'>('monthly')
  const [dow, setDow] = useState(0)
  const [dom, setDom] = useState(1)
  const [hour, setHour] = useState(7)
  const [label, setLabel] = useState('')
  const [recipients, setRecipients] = useState('')
  const [periodDays, setPeriodDays] = useState(30)
  const [includeRoi, setIncludeRoi] = useState(true)

  const { data: smtp } = useQuery({
    queryKey: ['smtp-status'],
    queryFn: async () => (await api.get<{ configured: boolean }>('/analytics/smtp-status')).data,
  })
  const { data: schedules } = useQuery({
    queryKey: ['report-schedules'],
    queryFn: async () => (await api.get<ReportSchedule[]>('/analytics/report-schedules')).data,
  })
  const { data: history } = useQuery({
    queryKey: ['report-history'],
    queryFn: async () => (await api.get<ReportHistory[]>('/analytics/report-history')).data,
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['report-schedules'] })
    qc.invalidateQueries({ queryKey: ['report-history'] })
  }
  const create = useMutation({
    mutationFn: () => api.post('/analytics/report-schedules', {
      label: label || null, frequency: freq, send_hour: hour, send_dow: dow, send_dom: dom,
      period_days: periodDays, include_roi: includeRoi,
      recipients: recipients.split(/[,;\n]/).map((s) => s.trim()).filter(Boolean),
    }),
    onSuccess: () => { setLabel(''); setRecipients(''); refresh() },
  })
  const del = useMutation({
    mutationFn: (id: number) => api.delete(`/analytics/report-schedules/${id}`),
    onSuccess: refresh,
  })
  const toggle = useMutation({
    mutationFn: (s: ReportSchedule) =>
      api.put(`/analytics/report-schedules/${s.id_schedule}`, { enabled: !s.enabled }),
    onSuccess: refresh,
  })
  const sendNow = useMutation({
    mutationFn: (id: number) => api.post(`/analytics/report-schedules/${id}/send-now`),
    onSuccess: refresh, onError: refresh,
  })

  const cadence = (s: ReportSchedule) => s.frequency === 'weekly'
    ? t('sched_weekly_at', { day: DOW[s.send_dow], hour: s.send_hour })
    : t('sched_monthly_at', { dom: s.send_dom, hour: s.send_hour })

  return (
    <Overlay onClose={onClose} title={t('sched_title')}>
      <p className="text-xs text-gray-400">{t('sched_hint')}</p>
      {smtp && !smtp.configured && (
        <p className="text-xs text-warning bg-warning/10 rounded px-2.5 py-1.5">{t('sched_no_smtp')}</p>
      )}

      {/* Création */}
      <div className="border border-gray-200 rounded-lg p-3 space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="col-span-2 text-xs text-gray-500">{t('sched_label')}
            <input value={label} onChange={(e) => setLabel(e.target.value)} className={inputCls}
              placeholder={t('sched_label_ph')} />
          </label>
          <label className="text-xs text-gray-500">{t('sched_frequency')}
            <select value={freq} onChange={(e) => setFreq(e.target.value as 'weekly' | 'monthly')} className={inputCls}>
              <option value="monthly">{t('sched_monthly')}</option>
              <option value="weekly">{t('sched_weekly')}</option>
            </select>
          </label>
          {freq === 'weekly' ? (
            <label className="text-xs text-gray-500">{t('sched_day')}
              <select value={dow} onChange={(e) => setDow(Number(e.target.value))} className={inputCls}>
                {DOW.map((d, i) => <option key={i} value={i}>{d}</option>)}
              </select>
            </label>
          ) : (
            <label className="text-xs text-gray-500">{t('sched_dom')}
              <NumberField min={1} max={28} value={dom}
                onCommit={(v) => setDom(v ?? 1)} className={inputCls} />
            </label>
          )}
          <label className="text-xs text-gray-500">{t('sched_hour')}
            <NumberField min={0} max={23} value={hour}
              onCommit={(v) => setHour(v ?? 0)} className={inputCls} />
          </label>
          <label className="text-xs text-gray-500">{t('sched_period')}
            <select value={periodDays} onChange={(e) => setPeriodDays(Number(e.target.value))} className={inputCls}>
              <option value={7}>7 j</option><option value={30}>30 j</option><option value={90}>90 j</option>
            </select>
          </label>
        </div>
        <label className="block text-xs text-gray-500">{t('sched_recipients')}
          <textarea value={recipients} onChange={(e) => setRecipients(e.target.value)} rows={2}
            className={inputCls} placeholder="dir@exemple.com, daf@exemple.com" />
        </label>
        <label className="flex items-center gap-2 text-xs text-gray-600">
          <input type="checkbox" checked={includeRoi} onChange={(e) => setIncludeRoi(e.target.checked)} />
          {t('sched_include_roi')}
        </label>
        <Button size="sm" className="w-full" disabled={create.isPending} onClick={() => create.mutate()}>
          {t('sched_create')}
        </Button>
      </div>

      {/* Liste */}
      <div className="space-y-2 max-h-[32vh] overflow-y-auto">
        {(schedules ?? []).length === 0 && (
          <p className="text-sm text-gray-400 py-3 text-center">{t('sched_none')}</p>
        )}
        {(schedules ?? []).map((s) => (
          <div key={s.id_schedule} className="flex items-center gap-2 border border-gray-200 rounded-lg p-2.5">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">
                {s.label || t('sched_untitled')} {!s.enabled && <span className="text-[10px] text-gray-400">({t('sched_paused')})</span>}
              </p>
              <p className="text-[11px] text-gray-400">
                {cadence(s)} · {s.recipients.length} dest. · {t('sched_next', {
                  d: s.next_run_at ? new Date(s.next_run_at).toLocaleString() : '—' })}
              </p>
            </div>
            <button title={t('sched_send_now')} onClick={() => sendNow.mutate(s.id_schedule)}
              disabled={sendNow.isPending}
              className="p-1.5 text-gray-400 hover:text-accent transition-sf"><Send className="w-4 h-4" /></button>
            <button onClick={() => toggle.mutate(s)}
              className="text-[10px] px-1.5 py-0.5 rounded border border-gray-200 text-gray-500 hover:border-accent">
              {s.enabled ? t('sched_pause') : t('sched_resume')}
            </button>
            <button title={t('sched_delete')} onClick={() => del.mutate(s.id_schedule)}
              className="p-1.5 text-gray-300 hover:text-danger transition-sf"><Trash2 className="w-4 h-4" /></button>
          </div>
        ))}
      </div>

      {/* Historique */}
      {(history ?? []).length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">{t('sched_history')}</p>
          <div className="space-y-1 max-h-[16vh] overflow-y-auto">
            {history!.slice(0, 12).map((h) => (
              <div key={h.id_history} className="flex items-center gap-2 text-[11px]">
                <span className={h.status === 'sent' ? 'text-success' : 'text-danger'}>
                  {h.status === 'sent' ? '✓' : '✗'}
                </span>
                <span className="text-gray-500">{new Date(h.created_at).toLocaleString()}</span>
                <span className="text-gray-400 truncate">
                  {h.period_from}→{h.period_until} · {h.recipients.length} dest.
                  {h.detail ? ` · ${h.detail}` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Overlay>
  )
}

// ── Modale de partage ────────────────────────────────────────────────────────
function ShareModal({ t, onClose }: { t: (k: string, v?: Record<string, string | number>) => string; onClose: () => void }) {
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [periodDays, setPeriodDays] = useState(30)
  const [expiresIn, setExpiresIn] = useState<string>('')
  const [password, setPassword] = useState('')
  const [ipAllowlist, setIpAllowlist] = useState('')
  const [copied, setCopied] = useState<number | null>(null)

  const { data: shares } = useQuery({
    queryKey: ['analytics-shares'],
    queryFn: async () => (await api.get<ShareLink[]>('/analytics/shares')).data,
  })
  const create = useMutation({
    mutationFn: () => api.post('/analytics/shares', {
      label: label || null, period_days: periodDays,
      expires_in_days: expiresIn ? Number(expiresIn) : null,
      password: password || null,
      ip_allowlist: ipAllowlist
        ? ipAllowlist.split(/[,;\n]/).map((s) => s.trim()).filter(Boolean)
        : null,
    }),
    onSuccess: () => {
      setLabel(''); setPassword(''); setIpAllowlist('')
      qc.invalidateQueries({ queryKey: ['analytics-shares'] })
    },
  })
  const revoke = useMutation({
    mutationFn: (id: number) => api.delete(`/analytics/shares/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['analytics-shares'] }),
  })

  const fullUrl = (u: string) =>
    typeof window !== 'undefined' ? `${window.location.origin}${u}` : u

  return (
    <Overlay onClose={onClose} title={t('share_title')}>
      <p className="text-xs text-gray-400">{t('share_hint')}</p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex-1 min-w-[160px] text-xs text-gray-500">
          {t('share_label')}
          <input value={label} onChange={(e) => setLabel(e.target.value)}
            className={inputCls} placeholder={t('share_label_ph')} />
        </label>
        <label className="text-xs text-gray-500">{t('share_period')}
          <select value={periodDays} onChange={(e) => setPeriodDays(Number(e.target.value))} className={inputCls}>
            <option value={7}>7 j</option><option value={30}>30 j</option><option value={90}>90 j</option>
          </select>
        </label>
        <label className="text-xs text-gray-500">{t('share_expires')}
          <select value={expiresIn} onChange={(e) => setExpiresIn(e.target.value)} className={inputCls}>
            <option value="">{t('share_permanent')}</option>
            <option value="1">24 h</option><option value="7">7 j</option><option value="30">30 j</option>
          </select>
        </label>
        <Button size="sm" onClick={() => create.mutate()} disabled={create.isPending}>
          {t('share_create')}
        </Button>
      </div>
      {/* Options avancées (§24.4) : mot de passe + IP allowlist — vides = lien ouvert */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex-1 min-w-[160px] text-xs text-gray-500">
          {t('share_pw_label')}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            className={inputCls} placeholder={t('share_pw_optional')} autoComplete="new-password" />
        </label>
        <label className="flex-1 min-w-[200px] text-xs text-gray-500">
          {t('share_ip_label')}
          <input value={ipAllowlist} onChange={(e) => setIpAllowlist(e.target.value)}
            className={inputCls} placeholder="81.2.3.4, 192.168.1.0/24" />
        </label>
      </div>
      {create.isError && (
        <p className="text-xs text-danger">{t('share_create_error')}</p>
      )}

      <div className="space-y-2 max-h-[45vh] overflow-y-auto">
        {(shares ?? []).filter((s) => !s.revoked).length === 0 && (
          <p className="text-sm text-gray-400 py-4 text-center">{t('share_none')}</p>
        )}
        {(shares ?? []).filter((s) => !s.revoked).map((s) => (
          <div key={s.id_share} className="flex items-center gap-2 border border-gray-200 rounded-lg p-2.5">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate flex items-center gap-1.5">
                {s.label || t('share_untitled')}
                {s.has_password && (
                  <span title={t('share_protected')}><Lock className="w-3 h-3 text-accent" /></span>
                )}
              </p>
              <p className="text-xs text-gray-400 truncate font-mono">{fullUrl(s.url)}</p>
              <p className="text-[11px] text-gray-400">
                {t('share_meta', {
                  days: s.period_days, count: s.access_count,
                  exp: s.expires_at ? new Date(s.expires_at).toLocaleDateString() : t('share_permanent'),
                })}
                {s.ip_allowlist?.length
                  ? ` · ${t('share_ip_count', { n: s.ip_allowlist.length })}` : ''}
              </p>
            </div>
            <button title={t('share_copy')} onClick={() => {
              navigator.clipboard.writeText(fullUrl(s.url)); setCopied(s.id_share)
              setTimeout(() => setCopied(null), 1500)
            }} className="p-1.5 text-gray-400 hover:text-accent transition-sf">
              {copied === s.id_share ? <span className="text-[10px] text-success">{t('share_copied')}</span> : <Copy className="w-4 h-4" />}
            </button>
            <button title={t('share_revoke')} onClick={() => revoke.mutate(s.id_share)}
              className="p-1.5 text-gray-300 hover:text-danger transition-sf">
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
    </Overlay>
  )
}

// ── Modale connecteurs BI (§24.7) ────────────────────────────────────────────
interface BiKey {
  id_key: number; key_prefix: string; label: string | null
  last_used_at: string | null; expires_at: string | null; created_at: string
  key: string | null
}
const BI_FEEDS = ['pop', 'network-metrics', 'content'] as const

function BiModal({ t, onClose }: { t: (k: string, v?: Record<string, string | number>) => string; onClose: () => void }) {
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [expiresIn, setExpiresIn] = useState<string>('')
  const [newKey, setNewKey] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  const { data: keys } = useQuery({
    queryKey: ['bi-keys'],
    queryFn: async () => (await api.get<BiKey[]>('/analytics/bi-keys')).data,
  })
  const create = useMutation({
    mutationFn: () => api.post<BiKey>('/analytics/bi-keys', {
      label: label || null,
      expires_in_days: expiresIn ? Number(expiresIn) : null,
    }),
    onSuccess: (res) => {
      setLabel(''); setNewKey(res.data.key)
      qc.invalidateQueries({ queryKey: ['bi-keys'] })
    },
  })
  const revoke = useMutation({
    mutationFn: (id: number) => api.delete(`/analytics/bi-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bi-keys'] }),
  })

  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const feedUrl = (feed: string) =>
    `${origin}/api/v1/analytics/export/${feed}.csv?api_key=${newKey ?? t('bi_key_placeholder')}`
  const copy = (id: string, text: string) => {
    navigator.clipboard.writeText(text); setCopied(id)
    setTimeout(() => setCopied(null), 1500)
  }

  return (
    <Overlay onClose={onClose} title={t('bi_title')}>
      <p className="text-xs text-gray-400">{t('bi_hint')}</p>

      {/* Création de clé */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex-1 min-w-[160px] text-xs text-gray-500">
          {t('bi_key_label')}
          <input value={label} onChange={(e) => setLabel(e.target.value)}
            className={inputCls} placeholder={t('bi_key_label_ph')} />
        </label>
        <label className="text-xs text-gray-500">{t('share_expires')}
          <select value={expiresIn} onChange={(e) => setExpiresIn(e.target.value)} className={inputCls}>
            <option value="">{t('share_permanent')}</option>
            <option value="90">90 j</option><option value="365">1 an</option>
          </select>
        </label>
        <Button size="sm" onClick={() => create.mutate()} disabled={create.isPending}>
          {t('bi_key_create')}
        </Button>
      </div>

      {/* Clé fraîchement créée — seule occasion de la copier */}
      {newKey && (
        <div className="bg-warning/10 border border-warning/30 rounded-lg p-3 space-y-1.5">
          <p className="text-xs font-medium text-gray-700">{t('bi_key_once')}</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs font-mono bg-surface border border-gray-200 rounded px-2 py-1.5 truncate">{newKey}</code>
            <button onClick={() => copy('new-key', newKey)}
              className="p-1.5 text-gray-400 hover:text-accent transition-sf">
              {copied === 'new-key' ? <span className="text-[10px] text-success">{t('share_copied')}</span> : <Copy className="w-4 h-4" />}
            </button>
          </div>
        </div>
      )}

      {/* Clés existantes */}
      <div className="space-y-2 max-h-[22vh] overflow-y-auto">
        {(keys ?? []).length === 0 && (
          <p className="text-sm text-gray-400 py-3 text-center">{t('bi_keys_none')}</p>
        )}
        {(keys ?? []).map((k) => (
          <div key={k.id_key} className="flex items-center gap-2 border border-gray-200 rounded-lg p-2.5">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">
                {k.label || t('share_untitled')}
                <span className="ml-2 text-xs font-mono text-gray-400">{k.key_prefix}…</span>
              </p>
              <p className="text-[11px] text-gray-400">
                {t('bi_key_meta', {
                  used: k.last_used_at ? new Date(k.last_used_at).toLocaleString() : t('bi_key_never'),
                  exp: k.expires_at ? new Date(k.expires_at).toLocaleDateString() : t('share_permanent'),
                })}
              </p>
            </div>
            <button title={t('share_revoke')} onClick={() => revoke.mutate(k.id_key)}
              className="p-1.5 text-gray-300 hover:text-danger transition-sf">
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      {/* Flux CSV */}
      <div>
        <p className="text-xs font-medium text-gray-600 mb-1.5">{t('bi_feeds')}</p>
        <div className="space-y-1.5">
          {BI_FEEDS.map((feed) => (
            <div key={feed} className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-32 shrink-0">{t(`bi_feed_${feed.replace('-', '_')}`)}</span>
              <code className="flex-1 text-[11px] font-mono bg-gray-50 border border-gray-200 rounded px-2 py-1 truncate">
                {feedUrl(feed)}
              </code>
              <button onClick={() => copy(feed, feedUrl(feed))}
                className="p-1.5 text-gray-400 hover:text-accent transition-sf">
                {copied === feed ? <span className="text-[10px] text-success">{t('share_copied')}</span> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-gray-400 mt-2">{t('bi_howto')}</p>
      </div>
    </Overlay>
  )
}

// ── Modale de personnalisation (white-label + ROI) ───────────────────────────
function BrandingModal({
  t, branding, onClose, onSaved,
}: {
  t: (k: string, v?: Record<string, string | number>) => string
  branding: Branding; onClose: () => void; onSaved: () => void
}) {
  const [form, setForm] = useState({
    report_title: branding.report_title ?? '',
    report_subtitle: branding.report_subtitle ?? '',
    primary_color: branding.primary_color,
    roi_hours_per_day: branding.roi_hours_per_day,
    roi_contacts_hour: branding.roi_contacts_hour,
    roi_cpm_eur: branding.roi_cpm_eur,
    roi_paper_eur: branding.roi_paper_eur,
  })
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: () => api.put('/analytics/branding', {
      report_title: form.report_title || null,
      report_subtitle: form.report_subtitle || null,
      primary_color: form.primary_color,
      roi_hours_per_day: Number(form.roi_hours_per_day),
      roi_contacts_hour: Number(form.roi_contacts_hour),
      roi_cpm_eur: Number(form.roi_cpm_eur),
      roi_paper_eur: Number(form.roi_paper_eur),
    }),
    onSuccess: () => { onSaved(); onClose() },
  })
  const uploadLogo = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData(); fd.append('file', file)
      return api.post('/analytics/branding/logo', fd,
        { headers: { 'Content-Type': 'multipart/form-data' } })
    },
    onSuccess: () => { onSaved(); qc.invalidateQueries({ queryKey: ['analytics-branding'] }) },
  })
  const removeLogo = useMutation({
    mutationFn: () => api.delete('/analytics/branding/logo'),
    onSuccess: () => { onSaved(); qc.invalidateQueries({ queryKey: ['analytics-branding'] }) },
  })
  const set = (k: keyof typeof form, v: string | number) => setForm((f) => ({ ...f, [k]: v }))

  return (
    <Overlay onClose={onClose} title={t('brand_title')}>
      <p className="text-xs text-gray-400">{t('brand_hint')}</p>

      {/* Logo */}
      <div className="flex items-center gap-3">
        <div className="w-24 h-12 border border-gray-200 rounded bg-gray-50 flex items-center justify-center overflow-hidden">
          {branding.logo_url
            ? <img src={branding.logo_url} alt="logo" className="max-w-full max-h-full object-contain" />
            : <span className="text-[10px] text-gray-400">{t('brand_no_logo')}</span>}
        </div>
        <label className="text-xs">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1.5 border border-gray-200 rounded cursor-pointer hover:border-accent transition-sf">
            <Upload className="w-3.5 h-3.5" /> {t('brand_upload_logo')}
          </span>
          <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadLogo.mutate(f) }} />
        </label>
        {branding.has_logo && (
          <button onClick={() => removeLogo.mutate()} className="text-xs text-gray-400 hover:text-danger">
            {t('brand_remove_logo')}
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="col-span-2 text-xs text-gray-500">{t('brand_report_title')}
          <input value={form.report_title} onChange={(e) => set('report_title', e.target.value)}
            className={inputCls} maxLength={120} />
        </label>
        <label className="col-span-2 text-xs text-gray-500">{t('brand_report_subtitle')}
          <input value={form.report_subtitle} onChange={(e) => set('report_subtitle', e.target.value)}
            className={inputCls} maxLength={200} />
        </label>
        <label className="text-xs text-gray-500">{t('brand_color')}
          <div className="flex items-center gap-2">
            <input type="color" value={form.primary_color}
              onChange={(e) => set('primary_color', e.target.value)}
              className="w-10 h-9 rounded border border-gray-200 bg-surface cursor-pointer" />
            <input value={form.primary_color} onChange={(e) => set('primary_color', e.target.value)}
              className={inputCls + ' font-mono'} />
          </div>
        </label>
      </div>

      <p className="text-xs font-medium text-gray-600 pt-1">{t('roi_params')}</p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <NumField label={t('roi_hours')} value={form.roi_hours_per_day}
          onChange={(v) => set('roi_hours_per_day', v)} step="0.5" />
        <NumField label={t('roi_contacts')} value={form.roi_contacts_hour}
          onChange={(v) => set('roi_contacts_hour', v)} />
        <NumField label={t('roi_cpm')} value={form.roi_cpm_eur}
          onChange={(v) => set('roi_cpm_eur', v)} step="0.5" />
        <NumField label={t('roi_paper')} value={form.roi_paper_eur}
          onChange={(v) => set('roi_paper_eur', v)} step="1" />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <Button size="sm" variant="secondary" onClick={onClose}>{t('brand_cancel')}</Button>
        <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>{t('brand_save')}</Button>
      </div>
    </Overlay>
  )
}

const inputCls = 'w-full mt-1 border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface'

function NumField({ label, value, onChange, step }: {
  label: string; value: number; onChange: (v: number) => void; step?: string
}) {
  return (
    <label className="text-xs text-gray-500">{label}
      <NumberField min={0} step={typeof step === 'number' ? step : 1} value={value}
        onCommit={(v) => onChange(v ?? 0)} className={inputCls} />
    </label>
  )
}

function Overlay({ children, title, onClose }: {
  children: React.ReactNode; title: string; onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}>
      <div className="bg-surface rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
