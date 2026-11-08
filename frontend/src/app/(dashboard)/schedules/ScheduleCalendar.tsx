'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslations, useLocale } from 'next-intl'
import { ChevronLeft, ChevronRight, Download, Megaphone, Music, Zap } from 'lucide-react'
import { downloadCsv } from '@/lib/csv'
import type { ScheduleRead, EventRead } from '@/types/api'

// Campagne Retail Media vue du calendrier unifié (sous-ensemble de CampaignRead).
export interface CalendarCampaignLite {
  id_campaign: number
  campaign_name: string
  status: string
  starts_on: string
  ends_on: string
  advertiser_name?: string | null
  sov_percent: number
}

// ── Modèle interne ───────────────────────────────────────────────────────────
// Un « bloc » = une occurrence récurrente (programme, event ou campagne) avec son créneau.
type BlockKind = 'content' | 'audio' | 'event' | 'campaign'
interface Block {
  key: string
  kind: BlockKind
  /** Id du programme source (kind content|audio) — permet d'ouvrir son drawer au clic. */
  scheduleId?: number
  name: string
  detail?: string
  status?: string          // campagnes : statut effectif (couleur + tooltip)
  priority: number
  days: number[] | null   // 0=Lun … 6=Dim ; null = tous les jours (always)
  allDay: boolean
  startMin: number        // minutes depuis 00:00
  endMin: number
  validFrom: number | null  // timestamp (events)
  validUntil: number | null
}

const DAY_MS = 86_400_000

// ── Helpers date ─────────────────────────────────────────────────────────────
function startOfDay(d: Date): Date { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
function addDays(d: Date, n: number): Date { const x = new Date(d); x.setDate(x.getDate() + n); return x }
function addMonths(d: Date, n: number): Date { const x = new Date(d); x.setMonth(x.getMonth() + n); return x }
function weekdayMon0(d: Date): number { return (d.getDay() + 6) % 7 }   // JS 0=Dim → 0=Lun
function startOfWeek(d: Date): Date { return addDays(startOfDay(d), -weekdayMon0(d)) }
function parseHM(s?: string | null): number {
  if (!s) return 0
  const [h, m] = s.split(':').map(Number)
  return (h || 0) * 60 + (m || 0)
}
function fmtHM(min: number): string {
  const h = Math.floor(min / 60), m = min % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
/** 'YYYY-MM-DD' → timestamp minuit local (la validité programme est en heure locale). */
function dateStrToLocalTs(s?: string | null): number | null {
  if (!s) return null
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1).getTime()
}

// Palette stable par nom pour les programmes ; events = ambre pointillé distinct ;
// campagnes = vert plein (le vert est RETIRÉ de la palette programmes pour rester univoque).
const SCHED_COLORS = [
  'bg-blue-100 dark:bg-blue-500/20 text-blue-800 dark:text-blue-200 border-blue-300 dark:border-blue-500/40',
  'bg-indigo-100 dark:bg-indigo-500/20 text-indigo-800 dark:text-indigo-200 border-indigo-300 dark:border-indigo-500/40',
  'bg-violet-100 dark:bg-violet-500/20 text-violet-800 dark:text-violet-200 border-violet-300 dark:border-violet-500/40',
  'bg-cyan-100 dark:bg-cyan-500/20 text-cyan-800 dark:text-cyan-200 border-cyan-300 dark:border-cyan-500/40',
  'bg-pink-100 dark:bg-pink-500/20 text-pink-800 dark:text-pink-200 border-pink-300 dark:border-pink-500/40',
  'bg-rose-100 dark:bg-rose-500/20 text-rose-800 dark:text-rose-200 border-rose-300 dark:border-rose-500/40',
]
function blockColor(b: Block): string {
  if (b.kind === 'event') return 'bg-amber-100 dark:bg-amber-500/20 text-amber-900 dark:text-amber-200 border-amber-400 dark:border-amber-500/50 border-dashed'
  if (b.kind === 'campaign') {
    if (b.status === 'paused') return 'bg-orange-100 dark:bg-orange-500/20 text-orange-900 dark:text-orange-200 border-orange-400 dark:border-orange-500/50'
    if (b.status === 'live' || b.status === 'scheduled') return 'bg-green-100 dark:bg-green-500/20 text-green-900 dark:text-green-200 border-green-400 dark:border-green-500/50'
    // draft / completed : présent mais éteint
    return 'bg-green-50 dark:bg-green-500/10 text-green-800/70 dark:text-green-200/60 border-green-200 dark:border-green-500/30 opacity-80'
  }
  let h = 0
  for (let i = 0; i < b.name.length; i++) h = (h * 31 + b.name.charCodeAt(i)) % SCHED_COLORS.length
  return SCHED_COLORS[h]
}

/**
 * Props d'interaction d'une vignette de calendrier : un bloc issu d'un PROGRAMME
 * (content|audio) ouvre son drawer au clic. Les events et campagnes ont leurs
 * pages dédiées et restent non cliquables ici.
 *
 * Un `<div role="button">` et non un `<button>` : les vignettes contiennent déjà
 * des `<div>` (règle « jamais de div dans un button »).
 */
function clickProps(b: Block, onOpenSchedule?: (id: number) => void) {
  if (!onOpenSchedule || b.scheduleId === undefined) return {}
  const open = () => onOpenSchedule(b.scheduleId!)
  return {
    role: 'button' as const,
    tabIndex: 0,
    onClick: open,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open() }
    },
  }
}

// Icône par famille (badge = toujours icône + couleur + texte, règle design system).
function BlockIcon({ b }: { b: Block }) {
  if (b.kind === 'event') return <Zap className="w-2.5 h-2.5 inline mr-0.5 -mt-0.5" />
  if (b.kind === 'campaign') return <Megaphone className="w-2.5 h-2.5 inline mr-0.5 -mt-0.5" />
  if (b.kind === 'audio') return <Music className="w-2.5 h-2.5 inline mr-0.5 -mt-0.5" />
  return null
}

// ── Extraction des blocs ─────────────────────────────────────────────────────
function buildBlocks(
  schedules: ScheduleRead[], events: EventRead[], campaigns: CalendarCampaignLite[],
): Block[] {
  const out: Block[] = []

  for (const s of schedules) {
    if (!s.is_active) continue   // le calendrier ne montre que les programmes actifs
    const kind: BlockKind = s.schedule_kind === 'audio' ? 'audio' : 'content'
    // Enveloppe de validité (dates début/fin) du programme — borne l'affichage par date.
    const vf = dateStrToLocalTs(s.valid_from)
    const vu = dateStrToLocalTs(s.valid_until)
    const rules = s.rules?.length ? s.rules : [{ rule_type: 'always' } as ScheduleRead['rules'][number]]
    rules.forEach((r, i) => {
      if (r.rule_type === 'weekly' && r.days_of_week && r.days_of_week.length) {
        const allDay = !r.time_start || !r.time_end
        out.push({
          key: `s${s.id_schedule}-${i}`, kind, scheduleId: s.id_schedule, name: s.schedule_name,
          priority: s.priority, days: r.days_of_week, allDay,
          // endMin <= startMin ⇒ fenêtre nocturne (ex. 22:00→04:00), scindée au rendu.
          startMin: allDay ? 0 : parseHM(r.time_start),
          endMin: allDay ? 1440 : parseHM(r.time_end),
          validFrom: vf, validUntil: vu,
        })
      } else {
        out.push({
          key: `s${s.id_schedule}-${i}`, kind, scheduleId: s.id_schedule, name: s.schedule_name,
          priority: s.priority, days: null, allDay: true, startMin: 0, endMin: 1440,
          validFrom: vf, validUntil: vu,
        })
      }
    })
  }

  for (const e of events) {
    if (e.status === 'cancelled') continue
    const detail = e.playlist_name ?? e.media_name ?? e.basket_name ?? undefined
    const vf = e.valid_from ? new Date(e.valid_from).getTime() : null
    const vu = e.valid_until ? new Date(e.valid_until).getTime() : null
    const conds = ((e.trigger_config?.conditions as Array<Record<string, unknown>>) ?? [])
      .filter((c) => c.source === 'schedule')
    if (conds.length === 0) {
      // Pas de créneau récurrent : placé sur toute la plage de validité (sinon non plaçable).
      if (vf || vu) out.push({
        key: `e${e.id_event}`, kind: 'event', name: e.event_name, detail,
        priority: e.priority, days: null, allDay: true, startMin: 0, endMin: 1440,
        validFrom: vf, validUntil: vu,
      })
      continue
    }
    conds.forEach((c, i) => {
      const ts = c.time_start as string | undefined, te = c.time_end as string | undefined
      const allDay = !ts || !te
      out.push({
        key: `e${e.id_event}-${i}`, kind: 'event', name: e.event_name, detail,
        priority: e.priority, days: (c.days_of_week as number[]) ?? null, allDay,
        startMin: allDay ? 0 : parseHM(ts), endMin: allDay ? 1440 : parseHM(te),
        validFrom: vf, validUntil: vu,
      })
    })
  }

  // Campagnes Retail Media : entités à plage de dates (pas de créneau horaire) →
  // bloc « journée entière » sur starts_on..ends_on, statut effectif en couleur/tooltip.
  for (const c of campaigns) {
    if (c.status === 'cancelled') continue
    const detailParts = [c.advertiser_name, `SOV ${c.sov_percent}%`].filter(Boolean)
    out.push({
      key: `c${c.id_campaign}`, kind: 'campaign', name: c.campaign_name,
      detail: detailParts.join(' · '), status: c.status,
      priority: 0, days: null, allDay: true, startMin: 0, endMin: 1440,
      validFrom: dateStrToLocalTs(c.starts_on), validUntil: dateStrToLocalTs(c.ends_on),
    })
  }
  return out
}

function activeOn(b: Block, day: Date): boolean {
  if (b.days && !b.days.includes(weekdayMon0(day))) return false
  const ds = startOfDay(day).getTime(), de = ds + DAY_MS - 1
  if (b.validFrom !== null && de < b.validFrom) return false
  if (b.validUntil !== null && ds > b.validUntil) return false
  return true
}

// Occurrence d'un bloc sur un jour donne (positionnee dans la grille).
// Une fenetre nocturne (endMin <= startMin) est scindee : tete [start→24h] le jour J
// + queue [00h→end] le lendemain (rattachee a la fenetre demarree la veille).
interface DayOcc { b: Block; startMin: number; endMin: number; isTail: boolean; key: string }
function occurrencesForDay(blocks: Block[], day: Date): DayOcc[] {
  const out: DayOcc[] = []
  const prev = addDays(day, -1)
  for (const b of blocks) {
    const overnight = !b.allDay && b.endMin <= b.startMin
    if (activeOn(b, day)) {
      out.push({ b, startMin: b.startMin, endMin: overnight ? 1440 : b.endMin, isTail: false, key: b.key })
    }
    if (overnight && activeOn(b, prev)) {
      out.push({ b, startMin: 0, endMin: b.endMin, isTail: true, key: b.key + '-t' })
    }
  }
  return out
}

// Affectation en colonnes (lanes) pour les segments horaires qui se chevauchent.
function assignLanes(items: { startMin: number; endMin: number }[]): { lane: number; lanes: number }[] {
  const sorted = items.map((it, idx) => ({ it, idx })).sort((a, z) => a.it.startMin - z.it.startMin)
  const laneEnds: number[] = []
  const laneOf: number[] = new Array(items.length).fill(0)
  for (const { it, idx } of sorted) {
    let lane = laneEnds.findIndex((end) => end <= it.startMin)
    if (lane === -1) { lane = laneEnds.length; laneEnds.push(it.endMin) }
    else laneEnds[lane] = it.endMin
    laneOf[idx] = lane
  }
  const lanes = Math.max(1, laneEnds.length)
  return laneOf.map((lane) => ({ lane, lanes }))
}

// ── Composant ────────────────────────────────────────────────────────────────
export default function ScheduleCalendar({
  schedules, events, campaigns = [], exportTag = 'all', onOpenSchedule,
}: {
  schedules: ScheduleRead[]
  events: EventRead[]
  campaigns?: CalendarCampaignLite[]
  exportTag?: string
  /** Clic sur la vignette d'un programme → ouverture de son drawer d'édition. */
  onOpenSchedule?: (id: number) => void
}) {
  const t = useTranslations('schedules')
  const locale = useLocale()
  const [view, setView] = useState<'week' | 'month'>('week')
  const [cursor, setCursor] = useState<Date>(() => startOfDay(new Date()))

  const blocks = useMemo(() => buildBlocks(schedules, events, campaigns), [schedules, events, campaigns])
  const today = startOfDay(new Date()).getTime()

  const dowFmt = useMemo(() => new Intl.DateTimeFormat(locale, { weekday: 'short' }), [locale])
  const dayNumFmt = useMemo(() => new Intl.DateTimeFormat(locale, { day: 'numeric' }), [locale])

  function navigate(dir: -1 | 1) {
    setCursor((c) => (view === 'week' ? addDays(c, dir * 7) : addMonths(c, dir)))
  }

  // Libellé de période
  const periodLabel = useMemo(() => {
    if (view === 'month') {
      return new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(cursor)
    }
    const ws = startOfWeek(cursor), we = addDays(ws, 6)
    const dm = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short' })
    const dmy = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric' })
    return `${dm.format(ws)} – ${dmy.format(we)}`
  }, [view, cursor, locale])

  function exportCsv() {
    const dayKeys = ['day_mon', 'day_tue', 'day_wed', 'day_thu', 'day_fri', 'day_sat', 'day_sun']
    const typeLabel: Record<BlockKind, string> = {
      content: t('legend_schedule'), audio: t('legend_audio'),
      event: t('legend_event'), campaign: t('legend_campaign'),
    }
    const rows: (string | number)[][] = [[
      t('csv_type'), t('csv_name'), t('csv_content'), t('csv_days'), t('csv_slot'),
      t('csv_validity'), t('col_priority'),
    ]]
    for (const b of blocks) {
      const days = b.days === null ? t('rule_always') : b.days.map((d) => t(dayKeys[d])).join(' ')
      const slot = b.allDay ? t('all_day') : `${fmtHM(b.startMin)}–${fmtHM(b.endMin)}`
      const validity = b.validFrom || b.validUntil
        ? `${b.validFrom ? new Date(b.validFrom).toLocaleDateString(locale) : '…'} → ${b.validUntil ? new Date(b.validUntil).toLocaleDateString(locale) : '…'}`
        : ''
      rows.push([
        typeLabel[b.kind],
        b.name, b.detail ?? '', days, slot, validity,
        b.kind === 'campaign' ? '' : b.priority,
      ])
    }
    // L'export suit les filtres actifs (type + cible) : blocks = uniquement le visible.
    downloadCsv(`programmation_${exportTag}_${new Date().toISOString().slice(0, 10)}.csv`, rows)
  }

  return (
    // Verrouillé au viewport : la barre de navigation est figée, seule la vue défile
    // (règle de mise en page du design system).
    <div className="bg-surface rounded-lg border border-gray-200 overflow-hidden shadow-sf-card flex flex-col h-full min-h-0">
      {/* Barre de navigation */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate(-1)} className="p-1.5 rounded hover:bg-gray-100 text-gray-500" title={t('prev')}>
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button onClick={() => navigate(1)} className="p-1.5 rounded hover:bg-gray-100 text-gray-500" title={t('next')}>
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            onClick={() => setCursor(startOfDay(new Date()))}
            className="px-2.5 py-1 text-xs font-medium rounded border border-gray-200 text-gray-600 hover:border-accent"
          >
            {t('today')}
          </button>
          <span className="text-sm font-semibold text-gray-800 capitalize ml-1">{periodLabel}</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Légende — 4 familles (répond à l'ambiguïté visuelle remontée par les testeurs) */}
          <span className="hidden lg:inline-flex items-center gap-1 text-[11px] text-gray-400">
            <span className="w-3 h-3 rounded-sm border bg-blue-100 dark:bg-blue-500/20 border-blue-300 dark:border-blue-500/40" /> {t('legend_schedule')}
            <span className="inline-flex items-center w-3 h-3 rounded-sm border bg-violet-100 dark:bg-violet-500/20 border-violet-300 dark:border-violet-500/40 ml-2 justify-center"><Music className="w-2 h-2" /></span> {t('legend_audio')}
            <span className="inline-flex items-center w-3 h-3 rounded-sm border border-dashed bg-amber-100 dark:bg-amber-500/20 border-amber-400 dark:border-amber-500/50 ml-2 justify-center"><Zap className="w-2 h-2" /></span> {t('legend_event')}
            <span className="inline-flex items-center w-3 h-3 rounded-sm border bg-green-100 dark:bg-green-500/20 border-green-400 dark:border-green-500/50 ml-2 justify-center"><Megaphone className="w-2 h-2" /></span> {t('legend_campaign')}
          </span>
          <div className="flex rounded border border-gray-200 overflow-hidden">
            {(['week', 'month'] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-3 py-1 text-xs font-medium ${view === v ? 'bg-accent text-white' : 'bg-surface text-gray-600 hover:bg-gray-50'}`}
              >
                {t(v === 'week' ? 'view_week' : 'view_month')}
              </button>
            ))}
          </div>
          <button
            onClick={exportCsv}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded border border-gray-200 text-gray-600 hover:border-accent"
          >
            <Download className="w-3.5 h-3.5" />
            {t('export')}
          </button>
        </div>
      </div>

      {view === 'week'
        ? <WeekView cursor={cursor} blocks={blocks} today={today} dowFmt={dowFmt} dayNumFmt={dayNumFmt} t={t} onOpenSchedule={onOpenSchedule} />
        : <MonthView cursor={cursor} blocks={blocks} today={today} dayNumFmt={dayNumFmt} locale={locale} onOpenSchedule={onOpenSchedule} />}
    </div>
  )
}

// ── Vue Semaine (grille heures × jours) ──────────────────────────────────────
function WeekView({
  cursor, blocks, today, dowFmt, dayNumFmt, t, onOpenSchedule,
}: {
  cursor: Date; blocks: Block[]; today: number
  dowFmt: Intl.DateTimeFormat; dayNumFmt: Intl.DateTimeFormat
  t: ReturnType<typeof useTranslations>
  onOpenSchedule?: (id: number) => void
}) {
  const ws = startOfWeek(cursor)
  const days = Array.from({ length: 7 }, (_, i) => addDays(ws, i))

  // Journée complète 0h–24h (un client type boîte de nuit a des programmes nocturnes).
  const timed = blocks.filter((b) => !b.allDay)
  const rangeStart = 0, rangeEnd = 1440
  const totalMin = rangeEnd - rangeStart
  const HOUR_PX = 40
  const gridH = (totalMin / 60) * HOUR_PX
  const hours = Array.from({ length: 25 }, (_, i) => i * 60)

  // Position de scroll par défaut : ~8h (le nocturne reste accessible en remontant).
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 8 * HOUR_PX
  }, [])

  const colTemplate = '56px repeat(7, 1fr)'

  return (
    <div className="flex-1 min-h-0 overflow-x-auto">
      <div ref={scrollRef} className="min-w-[720px] h-full overflow-y-auto">
        {/* En-tête figé (jours + bande journée) */}
        <div className="sticky top-0 z-10 bg-surface">
          <div className="grid border-b border-gray-100" style={{ gridTemplateColumns: colTemplate }}>
            <div />
            {days.map((d) => {
              const isToday = startOfDay(d).getTime() === today
              return (
                <div key={d.toISOString()} className={`px-1 py-2 text-center border-l border-gray-100 ${isToday ? 'bg-accent/5' : ''}`}>
                  <div className="text-[11px] text-gray-400 capitalize">{dowFmt.format(d)}</div>
                  <div className={`text-sm font-semibold ${isToday ? 'text-accent' : 'text-gray-700'}`}>{dayNumFmt.format(d)}</div>
                </div>
              )
            })}
          </div>

          {/* Bande "journée entière" */}
          <div className="grid border-b border-gray-100 bg-gray-50" style={{ gridTemplateColumns: colTemplate }}>
            <div className="px-1 py-1 text-[10px] text-gray-400 text-right pr-2 flex items-center justify-end">{t('all_day')}</div>
            {days.map((d) => {
              const allDayBlocks = blocks.filter((b) => b.allDay && activeOn(b, d))
              return (
                <div key={d.toISOString()} className="border-l border-gray-100 p-1 space-y-0.5 min-h-[26px]">
                  {allDayBlocks.map((b) => (
                    <div
                      key={b.key}
                      {...clickProps(b, onOpenSchedule)}
                      className={`text-[10px] leading-tight px-1 py-0.5 rounded border truncate ${blockColor(b)} ${b.scheduleId !== undefined && onOpenSchedule ? 'cursor-pointer hover:ring-1 hover:ring-accent/50' : ''}`}
                      title={`${b.name}${b.detail ? ' · ' + b.detail : ''}`}
                    >
                      <BlockIcon b={b} />{b.name}
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        </div>

        {/* Grille horaire */}
        <div className="grid" style={{ gridTemplateColumns: colTemplate }}>
          {/* Colonne heures */}
          <div className="relative" style={{ height: gridH }}>
            {hours.map((h) => (
              <div key={h} className="absolute right-2 -translate-y-1/2 text-[10px] text-gray-400" style={{ top: ((h - rangeStart) / 60) * HOUR_PX }}>
                {fmtHM(h)}
              </div>
            ))}
          </div>
          {/* Colonnes jours */}
          {days.map((d) => {
            const isToday = startOfDay(d).getTime() === today
            const occs = occurrencesForDay(timed, d)
            const lanes = assignLanes(occs)
            return (
              <div key={d.toISOString()} className={`relative border-l border-gray-100 ${isToday ? 'bg-accent/5' : ''}`} style={{ height: gridH }}>
                {/* Lignes d'heures */}
                {hours.slice(0, -1).map((h) => (
                  <div key={h} className="absolute left-0 right-0 border-t border-gray-50" style={{ top: ((h - rangeStart) / 60) * HOUR_PX }} />
                ))}
                {/* Segments (fenetre nocturne = tete + queue) */}
                {occs.map((o, i) => {
                  const b = o.b
                  const top = ((o.startMin - rangeStart) / 60) * HOUR_PX
                  const height = Math.max(((o.endMin - o.startMin) / 60) * HOUR_PX - 1, 14)
                  const { lane, lanes: laneCount } = lanes[i]
                  const width = 100 / laneCount
                  // Libelle = fenetre logique complete (ex. 22:00–04:00), meme sur la queue.
                  const slot = `${fmtHM(b.startMin)}–${fmtHM(b.endMin)}`
                  return (
                    <div
                      key={o.key}
                      {...clickProps(b, onOpenSchedule)}
                      className={`absolute rounded border px-1 overflow-hidden ${blockColor(b)} ${b.scheduleId !== undefined && onOpenSchedule ? 'cursor-pointer hover:ring-1 hover:ring-accent/50' : ''}`}
                      style={{ top, height, left: `calc(${lane * width}% + 1px)`, width: `calc(${width}% - 2px)` }}
                      title={`${b.name}${b.detail ? ' · ' + b.detail : ''} (${slot})`}
                    >
                      <div className="text-[10px] font-medium leading-tight truncate">
                        <BlockIcon b={b} />{b.name}
                      </div>
                      {height > 26 && <div className="text-[9px] opacity-70 leading-tight">{slot}</div>}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Vue Mois (grille de jours) ───────────────────────────────────────────────
function MonthView({
  cursor, blocks, today, dayNumFmt, locale, onOpenSchedule,
}: {
  cursor: Date; blocks: Block[]; today: number
  dayNumFmt: Intl.DateTimeFormat
  locale: string
  onOpenSchedule?: (id: number) => void
}) {
  const monthStart = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const gridStart = startOfWeek(monthStart)
  // Nombre de semaines RÉELLEMENT nécessaires (4 à 6) : à 42 cellules figées, un
  // mois de 5 semaines afficherait une rangée vide qui vole de la hauteur aux autres.
  const monthEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0)
  // Math.round sur l'écart en jours : un changement d'heure (DST) dans le mois
  // décale les timestamps d'une heure et fausserait une division entière brute.
  const spanDays = Math.round((startOfDay(monthEnd).getTime() - gridStart.getTime()) / DAY_MS)
  const weeks = Math.floor(spanDays / 7) + 1
  const cells = Array.from({ length: weeks * 7 }, (_, i) => addDays(gridStart, i))
  const dowFmt = new Intl.DateTimeFormat(locale, { weekday: 'short' })
  const headDays = Array.from({ length: 7 }, (_, i) => addDays(gridStart, i))
  const timed = blocks.filter((b) => !b.allDay)

  return (
    <div className="flex-1 min-h-0 overflow-x-auto">
      {/* La grille occupe toute la hauteur disponible : en-tête figé + N rangées
          de hauteur égale, chaque jour défilant en interne si besoin. */}
      <div className="min-w-[680px] h-full flex flex-col">
        <div className="shrink-0 grid grid-cols-7 border-b border-gray-100">
          {headDays.map((d) => (
            <div key={d.toISOString()} className="px-2 py-1.5 text-center text-[11px] font-medium text-gray-400 capitalize border-l border-gray-100 first:border-l-0">
              {dowFmt.format(d)}
            </div>
          ))}
        </div>
        <div
          className="flex-1 min-h-0 grid grid-cols-7"
          style={{ gridTemplateRows: `repeat(${weeks}, minmax(0, 1fr))` }}
        >
          {cells.map((d) => {
            const inMonth = d.getMonth() === cursor.getMonth()
            const isToday = startOfDay(d).getTime() === today
            // Items du jour : journée entière + occurrences horaires (incl. queue nocturne).
            const dayItems = [
              ...blocks.filter((b) => b.allDay && activeOn(b, d)).map((b) => ({ b, key: b.key, startMin: 0, allDay: true })),
              ...occurrencesForDay(timed, d).map((o) => ({ b: o.b, key: o.key, startMin: o.startMin, allDay: false })),
            ].sort((a, z) => Number(z.allDay) - Number(a.allDay) || a.startMin - z.startMin)
            return (
              <div
                key={d.toISOString()}
                className={`min-h-0 flex flex-col border-l border-t border-gray-100 first:border-l-0 p-1 ${inMonth ? '' : 'bg-gray-50/60'}`}
              >
                <div className={`shrink-0 text-[11px] font-medium mb-1 ${isToday ? 'text-accent' : inMonth ? 'text-gray-600' : 'text-gray-300'}`}>
                  <span className={isToday ? 'inline-flex items-center justify-center w-5 h-5 rounded-full bg-accent text-white' : ''}>
                    {dayNumFmt.format(d)}
                  </span>
                </div>
                {/* Tous les items sont rendus : la case défile plutôt que de tronquer
                    à N chips + « +X autres » (invisibles et inatteignables). */}
                <div className="flex-1 min-h-0 overflow-y-auto space-y-0.5">
                  {dayItems.map((it) => {
                    const b = it.b
                    const clickable = b.scheduleId !== undefined && onOpenSchedule
                    return (
                      <div
                        key={it.key}
                        {...clickProps(b, onOpenSchedule)}
                        className={`text-[10px] leading-tight px-1 py-0.5 rounded border truncate ${blockColor(b)} ${clickable ? 'cursor-pointer hover:ring-1 hover:ring-accent/50' : ''}`}
                        title={`${b.name}${b.detail ? ' · ' + b.detail : ''}${b.allDay ? '' : ' (' + fmtHM(b.startMin) + '–' + fmtHM(b.endMin) + ')'}`}
                      >
                        <BlockIcon b={b} />
                        {!it.allDay && <span className="opacity-70 mr-0.5">{fmtHM(it.startMin)}</span>}
                        {b.name}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
