'use client'

import { useRef, useState } from 'react'
import { clsx } from 'clsx'
import { Upload, X, Lock } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { fireDemoToast } from '@/lib/demo'
import type { EventRead, MediaRead } from '@/types/api'

// Must stay in sync with backend _MIME_TO_TYPE (media.py)
const ACCEPTED =
  '.mp4,.mov,.webm,.avi,.mkv,' +
  '.jpg,.jpeg,.png,.gif,.webp,.svg,' +
  '.mp3,.aac,.wav,.ogg,.oga,.opus,.flac,.m4a,' +
  '.pdf,.ppt,.pptx,' +
  '.html,.zip'

const ALLOWED_MIME_PREFIXES = [
  'image/',
  'video/',
  'audio/',
  'application/pdf',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml',
  'text/html',
  'application/zip',
]

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

// Extensions autoritatives (identiques au repli backend media.py) — le MIME du
// navigateur est peu fiable pour .ogg/.opus/.flac (souvent application/ogg ou vide).
const ACCEPTED_EXTS = new Set(ACCEPTED.split(',').map((e) => e.trim().toLowerCase()))

function extOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

function isMimeAllowed(type: string): boolean {
  if (!type) return true
  return ALLOWED_MIME_PREFIXES.some((p) => type.startsWith(p))
}

// Accepte par EXTENSION (comme le backend) OU par préfixe MIME. Évite de rejeter à
// tort un .ogg annoncé application/ogg alors que le backend l'accepte.
function isFileAllowed(file: File): boolean {
  return ACCEPTED_EXTS.has(extOf(file.name)) || isMimeAllowed(file.type)
}

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

interface UploadItem {
  id: string
  file: File
  progress: number
  status: 'pending' | 'uploading' | 'done' | 'error'
  error?: string
}

interface MediaUploaderProps {
  onUploaded: (media: MediaRead) => void
}

export default function MediaUploader({ onUploaded }: MediaUploaderProps) {
  const t = useTranslations('media')
  const inputRef = useRef<HTMLInputElement>(null)
  const isDemo = useAuthStore((s) => s.user?.is_demo)
  const [dragging, setDragging] = useState(false)
  const [queue, setQueue] = useState<UploadItem[]>([])

  // Embargo state
  const [embargoEnabled, setEmbargoEnabled] = useState(false)
  const [embargoMode, setEmbargoMode] = useState<'manual' | 'event'>('manual')
  const [embargoDatetime, setEmbargoDatetime] = useState('')
  const [embargoTz, setEmbargoTz] = useState('Europe/Zurich')
  const [embargoEventId, setEmbargoEventId] = useState<number | null>(null)

  // Passthrough (§XVI.2) : conserver les vidéos/audio tels quels (sans ré-encodage)
  const [passthrough, setPassthrough] = useState(false)

  // Events with embargo (for event-linked mode)
  const { data: embargoEvents = [] } = useQuery<EventRead[]>({
    queryKey: ['events-with-embargo'],
    queryFn: () => api.get<EventRead[]>('/events').then((r) =>
      r.data.filter((e) => e.not_before_utc != null)
    ),
    enabled: embargoEnabled && embargoMode === 'event',
  })

  function generateId(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
    })
  }

  function addFiles(files: FileList | null) {
    if (!files) return
    const newItems: UploadItem[] = Array.from(files).map((file) => ({
      id: generateId(),
      file,
      progress: 0,
      status: 'pending',
    }))
    setQueue((q) => [...q, ...newItems])
    newItems.forEach((item) => startUpload(item.id, item.file))
  }

  function startUpload(id: string, file: File) {
    if (!isFileAllowed(file)) {
      setQueue((q) =>
        q.map((f) =>
          f.id === id ? { ...f, status: 'error', error: t('upload_type_rejected') } : f
        )
      )
      return
    }

    const form = new FormData()
    form.append('file', file)

    // Embargo
    if (embargoEnabled) {
      if (embargoMode === 'manual' && embargoDatetime) {
        const utc = localDtToUtc(embargoDatetime, embargoTz)
        if (utc) form.append('not_before_utc', utc)
      } else if (embargoMode === 'event' && embargoEventId) {
        form.append('embargo_event_id', String(embargoEventId))
      }
    }

    // Passthrough : conserver le fichier tel quel (vidéo/audio ; backend ignore pour les images)
    if (passthrough) form.append('encode_mode', 'passthrough')

    setQueue((q) => q.map((f) => (f.id === id ? { ...f, status: 'uploading' } : f)))

    api
      .post<MediaRead>('/media/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: ({ loaded, total }) => {
          const pct = total ? Math.round((loaded / total) * 100) : 0
          setQueue((q) => q.map((f) => (f.id === id ? { ...f, progress: pct } : f)))
        },
      })
      .then(({ data }) => {
        setQueue((q) =>
          q.map((f) => (f.id === id ? { ...f, status: 'done', progress: 100 } : f))
        )
        onUploaded(data)
      })
      .catch((err) => {
        const msg = err.response?.data?.detail ?? t('upload_error')
        setQueue((q) =>
          q.map((f) => (f.id === id ? { ...f, status: 'error', error: msg } : f))
        )
      })
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          if (isDemo) { fireDemoToast(); return }
          addFiles(e.dataTransfer.files)
        }}
        onClick={() => { if (isDemo) { fireDemoToast(); return } inputRef.current?.click() }}
        className={clsx(
          'flex flex-col items-center justify-center gap-2 py-8 rounded-lg border-2 border-dashed cursor-pointer transition-sf',
          dragging
            ? 'border-accent bg-accent/10 dark:bg-blue-500/15'
            : 'border-gray-200 hover:border-accent hover:bg-gray-50'
        )}
      >
        <Upload className="w-7 h-7 text-gray-300" />
        <p className="text-sm font-medium text-gray-600">{t('upload_drag')}</p>
        <p className="text-xs text-gray-400 text-center px-4">{t('upload_hint')}</p>
        <Button variant="secondary" size="sm" type="button">
          {t('upload_browse')}
        </Button>
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED}
        className="hidden"
        onChange={(e) => addFiles(e.target.files)}
      />

      {/* Passthrough (§XVI.2) : conserver les vidéos tel quel */}
      <label className="flex items-start gap-2 cursor-pointer select-none border border-gray-200 rounded-lg p-3">
        <input
          type="checkbox"
          checked={passthrough}
          onChange={(e) => setPassthrough(e.target.checked)}
          className="accent-accent w-4 h-4 mt-0.5"
        />
        <span>
          <span className="text-xs font-medium text-gray-700">{t('upload_passthrough')}</span>
          <span className="block text-xs text-gray-400">{t('upload_passthrough_hint')}</span>
        </span>
      </label>

      {/* Embargo section */}
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
            {/* Mode selector */}
            <div className="flex gap-4">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="embargoMode"
                  checked={embargoMode === 'manual'}
                  onChange={() => { setEmbargoMode('manual'); setEmbargoEventId(null) }}
                  className="accent-accent w-3.5 h-3.5"
                />
                <span className="text-xs text-gray-700">{t('embargo_manual')}</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="embargoMode"
                  checked={embargoMode === 'event'}
                  onChange={() => { setEmbargoMode('event'); setEmbargoDatetime('') }}
                  className="accent-accent w-3.5 h-3.5"
                />
                <span className="text-xs text-gray-700">{t('embargo_linked_event')}</span>
              </label>
            </div>

            {/* Manual mode */}
            {embargoMode === 'manual' && (
              <div className="space-y-1.5">
                <div className="flex gap-2">
                  <input
                    type="datetime-local"
                    value={embargoDatetime}
                    onChange={(e) => { if (isDemo) { fireDemoToast(); return } setEmbargoDatetime(e.target.value) }}
                    className="flex-1 border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                  <select
                    value={embargoTz}
                    onChange={(e) => setEmbargoTz(e.target.value)}
                    className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                  >
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

            {/* Event-linked mode */}
            {embargoMode === 'event' && (
              <div>
                <select
                  value={embargoEventId ?? ''}
                  onChange={(e) => { if (isDemo) { fireDemoToast(); return } setEmbargoEventId(e.target.value ? Number(e.target.value) : null) }}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                >
                  <option value="">{t('embargo_select_event')}</option>
                  {embargoEvents.map((ev) => (
                    <option key={ev.id_event} value={ev.id_event}>
                      {ev.event_name} — {ev.not_before_utc ? new Date(ev.not_before_utc).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }) : ''} UTC
                    </option>
                  ))}
                </select>
                {embargoEvents.length === 0 && (
                  <p className="text-[10px] text-orange-500 mt-1">{t('embargo_no_events')}</p>
                )}
              </div>
            )}

            <p className="text-[10px] text-orange-600 dark:text-orange-300">{t('embargo_hint_media')}</p>
          </div>
        )}
      </div>

      {queue.length > 0 && (
        <div className="space-y-2">
          {queue.some((f) => f.status === 'done' || f.status === 'error') && (
            <div className="flex items-center justify-end">
              <button
                type="button"
                onClick={() => setQueue((q) => q.filter((f) => f.status === 'uploading' || f.status === 'pending'))}
                className="text-[11px] text-accent hover:underline"
              >
                {t('upload_clear_finished')}
              </button>
            </div>
          )}
          {queue.map((item) => (
            <div
              key={item.id}
              className="flex items-center gap-3 bg-surface rounded-lg border border-gray-200 p-3 shadow-sf-card"
            >
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-gray-800 truncate">{item.file.name}</p>
                {item.status === 'uploading' && (
                  <div className="mt-1.5 h-1 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent transition-all duration-150 rounded-full"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                )}
                {item.status === 'error' && (
                  <p className="text-xs text-danger mt-0.5">{item.error}</p>
                )}
              </div>
              <span
                className={clsx(
                  'text-xs shrink-0',
                  item.status === 'done'
                    ? 'text-success'
                    : item.status === 'error'
                    ? 'text-danger'
                    : 'text-gray-400'
                )}
              >
                {item.status === 'uploading'
                  ? `${item.progress}%`
                  : item.status === 'done'
                  ? '✓'
                  : item.status === 'error'
                  ? '✗'
                  : '…'}
              </span>
              <button
                onClick={() => setQueue((q) => q.filter((f) => f.id !== item.id))}
                className="text-gray-300 hover:text-gray-600 transition-sf shrink-0"
                aria-label="Remove"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
