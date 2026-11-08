'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Check, Ban, Trash2 } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'

interface OperatorKey {
  id_key: number
  key_prefix: string
  label: string | null
  expires_at: string | null
  last_used_at: string | null
  is_active: boolean
  token_value?: string | null
}

function fmt(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

export default function OperatorKeyDrawer({
  orgId, open, onClose,
}: { orgId: number; open: boolean; onClose: () => void }) {
  const t = useTranslations('provisioning')
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [days, setDays] = useState('90')
  const [created, setCreated] = useState<OperatorKey | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  const { data: keys = [] } = useQuery({
    queryKey: ['provisioning-keys', orgId],
    queryFn: async () => (await api.get<OperatorKey[]>(`/orgs/${orgId}/provisioning-keys`)).data,
    enabled: open,
  })

  const createMut = useMutation({
    mutationFn: async () =>
      (await api.post<OperatorKey>(`/orgs/${orgId}/provisioning-keys`, {
        label: label || 'operator', expires_in_days: Number(days) || 90,
      })).data,
    onSuccess: (d) => {
      setCreated(d); setLabel('')
      qc.invalidateQueries({ queryKey: ['provisioning-keys'] })
    },
  })
  const revokeMut = useMutation({
    mutationFn: async (id: number) => api.post(`/orgs/${orgId}/provisioning-keys/${id}/revoke`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['provisioning-keys'] }),
  })
  const deleteMut = useMutation({
    mutationFn: async (id: number) => api.delete(`/orgs/${orgId}/provisioning-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['provisioning-keys'] }),
  })

  const backendUrl = typeof window !== 'undefined' ? window.location.origin : ''
  const setupCmd = created
    ? `signflow-provision --cms ${backendUrl} --key ${created.token_value} --save-config`
    : ''

  function copy(text: string, key: string) {
    navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1500)
  }
  function close() { setCreated(null); onClose() }

  return (
    <Drawer open={open} onClose={close} title={t('opkey_title')}>
      <div className="space-y-5">
        <p className="text-xs text-gray-400">{t('opkey_hint')}</p>

        {created && (
          <div className="rounded-lg border border-success/30 bg-success/5 p-3 space-y-3">
            <p className="text-sm font-medium text-gray-800">{t('opkey_created')}</p>
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('opkey_key_label')}</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs bg-gray-50 border border-gray-200 rounded px-2 py-1.5 truncate">
                  {created.token_value}
                </code>
                <button onClick={() => copy(created.token_value ?? '', 'k')}
                  className="p-1.5 text-gray-400 hover:text-accent">
                  {copied === 'k' ? <Check className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
              <p className="text-[11px] text-amber-600 mt-1">{t('opkey_secret_warn')}</p>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('opkey_setup_cmd')}</label>
              <div className="flex items-start gap-2">
                <code className="flex-1 text-[11px] bg-gray-900 text-gray-100 rounded px-2 py-2 break-all">
                  {setupCmd}
                </code>
                <button onClick={() => copy(setupCmd, 'c')}
                  className="p-1.5 text-gray-400 hover:text-accent shrink-0">
                  {copied === 'c' ? <Check className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('opkey_label')}</label>
            <input value={label} onChange={(e) => setLabel(e.target.value)} className={inp}
              placeholder={t('opkey_label_ph')} />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('opkey_expires_days')}</label>
            <input value={days} onChange={(e) => setDays(e.target.value)} className={inp}
              type="number" min={1} max={730} />
          </div>
          <Button className="w-full" disabled={createMut.isPending} onClick={() => createMut.mutate()}>
            {createMut.isPending ? t('opkey_creating') : t('opkey_create')}
          </Button>
          {createMut.isError && <p className="text-xs text-danger">{t('opkey_error')}</p>}
        </div>

        <div>
          {keys.length === 0 ? (
            <p className="text-sm text-gray-400">{t('opkey_none')}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                  <th className="py-2">{t('opkey_col_key')}</th>
                  <th>{t('opkey_col_expires')}</th>
                  <th>{t('opkey_col_lastused')}</th>
                  <th>{t('opkey_col_status')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.id_key} className="border-b border-gray-50">
                    <td className="py-2">
                      <code className="text-xs">{k.key_prefix}…</code>
                      {k.label && <span className="block text-[11px] text-gray-400">{k.label}</span>}
                    </td>
                    <td className="text-xs text-gray-500">{fmt(k.expires_at)}</td>
                    <td className="text-xs text-gray-500">
                      {k.last_used_at ? fmt(k.last_used_at) : t('opkey_never_used')}
                    </td>
                    <td>
                      <StatusBadge status={k.is_active ? 'done' : 'offline'}
                        label={k.is_active ? t('active') : t('revoked')} />
                    </td>
                    <td className="text-right whitespace-nowrap">
                      {k.is_active && (
                        <button
                          onClick={() => { if (confirm(t('opkey_revoke_confirm'))) revokeMut.mutate(k.id_key) }}
                          className="p-1 text-gray-400 hover:text-amber-600" title={t('opkey_revoke')}>
                          <Ban className="w-4 h-4" />
                        </button>
                      )}
                      <button
                        onClick={() => { if (confirm(t('opkey_delete_confirm'))) deleteMut.mutate(k.id_key) }}
                        className="p-1 text-gray-400 hover:text-danger" title={t('opkey_delete')}>
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <Button variant="secondary" className="w-full" onClick={close}>{t('opkey_done')}</Button>
      </div>
    </Drawer>
  )
}

const inp = 'w-full px-3 py-2 text-sm rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface'
