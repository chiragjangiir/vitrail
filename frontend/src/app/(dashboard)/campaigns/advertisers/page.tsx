'use client'

// Retail Media §2.8 (S1) — annonceurs : CRUD simple (liste cartes + drawer).
// + S7 B2 : section « Accès portail » (comptes externes lecture seule, org-admin).
import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Copy, Handshake, KeyRound, Plus, Tags, Trash2, UserX } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import { CardGrid, EntityCard } from '@/components/ui/CardGrid'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'

interface Advertiser {
  id_advertiser: number; advertiser_name: string; contact_name: string | null
  contact_email: string | null; notes: string | null; is_active: boolean
  campaign_count: number; created_at: string
  allow_visual_campaigns: boolean; allow_audio_campaigns: boolean
  industry_categories: number[]; industry_category_names: string[]
}

interface IndustryCategory {
  id_category: number; category_name: string
  advertiser_count: number; excluded_site_count: number
}

interface PortalUser {
  id_user: number; email: string; full_name: string | null
  is_active: boolean; is_demo: boolean; last_login_at: string | null; created_at: string
}

const empty = {
  advertiser_name: '', contact_name: '', contact_email: '', notes: '',
  allow_visual_campaigns: true, allow_audio_campaigns: false,
  industry_categories: [] as number[],
}

export default function AdvertisersPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const isAdmin = useAuthStore((s) => s.isAdmin)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [catDrawerOpen, setCatDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<Advertiser | null>(null)
  const [form, setForm] = useState({ ...empty })
  const [err, setErr] = useState('')

  const { data: advertisers = [], isLoading } = useQuery<Advertiser[]>({
    queryKey: ['advertisers'],
    queryFn: () => api.get<Advertiser[]>('/advertisers/').then((r) => r.data),
  })
  // Catégories d'industrie (exclusion concurrentielle #10) — liste gérée par l'org
  const { data: categories = [] } = useQuery<IndustryCategory[]>({
    queryKey: ['industry-categories'],
    queryFn: () => api.get<IndustryCategory[]>('/campaigns/industry-categories').then((r) => r.data),
  })

  const openCreate = () => { setEditing(null); setForm({ ...empty }); setErr(''); setDrawerOpen(true) }
  const openEdit = (a: Advertiser) => {
    setEditing(a)
    setForm({
      advertiser_name: a.advertiser_name, contact_name: a.contact_name ?? '',
      contact_email: a.contact_email ?? '', notes: a.notes ?? '',
      allow_visual_campaigns: a.allow_visual_campaigns ?? true,
      allow_audio_campaigns: a.allow_audio_campaigns ?? false,
      industry_categories: a.industry_categories ?? [],
    })
    setErr('')
    setDrawerOpen(true)
  }

  const save = useMutation({
    mutationFn: () => {
      const body = {
        advertiser_name: form.advertiser_name,
        contact_name: form.contact_name || null,
        contact_email: form.contact_email || null,
        notes: form.notes || null,
        allow_visual_campaigns: form.allow_visual_campaigns,
        allow_audio_campaigns: form.allow_audio_campaigns,
        industry_categories: form.industry_categories,
      }
      return editing
        ? api.put(`/advertisers/${editing.id_advertiser}`, body)
        : api.post('/advertisers/', body)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['advertisers'] })
      setDrawerOpen(false)
    },
    onError: () => setErr(t('common.error')),
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/advertisers/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['advertisers'] }),
    onError: (e) => alert(
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      || t('common.error')),
  })

  return (
    <>
      <Topbar title={t('campaigns.advertisers_title')}>
        <Button size="sm" onClick={() => setCatDrawerOpen(true)}>
          <Tags className="w-3.5 h-3.5 mr-1" />{t('campaigns.industry_categories')}
        </Button>
        <Button size="sm" onClick={openCreate}>{t('campaigns.new_advertiser')}</Button>
      </Topbar>

      <main className="flex-1 overflow-y-auto">
        <div className="px-6 py-8">
          {isLoading ? (
            <div className="flex justify-center py-16">
              <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : advertisers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3 text-gray-400">
              <Handshake className="w-10 h-10" />
              <p className="text-sm">{t('campaigns.no_advertisers')}</p>
            </div>
          ) : (
            <CardGrid minItemWidth={300}>
              {advertisers.map((a) => (
                <EntityCard
                  key={a.id_advertiser}
                  onClick={() => openEdit(a)}
                  title={a.advertiser_name}
                  titleTitle={a.advertiser_name}
                  subtitle={a.contact_email || a.contact_name || undefined}
                  actions={
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (confirm(t('campaigns.delete_advertiser_confirm'))) remove.mutate(a.id_advertiser)
                      }}
                      className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf"
                      title={t('common.delete')}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  }
                  footer={
                    <span className="text-gray-400">
                      {t('campaigns.campaign_count', { count: a.campaign_count })}
                      {(a.industry_category_names ?? []).length > 0
                        && <> · {a.industry_category_names.join(', ')}</>}
                    </span>
                  }
                />
              ))}
            </CardGrid>
          )}
        </div>
      </main>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)}
              title={editing ? editing.advertiser_name : t('campaigns.new_advertiser')}>
        <div className="space-y-5">
          <Input label={t('campaigns.advertiser_name')} value={form.advertiser_name}
                 onChange={(e) => setForm({ ...form, advertiser_name: e.target.value })} autoFocus />
          <Input label={t('campaigns.contact_name')} value={form.contact_name}
                 onChange={(e) => setForm({ ...form, contact_name: e.target.value })} />
          <Input label={t('campaigns.contact_email')} type="email" value={form.contact_email}
                 onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
          <Input label={t('campaigns.notes')} value={form.notes}
                 onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          {/* Types de campagne autorisés au PORTAIL self-service (migr 0095) — le
              retailer CMS reste libre ; ceci gate seulement ce que l'annonceur peut créer. */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              {t('campaigns.portal_kinds_label')}
            </label>
            <div className="flex flex-col gap-1.5">
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={form.allow_visual_campaigns}
                       onChange={(e) => setForm({ ...form, allow_visual_campaigns: e.target.checked })}
                       className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                {t('campaigns.portal_kind_visual')}
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={form.allow_audio_campaigns}
                       onChange={(e) => setForm({ ...form, allow_audio_campaigns: e.target.checked })}
                       className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                {t('campaigns.portal_kind_audio')}
              </label>
            </div>
            <p className="text-xs text-gray-400 mt-1">{t('campaigns.portal_kinds_hint')}</p>
          </div>
          {/* Exclusion concurrentielle #10 : les catégories déterminent les sites où
              cet annonceur ne peut PAS diffuser — MULTI (une agence de pub porte
              plusieurs industries, retour Ed 12/07) */}
          {categories.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                {t('campaigns.industry_category')}
              </label>
              <div className="flex flex-wrap gap-1.5">
                {categories.map((c) => {
                  const active = form.industry_categories.includes(c.id_category)
                  return (
                    <button key={c.id_category} type="button"
                            onClick={() => setForm({
                              ...form,
                              industry_categories: active
                                ? form.industry_categories.filter((id) => id !== c.id_category)
                                : [...form.industry_categories, c.id_category],
                            })}
                            className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-sf ${
                              active
                                ? 'bg-accent text-white border-accent'
                                : 'bg-surface text-gray-600 border-gray-200 hover:bg-canvas'
                            }`}>
                      {c.category_name}
                    </button>
                  )
                })}
              </div>
              <p className="text-xs text-gray-400 mt-1">{t('campaigns.industry_category_hint')}</p>
            </div>
          )}
          {err && <p className="text-sm text-danger">{err}</p>}
          <Button onClick={() => save.mutate()} loading={save.isPending}
                  disabled={!form.advertiser_name.trim()} className="w-full">
            {editing ? t('common.save') : t('common.create')}
          </Button>

          {/* Accès portail (S7 B2) — org-admin : comptes externes lecture seule */}
          {editing && isAdmin() && (
            <PortalAccessSection advertiser={editing} t={t} />
          )}
        </div>
      </Drawer>

      <CategoriesDrawer open={catDrawerOpen} onClose={() => setCatDrawerOpen(false)}
                        categories={categories} t={t} />
    </>
  )
}

// ── Catégories d'industrie (#10) ────────────────────────────────────────────────
// Liste de l'org : un annonceur porte une catégorie, un site en exclut (drawer
// Sites) — les players du site sortent de l'inventaire de ces annonceurs.

function CategoriesDrawer({
  open, onClose, categories, t,
}: {
  open: boolean
  onClose: () => void
  categories: IndustryCategory[]
  t: ReturnType<typeof useTranslations>
}) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [catErr, setCatErr] = useState('')

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['industry-categories'] })
    qc.invalidateQueries({ queryKey: ['advertisers'] })
  }
  const add = useMutation({
    mutationFn: () => api.post('/campaigns/industry-categories', { category_name: name.trim() }),
    onSuccess: () => { setName(''); setCatErr(''); refresh() },
    onError: (e) => setCatErr(
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      || t('common.error')),
  })
  const removeCat = useMutation({
    mutationFn: (id: number) => api.delete(`/campaigns/industry-categories/${id}`),
    onSuccess: refresh,
  })

  return (
    <Drawer open={open} onClose={onClose} title={t('campaigns.industry_categories')}>
      <div className="space-y-4">
        <p className="text-xs text-gray-400">{t('campaigns.industry_categories_hint')}</p>
        <div className="space-y-1">
          {categories.map((c) => (
            <div key={c.id_category}
                 className="flex items-center justify-between gap-2 text-sm bg-gray-50 rounded-lg px-3 py-2">
              <span className="text-gray-800 truncate">{c.category_name}</span>
              <span className="inline-flex items-center gap-2 shrink-0 text-xs text-gray-400">
                {t('campaigns.category_usage', {
                  advertisers: c.advertiser_count, sites: c.excluded_site_count,
                })}
                <button
                  onClick={() => {
                    if (confirm(t('campaigns.category_delete_confirm', { name: c.category_name }))) {
                      removeCat.mutate(c.id_category)
                    }
                  }}
                  className="p-0.5 text-gray-300 hover:text-danger transition-sf"
                  title={t('common.delete')}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </span>
            </div>
          ))}
          {categories.length === 0 && (
            <p className="text-xs text-gray-400 px-1">{t('campaigns.no_categories')}</p>
          )}
        </div>
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <Input label={t('campaigns.new_category')} value={name}
                   onChange={(e) => setName(e.target.value)}
                   onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) add.mutate() }} />
          </div>
          <Button size="sm" disabled={!name.trim() || add.isPending}
                  onClick={() => add.mutate()} loading={add.isPending}>
            <Plus className="w-3.5 h-3.5 mr-1" />{t('campaigns.category_add')}
          </Button>
        </div>
        {catErr && <p className="text-xs text-danger">{catErr}</p>}
      </div>
    </Drawer>
  )
}

// ── Accès portail annonceur (S7 B2) ─────────────────────────────────────────────
// Inviter par email → compte CMS_ADVERTISER lié (lecture seule de SES campagnes,
// /portal) avec mot de passe initial affiché UNE fois ; révoquer = désactivation.

function PortalAccessSection({
  advertiser, t,
}: {
  advertiser: Advertiser
  t: ReturnType<typeof useTranslations>
}) {
  const qc = useQueryClient()
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [isDemo, setIsDemo] = useState(false)
  const [invited, setInvited] = useState<{ email: string; password: string | null; linked: boolean } | null>(null)
  const [inviteErr, setInviteErr] = useState('')
  const [copied, setCopied] = useState(false)

  const { data: users = [] } = useQuery<PortalUser[]>({
    queryKey: ['advertiser-users', advertiser.id_advertiser],
    queryFn: () => api.get<PortalUser[]>(
      `/advertisers/${advertiser.id_advertiser}/users`).then((r) => r.data),
  })

  const invite = useMutation({
    mutationFn: () => api.post<{ user: PortalUser; initial_password: string | null; linked_existing: boolean }>(
      `/advertisers/${advertiser.id_advertiser}/users`,
      { email: email.trim(), full_name: fullName.trim() || null, is_demo: isDemo },
    ).then((r) => r.data),
    onSuccess: (data) => {
      setInvited({ email: data.user.email, password: data.initial_password, linked: data.linked_existing })
      setEmail(''); setFullName(''); setIsDemo(false); setInviteErr('')
      qc.invalidateQueries({ queryKey: ['advertiser-users', advertiser.id_advertiser] })
    },
    onError: (e) => setInviteErr(
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      || t('common.error')),
  })

  const revoke = useMutation({
    mutationFn: ({ id_user, purge }: { id_user: number; purge?: boolean }) => api.delete(
      `/advertisers/${advertiser.id_advertiser}/users/${id_user}${purge ? '?purge=true' : ''}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['advertiser-users', advertiser.id_advertiser] }),
  })

  const copyCreds = () => {
    if (!invited) return
    const txt = `${window.location.origin}/login\n${invited.email}\n${invited.password}`
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(txt).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="border-t border-gray-100 pt-4 space-y-2">
      <label className="text-sm font-medium text-gray-700">{t('campaigns.portal_access')}</label>
      <p className="text-xs text-gray-400">{t('campaigns.portal_access_hint')}</p>

      <div className="space-y-1">
        {users.map((u) => (
          <div key={u.id_user} className="flex items-center justify-between gap-2 text-xs bg-gray-50 rounded px-2 py-1.5">
            {/* Badge démo HORS du truncate (retour Ed 12/07 #1 : coupé par
                l'ellipse avec un email long) */}
            <span className="flex items-center gap-1.5 min-w-0">
              <span className={`truncate ${u.is_active ? 'text-gray-700' : 'text-gray-400 line-through'}`}>
                {u.email}{u.full_name ? ` · ${u.full_name}` : ''}
              </span>
              {u.is_demo && (
                <span className="shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300">
                  {t('campaigns.portal_demo_badge')}
                </span>
              )}
            </span>
            <span className="inline-flex items-center gap-2 shrink-0">
              <span className="text-gray-400">
                {u.is_active
                  ? (u.last_login_at ? u.last_login_at.slice(0, 10) : t('campaigns.portal_never_logged'))
                  : t('campaigns.portal_revoked')}
              </span>
              {u.is_active ? (
                <button
                  onClick={() => { if (confirm(t('campaigns.portal_revoke_confirm', { email: u.email }))) revoke.mutate({ id_user: u.id_user }) }}
                  className="p-0.5 text-gray-300 hover:text-danger transition-sf"
                  title={t('campaigns.portal_revoke')}
                >
                  <UserX className="w-3.5 h-3.5" />
                </button>
              ) : (
                /* Ligne révoquée : « retirer de la liste » = délier de l'annonceur
                   (retour Ed 11/07 — sinon la ligne barrée reste à vie) */
                <button
                  onClick={() => { if (confirm(t('campaigns.portal_remove_confirm', { email: u.email }))) revoke.mutate({ id_user: u.id_user, purge: true }) }}
                  className="p-0.5 text-gray-300 hover:text-danger transition-sf"
                  title={t('campaigns.portal_remove')}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </span>
          </div>
        ))}
        {users.length === 0 && <p className="text-xs text-gray-400 px-1">{t('campaigns.portal_no_users')}</p>}
      </div>

      {invited && (
        <div className="rounded-lg bg-accent/10 px-3 py-2.5 space-y-1">
          {/* get-or-link : compte existant rattaché — mdp affiché seulement s'il a été
              (re)généré (compte désactivé réactivé) ; un compte actif garde le sien */}
          {invited.linked && (
            <p className="text-xs font-medium text-accent">{t('campaigns.portal_linked_existing')}</p>
          )}
          {invited.password ? (
            <>
              <p className="text-xs font-medium text-accent inline-flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5" />{t('campaigns.portal_password_once')}
              </p>
              <p className="text-sm font-mono text-gray-800">{invited.email} · {invited.password}</p>
              <button onClick={copyCreds} className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
                <Copy className="w-3 h-3" />{copied ? t('common.copied') : t('campaigns.portal_copy_creds')}
              </button>
            </>
          ) : (
            <p className="text-sm text-gray-800">{invited.email} · {t('campaigns.portal_password_kept')}</p>
          )}
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Input label={t('campaigns.contact_email')} type="email" value={email}
                 onChange={(e) => setEmail(e.target.value)} placeholder="buyer@brand.com" />
        </div>
        <div className="flex-1">
          <Input label={t('campaigns.contact_name')} value={fullName}
                 onChange={(e) => setFullName(e.target.value)} />
        </div>
        <Button size="sm" variant="secondary"
                disabled={!email.trim() || invite.isPending}
                onClick={() => invite.mutate()} loading={invite.isPending}>
          <Plus className="w-3.5 h-3.5 mr-1" />{t('campaigns.portal_invite')}
        </Button>
      </div>
      <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-600"
             title={t('campaigns.portal_demo_hint')}>
        <input type="checkbox" checked={isDemo} onChange={(e) => setIsDemo(e.target.checked)}
               className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
        {t('campaigns.portal_demo_label')}
      </label>
      {inviteErr && <p className="text-xs text-danger">{inviteErr}</p>}
    </div>
  )
}
