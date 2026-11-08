'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, Trash2, Sparkles } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import DataTable, { type Column } from '@/components/ui/DataTable'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'

interface FeedbackRow {
  id_feedback: number
  feedback_type: string
  description: string
  page_url: string | null
  route: string | null
  user_agent: string | null
  app_version: string | null
  console_errors: string[]
  screenshot_urls: string[]
  severity: number | null
  status: string
  admin_note: string | null
  ai_category: string | null
  ai_severity: number | null
  ai_summary: string | null
  ai_processed_at: string | null
  created_at: string
  org_name: string | null
  author_email: string | null
}

const STATUSES = ['new', 'triaged', 'planned', 'in_progress', 'done', 'rejected']
const TYPES = ['bug', 'suggestion', 'amelioration', 'ux', 'question']

const TYPE_CLS: Record<string, string> = {
  bug: 'bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-300',
  suggestion: 'bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300',
  amelioration: 'bg-violet-100 dark:bg-violet-500/20 text-violet-700 dark:text-violet-300',
  ux: 'bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300',
  question: 'bg-gray-100 text-gray-600',
}
const STATUS_BADGE: Record<string, 'online' | 'offline' | 'warning' | 'pending'> = {
  new: 'warning', triaged: 'pending', planned: 'pending',
  in_progress: 'pending', done: 'online', rejected: 'offline',
}

export default function FeedbackAdminPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [sel, setSel] = useState<FeedbackRow | null>(null)
  const [note, setNote] = useState('')
  const [status, setStatus] = useState('new')

  const params = new URLSearchParams()
  if (statusFilter) params.set('status_filter', statusFilter)
  if (typeFilter) params.set('feedback_type', typeFilter)

  const { data: rows = [], isLoading, error } = useQuery<FeedbackRow[]>({
    queryKey: ['feedback', statusFilter, typeFilter],
    queryFn: () => api.get<FeedbackRow[]>(`/admin/feedback?${params.toString()}`).then((r) => r.data),
    retry: false,
  })
  const forbidden = (error as { response?: { status?: number } })?.response?.status === 403

  const open = (r: FeedbackRow) => { setSel(r); setNote(r.admin_note ?? ''); setStatus(r.status) }

  const save = useMutation({
    mutationFn: () => api.patch(`/admin/feedback/${sel!.id_feedback}`, { status, admin_note: note }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['feedback'] }); setSel(null) },
  })
  const del = useMutation({
    mutationFn: () => api.delete(`/admin/feedback/${sel!.id_feedback}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['feedback'] }); setSel(null) },
  })

  const columns: Column<FeedbackRow>[] = [
    { key: 'created_at', header: t('feedback.col_date'),
      render: (r) => <span className="text-xs text-gray-500">{new Date(r.created_at).toLocaleDateString()}</span> },
    { key: 'org_name', header: t('feedback.col_org'),
      render: (r) => <span className="text-xs text-gray-600">{r.org_name}</span> },
    { key: 'feedback_type', header: t('feedback.col_type'),
      render: (r) => (
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${TYPE_CLS[r.feedback_type] ?? 'bg-gray-100 text-gray-600'}`}>
          {t(`feedback.type_${r.feedback_type}`)}
        </span>
      ) },
    { key: 'ai_category', header: t('feedback.col_ai'),
      render: (r) => r.ai_processed_at
        ? <span className="inline-flex items-center gap-1 text-xs text-gray-600"><Sparkles className="h-3 w-3 text-accent" />{r.ai_category}{r.ai_severity ? ` · ${t(`feedback.sev_${r.ai_severity}`)}` : ''}</span>
        : <span className="text-xs text-gray-300">{t('feedback.ai_pending')}</span> },
    { key: 'description', header: t('feedback.col_desc'),
      render: (r) => <span className="block max-w-[28rem] truncate text-sm text-gray-800" title={r.description}>{r.ai_summary || r.description}</span> },
    { key: 'status', header: t('feedback.col_status'),
      render: (r) => <StatusBadge status={STATUS_BADGE[r.status] ?? 'pending'} label={t(`feedback.status_${r.status}`)} /> },
  ]

  return (
    <>
      <Topbar title={t('feedback.admin_title')} />
      <main className="flex-1 overflow-y-auto">
        {/* Largeur de reference des pages de reglages centrees : max-w-5xl
            (arbitrage Ed 2026-07-23). Ne pas diverger page par page. */}
        <div className="mx-auto max-w-5xl px-6 py-5">
          {forbidden ? (
            <div className="flex flex-col items-center justify-center py-20 text-center text-gray-500">
              <MessageSquare className="mb-3 h-10 w-10 text-gray-300" />
              <p className="text-sm">{t('orgs.reserved')}</p>
            </div>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                  className="rounded border border-gray-200 bg-surface px-2 py-1.5 text-sm">
                  <option value="">{t('feedback.filter_status')} : {t('feedback.filter_all')}</option>
                  {STATUSES.map((s) => <option key={s} value={s}>{t(`feedback.status_${s}`)}</option>)}
                </select>
                <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}
                  className="rounded border border-gray-200 bg-surface px-2 py-1.5 text-sm">
                  <option value="">{t('feedback.filter_type')} : {t('feedback.filter_all')}</option>
                  {TYPES.map((ty) => <option key={ty} value={ty}>{t(`feedback.type_${ty}`)}</option>)}
                </select>
              </div>
              <DataTable<FeedbackRow>
                columns={columns}
                data={rows}
                loading={isLoading}
                rowKey={(r) => r.id_feedback}
                onRowClick={open}
                emptyMessage={t('feedback.empty')}
              />
            </>
          )}
        </div>
      </main>

      <Drawer open={sel !== null} onClose={() => setSel(null)} title={sel ? t(`feedback.type_${sel.feedback_type}`) : ''}>
        {sel && (
          <div className="space-y-4 text-sm">
            <p className="whitespace-pre-wrap rounded-lg bg-gray-50 px-3 py-2 text-gray-800">{sel.description}</p>

            {sel.screenshot_urls?.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-gray-600">{t('feedback.screenshots')}</p>
                <div className="flex flex-wrap gap-2">
                  {sel.screenshot_urls.map((u, i) => (
                    <a key={i} href={u} target="_blank" rel="noopener noreferrer"
                      className="block h-20 w-20 overflow-hidden rounded-lg border border-gray-200 transition-opacity hover:opacity-80">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={u} alt="" className="h-full w-full object-cover" />
                    </a>
                  ))}
                </div>
              </div>
            )}

            {sel.ai_processed_at && (
              <div className="rounded-lg border border-accent/30 bg-accent/5 px-3 py-2">
                <p className="flex items-center gap-1 text-xs font-medium text-gray-700">
                  <Sparkles className="h-3.5 w-3.5 text-accent" /> {t('feedback.col_ai')}
                </p>
                <p className="mt-1 text-xs text-gray-600">
                  {sel.ai_category}{sel.ai_severity ? ` · ${t(`feedback.sev_${sel.ai_severity}`)}` : ''}
                  {sel.ai_summary ? ` — ${sel.ai_summary}` : ''}
                </p>
              </div>
            )}

            <dl className="space-y-1 text-xs text-gray-500">
              <div><span className="text-gray-400">{t('feedback.col_author')} :</span> {sel.author_email} · {sel.org_name}</div>
              {sel.severity && <div><span className="text-gray-400">{t('feedback.severity_label')} :</span> {t(`feedback.sev_${sel.severity}`)}</div>}
              {sel.route && <div><span className="text-gray-400">Route :</span> <code>{sel.route}</code></div>}
              {sel.app_version && <div><span className="text-gray-400">Version :</span> {sel.app_version}</div>}
              {sel.user_agent && <div className="truncate" title={sel.user_agent}><span className="text-gray-400">UA :</span> {sel.user_agent}</div>}
              {sel.console_errors?.length > 0 && (
                <div>
                  <span className="text-gray-400">Erreurs JS :</span>
                  <ul className="mt-1 space-y-0.5">
                    {sel.console_errors.map((e, i) => (
                      <li key={i}><code className="block break-all rounded bg-red-500/10 dark:bg-red-500/15 px-1.5 py-0.5 text-[11px] text-red-700 dark:text-red-300">{e}</code></li>
                    ))}
                  </ul>
                </div>
              )}
            </dl>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">{t('feedback.col_status')}</label>
              <select value={status} onChange={(e) => setStatus(e.target.value)}
                className="w-full rounded border border-gray-200 bg-surface px-2 py-1.5 text-sm">
                {STATUSES.map((s) => <option key={s} value={s}>{t(`feedback.status_${s}`)}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">{t('feedback.note_label')}</label>
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3}
                className="w-full resize-none rounded-lg border border-gray-200 px-2 py-1.5 text-sm focus:border-accent focus:outline-none" />
            </div>

            <div className="flex items-center justify-between pt-1">
              <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>{t('feedback.save')}</Button>
              <button type="button" onClick={() => del.mutate()} disabled={del.isPending}
                className="flex items-center gap-1 text-xs text-gray-400 transition-colors hover:text-danger">
                <Trash2 className="h-3.5 w-3.5" /> {t('feedback.delete')}
              </button>
            </div>
          </div>
        )}
      </Drawer>
    </>
  )
}
