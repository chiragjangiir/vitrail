'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Plus, Trash2, Send, CheckCircle2, AlertTriangle, Eye, EyeOff, Copy, RefreshCw } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import { isDemoBlocked } from '@/lib/demo'

interface Channel { id_channel: number; name: string; channel_type: string; config: { url?: string; recipients?: string[]; secret?: string }; enabled: boolean }
interface Rule { id_rule: number; event_type: string; id_channel: number; enabled: boolean }
interface EventType { key: string; label: string }
interface LogRow { id_log: number; event_type: string; subject: string | null; status: string; detail: string | null; created_at: string }

const inp = 'rounded-lg border border-gray-200 bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none'

export default function NotificationsPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const inv = (k: string) => qc.invalidateQueries({ queryKey: [k] })

  const { data: channels = [] } = useQuery<Channel[]>({ queryKey: ['notif-channels'], queryFn: () => api.get('/notifications/channels').then((r) => r.data) })
  const { data: rules = [] } = useQuery<Rule[]>({ queryKey: ['notif-rules'], queryFn: () => api.get('/notifications/rules').then((r) => r.data) })
  const { data: events } = useQuery<{ event_types: EventType[] }>({ queryKey: ['notif-events'], queryFn: () => api.get('/notifications/event-types').then((r) => r.data) })
  const { data: log = [] } = useQuery<LogRow[]>({ queryKey: ['notif-log'], queryFn: () => api.get('/notifications/log').then((r) => r.data), refetchInterval: 15000 })
  const eventLabel = (k: string) => events?.event_types.find((e) => e.key === k)?.label || k

  // Canal webhook (POST JSON) ou EMAIL (SMTP, destinataires séparés par des virgules)
  const [chForm, setChForm] = useState({ name: '', type: 'webhook', url: '', recipients: '' })
  const [shownSecret, setShownSecret] = useState<number | null>(null)
  const chRecipients = chForm.recipients.split(/[,;\s]+/).filter(Boolean)
  const chValid = chForm.type === 'webhook'
    ? /^https?:\/\//.test(chForm.url)
    : chRecipients.length > 0 && chRecipients.every((r) => r.includes('@'))
  const addChannel = useMutation({
    mutationFn: () => api.post('/notifications/channels', {
      name: chForm.name,
      channel_type: chForm.type,
      config: chForm.type === 'webhook' ? { url: chForm.url } : { recipients: chRecipients },
    }),
    onSuccess: () => { setChForm({ name: '', type: 'webhook', url: '', recipients: '' }); inv('notif-channels') },
  })
  const delChannel = useMutation({ mutationFn: (id: number) => api.delete(`/notifications/channels/${id}`), onSuccess: () => { inv('notif-channels'); inv('notif-rules') } })
  const toggleChannel = useMutation({ mutationFn: (c: Channel) => api.put(`/notifications/channels/${c.id_channel}`, { enabled: !c.enabled }), onSuccess: () => inv('notif-channels') })
  // Rotation du secret : on renvoie l'URL INCHANGEE avec le drapeau. Le serveur
  // reconstruit la config a partir de l'ancienne, donc omettre l'URL l'effacerait.
  const rotateSecret = useMutation({
    mutationFn: (c: Channel) => api.put(`/notifications/channels/${c.id_channel}`,
      { config: { url: c.config.url, rotate_secret: true } }),
    onSuccess: () => inv('notif-channels'),
  })
  const [testRes, setTestRes] = useState<Record<number, boolean>>({})
  const testChannel = useMutation({
    mutationFn: (id: number) => api.post(`/notifications/channels/${id}/test`).then((r) => r.data),
    onSuccess: (d, id) => { setTestRes((s) => ({ ...s, [id]: d.ok })); inv('notif-log') },
  })

  const [ruleForm, setRuleForm] = useState({ event_type: '', id_channel: 0 })
  const addRule = useMutation({
    mutationFn: () => api.post('/notifications/rules', ruleForm),
    onSuccess: () => { setRuleForm({ event_type: '', id_channel: 0 }); inv('notif-rules') },
  })
  const delRule = useMutation({ mutationFn: (id: number) => api.delete(`/notifications/rules/${id}`), onSuccess: () => inv('notif-rules') })
  const toggleRule = useMutation({ mutationFn: (r: Rule) => api.put(`/notifications/rules/${r.id_rule}`, { enabled: !r.enabled }), onSuccess: () => inv('notif-rules') })

  const card = 'rounded-lg border border-gray-200 bg-surface p-4 space-y-3 shadow-sf-card'
  const h2 = 'flex items-center gap-2 text-sm font-semibold text-gray-900'

  return (
    <>
      <Topbar title={t('nav.notifications')} />
      <main className="flex-1 overflow-y-auto">
        <div className="w-full space-y-4 px-6 py-6">
          <p className="text-sm text-gray-500">{t('notifications.intro')}</p>

          {/* Canaux */}
          <div className={card}>
            <div className={h2}><Bell className="h-4 w-4 text-accent" />{t('notifications.channels_title')}</div>
            <div className="flex flex-wrap gap-2">
              <select className={inp} value={chForm.type}
                onChange={(e) => setChForm({ ...chForm, type: e.target.value })}>
                <option value="webhook">Webhook</option>
                <option value="email">{t('notifications.ch_type_email')}</option>
              </select>
              <input className={inp} placeholder={t('notifications.ch_name_ph')} value={chForm.name}
                onChange={(e) => setChForm({ ...chForm, name: e.target.value })} />
              {chForm.type === 'webhook' ? (
                <input className={inp + ' min-w-[18rem] flex-1'} placeholder={t('notifications.ch_url_ph')} value={chForm.url}
                  onChange={(e) => setChForm({ ...chForm, url: e.target.value })} />
              ) : (
                <input className={inp + ' min-w-[18rem] flex-1'} placeholder={t('notifications.ch_recipients_ph')} value={chForm.recipients}
                  onChange={(e) => setChForm({ ...chForm, recipients: e.target.value })} />
              )}
              <Button size="sm" loading={addChannel.isPending} disabled={!chValid}
                onClick={() => addChannel.mutate()}><Plus className="mr-1 h-4 w-4" />{t('common.create')}</Button>
            </div>
            {addChannel.isError && !isDemoBlocked(addChannel.error) && <p className="text-xs text-danger">{t('common.error')}</p>}
            <ul className="divide-y divide-gray-100">
              {channels.map((c) => (
                <li key={c.id_channel} className="flex items-center gap-2 py-1.5 text-sm">
                  <input type="checkbox" checked={c.enabled} onChange={() => toggleChannel.mutate(c)} />
                  <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-gray-500">
                    {c.channel_type}
                  </span>
                  <span className="font-medium text-gray-800">{c.name}</span>
                  <span className="truncate text-xs text-gray-400">
                    {c.channel_type === 'email' ? (c.config.recipients ?? []).join(', ') : c.config.url}
                  </span>
                  <span className="flex-1" />
                  {/* Secret de signature (P1.7). Un secret qu'on ne peut pas lire ne sert a
                      rien : c'est lui que l'integrateur pose dans son verificateur. Masque
                      par defaut — il finirait sinon sur une capture d'ecran de demonstration. */}
                  {c.channel_type === 'webhook' && c.config.secret && (
                    <>
                      {shownSecret === c.id_channel ? (
                        <code className="max-w-[16rem] truncate rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-700">
                          {c.config.secret}
                        </code>
                      ) : null}
                      <button type="button" title={t('notifications.secret_show')}
                        onClick={() => setShownSecret(shownSecret === c.id_channel ? null : c.id_channel)}
                        className="text-gray-400 hover:text-accent">
                        {shownSecret === c.id_channel ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                      <button type="button" title={t('notifications.secret_copy')}
                        onClick={() => navigator.clipboard?.writeText(c.config.secret ?? '')}
                        className="text-gray-400 hover:text-accent"><Copy className="h-4 w-4" /></button>
                      <button type="button" title={t('notifications.secret_rotate')}
                        onClick={() => { if (confirm(t('notifications.secret_rotate_confirm'))) rotateSecret.mutate(c) }}
                        className="text-gray-400 hover:text-warning"><RefreshCw className="h-4 w-4" /></button>
                    </>
                  )}
                  {testRes[c.id_channel] != null && (testRes[c.id_channel]
                    ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertTriangle className="h-4 w-4 text-danger" />)}
                  <button type="button" onClick={() => testChannel.mutate(c.id_channel)}
                    className="inline-flex items-center gap-1 text-xs text-accent hover:underline"><Send className="h-3.5 w-3.5" />{t('notifications.test')}</button>
                  <button type="button" onClick={() => delChannel.mutate(c.id_channel)} title={t('common.delete')}
                    className="text-gray-400 hover:text-danger"><Trash2 className="h-4 w-4" /></button>
                </li>
              ))}
              {channels.length === 0 && <li className="py-2 text-xs text-gray-400">{t('notifications.no_channel')}</li>}
            </ul>
          </div>

          {/* Règles */}
          <div className={card}>
            <div className={h2}>{t('notifications.rules_title')}</div>
            <div className="flex flex-wrap gap-2">
              <select className={inp} value={ruleForm.event_type} onChange={(e) => setRuleForm({ ...ruleForm, event_type: e.target.value })}>
                <option value="">{t('notifications.event')}…</option>
                {(events?.event_types ?? []).map((e) => <option key={e.key} value={e.key}>{e.label}</option>)}
              </select>
              <select className={inp} value={ruleForm.id_channel} onChange={(e) => setRuleForm({ ...ruleForm, id_channel: Number(e.target.value) })}>
                <option value={0}>{t('notifications.channel')}…</option>
                {channels.map((c) => <option key={c.id_channel} value={c.id_channel}>{c.name}</option>)}
              </select>
              <Button size="sm" loading={addRule.isPending} disabled={!ruleForm.event_type || !ruleForm.id_channel}
                onClick={() => addRule.mutate()}><Plus className="mr-1 h-4 w-4" />{t('common.create')}</Button>
            </div>
            <ul className="divide-y divide-gray-100">
              {rules.map((r) => (
                <li key={r.id_rule} className="flex items-center gap-2 py-1.5 text-sm">
                  <input type="checkbox" checked={r.enabled} onChange={() => toggleRule.mutate(r)} />
                  <span className="text-gray-800">{eventLabel(r.event_type)}</span>
                  <span className="text-xs text-gray-400">→ {channels.find((c) => c.id_channel === r.id_channel)?.name || `#${r.id_channel}`}</span>
                  <span className="flex-1" />
                  <button type="button" onClick={() => delRule.mutate(r.id_rule)} title={t('common.delete')}
                    className="text-gray-400 hover:text-danger"><Trash2 className="h-4 w-4" /></button>
                </li>
              ))}
              {rules.length === 0 && <li className="py-2 text-xs text-gray-400">{t('notifications.no_rule')}</li>}
            </ul>
          </div>

          {/* Journal */}
          <div className={card}>
            <div className={h2}>{t('notifications.log_title')}</div>
            {log.length === 0 ? <p className="text-xs text-gray-400">{t('notifications.no_log')}</p> : (
              <ul className="divide-y divide-gray-100 text-sm">
                {log.map((l) => (
                  <li key={l.id_log} className="flex items-center gap-2 py-1.5">
                    {l.status === 'sent' ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-600" /> : <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-danger" />}
                    <span className="text-gray-500">{eventLabel(l.event_type)}</span>
                    <span className="truncate text-gray-700">{l.subject}</span>
                    <span className="flex-1" />
                    <span className="text-xs text-gray-400">{l.detail}</span>
                    <span className="text-xs text-gray-400">{new Date(l.created_at).toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </main>
    </>
  )
}
