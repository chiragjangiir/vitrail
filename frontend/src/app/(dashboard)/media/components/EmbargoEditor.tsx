'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Lock } from 'lucide-react'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import type { EventRead, MediaListItem } from '@/types/api'

const EMBARGO_TIMEZONES = [
  { value: 'UTC',                 label: 'UTC' },
  { value: 'Europe/Zurich',       label: 'Europe/Zurich (Geneva)' },
  { value: 'Europe/Paris',        label: 'Europe/Paris' },
  { value: 'Europe/London',       label: 'Europe/London' },
  { value: 'Europe/Berlin',       label: 'Europe/Berlin' },
  { value: 'America/New_York',    label: 'America/New_York (ET)' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles (PT)' },
  { value: 'America/Sao_Paulo',   label: 'America/Sao_Paulo' },
  { value: 'Asia/Dubai',          label: 'Asia/Dubai' },
  { value: 'Asia/Singapore',      label: 'Asia/Singapore' },
  { value: 'Asia/Tokyo',          label: 'Asia/Tokyo' },
  { value: 'Australia/Sydney',    label: 'Australia/Sydney' },
]

function localDtToUtc(localDtStr: string, tz: string): string | null {
  if (!localDtStr) return null
  try {
    const naive = new Date(localDtStr + ':00Z')
    const fmt = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    })
    const p = fmt.formatToParts(naive).reduce((a, x) => ({ ...a, [x.type]: x.value }), {} as Record<string, string>)
    const h = p.hour === '24' ? '00' : p.hour
    const tzAsUtc = new Date(`${p.year}-${p.month}-${p.day}T${h}:${p.minute}:${p.second}Z`)
    return new Date(naive.getTime() + (naive.getTime() - tzAsUtc.getTime())).toISOString()
  } catch { return null }
}

function utcToLocalDt(utcStr: string | null | undefined, tz: string): string {
  if (!utcStr) return ''
  try {
    const d = new Date(utcStr)
    const fmt = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
    const p = fmt.formatToParts(d).reduce((a, x) => ({ ...a, [x.type]: x.value }), {} as Record<string, string>)
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
  } catch { return '' }
}

interface EmbargoEditorProps {
  item: MediaListItem
  isPending: boolean
  onSave: (not_before_utc: string | null, embargo_event_id: number | null) => void
  onCancel: () => void
}

export default function EmbargoEditor({ item, isPending, onSave, onCancel }: EmbargoEditorProps) {
  const t = useTranslations('media')
  const [embargoTz, setEmbargoTz] = useState('Europe/Zurich')

  const hasExistingEmbargo = !!(item.not_before_utc || item.embargo_event_id)
  const [embargoEnabled, setEmbargoEnabled] = useState(hasExistingEmbargo)
  const [embargoMode, setEmbargoMode] = useState<'manual' | 'event'>(
    item.embargo_event_id ? 'event' : 'manual'
  )
  const [embargoDatetime, setEmbargoDatetime] = useState(
    item.embargo_event_id ? '' : utcToLocalDt(item.not_before_utc, embargoTz)
  )
  const [embargoEventId, setEmbargoEventId] = useState<number | null>(item.embargo_event_id ?? null)

  const { data: embargoEvents = [] } = useQuery<EventRead[]>({
    queryKey: ['events-with-embargo'],
    queryFn: () => api.get<EventRead[]>('/events').then((r) =>
      r.data.filter((e) => e.not_before_utc != null)
    ),
    enabled: embargoMode === 'event',
  })

  function handleSave() {
    if (!embargoEnabled) {
      onSave(null, null)
      return
    }
    if (embargoMode === 'manual') {
      onSave(localDtToUtc(embargoDatetime, embargoTz), null)
    } else {
      onSave(null, embargoEventId)
    }
  }

  return (
    // data-write-perm : les champs (cases, dates, selects) sont auto-bloqués pour
    // un rôle sans media:edit ; le bouton Enregistrer est marqué data-write-action.
    <div className="space-y-4" data-write-perm="media:edit">
      <div className="text-sm text-gray-600 bg-gray-50 rounded-lg px-3 py-2 truncate">
        {item.media_name}
      </div>

      <div className="border border-orange-200 dark:border-orange-500/30 rounded-lg p-3 space-y-3 bg-orange-50/40">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={embargoEnabled}
            onChange={(e) => {
              setEmbargoEnabled(e.target.checked)
              if (!e.target.checked) { setEmbargoDatetime(''); setEmbargoEventId(null) }
            }}
            className="accent-accent w-4 h-4"
          />
          <Lock className="w-3.5 h-3.5 text-orange-600 dark:text-orange-300" />
          <span className="text-xs font-medium text-gray-700">{t('embargo_label')}</span>
        </label>

        {embargoEnabled && (
          <div className="pl-4 space-y-2">
            <div className="flex gap-4">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="eMode" checked={embargoMode === 'manual'}
                  onChange={() => { setEmbargoMode('manual'); setEmbargoEventId(null) }}
                  className="accent-accent w-3.5 h-3.5" />
                <span className="text-xs text-gray-700">{t('embargo_manual')}</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="eMode" checked={embargoMode === 'event'}
                  onChange={() => { setEmbargoMode('event'); setEmbargoDatetime('') }}
                  className="accent-accent w-3.5 h-3.5" />
                <span className="text-xs text-gray-700">{t('embargo_linked_event')}</span>
              </label>
            </div>

            {embargoMode === 'manual' && (
              <div className="space-y-1.5">
                <div className="flex gap-2">
                  <input type="datetime-local" value={embargoDatetime}
                    onChange={(e) => setEmbargoDatetime(e.target.value)}
                    className="flex-1 border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
                  <select value={embargoTz} onChange={(e) => setEmbargoTz(e.target.value)}
                    className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface">
                    {EMBARGO_TIMEZONES.map(({ value, label }) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </div>
                {embargoDatetime && (
                  <p className="text-[10px] text-gray-400 font-mono">
                    = {localDtToUtc(embargoDatetime, embargoTz)?.slice(0, 16).replace('T', ' ') ?? '—'} UTC
                  </p>
                )}
              </div>
            )}

            {embargoMode === 'event' && (
              <div>
                <select value={embargoEventId ?? ''}
                  onChange={(e) => setEmbargoEventId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface">
                  <option value="">{t('embargo_select_event')}</option>
                  {embargoEvents.map((ev) => (
                    <option key={ev.id_event} value={ev.id_event}>
                      {ev.event_name} — {ev.not_before_utc
                        ? new Date(ev.not_before_utc).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
                        : ''} UTC
                    </option>
                  ))}
                </select>
                {embargoMode === 'event' && embargoEvents.length === 0 && (
                  <p className="text-[10px] text-orange-500 mt-1">{t('embargo_no_events')}</p>
                )}
                {embargoEventId && embargoEvents.find((e) => e.id_event === embargoEventId)?.not_before_utc && (
                  <p className="text-[10px] text-gray-400 font-mono mt-1">
                    → {new Date(embargoEvents.find((e) => e.id_event === embargoEventId)!.not_before_utc!).toISOString().slice(0, 16).replace('T', ' ')} UTC
                  </p>
                )}
              </div>
            )}

            <p className="text-[10px] text-orange-600 dark:text-orange-300">{t('embargo_hint_media')}</p>
          </div>
        )}
      </div>

      <div className="flex gap-2 pt-1">
        <Button data-write-action onClick={handleSave} disabled={isPending} className="flex-1">
          {isPending ? t('saving') : t('save_embargo')}
        </Button>
        <Button variant="ghost" onClick={onCancel}>{t('cancel')}</Button>
      </div>
    </div>
  )
}
