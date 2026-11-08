'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Shield } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import NumberField from '@/components/ui/NumberField'
import { useAuthStore } from '@/store/auth'
import api from '@/lib/api'

type TwoFaPolicy = 'disabled' | 'optional' | 'required'

interface OrgAuthSettings {
  id_org: number
  auth_2fa_policy: TwoFaPolicy
  session_lifetime: number   // minutes (ex: 480 = 8h)
  max_sessions: number
  password_min_len: number
  password_policy: Record<string, boolean>
  ip_allowlist: string[] | null
  updated_at: string
}

export default function SecurityPage() {
  const t = useTranslations()
  const { user } = useAuthStore()
  const [policy, setPolicy] = useState<TwoFaPolicy>('optional')
  const [sessionLifetime, setSessionLifetime] = useState(480)
  const [ipList, setIpList] = useState('')
  const [saved, setSaved] = useState(false)

  const orgId = user?.id_org

  const { data } = useQuery<OrgAuthSettings>({
    queryKey: ['auth-settings', orgId],
    queryFn: () =>
      api.get<OrgAuthSettings>(`/orgs/${orgId}/auth-settings`).then((r) => r.data),
    enabled: !!orgId,
  })

  useEffect(() => {
    if (data) {
      setPolicy(data.auth_2fa_policy)
      setSessionLifetime(data.session_lifetime)
      setIpList(data.ip_allowlist?.join('\n') ?? '')
    }
  }, [data])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put(`/orgs/${orgId}/auth-settings`, {
        auth_2fa_policy: policy,
        session_lifetime: sessionLifetime,
        ip_allowlist: ipList
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const policyOptions: { value: TwoFaPolicy; label: string }[] = [
    { value: 'disabled', label: t('security.2fa_disabled') },
    { value: 'optional', label: t('security.2fa_optional') },
    { value: 'required', label: t('security.2fa_required') },
  ]

  return (
    <>
      <Topbar title={t('nav.security')} />
      <main className="flex-1 overflow-y-auto">
        {/* Largeur de reference des pages de reglages centrees : max-w-5xl
            (arbitrage Ed 2026-07-23). Ne pas diverger page par page. */}
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-8">

          {/* 2FA Policy */}
          <section className="bg-surface rounded-lg border border-gray-200 p-6 space-y-4 shadow-sf-card">
            <div className="flex items-center gap-3 mb-2">
              <Shield className="w-5 h-5 text-accent" />
              <h2 className="font-semibold text-gray-900">{t('security.2fa_policy')}</h2>
            </div>
            <div className="flex gap-2 flex-wrap">
              {policyOptions.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setPolicy(value)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium border transition-sf ${
                    policy === value
                      ? 'bg-accent text-white border-accent'
                      : 'bg-surface text-gray-600 border-gray-200 hover:border-accent hover:text-accent'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-400">{t('security.2fa_policy_hint')}</p>
          </section>

          {/* Session lifetime */}
          <section className="bg-surface rounded-lg border border-gray-200 p-6 space-y-4 shadow-sf-card">
            <h2 className="font-semibold text-gray-900">{t('security.session_duration')}</h2>
            <div className="max-w-xs">
              <NumberField
                min={30}
                max={43200}
                value={sessionLifetime}
                onCommit={(v) => setSessionLifetime(v ?? 30)}
                hint={t('security.session_hint')}
              />
            </div>
          </section>

          {/* IP allowlist */}
          <section className="bg-surface rounded-lg border border-gray-200 p-6 space-y-4 shadow-sf-card">
            <h2 className="font-semibold text-gray-900">{t('security.ip_allowlist')}</h2>
            <textarea
              value={ipList}
              onChange={(e) => setIpList(e.target.value)}
              rows={6}
              placeholder="192.168.1.0/24&#10;10.0.0.0/8"
              className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 font-mono focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent"
            />
            <p className="text-xs text-gray-400">{t('security.ip_hint')}</p>
          </section>

          {/* Save */}
          <div className="flex items-center gap-3">
            <Button
              onClick={() => saveMutation.mutate()}
              loading={saveMutation.isPending}
            >
              {t('security.save_settings')}
            </Button>
            {saved && <p className="text-sm text-success">{t('common.saved')}</p>}
            {saveMutation.isError && <p className="text-sm text-danger">{t('common.error')}</p>}
          </div>
        </div>
      </main>
    </>
  )
}
