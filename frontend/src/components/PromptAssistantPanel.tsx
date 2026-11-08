'use client'

// Assistant de rédaction de prompt — réutilisable (GenerateDialog + Studio).
// OPTIONNEL et non bloquant : l'utilisateur décrit son idée (FR/EN…), l'assistant
// rédige un prompt anglais optimisé + un negative prompt (si le modèle le supporte),
// et pré-remplit les champs du parent (toujours éditables). Deux modes : direct
// (one-shot) ou conversationnel (l'agent peut poser 1-3 questions avant de livrer).

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation } from '@tanstack/react-query'
import { Wand2, Send, ChevronDown, ChevronRight } from 'lucide-react'
import Button from '@/components/ui/Button'
import { assistPrompt, type AssistMessage, type AssistMode, type AssistResponse } from '@/lib/promptAssistant'

export default function PromptAssistantPanel({
  kind,
  model,
  referenceMediaIds,
  onApply,
}: {
  kind: 'image' | 'video' | 'music' | 'voice'
  model?: string
  referenceMediaIds?: number[]
  /** Pré-remplit les champs du parent. negativePrompt = null si non supporté. */
  onApply: (prompt: string, negativePrompt: string | null) => void
}) {
  const t = useTranslations()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<AssistMode>('one_shot')
  const [idea, setIdea] = useState('')
  const [messages, setMessages] = useState<AssistMessage[]>([])
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<AssistResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const reset = () => { setMessages([]); setAnswer(''); setResult(null); setErr(null) }

  const handleResult = (res: AssistResponse) => {
    setResult(res)
    if (res.ready && res.prompt && res.assisted) {
      onApply(res.prompt, res.supports_negative_prompt ? res.negative_prompt : null)
    }
  }

  const run = useMutation({
    mutationFn: (body: Parameters<typeof assistPrompt>[0]) => assistPrompt(body),
    onSuccess: (res, vars) => {
      if (vars.mode === 'conversational' && !res.ready && res.questions.length > 0) {
        // L'agent pose des questions → les ajouter au fil comme un tour assistant.
        setMessages((m) => [...m, { role: 'assistant', content: res.questions.join('\n') }])
      }
      handleResult(res)
    },
    onError: (e) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErr(typeof msg === 'string' ? msg : t('generation.assist_error'))
    },
  })

  const start = () => {
    setErr(null); setResult(null)
    const intent = idea.trim()
    if (!intent) return
    if (mode === 'one_shot') {
      run.mutate({ kind, model, mode, intent, reference_media_ids: referenceMediaIds })
    } else {
      const thread: AssistMessage[] = [{ role: 'user', content: intent }]
      setMessages(thread)
      run.mutate({ kind, model, mode, messages: thread, reference_media_ids: referenceMediaIds })
    }
  }

  const sendAnswer = () => {
    const a = answer.trim()
    if (!a) return
    setErr(null); setAnswer('')
    const thread: AssistMessage[] = [...messages, { role: 'user', content: a }]
    setMessages(thread)
    run.mutate({ kind, model, mode: 'conversational', messages: thread, reference_media_ids: referenceMediaIds })
  }

  const awaitingAnswer = mode === 'conversational' && result !== null && !result.ready && result.questions.length > 0

  return (
    <div className="rounded-lg border border-accent/30 bg-accent/5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-xs font-medium text-accent"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <Wand2 className="h-3.5 w-3.5" />
        {t('generation.assist_open')}
      </button>

      {open && (
        <div className="space-y-2 border-t border-accent/20 px-3 py-2">
          <p className="text-[11px] text-gray-500">{t('generation.assist_intro')}</p>

          {/* Mode direct / conversationnel */}
          <div className="flex gap-1.5">
            {(['one_shot', 'conversational'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => { setMode(m); reset() }}
                className={`rounded px-2 py-1 text-[11px] transition-sf ${
                  mode === m ? 'bg-accent text-white' : 'bg-surface border border-gray-200 text-gray-600'
                }`}
              >
                {t(`generation.assist_mode_${m === 'one_shot' ? 'oneshot' : 'chat'}`)}
              </button>
            ))}
          </div>

          {/* Idée initiale */}
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            rows={2}
            placeholder={t('generation.assist_idea_ph')}
            className="w-full resize-none rounded-lg border border-gray-200 bg-surface px-2 py-1.5 text-xs focus:border-accent focus:outline-none"
          />
          <Button size="sm" variant="secondary" loading={run.isPending && messages.length <= 1} disabled={!idea.trim()} onClick={start}>
            <Wand2 className="mr-1 h-3 w-3" />{t('generation.assist_run')}
          </Button>

          {/* Fil conversationnel (questions de l'agent) */}
          {mode === 'conversational' && messages.length > 0 && (
            <div className="space-y-1.5">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={`rounded px-2 py-1 text-[11px] ${
                    m.role === 'assistant' ? 'bg-accent/10 text-gray-700' : 'bg-surface border border-gray-200 text-gray-600'
                  }`}
                >
                  {m.content}
                </div>
              ))}
            </div>
          )}

          {awaitingAnswer && (
            <div className="flex gap-1.5">
              <input
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); sendAnswer() } }}
                placeholder={t('generation.assist_answer_ph')}
                className="flex-1 rounded-lg border border-gray-200 bg-surface px-2 py-1 text-xs focus:border-accent focus:outline-none"
              />
              <Button size="sm" variant="secondary" loading={run.isPending} disabled={!answer.trim()} onClick={sendAnswer}>
                <Send className="h-3 w-3" />
              </Button>
            </div>
          )}

          {/* Résultat appliqué / repli / notes */}
          {result && result.ready && result.assisted && result.prompt && (
            <p className="text-[11px] text-emerald-600 dark:text-emerald-400">
              ✓ {t('generation.assist_applied')}
              {result.notes && <span className="block text-gray-500">{result.notes}</span>}
            </p>
          )}
          {result && !result.assisted && (
            <p className="text-[11px] text-amber-600 dark:text-amber-400">{t('generation.assist_unavailable')}</p>
          )}
          {err && <p className="text-[11px] text-danger">{err}</p>}
        </div>
      )}
    </div>
  )
}
