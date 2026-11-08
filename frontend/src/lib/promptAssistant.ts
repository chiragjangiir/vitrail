// Assistant de rédaction de prompt — appel backend POST /generation/prompt-assist.
// OPTIONNEL : transforme une idée (FR/EN…) en prompt anglais optimisé + negative prompt
// model-aware. Repli gracieux (assisted=false) si l'org est en mode strict / LLM indispo.

import api from '@/lib/api'

export type AssistMode = 'one_shot' | 'conversational'
export type AssistMessage = { role: 'user' | 'assistant'; content: string }

export type AssistResponse = {
  ready: boolean
  questions: string[]
  prompt: string | null
  negative_prompt: string | null
  notes: string
  assisted: boolean
  supports_negative_prompt: boolean
}

export async function assistPrompt(body: {
  kind: 'image' | 'video' | 'music' | 'voice'
  model?: string
  mode: AssistMode
  intent?: string
  messages?: AssistMessage[]
  reference_media_ids?: number[]
}): Promise<AssistResponse> {
  const r = await api.post<AssistResponse>('/generation/prompt-assist', body)
  return r.data
}
