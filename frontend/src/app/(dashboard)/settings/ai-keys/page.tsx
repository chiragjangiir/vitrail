'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Trash2 } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import StatusBadge from '@/components/ui/StatusBadge'
import { useAuthStore } from '@/store/auth'
import api from '@/lib/api'

interface AiKey {
  provider: string
  key_last4: string | null
  status: string
  validated_at: string | null
  updated_at: string
}

const PROVIDERS = ['anthropic', 'fal', 'elevenlabs'] as const
const STATUS_BADGE: Record<string, 'online' | 'offline' | 'warning' | 'pending'> = {
  valid: 'online',
  invalid: 'offline',
  unverified: 'pending',
}

interface AiPlan {
  provider: string
  supported: boolean
  tier: string | null
  used: number | null
  limit: number | null
  remaining: number | null
  resets_at: string | null
  detail: string | null
}

/**
 * L'abonnement derrière une clé, lu EN DIRECT à chaque affichage.
 *
 * Rien n'est stocké côté serveur : un instantané pris à la saisie de la clé se périme à la
 * première remise à zéro mensuelle, et à tout changement d'offre — c'est-à-dire pile au
 * moment où l'on voudrait que la plateforme s'en aperçoive. Un provider qui n'expose pas
 * d'abonnement (fal, Anthropic) répond `supported: false` et le panneau ne s'affiche pas,
 * plutôt que de feindre une abstraction sur un seul provider.
 */
function PlanPanel({ orgId, provider }: { orgId: number; provider: string }) {
  const t = useTranslations()
  const { data } = useQuery<AiPlan>({
    queryKey: ['ai-key-plan', orgId, provider],
    queryFn: () =>
      api.get<AiPlan>(`/orgs/${orgId}/ai-keys/${provider}/plan`).then((r) => r.data),
    enabled: !!orgId,
    retry: false,
    staleTime: 60_000,
  })
  if (!data?.supported) return null

  // Une lecture impossible n'est pas un solde à zéro : on affiche ce que le serveur DIT.
  if (data.remaining === null || data.limit === null) {
    return data.detail ? (
      <p className="mt-2 border-t border-gray-200 pt-2 text-xs text-gray-400">{data.detail}</p>
    ) : null
  }

  const usedPct = data.limit > 0 ? Math.min(100, ((data.used ?? 0) / data.limit) * 100) : 0
  const low = data.remaining < data.limit * 0.1
  return (
    <div className="mt-2 border-t border-gray-200 pt-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-gray-500">{t('aiKeys.plan_title')}</span>
        {data.tier && (
          <span className="text-xs text-gray-400">
            {t('aiKeys.plan_tier')} : <span className="text-gray-500">{data.tier}</span>
          </span>
        )}
      </div>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className={`h-full rounded-full ${low ? 'bg-warning' : 'bg-accent'}`}
          style={{ width: `${usedPct}%` }}
        />
      </div>
      <p className={`mt-1 text-xs ${low ? 'text-warning' : 'text-gray-500'}`}>
        {t('aiKeys.plan_remaining', {
          remaining: data.remaining.toLocaleString(),
          limit: data.limit.toLocaleString(),
        })}
      </p>
      {data.resets_at && (
        <p className="text-xs text-gray-400">
          {t('aiKeys.plan_resets', { date: new Date(data.resets_at).toLocaleDateString() })}
        </p>
      )}
    </div>
  )
}

export default function AiKeysPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const orgId = user?.id_org
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [testMsg, setTestMsg] = useState<Record<string, string>>({})

  const { data: keys = [], error } = useQuery<AiKey[]>({
    queryKey: ['ai-keys', orgId],
    queryFn: () => api.get<AiKey[]>(`/orgs/${orgId}/ai-keys`).then((r) => r.data),
    enabled: !!orgId,
    retry: false,
  })
  const forbidden = (error as { response?: { status?: number } })?.response?.status === 403

  const byProvider = (p: string) => keys.find((k) => k.provider === p)

  const save = useMutation({
    mutationFn: (p: string) => api.put(`/orgs/${orgId}/ai-keys`, { provider: p, api_key: drafts[p] }),
    onSuccess: (_d, p) => {
      setDrafts((s) => ({ ...s, [p]: '' }))
      qc.invalidateQueries({ queryKey: ['ai-keys', orgId] })
    },
  })
  const del = useMutation({
    mutationFn: (p: string) => api.delete(`/orgs/${orgId}/ai-keys/${p}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-keys', orgId] }),
  })
  const test = useMutation({
    mutationFn: (p: string) =>
      api.post<{ ok: boolean | null; detail: string; status: string }>(
        `/orgs/${orgId}/ai-keys/${p}/test`,
      ).then((r) => r.data),
    onSuccess: (d, p) => {
      setTestMsg((s) => ({ ...s, [p]: d.detail }))
      qc.invalidateQueries({ queryKey: ['ai-keys', orgId] })
    },
  })

  return (
    <>
      <Topbar title={t('aiKeys.title')} />
      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-5">
          {forbidden ? (
            <div className="flex flex-col items-center justify-center py-20 text-center text-gray-500">
              <KeyRound className="mb-3 h-10 w-10 text-gray-300" />
              <p className="text-sm">{t('orgs.reserved')}</p>
            </div>
          ) : (
            <>
              <p className="mb-4 text-sm text-gray-500">{t('aiKeys.intro')}</p>
              {/* 3 colonnes égales (largeur + hauteur identiques via stretch), hint sur une ligne. */}
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                {PROVIDERS.map((p) => {
                  const k = byProvider(p)
                  return (
                    <div key={p} className="flex flex-col rounded-lg border border-gray-200 bg-surface p-4 shadow-sf-card">
                      <div className="mb-2">
                        <div className="flex items-center justify-between gap-2">
                          <h3 className="text-sm font-medium text-gray-900">{t(`aiKeys.provider_${p}`)}</h3>
                          {k ? (
                            <StatusBadge status={STATUS_BADGE[k.status] ?? 'pending'} label={t(`aiKeys.status_${k.status}`)} />
                          ) : (
                            <span className="shrink-0 text-xs text-gray-400">{t('aiKeys.not_set')}</span>
                          )}
                        </div>
                        <p className="mt-0.5 text-xs text-gray-400">{t(`aiKeys.hint_${p}`)}</p>
                      </div>
                      {k?.key_last4 && (
                        <p className="mb-2 text-xs text-gray-500">
                          {t('aiKeys.current_key')} : <code className="rounded bg-gray-100 px-1.5 py-0.5">…{k.key_last4}</code>
                        </p>
                      )}
                      <div className="flex items-end gap-2">
                        <div className="flex-1">
                          <Input
                            label={k ? t('aiKeys.replace') : t('aiKeys.set')}
                            type="password"
                            name={`ai-key-${p}`}
                            autoComplete="new-password"
                            value={drafts[p] ?? ''}
                            onChange={(e) => setDrafts((s) => ({ ...s, [p]: e.target.value }))}
                            placeholder={t('aiKeys.placeholder')}
                          />
                        </div>
                        <Button
                          size="sm"
                          disabled={!drafts[p]?.trim() || (save.isPending && save.variables === p)}
                          onClick={() => save.mutate(p)}
                        >
                          {t('aiKeys.save')}
                        </Button>
                      </div>
                      {k && (
                        <div className="mt-2 flex items-center gap-3">
                          <Button
                            size="sm"
                            variant="secondary"
                            loading={test.isPending && test.variables === p}
                            onClick={() => test.mutate(p)}
                          >
                            {t('aiKeys.test')}
                          </Button>
                          {testMsg[p] && <span className="text-xs text-gray-500">{testMsg[p]}</span>}
                          <button
                            type="button"
                            onClick={() => del.mutate(p)}
                            disabled={del.isPending}
                            className="ml-auto flex items-center gap-1 text-xs text-gray-400 transition-colors hover:text-danger"
                          >
                            <Trash2 className="h-3.5 w-3.5" /> {t('aiKeys.delete')}
                          </button>
                        </div>
                      )}
                      {k && orgId && <PlanPanel orgId={orgId} provider={p} />}
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </div>
      </main>
    </>
  )
}
