'use client'

// S6 Retail Media — calendrier des campagnes : barres par campagne sur le mois
// (couleur = statut effectif) + bandeau de charge d'inventaire par jour
// (max sur les players de Σ SOV vendue — mêmes seuils que l'occupancy-check S2 :
// ambre ≥ 80 %, rouge > 100 %). Clic sur une campagne → drawer.

import { useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export interface CalendarCampaign {
  id_campaign: number
  campaign_name: string
  status: string
  starts_on: string
  ends_on: string
  advertiser_name?: string | null
  sov_percent: number
}

export interface OccupancyDay { date: string; max_pct: number }

// Couleur de barre par statut effectif (mêmes familles que les badges de la liste).
const BAR: Record<string, string> = {
  live: 'bg-green-500/80',
  scheduled: 'bg-accent/70',
  draft: 'bg-gray-300 dark:bg-gray-600',
  paused: 'bg-orange-400/80',
  completed: 'bg-gray-200 dark:bg-gray-700',
  cancelled: 'bg-gray-200 dark:bg-gray-700 opacity-50',
}

function occColor(pct: number): string {
  if (pct > 100) return 'bg-red-500'
  if (pct >= 80) return 'bg-orange-400'
  if (pct > 0) return 'bg-green-400'
  return 'bg-gray-100 dark:bg-gray-800'
}

function monthDays(year: number, month: number): string[] {
  const n = new Date(year, month + 1, 0).getDate()
  return Array.from({ length: n }, (_, i) =>
    `${year}-${String(month + 1).padStart(2, '0')}-${String(i + 1).padStart(2, '0')}`)
}

export default function CampaignCalendar({
  campaigns, occupancy, year, month, onPrev, onNext, onSelect,
}: {
  campaigns: CalendarCampaign[]
  occupancy: OccupancyDay[]
  year: number
  month: number   // 0-based
  onPrev: () => void
  onNext: () => void
  onSelect: (id_campaign: number) => void
}) {
  const t = useTranslations()
  const days = useMemo(() => monthDays(year, month), [year, month])
  const first = days[0]
  const last = days[days.length - 1]
  // Date LOCALE (toISOString basculerait au jour UTC — faux avant 01:00/02:00 à Paris)
  const now = new Date()
  const todayIso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const occByDate = useMemo(
    () => Object.fromEntries(occupancy.map((d) => [d.date, d.max_pct])), [occupancy])

  // Campagnes chevauchant le mois, triées par début puis nom.
  const visible = useMemo(() =>
    campaigns
      .filter((c) => c.starts_on <= last && c.ends_on >= first)
      .sort((a, b) => a.starts_on.localeCompare(b.starts_on) || a.campaign_name.localeCompare(b.campaign_name)),
    [campaigns, first, last])

  const monthLabel = new Date(year, month, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  const grid = { display: 'grid', gridTemplateColumns: `minmax(160px, 220px) repeat(${days.length}, minmax(0, 1fr))` } as const

  return (
    <div className="bg-surface border border-gray-200 rounded-xl p-4 mb-4 shadow-sf-card">
      <div className="flex items-center justify-between mb-1">
        <p className="text-sm font-medium text-gray-700">{t('campaigns.calendar_title')}</p>
        <div className="flex items-center gap-1">
          <button onClick={onPrev} className="p-1.5 text-gray-400 hover:text-gray-700 rounded transition-sf" title={t('campaigns.calendar_prev')}>
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm text-gray-700 font-medium capitalize min-w-[140px] text-center">{monthLabel}</span>
          <button onClick={onNext} className="p-1.5 text-gray-400 hover:text-gray-700 rounded transition-sf" title={t('campaigns.calendar_next')}>
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
      <p className="text-xs text-gray-400 mb-3">{t('campaigns.calendar_hint')}</p>

      <div className="overflow-x-auto">
        <div className="min-w-[720px]">
          {/* En-tête : numéros de jour */}
          <div style={grid} className="items-end">
            <div />
            {days.map((d) => {
              const dt = new Date(d + 'T00:00:00')
              const weekend = dt.getDay() === 0 || dt.getDay() === 6
              return (
                <div key={d}
                     className={`text-center text-[10px] pb-1 ${d === todayIso ? 'text-accent font-semibold' : weekend ? 'text-gray-300' : 'text-gray-400'}`}>
                  {dt.getDate()}
                </div>
              )
            })}
          </div>

          {/* Bandeau d'occupation par jour (max players, Σ SOV vendue) */}
          <div style={grid} className="items-center mb-2">
            <span className="text-[11px] text-gray-500 pr-2 truncate">{t('campaigns.calendar_load')}</span>
            {days.map((d) => {
              const pct = occByDate[d] ?? 0
              return (
                <div key={d} className="px-px" title={`${d} · ${pct}%`}>
                  <div className={`h-2.5 rounded-sm ${occColor(pct)}`} />
                </div>
              )
            })}
          </div>

          {/* Barres par campagne */}
          {visible.length === 0 ? (
            <p className="text-xs text-gray-400 py-4 text-center">{t('campaigns.calendar_empty')}</p>
          ) : (
            <div className="space-y-1">
              {visible.map((c) => {
                const from = c.starts_on < first ? first : c.starts_on
                const to = c.ends_on > last ? last : c.ends_on
                const startIdx = days.indexOf(from)
                const endIdx = days.indexOf(to)
                return (
                  <div key={c.id_campaign} style={grid} className="items-center">
                    <button
                      onClick={() => onSelect(c.id_campaign)}
                      className="text-left text-xs text-gray-700 hover:text-accent truncate pr-2 transition-sf"
                      title={`${c.campaign_name}${c.advertiser_name ? ` · ${c.advertiser_name}` : ''}`}
                    >
                      {c.campaign_name}
                    </button>
                    {days.map((d, i) => (
                      <div key={d} className="h-5 flex items-center">
                        {i >= startIdx && i <= endIdx && (
                          <button
                            onClick={() => onSelect(c.id_campaign)}
                            title={`${c.campaign_name} · ${t(`campaigns.st_${c.status}`)} · SOV ${c.sov_percent}%`}
                            className={`h-3.5 w-full cursor-pointer ${BAR[c.status] ?? 'bg-gray-300'} ${
                              i === startIdx ? 'rounded-l-full' : ''} ${i === endIdx ? 'rounded-r-full' : ''} ${
                              c.starts_on < first && i === startIdx ? '!rounded-l-none' : ''} ${
                              c.ends_on > last && i === endIdx ? '!rounded-r-none' : ''}`}
                          />
                        )}
                      </div>
                    ))}
                  </div>
                )
              })}
            </div>
          )}

          {/* Légende */}
          <div className="flex flex-wrap items-center gap-3 mt-3 pt-2 border-t border-gray-100 text-[10px] text-gray-500">
            {(['live', 'scheduled', 'paused', 'draft', 'completed'] as const).map((s) => (
              <span key={s} className="inline-flex items-center gap-1">
                <span className={`w-2.5 h-2.5 rounded-full ${BAR[s]}`} />
                {t(`campaigns.st_${s}`)}
              </span>
            ))}
            <span className="ml-auto inline-flex items-center gap-3">
              <span className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-orange-400" />{t('campaigns.calendar_warn')}</span>
              <span className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-red-500" />{t('campaigns.calendar_over')}</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
