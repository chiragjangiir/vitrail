'use client'

/**
 * AI Assistant (§XXVII) — widget flottant + drawer de chat SSE.
 *
 * Bouton fixe en bas à droite (toutes les pages dashboard) + raccourci Ctrl+Shift+A.
 * Le drawer streame la réponse de `POST /api/v1/assistant/chat` (Server-Sent Events) :
 * chaque trame `data: {delta}` est ajoutée au message assistant en cours, `data: {done}`
 * clôt l'échange (session_id mémorisé pour la continuité). La réponse est forcée dans la
 * locale de l'utilisateur (gérée côté serveur). Suggestions contextuelles selon la page.
 */

import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useLocale, useTranslations } from 'next-intl'
import { useQueryClient } from '@tanstack/react-query'
import { Sparkles, X, Send, Check, Ban, Mic, Maximize2, Minimize2 } from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { useWidgetPanels } from '@/store/widgets'
import { fireDemoToast } from '@/lib/demo'

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

type ProposalStatus = 'pending' | 'running' | 'done' | 'error' | 'cancelled'

interface ProposalStep {
  description: string
  warnings: string[]
}

interface Proposal {
  token: string
  steps: ProposalStep[]
  status: ProposalStatus
  result?: string
  /** Indice du message (bulle assistant) du tour qui a produit cette proposition →
   *  ancre la carte juste après ce message dans la timeline (ordre chronologique). */
  afterMessageIndex: number
}

const API_BASE = `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/api/v1`

/* ── Dictée vocale (Web Speech API navigateur — transcription locale, 0 infra) ──
 * Types minimaux (l'API n'est pas dans le lib DOM standard) + détection de support
 * (Chrome/Edge OK, Firefox limité → bouton masqué si absent). La langue suit la locale. */
interface SpeechRecognitionResultLike {
  isFinal: boolean
  0: { transcript: string }
}
interface SpeechRecognitionEventLike {
  resultIndex: number
  results: { length: number; [i: number]: SpeechRecognitionResultLike }
}
interface SpeechRecognitionLike {
  lang: string
  interimResults: boolean
  continuous: boolean
  start: () => void
  stop: () => void
  onresult: ((e: SpeechRecognitionEventLike) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

/** Langues de dictée proposées (étiquettes BCP-47 attendues par SpeechRecognition). */
const DICTATION_LANGS: { code: string; label: string }[] = [
  { code: 'fr-FR', label: 'Français' },
  { code: 'en-US', label: 'English (US)' },
  { code: 'en-GB', label: 'English (UK)' },
  { code: 'es-ES', label: 'Español' },
  { code: 'de-DE', label: 'Deutsch' },
  { code: 'it-IT', label: 'Italiano' },
  { code: 'pt-PT', label: 'Português' },
  { code: 'pt-BR', label: 'Português (BR)' },
  { code: 'nl-NL', label: 'Nederlands' },
]

/** Meilleure langue de dictée par défaut : ce que l'utilisateur PARLE (langues du
 * navigateur/OS) prime sur la locale de l'UI Vitrail (souvent laissée à l'anglais). */
function defaultDictationLang(uiLocale: string): string {
  const codes = DICTATION_LANGS.map((l) => l.code)
  const prefs: string[] = []
  if (typeof navigator !== 'undefined') {
    if (Array.isArray(navigator.languages)) prefs.push(...navigator.languages)
    if (navigator.language) prefs.push(navigator.language)
  }
  if (uiLocale) prefs.push(uiLocale)
  for (const p of prefs) {
    const exact = codes.find((c) => c.toLowerCase() === p.toLowerCase())
    if (exact) return exact
    const byPrefix = codes.find((c) => c.slice(0, 2) === p.slice(0, 2).toLowerCase())
    if (byPrefix) return byPrefix
  }
  return 'en-US'
}

/** Suggestions par préfixe de page (clés i18n dans le namespace `assistant.suggestions`). */
function suggestionKeys(pathname: string): string[] {
  if (pathname.startsWith('/players')) return ['players_online', 'enroll_player']
  if (pathname.startsWith('/media')) return ['import_media', 'feeds']
  if (pathname.startsWith('/playlists')) return ['create_playlist', 'import_media']
  if (pathname.startsWith('/schedules')) return ['active_schedules', 'spot']
  return ['players_online', 'getting_started']
}

export default function AIAssistantWidget() {
  const t = useTranslations('assistant')
  const locale = useLocale()
  const pathname = usePathname()
  const queryClient = useQueryClient()
  const isDemo = useAuthStore((s) => s.user?.is_demo)  // masqué pour un compte démo (§II)

  // État ouvert/fermé partagé avec le bouton déclencheur de la TOPBAR (store dédié).
  const open = useWidgetPanels((s) => s.assistantOpen)
  const setOpen = useWidgetPanels((s) => s.setAssistant)
  const toggleOpen = useWidgetPanels((s) => s.toggleAssistant)
  const [expanded, setExpanded] = useState(false)
  const [messages, setMessages] = useState<Msg[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [listening, setListening] = useState(false)
  const [micSupported, setMicSupported] = useState(false)
  const [dictationLang, setDictationLang] = useState('en-US')
  const sessionRef = useRef<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)

  useEffect(() => {
    setMicSupported(getSpeechRecognitionCtor() !== null)
  }, [])

  // Taille agrandie : choix persisté (localStorage).
  useEffect(() => {
    if (typeof window !== 'undefined') setExpanded(localStorage.getItem('sf_assistant_expanded') === '1')
  }, [])
  const toggleExpanded = useCallback(() => {
    setExpanded((v) => {
      const next = !v
      try { localStorage.setItem('sf_assistant_expanded', next ? '1' : '0') } catch { /* non bloquant */ }
      return next
    })
  }, [])

  // Langue de dictée : choix sauvegardé sinon meilleur défaut (langue du navigateur).
  useEffect(() => {
    const saved =
      typeof window !== 'undefined' ? localStorage.getItem('sf_dictation_lang') : null
    setDictationLang(saved || defaultDictationLang(locale))
  }, [locale])

  // Raccourci clavier Ctrl+Shift+A
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && (e.key === 'A' || e.key === 'a')) {
        e.preventDefault()
        toggleOpen()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, proposals, open])

  const send = useCallback(
    async (text: string) => {
      const question = text.trim()
      if (!question || streaming) return
      recognitionRef.current?.stop()
      const history: Msg[] = [...messages, { role: 'user', content: question }]
      setMessages([...history, { role: 'assistant', content: '' }])
      setInput('')
      setStreaming(true)

      try {
        const token = typeof window !== 'undefined' ? localStorage.getItem('sf_access_token') : null
        const res = await fetch(`${API_BASE}/assistant/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            messages: history,
            page_context: { page: pathname },
            locale,
            session_id: sessionRef.current,
          }),
        })
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const blocks = buffer.split('\n\n')
          buffer = blocks.pop() ?? ''
          for (const block of blocks) {
            const line = block.trim()
            if (!line.startsWith('data:')) continue
            const payload = JSON.parse(line.slice(5).trim())
            if (payload.delta) {
              setMessages((prev) => {
                const next = [...prev]
                next[next.length - 1] = {
                  role: 'assistant',
                  content: next[next.length - 1].content + payload.delta,
                }
                return next
              })
            }
            if (payload.action) {
              // Ancre la carte au message assistant de CE tour (index = history.length,
              // car setMessages a posé la bulle assistant juste après l'historique).
              setProposals((prev) => [
                ...prev,
                { ...payload.action, status: 'pending', afterMessageIndex: history.length },
              ])
            }
            if (payload.done && payload.quota_exceeded) {
              setMessages((prev) => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: t('quota_exceeded') }
                return next
              })
            }
            if (payload.done && payload.session_id) sessionRef.current = payload.session_id
          }
        }
      } catch {
        setMessages((prev) => {
          const next = [...prev]
          next[next.length - 1] = { role: 'assistant', content: t('error') }
          return next
        })
      } finally {
        setStreaming(false)
      }
    },
    [messages, streaming, pathname, locale, t],
  )

  const setProposalAt = useCallback((idx: number, patch: Partial<Proposal>) => {
    setProposals((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)))
  }, [])

  const confirmAction = useCallback(
    async (idx: number, token: string) => {
      setProposalAt(idx, { status: 'running' })
      try {
        const tk = typeof window !== 'undefined' ? localStorage.getItem('sf_access_token') : null
        const res = await fetch(`${API_BASE}/assistant/action/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(tk ? { Authorization: `Bearer ${tk}` } : {}) },
          body: JSON.stringify({ token }),
        })
        const data = await res.json()
        if (data.ok) {
          setProposalAt(idx, { status: 'done', result: data.message })
          // L'action a modifié des données serveur (playlist, feed, panier audio…) : on
          // invalide le cache React Query pour que la page courante se rafraîchisse sans F5.
          queryClient.invalidateQueries()
        } else {
          setProposalAt(idx, { status: 'error', result: data.error || t('error') })
        }
      } catch {
        setProposalAt(idx, { status: 'error', result: t('error') })
      }
    },
    [setProposalAt, t, queryClient],
  )

  // Dictée : démarre/arrête la reconnaissance vocale ; le texte transcrit remplit l'input
  // (l'utilisateur relit puis envoie → le flux chat/batch existant prend le relais).
  const toggleMic = useCallback(() => {
    if (listening) {
      recognitionRef.current?.stop()
      return
    }
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) return
    const rec = new Ctor()
    rec.lang = dictationLang
    rec.interimResults = true
    rec.continuous = false
    let base = input.trim()
    rec.onresult = (e) => {
      let finalText = ''
      let interim = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i]
        const txt = r[0]?.transcript ?? ''
        if (r.isFinal) finalText += txt
        else interim += txt
      }
      if (finalText) base = `${base} ${finalText}`.trim()
      setInput(`${base} ${interim}`.trim())
    }
    rec.onend = () => {
      setListening(false)
      recognitionRef.current = null
    }
    rec.onerror = () => setListening(false)
    recognitionRef.current = rec
    try {
      rec.start()
      setListening(true)
    } catch {
      setListening(false)
    }
  }, [listening, dictationLang, input])

  // Coupe la dictée si le drawer se ferme.
  useEffect(() => {
    if (!open && recognitionRef.current) recognitionRef.current.stop()
  }, [open])

  // Carte de proposition d'action (une par tour, listant ses étapes → une seule
  // confirmation → exécution avec publish différé côté serveur). `idx` = position dans
  // `proposals` (nécessaire pour confirmAction/setProposalAt).
  const renderProposal = (p: Proposal, idx: number) => (
    <div key={`prop-${idx}`} className="rounded-xl border border-accent/30 bg-accent/5 p-3 text-sm">
      {p.steps.length > 1 ? (
        <ol className="list-decimal space-y-1 pl-5 text-gray-800">
          {p.steps.map((s, si) => (
            <li key={si}>
              <span className="font-medium">{s.description}</span>
              {s.warnings?.map((w, wi) => (
                <span key={wi} className="mt-0.5 block text-xs text-amber-700 dark:text-amber-300">⚠️ {w}</span>
              ))}
            </li>
          ))}
        </ol>
      ) : (
        <>
          <p className="font-medium text-gray-800">{p.steps[0]?.description}</p>
          {p.steps[0]?.warnings?.map((w, wi) => (
            <p key={wi} className="mt-1 text-xs text-amber-700 dark:text-amber-300">⚠️ {w}</p>
          ))}
        </>
      )}
      {p.status === 'pending' && (
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={() => confirmAction(idx, p.token)}
            className="flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent/90"
          >
            <Check className="h-3.5 w-3.5" /> {t('action_confirm')}
          </button>
          <button
            type="button"
            onClick={() => setProposalAt(idx, { status: 'cancelled' })}
            className="flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-100"
          >
            <Ban className="h-3.5 w-3.5" /> {t('action_cancel')}
          </button>
        </div>
      )}
      {p.status === 'running' && <p className="mt-2 text-xs text-gray-500">{t('action_running')}</p>}
      {p.status === 'done' && (
        <p className="mt-2 text-xs font-medium text-green-700 dark:text-green-300">✓ {p.result || t('action_done')}</p>
      )}
      {p.status === 'error' && (
        <p className="mt-2 text-xs font-medium text-red-600 dark:text-red-300">{p.result || t('error')}</p>
      )}
      {p.status === 'cancelled' && <p className="mt-2 text-xs text-gray-400">{t('action_cancelled')}</p>}
    </div>
  )

  // Compte DÉMO : vitrine STATIQUE de l'assistant (demande Ed 10/07) — le bouton reste
  // visible et le panneau présente la feature (fausse conversation, capacités, exemples)
  // sans AUCUN appel LLM (zéro jeton). Les exemples cliqués → toast « compte démo ».
  if (isDemo) {
    return (
      <>
        {/* Déclencheur = bouton de la TOPBAR (plus de FAB flottant). */}
        {open && (
          <div className="fixed bottom-20 right-5 z-50 flex h-[560px] w-[420px] max-h-[calc(100vh-6rem)] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-xl border border-gray-200 bg-surface shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-100 bg-sidebar px-4 py-3 text-white">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4" />
                <span className="text-sm font-semibold">{t('title')}</span>
                <span className="rounded bg-amber-500/90 px-1.5 py-0.5 text-[10px] font-medium">
                  {t('demo_badge')}
                </span>
              </div>
              <button type="button" onClick={() => setOpen(false)} aria-label={t('close')}
                      className="rounded p-1 transition-colors hover:bg-white/10">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
              <p className="text-sm text-gray-500">{t('demo_intro')}</p>

              {/* Aperçu d'une conversation (statique) */}
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-3 py-2 text-sm text-white">
                  {t('demo_sample_q')}
                </div>
              </div>
              <div className="flex justify-start">
                <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-gray-100 px-3 py-2 text-sm text-gray-800">
                  {t('demo_sample_a')}
                </div>
              </div>

              {/* Capacités */}
              <div className="space-y-1.5 rounded-lg border border-gray-200 p-3">
                <p className="text-xs font-medium text-gray-500">{t('demo_caps_title')}</p>
                {(['demo_caps_1', 'demo_caps_2', 'demo_caps_3', 'demo_caps_4'] as const).map((k) => (
                  <p key={k} className="flex gap-1.5 text-xs text-gray-600">
                    <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-accent" />{t(k)}
                  </p>
                ))}
              </div>

              {/* Exemples (cliquer = toast compte démo) */}
              <div className="flex flex-col gap-2">
                {(['demo_ex_1', 'demo_ex_2', 'demo_ex_3'] as const).map((k) => (
                  <button key={k} type="button" onClick={fireDemoToast}
                          className="rounded-lg border border-gray-200 px-3 py-2 text-left text-sm text-gray-700 transition-colors hover:border-accent hover:bg-accent/5">
                    {t(k)}
                  </button>
                ))}
              </div>

              <p className="text-[11px] text-gray-400">{t('demo_note')}</p>
            </div>

            <div className="flex items-center gap-2 border-t border-gray-100 px-3 py-3">
              <input disabled placeholder={t('demo_placeholder')}
                     className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm opacity-60" />
            </div>
          </div>
        )}
      </>
    )
  }

  return (
    <>
      {/* Déclencheur = bouton de la TOPBAR (plus de FAB flottant, cf. store widgets). */}
      {open && (
        <div
          className={`fixed bottom-20 right-5 z-50 flex max-h-[calc(100vh-6rem)] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-xl border border-gray-200 bg-surface shadow-2xl ${
            expanded ? 'h-[85vh] w-[720px]' : 'h-[560px] w-[420px]'
          }`}
        >
          {/* En-tête */}
          <div className="flex items-center justify-between border-b border-gray-100 bg-sidebar px-4 py-3 text-white">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              <span className="text-sm font-semibold">{t('title')}</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={toggleExpanded}
                aria-label={expanded ? t('shrink') : t('expand')}
                title={expanded ? t('shrink') : t('expand')}
                className="rounded p-1 transition-colors hover:bg-white/10"
              >
                {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t('close')}
                className="rounded p-1 transition-colors hover:bg-white/10"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Historique */}
          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {messages.length === 0 && (
              <div className="space-y-3">
                <p className="text-sm text-gray-500">{t('intro')}</p>
                <div className="flex flex-col gap-2">
                  {suggestionKeys(pathname).map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => send(t(`suggestions.${k}`))}
                      className="rounded-lg border border-gray-200 px-3 py-2 text-left text-sm text-gray-700 transition-colors hover:border-accent hover:bg-accent/5"
                    >
                      {t(`suggestions.${k}`)}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {/* Timeline unique : chaque message, suivi des cartes d'action ancrées à ce
                tour → ordre chronologique (plus de bloc de propositions séparé en bas). */}
            {messages.map((m, i) => (
              <Fragment key={i}>
                <div className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                  <div
                    className={
                      m.role === 'user'
                        ? 'max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent px-3 py-2 text-sm text-white'
                        : 'max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-gray-100 px-3 py-2 text-sm text-gray-800'
                    }
                  >
                    {m.content || (streaming && i === messages.length - 1 ? '…' : '')}
                  </div>
                </div>
                {proposals
                  .map((p, idx) => ({ p, idx }))
                  .filter(({ p }) => p.afterMessageIndex === i)
                  .map(({ p, idx }) => renderProposal(p, idx))}
              </Fragment>
            ))}
            {/* Filet de sécurité : cartes ancrées au-delà du dernier message rendu. */}
            {proposals
              .map((p, idx) => ({ p, idx }))
              .filter(({ p }) => p.afterMessageIndex >= messages.length)
              .map(({ p, idx }) => renderProposal(p, idx))}
          </div>

          {/* Saisie */}
          <form
            onSubmit={(e) => {
              e.preventDefault()
              send(input)
            }}
            className="flex items-center gap-2 border-t border-gray-100 px-3 py-3"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t('placeholder')}
              disabled={streaming}
              className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-accent focus:outline-none disabled:opacity-60"
            />
            {micSupported && (
              <select
                value={dictationLang}
                onChange={(e) => {
                  setDictationLang(e.target.value)
                  try {
                    localStorage.setItem('sf_dictation_lang', e.target.value)
                  } catch {
                    /* localStorage indisponible — non bloquant */
                  }
                }}
                disabled={streaming || listening}
                aria-label={t('mic_start')}
                title={t('mic_start')}
                className="max-w-[7rem] rounded-lg border border-gray-200 px-1.5 py-2 text-xs text-gray-600 focus:border-accent focus:outline-none disabled:opacity-50"
              >
                {DICTATION_LANGS.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            )}
            {micSupported && (
              <button
                type="button"
                onClick={toggleMic}
                disabled={streaming}
                aria-label={listening ? t('mic_stop') : t('mic_start')}
                aria-pressed={listening}
                title={listening ? t('mic_stop') : t('mic_start')}
                className={
                  listening
                    ? 'flex h-9 w-9 items-center justify-center rounded-lg bg-red-500 text-white transition-colors hover:bg-red-600 animate-pulse'
                    : 'flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 text-gray-500 transition-colors hover:border-accent hover:text-accent disabled:opacity-50'
                }
              >
                <Mic className="h-4 w-4" />
              </button>
            )}
            <button
              type="submit"
              disabled={streaming || !input.trim()}
              aria-label={t('send')}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      )}
    </>
  )
}
