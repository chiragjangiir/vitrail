'use client'

import { useMemo } from 'react'
import {
  Activity, Monitor, ShieldCheck, AlertTriangle, TrendingUp,
} from 'lucide-react'

export interface FleetCounts {
  total: number; online: number; warning: number; offline: number; maintenance: number
}
export interface TopContentRow {
  id_media: number | null; media_name: string | null; media_type: string | null
  plays: number; seconds: number
}
export interface MetricsPoint {
  date: string; players_total: number; players_online: number
  online_pct: number | null; conformity_pct: number | null
  alerts_active: number; plays_count: number; health_score: number | null
}
export interface ExecutiveDashboard {
  from_date: string; until_date: string
  health_score: number | null; fleet: FleetCounts
  conformity_pct: number | null; alerts_active: number; uptime_pct: number | null
  plays_count: number; play_seconds: number
  top_content: TopContentRow[]; series: MetricsPoint[]
}
export interface RoiEstimate {
  screens: number; days: number; hours_per_day: number; contacts_per_hour: number
  cpm_eur: number; paper_eur_per_month: number; uptime_pct: number
  impressions: number; network_value_eur: number; paper_savings_eur: number; total_roi_eur: number
}

type T = (key: string, values?: Record<string, string | number>) => string

export function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m`
  return `${sec}s`
}
export function fmtEur(v: number): string {
  return `${Math.round(v).toLocaleString('fr-FR')} €`
}
export function healthColor(score: number | null): string {
  if (score === null) return 'text-gray-400'
  if (score >= 80) return 'text-success'
  if (score >= 50) return 'text-warning'
  return 'text-danger'
}
function healthStroke(score: number | null): string {
  if (score === null) return 'stroke-gray-300'
  if (score >= 80) return 'stroke-success'
  if (score >= 50) return 'stroke-warning'
  return 'stroke-danger'
}

function HealthGauge({ score }: { score: number | null }) {
  const r = 52
  const c = 2 * Math.PI * r
  const frac = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100
  return (
    <div className="relative w-[140px] h-[140px] shrink-0">
      <svg viewBox="0 0 140 140" className="w-full h-full -rotate-90">
        <circle cx="70" cy="70" r={r} className="fill-none stroke-gray-200" strokeWidth="12" />
        <circle
          cx="70" cy="70" r={r}
          className={`fill-none ${healthStroke(score)} transition-sf`}
          strokeWidth="12" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - frac)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-4xl font-semibold leading-none ${healthColor(score)}`}>
          {score === null ? '—' : score}
        </span>
        <span className="text-[10px] text-gray-400 mt-1">/ 100</span>
      </div>
    </div>
  )
}

const FLEET_SEGMENTS = [
  { key: 'online', cls: 'fill-success', dot: 'bg-success' },
  { key: 'warning', cls: 'fill-warning', dot: 'bg-warning' },
  { key: 'offline', cls: 'fill-danger', dot: 'bg-danger' },
  { key: 'maintenance', cls: 'fill-gray-400', dot: 'bg-gray-400' },
] as const

function FleetDonut({ fleet, t }: { fleet: FleetCounts; t: T }) {
  const total = fleet.total || 0
  const r = 46; const cx = 60; const cy = 60
  let acc = 0
  const arcs = FLEET_SEGMENTS.map((seg) => {
    const val = fleet[seg.key as keyof FleetCounts] as number
    const frac = total > 0 ? val / total : 0
    const a0 = acc * 2 * Math.PI
    acc += frac
    const a1 = acc * 2 * Math.PI
    const large = a1 - a0 > Math.PI ? 1 : 0
    const x0 = cx + r * Math.cos(a0 - Math.PI / 2)
    const y0 = cy + r * Math.sin(a0 - Math.PI / 2)
    const x1 = cx + r * Math.cos(a1 - Math.PI / 2)
    const y1 = cy + r * Math.sin(a1 - Math.PI / 2)
    return { seg, frac, d: `M ${cx} ${cy} L ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1} Z` }
  })
  return (
    <div className="flex items-center gap-5">
      <div className="relative w-[120px] h-[120px] shrink-0">
        <svg viewBox="0 0 120 120" className="w-full h-full">
          {total === 0 ? (
            <circle cx={cx} cy={cy} r={r} className="fill-none stroke-gray-200" strokeWidth="16" />
          ) : (
            arcs.filter((a) => a.frac > 0).map((a) => (
              a.frac >= 0.9999
                ? <circle key={a.seg.key} cx={cx} cy={cy} r={r} className={a.seg.cls} />
                : <path key={a.seg.key} d={a.d} className={a.seg.cls} />
            ))
          )}
          <circle cx={cx} cy={cy} r={26} className="fill-surface" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-semibold text-gray-900 leading-none">{fleet.total}</span>
        </div>
      </div>
      <div className="space-y-1.5">
        {FLEET_SEGMENTS.map((seg) => (
          <div key={seg.key} className="flex items-center gap-2 text-sm">
            <span className={`w-2.5 h-2.5 rounded-full ${seg.dot}`} />
            <span className="text-gray-500 w-24">{t(seg.key)}</span>
            <span className="font-medium text-gray-900">{fleet[seg.key as keyof FleetCounts]}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Sparkline({
  points, max = 100, strokeCls, fillCls,
}: { points: (number | null)[]; max?: number; strokeCls: string; fillCls: string }) {
  const vals = points.map((p) => (p === null ? 0 : p))
  if (vals.length === 0) return null
  const w = 100; const h = 32; const n = vals.length
  const xa = (i: number) => (n === 1 ? w / 2 : (i / (n - 1)) * w)
  const ya = (v: number) => h - (Math.max(0, Math.min(max, v)) / max) * h
  const line = vals.map((v, i) => `${xa(i)},${ya(v)}`).join(' ')
  const area = `${xa(0)},${h} ${line} ${xa(n - 1)},${h}`
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full h-10">
      <polygon points={area} className={fillCls} opacity={0.15} />
      <polyline
        points={line} className={`fill-none ${strokeCls}`}
        strokeWidth="1.5" vectorEffect="non-scaling-stroke"
        strokeLinejoin="round" strokeLinecap="round"
      />
    </svg>
  )
}

function KpiCard({
  icon: Icon, label, value, sub, valueCls = 'text-accent',
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string; value: string; sub?: string; valueCls?: string
}) {
  return (
    <div className="bg-surface rounded-lg border border-gray-200 p-4 shadow-sf-card">
      <div className="flex items-center gap-2 text-gray-500 mb-2">
        <Icon className="w-4 h-4 text-accent" />
        <span className="text-xs">{label}</span>
      </div>
      <p className={`text-2xl font-semibold leading-none ${valueCls}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1.5">{sub}</p>}
    </div>
  )
}

/** Rendu partagé du dashboard (KPIs + graphiques) — utilisé par la page authentifiée
 *  et la vue publique (share link). Purement présentationnel. */
export function DashboardView({ data, t }: { data: ExecutiveDashboard; t: T }) {
  const topMax = useMemo(
    () => Math.max(1, ...(data.top_content ?? []).map((c) => c.plays)), [data])
  const alertsMax = useMemo(
    () => Math.max(1, ...(data.series ?? []).map((s) => s.alerts_active)), [data])
  const fmtPct = (v: number | null) => (v === null ? '—' : `${v}%`)

  return (
    <div className="space-y-6">
      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
        <div className="bg-surface rounded-lg border border-gray-200 p-4 flex items-center gap-4 col-span-2 md:col-span-1 xl:col-span-2 shadow-sf-card">
          <HealthGauge score={data.health_score} />
          <div>
            <div className="flex items-center gap-2 text-gray-500 mb-1">
              <Activity className="w-4 h-4 text-accent" />
              <span className="text-xs">{t('kpi_health')}</span>
            </div>
            <p className="text-xs text-gray-400">{t('kpi_health_hint')}</p>
          </div>
        </div>
        <KpiCard icon={TrendingUp} label={t('kpi_uptime')}
          value={fmtPct(data.uptime_pct)} valueCls={healthColor(data.uptime_pct)} />
        <KpiCard icon={ShieldCheck} label={t('kpi_conformity')}
          value={fmtPct(data.conformity_pct)} valueCls={healthColor(data.conformity_pct)} />
        <KpiCard icon={Monitor} label={t('kpi_players')}
          value={`${data.fleet.online} / ${data.fleet.total}`} sub={t('kpi_players_sub')} />
        <KpiCard icon={AlertTriangle} label={t('kpi_alerts')}
          value={`${data.alerts_active}`}
          valueCls={data.alerts_active > 0 ? 'text-warning' : 'text-gray-900'}
          sub={t('kpi_alerts_sub')} />
      </div>

      {/* Donut + sparklines */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">{t('fleet_title')}</h2>
          <FleetDonut fleet={data.fleet} t={t} />
        </div>
        <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-900">{t('uptime_title')}</h2>
            <span className={`text-sm font-medium ${healthColor(data.uptime_pct)}`}>
              {fmtPct(data.uptime_pct)}
            </span>
          </div>
          <Sparkline points={(data.series ?? []).map((s) => s.online_pct)}
            strokeCls="stroke-accent" fillCls="fill-accent" />
          <p className="text-xs text-gray-400 mt-2">{t('uptime_hint')}</p>
        </div>
        <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-900">{t('health_title')}</h2>
            <span className={`text-sm font-medium ${healthColor(data.health_score)}`}>
              {data.health_score ?? '—'}
            </span>
          </div>
          <Sparkline points={(data.series ?? []).map((s) => s.health_score)}
            strokeCls="stroke-success" fillCls="fill-success" />
          <p className="text-xs text-gray-400 mt-2">{t('health_hint')}</p>
        </div>
      </div>

      {/* Top contenus + alertes */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-900">{t('top_content_title')}</h2>
            <span className="text-xs text-gray-400">
              {t('content_summary', {
                plays: data.plays_count.toLocaleString('fr-FR'),
                dur: fmtDuration(data.play_seconds),
              })}
            </span>
          </div>
          {(data.top_content ?? []).length === 0 ? (
            <p className="text-sm text-gray-400 py-6 text-center">{t('no_data')}</p>
          ) : (
            <div className="space-y-3">
              {data.top_content.map((c, i) => (
                <div key={c.id_media ?? i} className="flex items-center gap-3">
                  <span className="text-xs text-gray-400 w-4">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-sm text-gray-700 truncate">
                        {c.media_name ?? `#${c.id_media}`}
                      </span>
                      <span className="text-xs text-gray-500 shrink-0">
                        {c.plays.toLocaleString('fr-FR')} · {fmtDuration(c.seconds)}
                      </span>
                    </div>
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-accent rounded-full"
                        style={{ width: `${Math.round((c.plays / topMax) * 100)}%` }} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">{t('alerts_title')}</h2>
          {(data.series ?? []).length === 0 ? (
            <p className="text-sm text-gray-400 py-6 text-center">{t('no_history')}</p>
          ) : (
            <div className="flex items-end gap-0.5 h-28">
              {data.series.map((s) => (
                <div key={s.date} className="flex-1 flex flex-col justify-end"
                  title={`${s.date} · ${s.alerts_active}`}>
                  <div className={`rounded-t ${s.alerts_active > 0 ? 'bg-warning/70' : 'bg-gray-200'}`}
                    style={{ height: `${Math.max(4, Math.round((s.alerts_active / alertsMax) * 100))}%` }} />
                </div>
              ))}
            </div>
          )}
          <p className="text-xs text-gray-400 mt-3">{t('alerts_hint')}</p>
        </div>
      </div>
    </div>
  )
}
