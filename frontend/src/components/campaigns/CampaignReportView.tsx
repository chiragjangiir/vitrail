'use client'

// Retail Media §2.8 S4 — rendu du rapport annonceur (partagé : page interne + portail
// + /share public). Retour Ed #3 : la répartition par écran devient HIÉRARCHIQUE
// (groupes de sites → sites → écrans, repliables, agrégats et SOV moyen par niveau) ;
// dégradation automatique : pas de groupe → sites ; pas de site → écrans à plat.
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, FileDown, ShieldCheck } from 'lucide-react'
import Button from '@/components/ui/Button'

export interface CampaignReport {
  campaign: {
    id_campaign: number
    campaign_name: string
    advertiser_name: string | null
    status: string
    starts_on: string
    ends_on: string
    sov_percent: number
    campaign_kind?: 'visual' | 'audio'
    spots_per_hour?: number | null
  }
  period: { from: string; until: string }
  totals: {
    plays: number
    signed_plays: number
    airtime_ms: number
    players_reached: number
    players_targeted: number
  }
  sov: { sold_pct: number; served_pct: number | null }
  // S2 audio : spots servis vs attendus (spots/h × heures d'ouverture des sites)
  spots?: {
    sold_per_hour: number
    served: number
    expected: number
    served_ratio_pct: number | null
  } | null
  amount: {
    model: string
    amount: number | null
    currency: string
    cpm_rate: number | null
    cpm_indicative: number | null
  }
  per_player: {
    id_player: number
    player_name: string
    id_site?: number | null
    plays: number
    signed_plays: number
    airtime_ms: number
    sov_served_pct: number | null
  }[]
  per_site?: {
    id_site: number | null
    site_name: string | null
    plays: number
    signed_plays: number
    airtime_ms: number
    players_reached: number
    sov_served_pct: number | null
  }[]
  per_site_group?: {
    id_site_group: number
    group_name: string
    plays: number
    signed_plays: number
    airtime_ms: number
    players_reached: number
    site_ids: number[]
    sov_served_pct: number | null
  }[]
  per_day: { date: string; plays: number; airtime_ms: number }[]
  per_creative: { id_media: number; media_name: string; plays: number; airtime_ms: number }[]
}

export type PdfLevel = 'player' | 'site' | 'site_group'

/** Bouton PDF avec choix de granularité (retour Ed #3) — menu seulement si le
 *  rapport a des sites ; sinon téléchargement direct par écran. */
export function PdfLevelButton({ report, onDownload, loading, t }: {
  report: CampaignReport | undefined
  onDownload: (level: PdfLevel) => void
  loading: boolean
  t: (key: string, values?: Record<string, string | number>) => string
}) {
  const [openMenu, setOpenMenu] = useState(false)
  const hasSites = (report?.per_site ?? []).some((s) => s.id_site != null)
  const hasGroups = (report?.per_site_group ?? []).length > 0
  if (!hasSites) {
    return (
      <Button size="sm" onClick={() => onDownload('player')} loading={loading}>
        <FileDown className="w-3.5 h-3.5 mr-1" />{t('report_pdf')}
      </Button>
    )
  }
  const pick = (level: PdfLevel) => { setOpenMenu(false); onDownload(level) }
  return (
    <div className="relative">
      <Button size="sm" onClick={() => setOpenMenu(!openMenu)} loading={loading}>
        <FileDown className="w-3.5 h-3.5 mr-1" />{t('report_pdf')}
        <ChevronDown className="w-3.5 h-3.5 ml-1" />
      </Button>
      {openMenu && (
        <div className="absolute right-0 mt-1 z-40 bg-surface border border-gray-200 rounded-lg shadow-sf-card py-1 min-w-[200px]">
          {hasGroups && (
            <button onClick={() => pick('site_group')}
                    className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-canvas transition-sf">
              {t('report_pdf_by_group')}
            </button>
          )}
          <button onClick={() => pick('site')}
                  className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-canvas transition-sf">
            {t('report_pdf_by_site')}
          </button>
          <button onClick={() => pick('player')}
                  className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-canvas transition-sf">
            {t('report_pdf_by_screen')}
          </button>
        </div>
      )}
    </div>
  )
}

export function fmtDuration(ms: number): string {
  const s = Math.round(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s % 60}s`
  return `${s}s`
}

function fmtAmount(v: number, currency: string): string {
  return `${v.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} ${currency}`
}

function Tile({ label, value, sub, accent }: {
  label: string; value: string; sub?: string; accent?: boolean
}) {
  return (
    <div className="bg-surface rounded-lg border border-gray-200 p-4 shadow-sf-card">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-xl font-semibold ${accent ? 'text-accent' : 'text-gray-900'}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  )
}

interface BreakdownRow {
  key: string
  depth: number
  expandable: boolean
  label: string
  pill: string | null
  plays: number
  airtime_ms: number
  sov: number | null
  emphasized: boolean
}

export default function CampaignReportView({ report, t }: {
  report: CampaignReport
  t: (key: string, values?: Record<string, string | number>) => string
}) {
  const { totals, sov, amount } = report
  const signedPct = totals.plays ? Math.round((1000 * totals.signed_plays) / totals.plays) / 10 : 0
  const maxDay = Math.max(1, ...report.per_day.map((d) => d.plays))

  // ── Répartition hiérarchique (Ed #3) : groupes → sites → écrans, repliables ──
  const [open, setOpen] = useState<Set<string>>(new Set())
  const toggle = (k: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })

  const perSite = useMemo(() => report.per_site ?? [], [report.per_site])
  const perGroup = useMemo(() => report.per_site_group ?? [], [report.per_site_group])
  const hasSiteLevels = perSite.some((s) => s.id_site != null)
  const rows = useMemo<BreakdownRow[]>(() => {
    const playerRow = (p: CampaignReport['per_player'][number], depth: number): BreakdownRow => ({
      key: `p${p.id_player}`, depth, expandable: false, label: p.player_name,
      pill: null, plays: p.plays, airtime_ms: p.airtime_ms, sov: p.sov_served_pct,
      emphasized: false,
    })
    if (!hasSiteLevels) return report.per_player.map((p) => playerRow(p, 0))

    const playersBySite = new Map<number | null, CampaignReport['per_player']>()
    for (const p of report.per_player) {
      const k = p.id_site ?? null
      const arr = playersBySite.get(k) ?? []
      arr.push(p)
      playersBySite.set(k, arr)
    }
    const siteRows = (s: NonNullable<CampaignReport['per_site']>[number], depth: number): BreakdownRow[] => {
      const k = `s${s.id_site ?? 'none'}`
      const out: BreakdownRow[] = [{
        key: k, depth, expandable: true,
        label: s.site_name ?? t('report_no_site'),
        pill: t('report_screens_pill', { n: s.players_reached }),
        plays: s.plays, airtime_ms: s.airtime_ms, sov: s.sov_served_pct,
        emphasized: true,
      }]
      if (open.has(k)) {
        out.push(...(playersBySite.get(s.id_site ?? null) ?? []).map((p) => playerRow(p, depth + 1)))
      }
      return out
    }
    const out: BreakdownRow[] = []
    if (perGroup.length > 0) {
      const grouped = new Set(perGroup.flatMap((g) => g.site_ids))
      for (const g of perGroup) {
        const k = `g${g.id_site_group}`
        out.push({
          key: k, depth: 0, expandable: true, label: g.group_name,
          pill: t('report_sites_pill', { n: g.site_ids.length }),
          plays: g.plays, airtime_ms: g.airtime_ms, sov: g.sov_served_pct,
          emphasized: true,
        })
        if (open.has(k)) {
          for (const s of perSite.filter((x) => x.id_site != null && g.site_ids.includes(x.id_site))) {
            out.push(...siteRows(s, 1))
          }
        }
      }
      // Sites hors groupe (et écrans sans site) au même niveau que les groupes
      for (const s of perSite.filter((x) => x.id_site == null || !grouped.has(x.id_site))) {
        out.push(...siteRows(s, 0))
      }
    } else {
      for (const s of perSite) out.push(...siteRows(s, 0))
    }
    return out
  }, [report.per_player, perSite, perGroup, hasSiteLevels, open, t])

  return (
    <div className="space-y-6">
      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <Tile label={t('report_kpi_plays')} value={totals.plays.toLocaleString('fr-FR')} />
        <Tile label={t('report_kpi_signed')} value={`${signedPct} %`}
              sub={totals.signed_plays.toLocaleString('fr-FR')} />
        <Tile label={t('report_kpi_airtime')} value={fmtDuration(totals.airtime_ms)} />
        <Tile label={t('report_kpi_players')}
              value={`${totals.players_reached} / ${totals.players_targeted}`} />
        {report.spots ? (
          // S2 audio : la tuile SOV devient « spots servis / attendus »
          <Tile label={t('report_kpi_spots')}
                value={report.spots.served_ratio_pct == null ? '—' : `${report.spots.served_ratio_pct} %`}
                sub={t('report_kpi_spots_sub', {
                  served: report.spots.served, expected: report.spots.expected,
                  sold: report.spots.sold_per_hour,
                })} accent />
        ) : (
          <Tile label={t('report_kpi_sov')}
                value={sov.served_pct == null ? '—' : `${sov.served_pct} %`}
                sub={t('report_kpi_sov_sold', { pct: sov.sold_pct })} accent />
        )}
        <Tile label={t('report_kpi_amount')}
              value={amount.amount == null ? '—' : fmtAmount(amount.amount, amount.currency)}
              sub={amount.model === 'sov' ? t('report_model_sov') : t('report_model_flat')}
              accent />
      </div>

      {amount.cpm_indicative != null && (
        <p className="text-xs text-gray-400">
          {t('report_cpm_indicative', {
            value: fmtAmount(amount.cpm_indicative, amount.currency),
            rate: amount.cpm_rate ?? 0,
          })}
        </p>
      )}

      {/* Diffusion quotidienne (mini-barres) */}
      {report.per_day.length > 0 && (
        <div className="bg-surface rounded-lg border border-gray-200 p-5 shadow-sf-card">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">{t('report_by_day')}</h2>
          <div className="flex items-end gap-1 h-28">
            {report.per_day.map((d) => (
              <div key={d.date} className="flex-1 flex flex-col items-center gap-1 min-w-0"
                   title={`${d.date} — ${d.plays}`}>
                <span className="text-[10px] text-gray-500">{d.plays}</span>
                <div className="w-full rounded-t bg-accent"
                     style={{ height: `${Math.max(4, (d.plays / maxDay) * 80)}px` }} />
                <span className="text-[10px] text-gray-400 truncate w-full text-center">
                  {d.date.slice(5)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Par écran — hiérarchie repliable groupes → sites → écrans (Ed #3) ;
          hauteur bornée au viewport + scroll interne + en-tête sticky (Ed #2). */}
      {report.per_player.length > 0 && (
        <div className="bg-surface rounded-lg border border-gray-200 overflow-hidden shadow-sf-card">
          <h2 className="text-sm font-semibold text-gray-900 px-5 pt-4 pb-2">
            {t('report_by_player')}
          </h2>
          <div className="max-h-[45vh] overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                <th className="px-5 py-2 font-medium sticky top-0 bg-surface">
                  {hasSiteLevels ? t('report_col_breakdown') : t('report_col_player')}
                </th>
                <th className="px-5 py-2 font-medium text-right sticky top-0 bg-surface">{t('report_col_plays')}</th>
                <th className="px-5 py-2 font-medium text-right sticky top-0 bg-surface">{t('report_col_airtime')}</th>
                <th className="px-5 py-2 font-medium text-right sticky top-0 bg-surface">{t('report_col_sov')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}
                    className={`border-b border-gray-100 last:border-0 ${r.emphasized ? 'bg-canvas/60' : ''}`}>
                  <td className="px-5 py-2.5 text-gray-800">
                    <div className="flex items-center gap-1.5"
                         style={{ paddingLeft: `${r.depth * 20}px` }}>
                      {r.expandable ? (
                        <button type="button" onClick={() => toggle(r.key)}
                                className="inline-flex items-center gap-1.5 text-left hover:text-accent transition-sf">
                          {open.has(r.key)
                            ? <ChevronDown className="w-3.5 h-3.5 shrink-0 text-gray-400" />
                            : <ChevronRight className="w-3.5 h-3.5 shrink-0 text-gray-400" />}
                          <span className={r.emphasized ? 'font-medium text-gray-900' : ''}>{r.label}</span>
                        </button>
                      ) : (
                        <span>{r.label}</span>
                      )}
                      {r.pill && (
                        <span className="px-1.5 py-0.5 rounded-full bg-accent/10 text-accent text-[11px] font-medium whitespace-nowrap">
                          {r.pill}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className={`px-5 py-2.5 text-right ${r.emphasized ? 'font-semibold text-gray-900' : 'font-medium text-gray-900'}`}>
                    {r.plays.toLocaleString('fr-FR')}
                  </td>
                  <td className="px-5 py-2.5 text-right text-gray-600">
                    {fmtDuration(r.airtime_ms)}
                  </td>
                  <td className="px-5 py-2.5 text-right text-gray-600">
                    {r.sov == null ? '—' : `${r.sov} %`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      {/* Par créatif */}
      {report.per_creative.length > 1 && (
        <div className="bg-surface rounded-lg border border-gray-200 overflow-hidden shadow-sf-card">
          <h2 className="text-sm font-semibold text-gray-900 px-5 pt-4 pb-2">
            {t('report_by_creative')}
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                <th className="px-5 py-2 font-medium">{t('report_col_creative')}</th>
                <th className="px-5 py-2 font-medium text-right">{t('report_col_plays')}</th>
                <th className="px-5 py-2 font-medium text-right">{t('report_col_airtime')}</th>
              </tr>
            </thead>
            <tbody>
              {report.per_creative.map((c) => (
                <tr key={c.id_media} className="border-b border-gray-100 last:border-0">
                  <td className="px-5 py-2.5 text-gray-800">{c.media_name}</td>
                  <td className="px-5 py-2.5 text-right font-medium text-gray-900">
                    {c.plays.toLocaleString('fr-FR')}
                  </td>
                  <td className="px-5 py-2.5 text-right text-gray-600">
                    {fmtDuration(c.airtime_ms)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="flex items-center gap-2 text-xs text-gray-400">
        <ShieldCheck className="w-4 h-4 shrink-0 text-accent" />
        {t('report_pop_note')}
      </p>
    </div>
  )
}
