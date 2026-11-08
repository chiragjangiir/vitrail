'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Plus, Building2, AlertTriangle, Trash2 } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import DataTable, { type Column } from '@/components/ui/DataTable'
import Button from '@/components/ui/Button'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'
import OrgDrawer from './components/OrgDrawer'
import DeletionImpactDrawer from '@/components/admin/DeletionImpactDrawer'

export interface OrgRow {
  id_org: number
  org_name: string
  org_slug: string
  is_active: boolean
  rendition_policy: string
  ai_quota_unit: string
  ai_quota_tokens: number | null
  ai_quota_eur: number | null
  ai_quota_period: string
  ai_alert_threshold_pct: number
  ai_byok_mode: string
  // Plafonds de DÉPENSE BYOK en USD (P3.2) — NULL/0 = aucun plafond.
  ai_spend_cap_usd: number | null
  ai_user_spend_cap_usd: number | null
  ai_spend_cap_period: string
  created_at: string
}

interface AiUsageRow {
  id_org: number
  period: string
  unit: string
  limit: number | null
  used: number
  used_tokens: number
  used_messages: number
  cost_eur: number
  pct: number | null
  blocked: boolean
  over_threshold: boolean
  threshold_pct: number
}

export default function OrgsPage() {
  const t = useTranslations()
  const [drawer, setDrawer] = useState<{ open: boolean; org: OrgRow | null }>({ open: false, org: null })
  const [purgeOrg, setPurgeOrg] = useState<OrgRow | null>(null)

  const { data: orgs = [], isLoading, error } = useQuery<OrgRow[]>({
    queryKey: ['orgs'],
    queryFn: () => api.get<OrgRow[]>('/orgs').then((r) => r.data),
    retry: false,
  })

  const { data: usage = [] } = useQuery<AiUsageRow[]>({
    queryKey: ['assistant-usage'],
    queryFn: () => api.get<AiUsageRow[]>('/admin/assistant/usage').then((r) => r.data),
    retry: false,
  })
  const usageMap = new Map(usage.map((u) => [u.id_org, u]))

  const forbidden = (error as { response?: { status?: number } })?.response?.status === 403

  const columns: Column<OrgRow>[] = [
    { key: 'org_name', header: t('orgs.col_name'),
      render: (o) => <span className="font-medium text-gray-900">{o.org_name}</span> },
    { key: 'org_slug', header: t('orgs.col_slug'),
      render: (o) => <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{o.org_slug}</code> },
    { key: 'is_active', header: t('orgs.col_status'),
      render: (o) => o.is_active
        ? <StatusBadge status="online" label={t('orgs.status_active')} />
        : <StatusBadge status="offline" label={t('orgs.status_inactive')} /> },
    { key: 'ai_usage', header: t('orgs.col_ai_usage'),
      render: (o) => {
        const u = usageMap.get(o.id_org)
        if (!u) return <span className="text-gray-400">—</span>
        const fmt = (v: number | null) =>
          v == null ? '∞' : u.unit === 'eur' ? `${v.toFixed(2)} €` : v.toLocaleString()
        const used = u.unit === 'eur' ? `${u.used.toFixed(2)} €` : u.used_tokens.toLocaleString()
        return (
          <span className="text-xs text-gray-600">
            {used} / {fmt(u.limit)}
            {u.unit !== 'eur' && (
              <span className="text-gray-400"> · {u.cost_eur.toFixed(2)} €</span>
            )}
            {u.pct != null && (
              <span className={`ml-1.5 inline-flex items-center gap-0.5 font-medium ${
                u.blocked ? 'text-danger' : u.over_threshold ? 'text-amber-600 dark:text-amber-300' : 'text-gray-500'
              }`}>
                {(u.blocked || u.over_threshold) && <AlertTriangle className="w-3 h-3" />}
                {u.pct}%
              </span>
            )}
          </span>
        )
      } },
    // P3.3 — il n'existait AUCUN moyen de retirer une organisation : on pouvait en créer,
    // jamais en supprimer. Le bouton ouvre le rapport d'impact, il ne tente rien à l'aveugle.
    { key: 'actions', header: '',
      render: (o) => (
        <button type="button" title={t('admin_delete.purge')}
          onClick={(e) => { e.stopPropagation(); setPurgeOrg(o) }}
          className="p-0.5 text-gray-300 transition-sf hover:text-danger"
          data-testid={`purge-org-${o.id_org}`}>
          <Trash2 className="w-4 h-4" />
        </button>
      ) }
  ]

  return (
    <>
      <Topbar title={t('nav.organizations')} />
      <main className="flex-1 overflow-y-auto">
        {/* Largeur de reference des pages de reglages centrees : max-w-5xl
            (arbitrage Ed 2026-07-23). Ne pas diverger page par page. */}
        <div className="max-w-5xl mx-auto px-6 py-5">
          {forbidden ? (
            <div className="flex flex-col items-center justify-center py-20 text-center text-gray-500">
              <Building2 className="w-10 h-10 mb-3 text-gray-300" />
              <p className="text-sm">{t('orgs.reserved')}</p>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-end mb-4">
                <Button size="sm" onClick={() => setDrawer({ open: true, org: null })}>
                  <Plus className="w-3.5 h-3.5" />
                  {t('orgs.create')}
                </Button>
              </div>
              <DataTable<OrgRow>
                columns={columns}
                data={orgs}
                loading={isLoading}
                rowKey={(o) => o.id_org}
                onRowClick={(o) => setDrawer({ open: true, org: o })}
                emptyMessage={t('orgs.empty')}
              />
            </>
          )}
        </div>
      </main>

      <OrgDrawer open={drawer.open} org={drawer.org} onClose={() => setDrawer({ open: false, org: null })} />

      {purgeOrg && (
        <DeletionImpactDrawer
          open
          onClose={() => setPurgeOrg(null)}
          label={purgeOrg.org_name}
          impactUrl={`/orgs/${purgeOrg.id_org}/deletion-impact`}
          onPurge={() => api.delete(`/orgs/${purgeOrg.id_org}`)}
          onSoftAction={purgeOrg.is_active
            ? () => api.patch(`/orgs/${purgeOrg.id_org}`, { is_active: false })
            : undefined}
          invalidate={['orgs']}
        />
      )}
    </>
  )
}
