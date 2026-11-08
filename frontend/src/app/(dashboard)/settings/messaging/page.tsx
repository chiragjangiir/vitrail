'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, Trash2 } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import SearchInput from '@/components/ui/SearchInput'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'

interface OrgIdentity {
  id_identity: number
  id_user: number
  email: string
  channel: string
  display_name: string | null
  is_active: boolean
  last_seen_at: string | null
  created_at: string
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

export default function MessagingSettingsPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')

  const { data: identities = [], error, isLoading } = useQuery<OrgIdentity[]>({
    queryKey: ['messaging-identities'],
    queryFn: () => api.get<OrgIdentity[]>('/messaging/identities').then((r) => r.data),
    retry: false,
  })
  const forbidden = (error as { response?: { status?: number } })?.response?.status === 403

  // Recherche sur l'e-mail et le nom affiché de l'utilisateur lié.
  const q = search.trim().toLowerCase()
  const shown = q
    ? identities.filter((i) =>
        i.email.toLowerCase().includes(q) || (i.display_name ?? '').toLowerCase().includes(q))
    : identities

  const del = useMutation({
    mutationFn: (id: number) => api.delete(`/messaging/identities/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['messaging-identities'] }),
  })

  return (
    <>
      <Topbar title={t('messaging.title')} />
      {/* Page verrouillée au viewport : intro + recherche fixes, seule la liste défile.
          L'ancien `max-h-[70vh]` imbriqué dans le défilement de page créait deux
          barres de défilement concurrentes. */}
      <main className="flex-1 flex flex-col min-h-0 w-full px-6 pt-5">
          {forbidden ? (
            <div className="flex flex-col items-center justify-center py-20 text-center text-gray-500">
              <Send className="mb-3 h-10 w-10 text-gray-300" />
              <p className="text-sm">{t('messaging.reserved')}</p>
            </div>
          ) : (
            <>
              <div className="shrink-0">
                <p className="mb-4 text-sm text-gray-500">{t('messaging.admin_intro')}</p>
                <div className="mb-4">
                  <SearchInput
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder={t('common.search')}
                  />
                </div>
              </div>
              {!isLoading && shown.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 gap-3 text-gray-400">
                  <Send className="w-10 h-10" />
                  <p className="text-sm">{t('messaging.empty')}</p>
                </div>
              ) : (
                <div className="flex-1 min-h-0 mb-5 bg-surface rounded-lg border border-gray-200 overflow-y-auto shadow-sf-card">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
                      <tr>
                        {['col_user', 'col_name', 'col_channel', 'col_linked_on', 'col_last_seen'].map((k) => (
                          <th
                            key={k}
                            className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide"
                          >
                            {t(`messaging.${k}`)}
                          </th>
                        ))}
                        <th className="w-10" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {shown.map((i) => (
                        <tr key={i.id_identity}>
                          <td className="px-4 py-3 font-medium text-gray-900">{i.email}</td>
                          <td className="px-4 py-3 text-gray-600">{i.display_name ?? '—'}</td>
                          <td className="px-4 py-3">
                            <StatusBadge
                              status={i.is_active ? 'online' : 'offline'}
                              label={i.channel}
                            />
                          </td>
                          <td className="px-4 py-3 text-gray-500">{formatDate(i.created_at)}</td>
                          <td className="px-4 py-3 text-gray-500">{formatDate(i.last_seen_at)}</td>
                          <td className="px-4 py-3">
                            <button
                              type="button"
                              onClick={() => {
                                if (confirm(t('messaging.unlink_confirm'))) {
                                  del.mutate(i.id_identity)
                                }
                              }}
                              disabled={del.isPending}
                              className="text-gray-300 hover:text-danger transition-sf"
                              title={t('messaging.unlink')}
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
      </main>
    </>
  )
}
