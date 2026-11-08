'use client'

// Approval Workflow §XXI (S7 C1) — file d'attente générique des demandes
// d'approbation : compteurs, filtre par statut, drawer détail (timeline des
// commentaires + actions approve/reject/request-changes/resubmit).
// v1 : resource type `campaign` (soumission depuis le drawer campagne).
import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2, ClipboardCheck, Download, FileText, MessageSquare, Pencil,
  Search, Send, Trash2, XCircle,
} from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'

interface ApprovalComment {
  id_comment: number; id_user: number; comment_text: string
  action: string | null; created_at: string; user_name?: string | null
}
interface Approval {
  id_request: number; resource_type: string; resource_id: number; status: string
  submitted_by: number; submitted_at: string; due_date: string | null; notes: string | null
  reviewed_by: number | null; reviewed_at: string | null; published_at: string | null
  resource_name?: string | null; submitted_by_name?: string | null
  reviewed_by_name?: string | null
  // Retour d'envoi email annonceur (#9) — présent quand la décision l'a demandé
  email_sent_to?: number | null; email_error?: string | null
}
interface ApprovalCreative {
  id_creative: number; media_name: string; media_type: string; duration_ms: number
  approval_status: string; preview_url: string | null; thumbnail_url: string | null
}
interface ApprovalCampaign {
  advertiser_name: string | null; industry_categories: string[]
  starts_on: string; ends_on: string
  daily_hours: { start: string; end: string } | null
  sov_percent: number; priority: number; pricing_model: string
  price_amount: number | null; price_currency: string; cpm_rate: number | null
  targets: { target_type: string; name: string | null }[]
  target_player_count: number
  occupancy: { warning: boolean; blocked: boolean; max_projected_pct: number } | null
  // SOV réalisable (anti-martèlement) — le valideur voit l'écart demandé/physique
  achievable?: { max_sov_pct: number; worst_player_name: string | null } | null
  other_campaigns: {
    id_campaign: number; campaign_name: string; sov_percent: number
    starts_on: string; ends_on: string; shared_players: number
  }[]
  price: { estimated_price: number; priced_players: number; unpriced_players: number; days: number } | null
}
/** Contenu gouverné §XVIII : aperçu du BROUILLON soumis (ce que le valideur approuve). */
interface ApprovalPlaylist {
  id_playlist: number; playlist_name: string; item_count: number
  items: { media_name: string | null; media_type: string | null; duration_ms: number | null; thumbnail_url: string | null }[]
  /** Réglages en attente (rotation) — une boucle qui change sans que le contenu bouge. */
  pending_settings?: { key: string; from: string | number | boolean; to: string | number | boolean }[]
}
interface ApprovalDetail extends Approval {
  comments: ApprovalComment[]; creatives: ApprovalCreative[]
  campaign?: ApprovalCampaign | null
  playlist?: ApprovalPlaylist | null
}
interface Dashboard {
  pending_review: number; changes_requested: number; approved: number
  rejected: number; published: number; urgent: number; is_reviewer?: boolean
}

// Statuts terminaux = supprimables (ménage de la file, retour Ed 12/07)
const TERMINAL = ['rejected', 'published', 'cancelled']

const BADGE: Record<string, 'online' | 'info' | 'pending' | 'warning' | 'done' | 'offline'> = {
  pending_review: 'pending', changes_requested: 'warning', approved: 'info',
  published: 'online', rejected: 'offline', cancelled: 'offline',
}

const FILTERS = ['all', 'pending_review', 'changes_requested', 'approved', 'rejected', 'published'] as const

export default function ApprovalsPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const me = useAuthStore((s) => s.user)
  const isAdmin = useAuthStore((s) => s.isAdmin)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all')
  const [selected, setSelected] = useState<number | null>(null)

  // Cloche topbar (Ed #7) : /approvals?open={id} ouvre directement le drawer.
  // window.location plutôt que useSearchParams (pas de Suspense requis au build).
  useEffect(() => {
    const openId = new URLSearchParams(window.location.search).get('open')
    if (openId && !Number.isNaN(Number(openId))) setSelected(Number(openId))
  }, [])
  const [comment, setComment] = useState('')
  const [err, setErr] = useState('')
  const [search, setSearch] = useState('')
  // Email annonceur à la décision (#9) : case cochée par défaut + retour d'envoi
  const [notifyEmail, setNotifyEmail] = useState(true)
  const [emailInfo, setEmailInfo] = useState<{ text: string; tone: 'ok' | 'warn' | 'err' } | null>(null)

  const { data: dash } = useQuery<Dashboard>({
    queryKey: ['approvals-dashboard'],
    queryFn: () => api.get<Dashboard>('/approvals/dashboard').then((r) => r.data),
  })
  const { data: approvals = [], isLoading } = useQuery<Approval[]>({
    queryKey: ['approvals', filter],
    queryFn: () => api.get<Approval[]>(
      filter === 'all' ? '/approvals/' : `/approvals/?status=${filter}`
    ).then((r) => r.data),
  })
  const { data: detail } = useQuery<ApprovalDetail>({
    queryKey: ['approval', selected],
    queryFn: () => api.get<ApprovalDetail>(`/approvals/${selected}`).then((r) => r.data),
    enabled: selected !== null,
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['approvals'] })
    qc.invalidateQueries({ queryKey: ['approvals-dashboard'] })
    if (selected !== null) qc.invalidateQueries({ queryKey: ['approval', selected] })
  }

  const act = useMutation({
    mutationFn: ({ action, body }: { action: string; body: { comment?: string; notify_advertiser?: boolean } }) =>
      api.post<Approval>(`/approvals/${selected}/${action}`, body),
    onSuccess: (r) => {
      setComment(''); setErr(''); refresh()
      const d = r.data
      if (d?.email_error) {
        setEmailInfo({ text: `${t('approvals.email_failed')} — ${d.email_error}`, tone: 'err' })
      } else if (d?.email_sent_to != null) {
        setEmailInfo(d.email_sent_to > 0
          ? { text: t('approvals.email_sent', { count: d.email_sent_to }), tone: 'ok' }
          : { text: t('approvals.email_no_recipients'), tone: 'warn' })
      }
    },
    onError: (e: unknown) => {
      const detail_ = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErr(detail_ || t('approvals.action_error'))
    },
  })

  // Ménage : suppression d'une demande TERMINÉE (le backend refuse les actives)
  const removeReq = useMutation({
    mutationFn: (id: number) => api.delete(`/approvals/${id}`),
    onSuccess: () => { if (selected !== null) setSelected(null); refresh() },
  })

  // Exports CSV/PDF (suivent le filtre de statut courant)
  const download = async (fmt: 'csv' | 'pdf') => {
    const qs = filter === 'all' ? '' : `?status=${filter}`
    const r = await api.get(`/approvals/export.${fmt}${qs}`, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `approvals.${fmt}`
    a.click()
    URL.revokeObjectURL(url)
  }

  const needComment = (action: string) =>
    (action === 'reject' || action === 'request-changes') && !comment.trim()

  const runAction = (action: string) => {
    if (needComment(action)) { setErr(t('approvals.comment_required')); return }
    const isDecision = ['approve', 'reject', 'request-changes'].includes(action)
    act.mutate({ action, body: {
      comment: comment.trim() || undefined,
      // #9 : email annonceur seulement sur une décision de campagne
      ...(isDecision && detail?.resource_type === 'campaign'
        ? { notify_advertiser: notifyEmail } : {}),
    } })
  }

  const counters: { key: (typeof FILTERS)[number]; value: number }[] = dash ? [
    { key: 'pending_review', value: dash.pending_review },
    { key: 'changes_requested', value: dash.changes_requested },
    { key: 'approved', value: dash.approved },
    { key: 'rejected', value: dash.rejected },
    { key: 'published', value: dash.published },
  ] : []

  const canResubmit = detail && detail.status === 'changes_requested'
    && (isAdmin() || detail.submitted_by === me?.id_user)

  // Recherche client-side (ressource / soumetteur) — à droite des pastilles
  const q = search.trim().toLowerCase()
  const visible = q
    ? approvals.filter((a) =>
        (a.resource_name || `#${a.resource_id}`).toLowerCase().includes(q)
        || (a.submitted_by_name || '').toLowerCase().includes(q))
    : approvals
  const canDelete = (a: Approval) =>
    TERMINAL.includes(a.status) && (dash?.is_reviewer || isAdmin())

  const actionIcon = (action: string | null) => {
    if (action === 'approved') return <CheckCircle2 className="w-3.5 h-3.5 text-success" />
    if (action === 'rejected') return <XCircle className="w-3.5 h-3.5 text-danger" />
    if (action === 'changes_requested') return <Pencil className="w-3.5 h-3.5 text-warning" />
    if (action === 'submitted' || action === 'resubmitted') return <Send className="w-3.5 h-3.5 text-accent" />
    if (action === 'published') return <CheckCircle2 className="w-3.5 h-3.5 text-accent" />
    return <MessageSquare className="w-3.5 h-3.5 text-gray-400" />
  }

  return (
    <>
      <Topbar title={t('approvals.title')}>
        {/* Exports (retour Ed 12/07) — suivent le filtre de statut courant */}
        <Button size="sm" onClick={() => download('csv')}>
          <Download className="w-3.5 h-3.5 mr-1" />CSV
        </Button>
        <Button size="sm" onClick={() => download('pdf')}>
          <FileText className="w-3.5 h-3.5 mr-1" />PDF
        </Button>
      </Topbar>

      {/* Page verrouillée : les pastilles restent en place, la LISTE scrolle
          en interne (retour Ed 12/07 — la page ne bouge plus) */}
      <main className="flex-1 min-h-0 overflow-hidden flex flex-col">
        <div className="px-6 py-8 space-y-5 flex-1 min-h-0 flex flex-col">
          {/* Compteurs + filtre par statut (pills) + recherche */}
          <div className="flex items-center gap-2 flex-wrap shrink-0">
            <button
              onClick={() => setFilter('all')}
              className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-sf ${
                filter === 'all'
                  ? 'bg-accent text-white border-accent shadow-sf-accent'
                  : 'bg-surface text-gray-600 border-gray-200 hover:bg-canvas'
              }`}
            >
              {t('approvals.filter_all')}
            </button>
            {counters.map((c) => (
              <button
                key={c.key}
                onClick={() => setFilter(c.key)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-sf ${
                  filter === c.key
                    ? 'bg-accent text-white border-accent shadow-sf-accent'
                    : 'bg-surface text-gray-600 border-gray-200 hover:bg-canvas'
                }`}
              >
                {t(`approvals.st_${c.key}`)}
                <span className={`ml-1.5 ${filter === c.key ? 'text-white/80' : 'text-gray-400'}`}>
                  {c.value}
                </span>
              </button>
            ))}
            {dash && dash.urgent > 0 && (
              <span className="px-3 py-1.5 rounded-full text-xs font-medium bg-amber-500/10 text-warning border border-amber-400/20">
                {t('approvals.urgent_count', { count: dash.urgent })}
              </span>
            )}
            <div className="relative ml-auto">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('approvals.search_placeholder')}
                className="pl-9 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg bg-surface w-56 focus:outline-none focus:ring-2 focus:ring-accent/40"
              />
            </div>
          </div>

          {isLoading ? (
            <div className="flex justify-center py-16">
              <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : visible.length === 0 ? (
            <div className="flex flex-col items-center py-16 text-center">
              <ClipboardCheck className="w-10 h-10 text-gray-300 mb-3" />
              <p className="text-sm text-gray-500">{t('approvals.empty')}</p>
              <p className="text-xs text-gray-400 mt-1">{t('approvals.empty_hint')}</p>
            </div>
          ) : (
            <div className="bg-surface border border-gray-200 rounded-xl shadow-sf-card overflow-y-auto overflow-x-auto flex-1 min-h-0">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_0_theme(colors.gray.100)]">
                  <tr>
                    <th className="px-4 py-3 text-left">{t('approvals.col_resource')}</th>
                    <th className="px-4 py-3 text-left">{t('approvals.col_type')}</th>
                    <th className="px-4 py-3 text-left">{t('approvals.col_submitted_by')}</th>
                    <th className="px-4 py-3 text-left">{t('approvals.col_submitted_at')}</th>
                    <th className="px-4 py-3 text-left">{t('approvals.col_due')}</th>
                    <th className="px-4 py-3 text-left">{t('approvals.col_status')}</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((a) => (
                    <tr
                      key={a.id_request}
                      onClick={() => { setSelected(a.id_request); setComment(''); setErr(''); setEmailInfo(null) }}
                      className="border-b border-gray-100 last:border-0 hover:bg-canvas cursor-pointer transition-sf"
                    >
                      <td className="px-4 py-3 font-medium text-gray-800">
                        {a.resource_name || `#${a.resource_id}`}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {t(`approvals.type_${a.resource_type}`)}
                      </td>
                      <td className="px-4 py-3 text-gray-600">{a.submitted_by_name || '—'}</td>
                      <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                        {new Date(a.submitted_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                        {a.due_date ? new Date(a.due_date).toLocaleDateString() : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={BADGE[a.status] ?? 'pending'}
                                     label={t(`approvals.st_${a.status}`)} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        {/* Ménage (Ed 12/07) : demandes TERMINÉES seulement */}
                        {canDelete(a) && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              if (confirm(t('approvals.delete_confirm'))) removeReq.mutate(a.id_request)
                            }}
                            className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf"
                            title={t('approvals.delete_request')}
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
          )}
        </div>
      </main>

      <Drawer open={selected !== null} onClose={() => setSelected(null)}
              title={detail?.resource_name || t('approvals.title')}>
        {detail && (
          <div className="space-y-5">
            <div className="space-y-2">
              <div>
                <StatusBadge status={BADGE[detail.status] ?? 'pending'}
                             label={t(`approvals.st_${detail.status}`)} />
              </div>
              <div className="text-xs text-gray-500 space-y-0.5">
                <p>
                  {t('approvals.col_type')} : {t(`approvals.type_${detail.resource_type}`)}
                  {' · '}
                  {t('approvals.col_submitted_by')} : {detail.submitted_by_name || '—'}
                  {' · '}
                  {new Date(detail.submitted_at).toLocaleString()}
                </p>
                {detail.due_date && (
                  <p>{t('approvals.col_due')} : {new Date(detail.due_date).toLocaleString()}</p>
                )}
                {detail.reviewed_by_name && (
                  <p>{t('approvals.reviewed_by')} : {detail.reviewed_by_name}</p>
                )}
              </div>
              {/* Retour d'envoi email annonceur (#9) — affiché ici pour rester visible
                  après la décision (le bloc actions disparaît au changement d'état) */}
              {emailInfo && (
                <p className={`text-xs rounded-lg px-2.5 py-1.5 border ${
                  emailInfo.tone === 'ok'
                    ? 'bg-emerald-500/10 text-success border-emerald-400/20'
                    : emailInfo.tone === 'warn'
                      ? 'bg-amber-500/10 text-warning border-amber-400/20'
                      : 'bg-red-500/10 text-danger border-red-400/20'
                }`}>
                  {emailInfo.text}
                </p>
              )}
            </div>

            {/* Paramètres commerciaux + cibles + occupation projetée — le reviewer
                ne valide plus à l'aveugle (retour Ed 11/07) */}
            {detail.campaign && (
              <div className="bg-canvas border border-gray-100 rounded-lg p-3 space-y-2.5">
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                  <div>
                    <p className="text-xs text-gray-400">{t('campaigns.advertiser')}</p>
                    <p className="text-gray-800">
                      {detail.campaign.advertiser_name || '—'}
                      {(detail.campaign.industry_categories ?? []).length > 0 && (
                        <span className="text-gray-500"> · {detail.campaign.industry_categories.join(', ')}</span>
                      )}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">{t('approvals.period')}</p>
                    <p className="text-gray-800">
                      {new Date(detail.campaign.starts_on).toLocaleDateString()} → {new Date(detail.campaign.ends_on).toLocaleDateString()}
                      {detail.campaign.daily_hours && (
                        <span className="text-gray-500"> · {detail.campaign.daily_hours.start}–{detail.campaign.daily_hours.end}</span>
                      )}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">{t('campaigns.sov_label')}</p>
                    <p className="text-gray-800">{Number(detail.campaign.sov_percent)} % · {t('approvals.priority_short', { p: detail.campaign.priority })}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">{t('campaigns.pricing')}</p>
                    <p className="text-gray-800">
                      {t(detail.campaign.pricing_model === 'flat' ? 'campaigns.pricing_flat' : 'campaigns.pricing_sov')}
                      {detail.campaign.price_amount != null && (
                        <span> · {detail.campaign.price_amount} {detail.campaign.price_currency}</span>
                      )}
                    </p>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">{t('approvals.target')}</p>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {detail.campaign.targets.map((tg, i) => (
                      <span key={i} className="px-2 py-0.5 rounded-full bg-surface border border-gray-200 text-xs text-gray-700">
                        {tg.name || t('campaigns.target_org')}
                      </span>
                    ))}
                    <span className="px-2 py-0.5 rounded-full bg-accent/10 text-accent text-xs font-medium">
                      {t('campaigns.target_players_pill', { count: detail.campaign.target_player_count })}
                    </span>
                  </div>
                </div>
                {detail.campaign.price && (
                  <div className="text-xs rounded-lg px-2.5 py-1.5 bg-accent/10 text-accent border border-accent/20">
                    {t('campaigns.estimated_price', { price: detail.campaign.price.estimated_price })}
                    {' '}· {t('campaigns.estimated_price_details', {
                      players: detail.campaign.price.priced_players,
                      days: detail.campaign.price.days,
                    })}
                    {detail.campaign.price_amount != null && (
                      <> · {t('approvals.contract_price', {
                        price: detail.campaign.price_amount,
                        currency: detail.campaign.price_currency,
                      })}</>
                    )}
                  </div>
                )}
                {detail.campaign.occupancy && (
                  <div className={`text-xs rounded-lg px-2.5 py-1.5 border ${
                    detail.campaign.occupancy.blocked
                      ? 'bg-red-500/10 text-danger border-red-400/20'
                      : detail.campaign.occupancy.warning
                        ? 'bg-amber-500/10 text-warning border-amber-400/20'
                        : 'bg-surface text-gray-600 border-gray-200'
                  }`}>
                    {t('approvals.occupancy_max', { pct: detail.campaign.occupancy.max_projected_pct })}
                    {detail.campaign.occupancy.blocked && <> — {t('campaigns.occupancy_blocked')}</>}
                    {!detail.campaign.occupancy.blocked && detail.campaign.occupancy.warning
                      && <> — {t('campaigns.occupancy_warning')}</>}
                    {/* D'où vient l'occupation : campagnes déjà en place sur les cibles */}
                    {(detail.campaign.other_campaigns ?? []).length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {detail.campaign.other_campaigns.map((oc) => (
                          <li key={oc.id_campaign} className="text-gray-600">
                            {oc.campaign_name} : {Number(oc.sov_percent)} %
                            {' '}({new Date(oc.starts_on).toLocaleDateString()} → {new Date(oc.ends_on).toLocaleDateString()},
                            {' '}{t('campaigns.target_players_pill', { count: oc.shared_players })})
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                {/* SOV réalisable : la SOV vendue dépasse le plafond physique des
                    boucles ciblées (anti-martèlement) → sous-service garanti */}
                {detail.campaign.achievable
                  && Number(detail.campaign.sov_percent) > detail.campaign.achievable.max_sov_pct && (
                  <div className="text-xs rounded-lg px-2.5 py-1.5 border bg-amber-500/10 text-warning border-amber-400/20">
                    {t('approvals.sov_achievable', {
                      sov: Number(detail.campaign.sov_percent),
                      max: detail.campaign.achievable.max_sov_pct,
                      player: detail.campaign.achievable.worst_player_name ?? '—',
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Playlist gouvernée §XVIII (R15) — le valideur voit le BROUILLON soumis :
                approuver publiera exactement ces items. Sans cet aperçu il validerait
                un simple nom de playlist. */}
            {detail.playlist && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                  {t('approvals.playlist_preview', { count: detail.playlist.item_count })}
                </p>
                {/* Rotation en attente : le contenu peut être inchangé alors que la BOUCLE
                    change (N items par tour, ordre, pub interdite dans le bloc). */}
                {(detail.playlist.pending_settings ?? []).length > 0 && (
                  <div className="mb-2 rounded-md border border-amber-300 dark:border-amber-500/40 bg-amber-500/10 px-3 py-2 space-y-0.5">
                    <p className="text-xs font-medium text-amber-700 dark:text-amber-300">
                      {t('approvals.playlist_settings_pending')}
                    </p>
                    {detail.playlist.pending_settings!.map((s) => (
                      <p key={s.key} className="text-[11px] text-amber-700/90 dark:text-amber-300/80">
                        {t(`approvals.setting_${s.key}` as 'approvals.setting_rotation_mode')} :{' '}
                        <span className="line-through opacity-60">{String(s.from)}</span> → <span className="font-medium">{String(s.to)}</span>
                      </p>
                    ))}
                  </div>
                )}
                {detail.playlist.items.length === 0 ? (
                  <p className="text-xs text-gray-400">{t('approvals.playlist_empty')}</p>
                ) : (
                  <div className="bg-canvas border border-gray-100 rounded-lg divide-y divide-gray-100">
                    {detail.playlist.items.map((it, i) => (
                      <div key={i} className="flex items-center gap-2.5 p-2">
                        <span className="w-5 text-[11px] text-gray-400 text-right shrink-0">{i + 1}</span>
                        {it.thumbnail_url ? (
                          /* eslint-disable-next-line @next/next/no-img-element */
                          <img src={it.thumbnail_url} alt={it.media_name ?? ''}
                               className="w-14 h-8 object-cover rounded bg-black/10 shrink-0" />
                        ) : (
                          <span className="w-14 h-8 rounded bg-black/10 shrink-0" />
                        )}
                        <span className="flex-1 text-sm text-gray-800 truncate">
                          {it.media_name ?? t('approvals.playlist_item_unknown')}
                        </span>
                        <span className="text-xs text-gray-400 shrink-0">
                          {it.media_type ?? '—'}
                          {it.duration_ms ? ` · ${Math.round(it.duration_ms / 1000)}s` : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Créatifs de la campagne — le reviewer VOIT ce qu'il approuve
                (vidéo lisible inline, image affichée ; URLs signées côté backend) */}
            {(detail.creatives ?? []).length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                  {t('approvals.creatives')}
                </p>
                <div className="space-y-3">
                  {detail.creatives.map((cr) => (
                    <div key={cr.id_creative}
                         className="bg-canvas border border-gray-100 rounded-lg p-2">
                      {cr.media_type === 'video' && cr.preview_url ? (
                        <video controls preload="metadata" src={cr.preview_url}
                               poster={cr.thumbnail_url ?? undefined}
                               className="w-full max-h-56 rounded-lg bg-black" />
                      ) : (cr.preview_url || cr.thumbnail_url) ? (
                        /* eslint-disable-next-line @next/next/no-img-element */
                        <img src={cr.preview_url ?? cr.thumbnail_url ?? ''} alt={cr.media_name}
                             className="w-full max-h-56 object-contain rounded-lg bg-black/5" />
                      ) : null}
                      <div className="flex items-center justify-between gap-2 mt-1.5 px-1">
                        <span className="text-sm text-gray-800 truncate">
                          {cr.media_name}
                          {cr.duration_ms > 0 && (
                            <span className="text-xs text-gray-400 ml-1.5">
                              {Math.round(cr.duration_ms / 1000)}s
                            </span>
                          )}
                        </span>
                        {cr.approval_status !== 'approved' && (
                          <StatusBadge
                            status={cr.approval_status === 'pending' ? 'pending' : 'offline'}
                            label={t(cr.approval_status === 'pending'
                              ? 'campaigns.creative_pending' : 'campaigns.creative_rejected')} />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Timeline des commentaires */}
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                {t('approvals.timeline')}
              </p>
              <div className="space-y-2">
                {detail.comments.map((c) => (
                  <div key={c.id_comment}
                       className="flex gap-2 bg-canvas border border-gray-100 rounded-lg px-3 py-2">
                    <div className="mt-0.5 shrink-0">{actionIcon(c.action)}</div>
                    <div className="min-w-0">
                      <p className="text-xs text-gray-500">
                        <span className="font-medium text-gray-700">{c.user_name || '—'}</span>
                        {c.action && <> · {t(`approvals.act_${c.action}`)}</>}
                        {' · '}{new Date(c.created_at).toLocaleString()}
                      </p>
                      <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">
                        {c.comment_text}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Actions selon l'état (le backend re-vérifie RBAC + machine à états) */}
            {['pending_review', 'changes_requested'].includes(detail.status) && (
              <div className="space-y-3 border-t border-gray-100 pt-4">
                {detail.status === 'pending_review'
                  && (detail.creatives ?? []).some((c) => c.approval_status === 'pending') && (
                  <p className="text-xs text-gray-500">{t('approvals.approve_covers_creatives')}</p>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">
                    {t('approvals.comment_label')}
                  </label>
                  <textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    rows={2}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
                    placeholder={t('approvals.comment_placeholder')}
                  />
                </div>
                {/* #9 : notifier les comptes portail de l'annonceur à la décision */}
                {detail.resource_type === 'campaign' && (
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input type="checkbox" checked={notifyEmail}
                           onChange={(e) => setNotifyEmail(e.target.checked)}
                           className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                    {t('approvals.notify_email')}
                  </label>
                )}
                {err && <p className="text-xs text-danger">{err}</p>}
                <div className="flex items-center gap-2 flex-wrap">
                  {detail.status === 'pending_review' && (
                    <>
                      <Button size="sm" onClick={() => runAction('approve')}
                              loading={act.isPending}>
                        <CheckCircle2 className="w-3.5 h-3.5 mr-1" />{t('approvals.approve')}
                      </Button>
                      <Button size="sm" variant="secondary"
                              onClick={() => runAction('request-changes')}>
                        <Pencil className="w-3.5 h-3.5 mr-1" />{t('approvals.request_changes')}
                      </Button>
                    </>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => runAction('reject')}>
                    <XCircle className="w-3.5 h-3.5 mr-1" />{t('approvals.reject')}
                  </Button>
                  {canResubmit && (
                    <Button size="sm" onClick={() => runAction('resubmit')}>
                      <Send className="w-3.5 h-3.5 mr-1" />{t('approvals.resubmit')}
                    </Button>
                  )}
                  <Button size="sm" variant="secondary"
                          onClick={() => {
                            if (!comment.trim()) { setErr(t('approvals.comment_required')); return }
                            act.mutate({ action: 'comments', body: { comment: comment.trim() } })
                          }}>
                    <MessageSquare className="w-3.5 h-3.5 mr-1" />{t('approvals.add_comment')}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </Drawer>
    </>
  )
}
