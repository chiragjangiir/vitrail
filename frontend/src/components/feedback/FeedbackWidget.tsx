'use client'

/**
 * Widget de retour utilisateur (§ retours UI).
 *
 * Bouton flottant (toutes les pages dashboard) → panneau : type (bug/suggestion/amélioration/
 * ux/question), gravité (si bug), description. À l'envoi, auto-capture du contexte (URL, route,
 * user-agent, version, dernières erreurs JS) → POST /feedback. Le triage IA est fait côté
 * serveur (worker). Stocké en base, exploitable par le super-admin (et l'assistant de dev).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { MessageSquarePlus, X, Send, Check, Maximize2, Minimize2, ImagePlus } from 'lucide-react'
import { getRecentErrors, installErrorBuffer } from '@/lib/errorBuffer'
import { useWidgetPanels } from '@/store/widgets'

const API_BASE = `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/api/v1`
const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? '0.1.0'
const MAX_SCREENSHOTS = 8

type FeedbackType = 'bug' | 'suggestion' | 'amelioration' | 'ux' | 'question'

interface Screenshot {
  key: string
  previewUrl: string
}

const TYPES: { key: FeedbackType; emoji: string }[] = [
  { key: 'bug', emoji: '🐞' },
  { key: 'suggestion', emoji: '💡' },
  { key: 'amelioration', emoji: '✨' },
  { key: 'ux', emoji: '🎨' },
  { key: 'question', emoji: '❓' },
]

export default function FeedbackWidget() {
  const t = useTranslations('feedback')
  const pathname = usePathname()

  // État ouvert/fermé partagé avec le bouton déclencheur de la TOPBAR (store dédié).
  const open = useWidgetPanels((s) => s.feedbackOpen)
  const setOpen = useWidgetPanels((s) => s.setFeedback)
  const [expanded, setExpanded] = useState(false)
  const [type, setType] = useState<FeedbackType>('bug')
  const [severity, setSeverity] = useState(2)
  const [description, setDescription] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState(false)
  const [screenshots, setScreenshots] = useState<Screenshot[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { installErrorBuffer() }, [])

  // Taille agrandie : choix persisté (localStorage).
  useEffect(() => {
    if (typeof window !== 'undefined') setExpanded(localStorage.getItem('sf_feedback_expanded') === '1')
  }, [])
  const toggleExpanded = useCallback(() => {
    setExpanded((v) => {
      const next = !v
      try { localStorage.setItem('sf_feedback_expanded', next ? '1' : '0') } catch { /* non bloquant */ }
      return next
    })
  }, [])

  // Réinitialise le formulaire à chaque ouverture (et libère les aperçus précédents).
  useEffect(() => {
    if (open) {
      setType('bug'); setSeverity(2); setDescription(''); setSent(false); setError(false)
      setScreenshots((prev) => { prev.forEach((s) => URL.revokeObjectURL(s.previewUrl)); return [] })
      setUploading(false)
    }
  }, [open])

  // Upload manuel d'images (clic / glisser-déposer / coller) → MinIO → on retient la clé.
  const addFiles = useCallback(async (files: File[]) => {
    const images = files.filter((f) => f.type.startsWith('image/'))
    if (images.length === 0) return
    const token = typeof window !== 'undefined' ? localStorage.getItem('sf_access_token') : null
    setUploading(true)
    try {
      for (const file of images) {
        let room = 0
        setScreenshots((prev) => { room = MAX_SCREENSHOTS - prev.length; return prev })
        if (room <= 0) break
        const form = new FormData()
        form.append('file', file)
        try {
          const res = await fetch(`${API_BASE}/feedback/screenshot`, {
            method: 'POST',
            headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
            body: form,
          })
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const { key } = await res.json()
          setScreenshots((prev) =>
            prev.length >= MAX_SCREENSHOTS ? prev : [...prev, { key, previewUrl: URL.createObjectURL(file) }],
          )
        } catch {
          setError(true)
        }
      }
    } finally {
      setUploading(false)
    }
  }, [])

  const removeScreenshot = useCallback((key: string) => {
    setScreenshots((prev) => {
      const gone = prev.find((s) => s.key === key)
      if (gone) URL.revokeObjectURL(gone.previewUrl)
      return prev.filter((s) => s.key !== key)
    })
  }, [])

  const submit = useCallback(async () => {
    if (!description.trim() || sending) return
    setSending(true)
    setError(false)
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('sf_access_token') : null
      const res = await fetch(`${API_BASE}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          feedback_type: type,
          description: description.trim(),
          severity: type === 'bug' ? severity : null,
          page_url: typeof window !== 'undefined' ? window.location.href : null,
          route: pathname,
          user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : null,
          app_version: APP_VERSION,
          console_errors: getRecentErrors(),
          screenshot_keys: screenshots.map((s) => s.key),
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSent(true)
      setTimeout(() => setOpen(false), 1600)
    } catch {
      setError(true)
    } finally {
      setSending(false)
    }
  }, [description, sending, type, severity, pathname, screenshots])

  return (
    <>
      {/* Déclencheur = bouton de la TOPBAR (plus de FAB flottant, cf. store widgets). */}
      {open && (
        <div
          className={`fixed bottom-20 right-5 z-50 flex max-h-[calc(100vh-6rem)] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-xl border border-gray-200 bg-surface shadow-2xl ${
            expanded ? 'w-[640px]' : 'w-[380px]'
          }`}
        >
          <div className="flex items-center justify-between border-b border-gray-100 bg-sidebar px-4 py-3 text-white">
            <div className="flex items-center gap-2">
              <MessageSquarePlus className="h-4 w-4" />
              <span className="text-sm font-semibold">{t('title')}</span>
            </div>
            <div className="flex items-center gap-1">
              <button type="button" onClick={toggleExpanded} aria-label={expanded ? t('shrink') : t('expand')}
                title={expanded ? t('shrink') : t('expand')}
                className="rounded p-1 transition-colors hover:bg-white/10">
                {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>
              <button type="button" onClick={() => setOpen(false)} aria-label={t('close')}
                className="rounded p-1 transition-colors hover:bg-white/10">
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {sent ? (
            <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
              <Check className="h-8 w-8 text-green-600 dark:text-green-300" />
              <p className="text-sm text-gray-700">{t('sent')}</p>
            </div>
          ) : (
            <div
              className="space-y-3 overflow-y-auto px-4 py-3"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); addFiles(Array.from(e.dataTransfer.files)) }}
            >
              <p className="text-xs text-gray-500">{t('intro')}</p>

              <div className="flex flex-wrap gap-1.5">
                {TYPES.map((ty) => (
                  <button
                    key={ty.key}
                    type="button"
                    onClick={() => setType(ty.key)}
                    className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                      type === ty.key ? 'bg-accent text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                  >
                    {ty.emoji} {t(`type_${ty.key}`)}
                  </button>
                ))}
              </div>

              {type === 'bug' && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">{t('severity_label')}</span>
                  {[1, 2, 3].map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setSeverity(s)}
                      className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
                        severity === s ? 'bg-accent text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {t(`sev_${s}`)}
                    </button>
                  ))}
                </div>
              )}

              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                onPaste={(e) => {
                  const imgs = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith('image/'))
                  if (imgs.length) { e.preventDefault(); addFiles(imgs) }
                }}
                placeholder={t('placeholder')}
                rows={expanded ? 12 : 4}
                className="w-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-accent focus:outline-none"
              />

              {/* Captures jointes (clic / glisser-déposer / coller). */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-600">{t('screenshots')}</span>
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading || screenshots.length >= MAX_SCREENSHOTS}
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-2 py-1 text-xs text-gray-600 transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
                  >
                    <ImagePlus className="h-3.5 w-3.5" /> {uploading ? t('uploading') : t('add_screenshot')}
                  </button>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = '' }}
                />
                {screenshots.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {screenshots.map((s) => (
                      <div key={s.key} className="group relative h-16 w-16 overflow-hidden rounded-lg border border-gray-200">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={s.previewUrl} alt="" className="h-full w-full object-cover" />
                        <button
                          type="button"
                          onClick={() => removeScreenshot(s.key)}
                          aria-label={t('remove_screenshot')}
                          className="absolute right-0.5 top-0.5 rounded-full bg-black/60 p-0.5 text-white opacity-0 transition-opacity group-hover:opacity-100"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-[11px] text-gray-400">{t('screenshot_hint')}</p>
              </div>

              {error && <p className="text-xs text-danger">{t('error')}</p>}

              <button
                type="button"
                onClick={submit}
                disabled={sending || uploading || !description.trim()}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
              >
                <Send className="h-4 w-4" /> {sending ? t('sending') : t('submit')}
              </button>
            </div>
          )}
        </div>
      )}
    </>
  )
}
