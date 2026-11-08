'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Copy, Check, Trash2, Ban, Search } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import Drawer from '@/components/ui/Drawer'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import type { ProvisioningTokenRead } from '@/types/api'
import BrightSignSdDrawer from './BrightSignSdDrawer'
import PayloadDrawer from './PayloadDrawer'
import OperatorKeyDrawer from './OperatorKeyDrawer'

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button
      onClick={handleCopy}
      className="p-1.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition-sf"
      title="Copy"
    >
      {copied ? <Check className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
    </button>
  )
}

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' })
}

export default function ProvisioningPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const orgId = user?.id_org

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [sdDrawerOpen, setSdDrawerOpen] = useState(false)
  const [payloadDrawerOpen, setPayloadDrawerOpen] = useState(false)
  const [opKeyDrawerOpen, setOpKeyDrawerOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [label, setLabel] = useState('')
  const [noExpiry, setNoExpiry] = useState(false)
  const [expiresAt, setExpiresAt] = useState('')
  const [maxUses, setMaxUses] = useState<string>('')
  const [createdToken, setCreatedToken] = useState<string | null>(null)

  const { data: tokens = [], isLoading } = useQuery<ProvisioningTokenRead[]>({
    queryKey: ['provisioning-tokens', orgId],
    queryFn: () =>
      api
        .get<ProvisioningTokenRead[]>(`/orgs/${orgId}/provisioning-tokens`)
        .then((r) => r.data),
    enabled: !!orgId,
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api
        .post<ProvisioningTokenRead>(`/orgs/${orgId}/provisioning-tokens`, {
          label,
          expires_at: noExpiry ? null : expiresAt ? new Date(expiresAt).toISOString() : null,
          max_uses: maxUses ? Number(maxUses) : null,
        })
        .then((r) => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['provisioning-tokens'] })
      setCreatedToken(data.token_value ?? null)
      resetForm()
    },
  })

  const revokeMutation = useMutation({
    mutationFn: (id: number) =>
      api.post(`/orgs/${orgId}/provisioning-tokens/${id}/revoke`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['provisioning-tokens'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      api.delete(`/orgs/${orgId}/provisioning-tokens/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['provisioning-tokens'] }),
  })

  function resetForm() {
    setLabel('')
    setNoExpiry(false)
    setExpiresAt('')
    setMaxUses('')
  }

  function closeDrawer() {
    setDrawerOpen(false)
    setCreatedToken(null)
    resetForm()
  }

  const minDate = new Date(Date.now() + 60000).toISOString().slice(0, 16)
  const canCreate = label.trim().length > 0 && (noExpiry || expiresAt.length > 0)

  return (
    <>
      <Topbar title={t('provisioning.title')}>
        <Button size="sm" onClick={() => setSdDrawerOpen(true)}>
          {t('brightsign_sd.button')}
        </Button>
        <Button size="sm" onClick={() => setPayloadDrawerOpen(true)}>
          {t('provisioning.payload_button')}
        </Button>
        <Button size="sm" onClick={() => setOpKeyDrawerOpen(true)}>
          {t('provisioning.opkey_button')}
        </Button>
        <Button size="sm" onClick={() => { setCreatedToken(null); setDrawerOpen(true) }}>
          {t('provisioning.new_token')}
        </Button>
      </Topbar>
      {orgId && <BrightSignSdDrawer orgId={orgId} open={sdDrawerOpen} onClose={() => setSdDrawerOpen(false)} />}
      {orgId && <PayloadDrawer orgId={orgId} open={payloadDrawerOpen} onClose={() => setPayloadDrawerOpen(false)} />}
      {orgId && <OperatorKeyDrawer orgId={orgId} open={opKeyDrawerOpen} onClose={() => setOpKeyDrawerOpen(false)} />}

      <main className="flex-1 overflow-y-auto">
        <div className="w-full px-6 py-8 space-y-6">

          <p className="text-sm text-gray-500">{t('provisioning.hint')}</p>

          {isLoading ? (
            <div className="flex justify-center py-8">
              <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : tokens.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3 text-gray-400">
              <KeyRound className="w-10 h-10" />
              <p className="text-sm">{t('provisioning.no_tokens')}</p>
            </div>
          ) : (
            <>
              <div className="relative mb-4">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('common.search')}
                  className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
                />
              </div>
            <div className="bg-surface rounded-lg border border-gray-200 overflow-y-auto max-h-[60vh] shadow-sf-card">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
                  <tr>
                    {['col_label', 'col_prefix', 'col_uses', 'col_expires', 'col_status'].map((k) => (
                      <th key={k} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                        {t(`provisioning.${k}`)}
                      </th>
                    ))}
                    <th className="w-10" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {tokens.filter((tok) => !search || (tok.label ?? '').toLowerCase().includes(search.toLowerCase()) || tok.key_prefix.toLowerCase().includes(search.toLowerCase())).map((tok) => (
                    <tr key={tok.id_key}>
                      <td className="px-4 py-3 font-medium text-gray-900">{tok.label ?? '—'}</td>
                      <td className="px-4 py-3 font-mono text-xs text-gray-500">{tok.key_prefix}…</td>
                      <td className="px-4 py-3 text-gray-600">
                        {tok.use_count}
                        {tok.max_uses !== null ? ` / ${tok.max_uses}` : ''}
                      </td>
                      <td className="px-4 py-3 text-gray-500">{formatDate(tok.expires_at)}</td>
                      <td className="px-4 py-3">
                        <StatusBadge
                          status={tok.is_active ? 'online' : 'offline'}
                          label={tok.is_active ? t('provisioning.active') : t('provisioning.revoked')}
                        />
                      </td>
                      <td className="px-4 py-3">
                        {tok.is_active ? (
                          <button
                            onClick={() => {
                              if (confirm(t('provisioning.revoke_confirm'))) {
                                revokeMutation.mutate(tok.id_key)
                              }
                            }}
                            className="text-gray-300 hover:text-warning transition-sf"
                            title={t('provisioning.revoke')}
                          >
                            <Ban className="w-4 h-4" />
                          </button>
                        ) : (
                          <button
                            onClick={() => {
                              if (confirm(t('provisioning.delete_confirm'))) {
                                deleteMutation.mutate(tok.id_key)
                              }
                            }}
                            className="text-gray-300 hover:text-danger transition-sf"
                            title={t('provisioning.delete')}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </>
          )}
        </div>
      </main>

      <Drawer open={drawerOpen} onClose={closeDrawer} title={t('provisioning.new_token')}>
        {createdToken ? (
          <div className="space-y-5">
            <div className="rounded-lg bg-green-50 dark:bg-green-500/15 border border-green-200 dark:border-green-500/30 p-4 space-y-3">
              <p className="text-sm font-medium text-green-800 dark:text-green-200">{t('provisioning.token_created')}</p>
              <p className="text-xs text-green-700 dark:text-green-300">{t('provisioning.token_one_time')}</p>
              <div className="flex items-center gap-2 bg-surface rounded border border-green-200 dark:border-green-500/30 px-3 py-2">
                <code className="flex-1 text-xs font-mono text-gray-800 break-all">{createdToken}</code>
                <CopyButton value={createdToken} />
              </div>
            </div>
            <p className="text-xs text-gray-500">{t('provisioning.token_use_hint')}</p>
            <Button variant="secondary" className="w-full" onClick={closeDrawer}>
              {t('common.close')}
            </Button>
          </div>
        ) : (
          <div className="space-y-5">
            <Input
              label={t('provisioning.label_field')}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('provisioning.label_placeholder')}
              autoFocus
            />

            {/* Expiry */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-gray-700">{t('provisioning.expires_field')}</label>
                <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={noExpiry}
                    onChange={(e) => {
                      setNoExpiry(e.target.checked)
                      if (e.target.checked) setExpiresAt('')
                    }}
                    className="rounded-lg border-gray-300 text-accent focus:ring-accent/40"
                  />
                  {t('provisioning.no_expiry')}
                </label>
              </div>
              {!noExpiry && (
                <input
                  type="datetime-local"
                  min={minDate}
                  value={expiresAt}
                  onChange={(e) => setExpiresAt(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
              )}
            </div>

            <Input
              label={t('provisioning.max_players_field')}
              type="number"
              min={1}
              value={maxUses}
              onChange={(e) => setMaxUses(e.target.value)}
              placeholder={t('provisioning.max_players_placeholder')}
            />

            <Button
              onClick={() => createMutation.mutate()}
              loading={createMutation.isPending}
              disabled={!canCreate}
              className="w-full"
            >
              {t('provisioning.generate')}
            </Button>
          </div>
        )}
      </Drawer>
    </>
  )
}
