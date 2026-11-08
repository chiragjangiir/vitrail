'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import type { OrgRow } from '../page'

interface UsageDay { date: string; tokens: number; messages: number; cost_eur: number }

/** Mini-graphe à barres (30 j) de l'usage IA — SVG inline, 0 dépendance. */
function UsageHistory({ idOrg }: { idOrg: number }) {
  const t = useTranslations()
  const { data = [] } = useQuery<UsageDay[]>({
    queryKey: ['assistant-usage-history', idOrg],
    queryFn: () => api.get<UsageDay[]>(`/admin/assistant/usage/${idOrg}/history?days=30`).then((r) => r.data),
  })
  const max = Math.max(1, ...data.map((d) => d.tokens))
  const totalCost = data.reduce((s, d) => s + d.cost_eur, 0)
  return (
    <div className="pb-3 border-b border-gray-200 space-y-2">
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-gray-700">{t('orgs.ai_history')}</span>
        <span className="text-xs text-gray-400">{t('orgs.ai_history_cost', { cost: totalCost.toFixed(2) })}</span>
      </div>
      {data.every((d) => d.tokens === 0) ? (
        <p className="text-xs text-gray-400">{t('orgs.ai_history_empty')}</p>
      ) : (
        <div className="flex items-end gap-0.5 h-20">
          {data.map((d) => (
            <div
              key={d.date}
              title={`${d.date} — ${d.tokens.toLocaleString()} tok · ${d.cost_eur.toFixed(2)} €`}
              className="flex-1 bg-accent/30 hover:bg-accent rounded-t transition-sf"
              style={{ height: `${Math.max(2, (d.tokens / max) * 100)}%` }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface ProvisionResult {
  email: string
  totp_secret: string
  totp_uri: string
}

/** Drawer super-admin (provisioning plateforme) :
 *  - org=null  → créer un tenant + son 1er admin (mot de passe + QR 2FA).
 *  - org=...   → gérer un tenant existant : réinitialiser l'accès d'un admin
 *               (récupération) sans voir le contenu de l'org. */
export default function OrgDrawer({
  open, org, onClose,
}: { open: boolean; org: OrgRow | null; onClose: () => void }) {
  const t = useTranslations()
  const qc = useQueryClient()
  const manage = org !== null

  const [orgName, setOrgName] = useState('')
  const [orgSlug, setOrgSlug] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [adminPwd, setAdminPwd] = useState('')
  const [renditionPolicy, setRenditionPolicy] = useState('off')
  const [aiQuotaUnit, setAiQuotaUnit] = useState('tokens')
  const [aiQuotaTokens, setAiQuotaTokens] = useState('')
  const [aiQuotaEur, setAiQuotaEur] = useState('')
  const [aiQuotaPeriod, setAiQuotaPeriod] = useState('monthly')
  const [aiAlertThreshold, setAiAlertThreshold] = useState('80')
  const [aiByokMode, setAiByokMode] = useState('strict')
  // Plafonds de DÉPENSE BYOK (P3.2) — en USD, l'unité des fournisseurs. Vide/0 = aucun.
  const [spendCap, setSpendCap] = useState('')
  const [userSpendCap, setUserSpendCap] = useState('')
  const [spendPeriod, setSpendPeriod] = useState('month')
  const [result, setResult] = useState<ProvisionResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setOrgName(''); setOrgSlug(''); setAdminEmail(''); setAdminPwd('')
      setRenditionPolicy(org?.rendition_policy ?? 'off')
      setAiQuotaUnit(org?.ai_quota_unit ?? 'tokens')
      setAiQuotaTokens(org?.ai_quota_tokens ? String(org.ai_quota_tokens) : '')
      setAiQuotaEur(org?.ai_quota_eur ? String(org.ai_quota_eur) : '')
      setAiQuotaPeriod(org?.ai_quota_period ?? 'monthly')
      setAiAlertThreshold(org?.ai_alert_threshold_pct != null ? String(org.ai_alert_threshold_pct) : '80')
      setAiByokMode(org?.ai_byok_mode ?? 'strict')
      setSpendCap(org?.ai_spend_cap_usd ? String(org.ai_spend_cap_usd) : '')
      setUserSpendCap(org?.ai_user_spend_cap_usd ? String(org.ai_user_spend_cap_usd) : '')
      setSpendPeriod(org?.ai_spend_cap_period ?? 'month')
      setResult(null); setError(null)
    }
  }, [open, org])

  const onErr = (e: unknown) => {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setError(typeof msg === 'string' ? msg : t('orgs.save_error'))
  }

  // Auto-slug depuis le nom (création).
  const onName = (v: string) => {
    setOrgName(v)
    setOrgSlug(v.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''))
  }

  const create = useMutation({
    mutationFn: async () => {
      const created = await api.post<{ id_org: number }>('/orgs', {
        org_name: orgName.trim(), org_slug: orgSlug.trim(),
      })
      let prov: ProvisionResult | null = null
      if (adminEmail.trim() && adminPwd.length >= 8) {
        const r = await api.post<ProvisionResult>(`/orgs/${created.data.id_org}/provision-admin`, {
          email: adminEmail.trim(), password: adminPwd,
        })
        prov = r.data
      }
      return prov
    },
    onSuccess: (prov) => {
      qc.invalidateQueries({ queryKey: ['orgs'] })
      if (prov) setResult(prov)
      else onClose()
    },
    onError: onErr,
  })

  const resetAdmin = useMutation({
    mutationFn: () =>
      api.post<ProvisionResult>(`/orgs/${org!.id_org}/reset-admin`, {
        email: adminEmail.trim(), password: adminPwd,
      }).then((r) => r.data),
    onSuccess: (r) => setResult(r),
    onError: onErr,
  })

  const toggleActive = useMutation({
    mutationFn: () => api.patch(`/orgs/${org!.id_org}`, { is_active: !org!.is_active }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['orgs'] }); onClose() },
    onError: onErr,
  })

  // Politique de renditions adaptatives (off | auto_fhd) — on garde le drawer ouvert.
  const saveRendition = useMutation({
    mutationFn: (policy: string) => api.patch(`/orgs/${org!.id_org}`, { rendition_policy: policy }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['orgs'] }),
    onError: onErr,
  })

  // Politique d'accès aux clés IA : strict (défaut) | platform (autorise la clé Anthropic plateforme).
  const saveByok = useMutation({
    mutationFn: (mode: string) => api.patch(`/orgs/${org!.id_org}`, { ai_byok_mode: mode }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['orgs'] }),
    onError: onErr,
  })

  // Crédit de l'assistant IA (0 / vide = illimité) : unité tokens|eur + période + seuil d'alerte.
  const saveQuota = useMutation({
    mutationFn: () => api.patch(`/orgs/${org!.id_org}`, {
      ai_quota_unit: aiQuotaUnit,
      ai_quota_tokens: aiQuotaUnit === 'tokens' ? (aiQuotaTokens.trim() === '' ? 0 : Number(aiQuotaTokens)) : undefined,
      ai_quota_eur: aiQuotaUnit === 'eur' ? (aiQuotaEur.trim() === '' ? 0 : Number(aiQuotaEur)) : undefined,
      ai_quota_period: aiQuotaPeriod,
      ai_alert_threshold_pct: aiAlertThreshold.trim() === '' ? 0 : Number(aiAlertThreshold),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['orgs'] })
      qc.invalidateQueries({ queryKey: ['assistant-usage'] })
    },
    onError: onErr,
  })

  // Plafonds de dépense BYOK (P3.2). ⚠️ On envoie **0** et jamais `undefined` pour retirer un
  // plafond : `update_org` filtre les valeurs nulles (`exclude_none`), un champ vidé ne
  // partirait donc pas et le plafond resterait en place — un réglage qui semble effacé et ne
  // l'est pas est pire que pas de réglage.
  const saveSpend = useMutation({
    mutationFn: () => api.patch(`/orgs/${org!.id_org}`, {
      ai_spend_cap_usd: spendCap.trim() === '' ? 0 : Number(spendCap),
      ai_user_spend_cap_usd: userSpendCap.trim() === '' ? 0 : Number(userSpendCap),
      ai_spend_cap_period: spendPeriod,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['orgs'] }),
    onError: onErr,
  })

  const title = manage ? `${t('orgs.manage')} — ${org!.org_name}` : t('orgs.create')

  return (
    <Drawer open={open} onClose={onClose} title={title}>
      {result ? (
        <div className="space-y-3">
          <p className="text-sm text-success bg-green-50 dark:bg-green-500/15 rounded-md px-3 py-2">
            {manage ? t('orgs.reset_done') : t('orgs.created_ok')}
          </p>
          <div className="text-sm">
            <p className="font-medium text-gray-900">{t('orgs.admin_label')} : {result.email}</p>
            <p className="text-xs text-gray-500 mt-2">{t('orgs.totp_scan')}</p>
            <div className="inline-block bg-surface p-3 rounded-lg border border-gray-200 mt-1 shadow-sf-card">
              <QRCodeSVG value={result.totp_uri} size={160} />
            </div>
            <p className="text-xs text-gray-500 mt-2">{t('orgs.totp_secret')}</p>
            <code className="block text-xs bg-gray-100 p-2 rounded break-all">{result.totp_secret}</code>
          </div>
          <Button size="sm" onClick={onClose}>{t('orgs.done')}</Button>
        </div>
      ) : manage ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-gray-200">
            <span className="text-sm text-gray-700">
              {org!.is_active ? t('orgs.status_active') : t('orgs.status_inactive')}
            </span>
            <Button size="sm" variant={org!.is_active ? 'danger' : 'primary'}
              disabled={toggleActive.isPending} onClick={() => toggleActive.mutate()}>
              {org!.is_active ? t('orgs.suspend') : t('orgs.reactivate')}
            </Button>
          </div>
          <div className="flex items-center justify-between gap-3 pb-3 border-b border-gray-200">
            <div>
              <span className="text-sm text-gray-700">{t('orgs.rendition_policy')}</span>
              <p className="text-xs text-gray-400">{t('orgs.rendition_policy_hint')}</p>
            </div>
            <select
              value={renditionPolicy}
              disabled={saveRendition.isPending}
              onChange={(e) => { setRenditionPolicy(e.target.value); saveRendition.mutate(e.target.value) }}
              className="rounded border border-gray-200 px-2 py-1 bg-surface text-sm shrink-0"
            >
              <option value="off">{t('orgs.rendition_off')}</option>
              <option value="auto_fhd">{t('orgs.rendition_auto_fhd')}</option>
            </select>
          </div>
          <div className="flex items-center justify-between gap-3 pb-3 border-b border-gray-200">
            <div>
              <span className="text-sm text-gray-700">{t('orgs.ai_byok_mode')}</span>
              <p className="text-xs text-gray-400">{t('orgs.ai_byok_mode_hint')}</p>
            </div>
            <select
              value={aiByokMode}
              disabled={saveByok.isPending}
              onChange={(e) => { setAiByokMode(e.target.value); saveByok.mutate(e.target.value) }}
              className="rounded border border-gray-200 px-2 py-1 bg-surface text-sm shrink-0"
            >
              <option value="strict">{t('orgs.ai_byok_strict')}</option>
              <option value="platform">{t('orgs.ai_byok_platform')}</option>
            </select>
          </div>
          <div className="pb-3 border-b border-gray-200 space-y-2">
            <div>
              <span className="text-sm text-gray-700">{t('orgs.ai_quota')}</span>
              <p className="text-xs text-gray-400">{t('orgs.ai_quota_hint')}</p>
            </div>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                {aiQuotaUnit === 'eur' ? (
                  <Input label={t('orgs.ai_quota_value')} type="number" min={0} step="0.01" value={aiQuotaEur}
                    onChange={(e) => setAiQuotaEur(e.target.value)} placeholder={t('orgs.ai_quota_unlimited')} />
                ) : (
                  <Input label={t('orgs.ai_quota_value')} type="number" min={0} value={aiQuotaTokens}
                    onChange={(e) => setAiQuotaTokens(e.target.value)} placeholder={t('orgs.ai_quota_unlimited')} />
                )}
              </div>
              <select
                value={aiQuotaUnit}
                onChange={(e) => setAiQuotaUnit(e.target.value)}
                className="rounded border border-gray-200 px-2 py-2 bg-surface text-sm shrink-0"
              >
                <option value="tokens">{t('orgs.ai_unit_tokens')}</option>
                <option value="eur">{t('orgs.ai_unit_eur')}</option>
              </select>
              <select
                value={aiQuotaPeriod}
                onChange={(e) => setAiQuotaPeriod(e.target.value)}
                className="rounded border border-gray-200 px-2 py-2 bg-surface text-sm shrink-0"
              >
                <option value="monthly">{t('orgs.ai_period_monthly')}</option>
                <option value="weekly">{t('orgs.ai_period_weekly')}</option>
              </select>
            </div>
            <div className="flex items-end gap-2">
              <div className="w-32">
                <Input label={t('orgs.ai_alert_threshold')} type="number" min={0} max={100} value={aiAlertThreshold}
                  onChange={(e) => setAiAlertThreshold(e.target.value)} placeholder="80" />
              </div>
              <Button size="sm" variant="secondary" disabled={saveQuota.isPending}
                onClick={() => saveQuota.mutate()}>
                {t('orgs.ai_quota_save')}
              </Button>
            </div>
          </div>
          {/* Plafonds de DÉPENSE BYOK (P3.2) — distincts du crédit assistant juste au-dessus :
              celui-là compte les tokens de l'assistant sur la clé Anthropic, ceux-ci
              l'argent réel dépensé chez fal et ElevenLabs avec la clé DU CLIENT. */}
          <div className="space-y-2 rounded-lg border border-white/5 p-3">
            <div>
              <span className="text-sm text-gray-700">{t('orgs.spend_cap')}</span>
              <p className="text-xs text-gray-400">{t('orgs.spend_cap_hint')}</p>
            </div>
            <div className="flex items-end gap-2">
              <div className="w-28">
                <Input label={t('orgs.spend_cap_org')} type="number" min={0} step="0.01"
                  value={spendCap} onChange={(e) => setSpendCap(e.target.value)}
                  placeholder="0" data-testid="spend-cap-org" />
              </div>
              <div className="w-28">
                <Input label={t('orgs.spend_cap_user')} type="number" min={0} step="0.01"
                  value={userSpendCap} onChange={(e) => setUserSpendCap(e.target.value)}
                  placeholder="0" data-testid="spend-cap-user" />
              </div>
              <select
                value={spendPeriod}
                onChange={(e) => setSpendPeriod(e.target.value)}
                className="rounded border border-gray-200 px-2 py-2 bg-surface text-sm shrink-0"
              >
                <option value="day">{t('orgs.spend_period_day')}</option>
                <option value="week">{t('orgs.spend_period_week')}</option>
                <option value="month">{t('orgs.spend_period_month')}</option>
              </select>
              <Button size="sm" variant="secondary" disabled={saveSpend.isPending}
                onClick={() => saveSpend.mutate()} data-testid="spend-cap-save">
                {t('orgs.ai_quota_save')}
              </Button>
            </div>
          </div>
          <UsageHistory idOrg={org!.id_org} />
          <p className="text-xs text-gray-500">{t('orgs.reset_admin_hint')}</p>
          <Input label={t('orgs.admin_email')} type="email" value={adminEmail}
            onChange={(e) => setAdminEmail(e.target.value)} placeholder="admin@org.demo" />
          <Input label={t('orgs.admin_password')} type="password" value={adminPwd}
            onChange={(e) => setAdminPwd(e.target.value)} placeholder={t('orgs.password_hint')} />
          {error && <p className="text-xs text-danger bg-red-500/10 dark:bg-red-500/15 rounded-md px-3 py-2">{error}</p>}
          <Button onClick={() => resetAdmin.mutate()}
            disabled={!adminEmail.trim() || adminPwd.length < 8 || resetAdmin.isPending} size="sm">
            {t('orgs.reset_admin')}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <Input label={t('orgs.col_name')} value={orgName}
            onChange={(e) => onName(e.target.value)} placeholder="Boutique Démo" />
          <Input label={t('orgs.col_slug')} value={orgSlug}
            onChange={(e) => setOrgSlug(e.target.value)} placeholder="boutique-demo" />
          <div className="pt-3 border-t border-gray-200 space-y-3">
            <p className="text-xs text-gray-500">{t('orgs.admin_optional')}</p>
            <Input label={t('orgs.admin_email')} type="email" value={adminEmail}
              onChange={(e) => setAdminEmail(e.target.value)} placeholder="admin@boutique.demo" />
            <Input label={t('orgs.admin_password')} type="password" value={adminPwd}
              onChange={(e) => setAdminPwd(e.target.value)} placeholder={t('orgs.password_hint')} />
          </div>
          {error && <p className="text-xs text-danger bg-red-500/10 dark:bg-red-500/15 rounded-md px-3 py-2">{error}</p>}
          <Button onClick={() => create.mutate()}
            disabled={!orgName.trim() || !orgSlug.trim() || create.isPending} size="sm">
            {t('orgs.create')}
          </Button>
        </div>
      )}
    </Drawer>
  )
}
