'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, X, ShieldCheck, Trash2 } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import { roleLabel } from '@/lib/roleLabel'
import type { UserRead, RoleRead } from '@/types/api'

interface AssignedRole {
  id_role: number
  role_key: string
  label: string
  is_deny: boolean
}

const LOCALES = ['en', 'fr', 'es', 'pt', 'de']

/** Drawer de création / édition d'un utilisateur + assignation de rôles (§II.1).
 *  editId=null → création ; après création on bascule en édition pour assigner les rôles. */
export default function UserDrawer({
  open, editId, onClose,
}: { open: boolean; editId: number | null; onClose: () => void }) {
  const t = useTranslations()
  const qc = useQueryClient()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [locale, setLocale] = useState('en')
  const [isDemo, setIsDemo] = useState(false)
  const [createdId, setCreatedId] = useState<number | null>(null)
  const [addRoleId, setAddRoleId] = useState('')
  const [totp, setTotp] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  // L'utilisateur actif = édité, ou fraîchement créé (pour enchaîner sur les rôles).
  const activeId = editId ?? createdId

  // Charge l'utilisateur en édition.
  const { data: user } = useQuery<UserRead>({
    queryKey: ['users', editId],
    queryFn: () => api.get<UserRead>(`/users/${editId}`).then((r) => r.data),
    enabled: open && editId !== null,
  })

  // Rôles disponibles (système + custom) et rôles assignés à l'utilisateur actif.
  const { data: allRoles = [] } = useQuery<RoleRead[]>({
    queryKey: ['roles'],
    queryFn: () => api.get<RoleRead[]>('/roles').then((r) => r.data),
    enabled: open,
  })
  const { data: assigned = [] } = useQuery<AssignedRole[]>({
    queryKey: ['users', activeId, 'roles'],
    queryFn: () => api.get<AssignedRole[]>(`/users/${activeId}/roles`).then((r) => r.data),
    enabled: open && activeId !== null,
  })

  useEffect(() => {
    if (!open) return
    setError(null); setAddRoleId(''); setPassword(''); setTotp(null)
    if (editId === null) {
      setEmail(''); setFullName(''); setLocale('en'); setCreatedId(null); setIsDemo(false)
    }
  }, [open, editId])

  useEffect(() => {
    if (user) {
      setEmail(user.email); setFullName(user.full_name ?? ''); setLocale(user.locale)
      setIsDemo(user.is_demo ?? false)
    }
  }, [user])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['users'] })
    if (activeId !== null) qc.invalidateQueries({ queryKey: ['users', activeId, 'roles'] })
  }

  const saveUser = useMutation({
    mutationFn: async () => {
      if (activeId !== null) {
        return api.patch(`/users/${activeId}`, { full_name: fullName || null, locale, is_demo: isDemo })
      }
      return api.post<UserRead>('/users', { email, password, full_name: fullName || null, locale, is_demo: isDemo })
    },
    onSuccess: (res) => {
      setError(null)
      if (editId === null && createdId === null && res?.data?.id_user) {
        setCreatedId(res.data.id_user)  // bascule en édition → section rôles
      }
      invalidate()
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof msg === 'string' ? msg : t('iam.save_error'))
    },
  })

  const addRole = useMutation({
    mutationFn: (id_role: number) => api.post(`/users/${activeId}/roles`, { id_role, is_deny: false }),
    onSuccess: () => { setAddRoleId(''); invalidate() },
  })
  const removeRole = useMutation({
    mutationFn: (id_role: number) => api.delete(`/users/${activeId}/roles/${id_role}`),
    onSuccess: invalidate,
  })
  const resetTotp = useMutation({
    mutationFn: () =>
      api.post<{ secret: string; otpauth_uri: string }>(`/users/${activeId}/totp/reset`).then((r) => r.data),
    onSuccess: (d) => { setTotp(d); qc.invalidateQueries({ queryKey: ['users'] }) },
  })
  const disableTotp = useMutation({
    mutationFn: () => api.post(`/users/${activeId}/totp/disable`),
    onSuccess: () => { setTotp(null); qc.invalidateQueries({ queryKey: ['users'] }) },
  })
  const deleteUser = useMutation({
    mutationFn: () => api.delete(`/users/${activeId}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); onClose() },
  })

  const assignedIds = new Set(assigned.map((r) => r.id_role))
  // Rôles retirés de la liste :
  //  • CMS_SUPER_ADMIN — rôle PLATEFORME : le serveur refuse son assignation par
  //    un org-admin (403 « Rôle non assignable », anti-escalade). Le proposer ne
  //    menait qu'à une erreur — demande Ed 2026-07-20.
  //  • CMS_PLAYER / CMS_API_USER — rôles MORTS (audit 2026-07-20) : 0 permission,
  //    jamais lus par le code. Les players s'authentifient par jeton machine
  //    (JWT `type=player`, hors RBAC) et les clés API par leurs scopes
  //    `sfk_`/`sfr_`/`sfi_`. Les assigner n'a aucun effet.
  const HIDDEN_ROLE_KEYS = ['CMS_SUPER_ADMIN', 'CMS_PLAYER', 'CMS_API_USER']
  const assignable = allRoles.filter(
    (r) => !assignedIds.has(r.id_role) && !HIDDEN_ROLE_KEYS.includes(r.role_key)
  )
  const canSave = activeId !== null ? true : (!!email.trim() && password.length >= 8)

  const title = editId !== null
    ? t('iam.edit_user')
    : createdId !== null ? t('iam.user_created_assign') : t('iam.new_user')

  return (
    <Drawer open={open} onClose={onClose} title={title}>
      <div className="space-y-4">
        <Input label={t('iam.email')} type="email" value={email} disabled={activeId !== null}
          onChange={(e) => setEmail(e.target.value)} placeholder="user@org.com" />

        {activeId === null && (
          <Input label={t('iam.password')} type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} placeholder={t('iam.password_hint')} />
        )}

        <Input label={t('iam.full_name')} value={fullName}
          onChange={(e) => setFullName(e.target.value)} placeholder="Jane Doe" />

        <div>
          <label className="text-sm font-medium text-gray-800">{t('iam.locale')}</label>
          <select value={locale} onChange={(e) => setLocale(e.target.value)}
            className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
            {LOCALES.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
          </select>
        </div>

        <label className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 p-2.5 dark:bg-surface shadow-sf-card">
          <input type="checkbox" className="mt-0.5" checked={isDemo}
            onChange={(e) => setIsDemo(e.target.checked)} />
          <span className="text-xs text-gray-600">
            <span className="font-medium text-gray-800">{t('iam.demo_account')}</span> — {t('iam.demo_hint')}
          </span>
        </label>

        {error && <p className="text-xs text-danger bg-red-500/10 dark:bg-red-500/15 rounded-md px-3 py-2">{error}</p>}

        <Button onClick={() => saveUser.mutate()} disabled={!canSave || saveUser.isPending} size="sm">
          {activeId !== null ? t('iam.save') : t('iam.create_and_assign')}
        </Button>

        {/* ── Section rôles (uniquement quand l'utilisateur existe) ── */}
        {activeId !== null && (
          <div className="pt-4 border-t border-gray-200 space-y-3">
            <h3 className="text-sm font-semibold text-gray-900">{t('iam.roles_section')}</h3>

            <div className="flex flex-wrap gap-2">
              {assigned.length === 0 && <span className="text-xs text-gray-400">{t('iam.no_roles_assigned')}</span>}
              {assigned.map((r) => (
                <span key={r.id_role}
                  className="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded bg-accent/10 text-accent text-xs font-medium">
                  {roleLabel(r, t)}
                  <button onClick={() => removeRole.mutate(r.id_role)} aria-label={t('iam.remove_role')}
                    className="p-0.5 rounded hover:bg-accent/20">
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>

            <div className="flex gap-2">
              {/* min-w-0 : sans lui, un <select> à option très longue (ex.
                  « Gestionnaire de gouvernance (CMS_GOVERNANCE_MANAGER) ») garde sa
                  largeur intrinsèque et pousse le bouton « + » hors du drawer (retour Ed). */}
              <select value={addRoleId} onChange={(e) => setAddRoleId(e.target.value)}
                className="flex-1 min-w-0 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
                <option value="">{t('iam.pick_role')}</option>
                {assignable.map((r) => (
                  <option key={r.id_role} value={r.id_role}>{roleLabel(r, t)} ({r.role_key})</option>
                ))}
              </select>
              <Button size="sm" className="shrink-0" disabled={!addRoleId || addRole.isPending}
                onClick={() => addRole.mutate(Number(addRoleId))}>
                <Plus className="w-3.5 h-3.5" />
                {t('iam.add_role')}
              </Button>
            </div>
          </div>
        )}

        {/* ── Section 2FA / TOTP (enrôlement par l'admin → QR Google Authenticator) ── */}
        {activeId !== null && (
          <div className="pt-4 border-t border-gray-200 space-y-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4" /> {t('iam.totp_section')}
            </h3>
            {totp ? (
              <div className="space-y-2">
                <p className="text-xs text-gray-500">{t('iam.totp_scan')}</p>
                <div className="inline-block bg-surface p-3 rounded-lg border border-gray-200 shadow-sf-card">
                  <QRCodeSVG value={totp.otpauth_uri} size={160} />
                </div>
                <p className="text-xs text-gray-500">{t('iam.totp_secret')}</p>
                <code className="block text-xs bg-gray-100 p-2 rounded break-all">{totp.secret}</code>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" disabled={resetTotp.isPending}
                  onClick={() => resetTotp.mutate()}>
                  <ShieldCheck className="w-3.5 h-3.5" />
                  {user?.totp_enabled ? t('iam.totp_reset') : t('iam.totp_setup')}
                </Button>
                {user?.totp_enabled && (
                  <Button size="sm" variant="secondary" disabled={disableTotp.isPending}
                    onClick={() => disableTotp.mutate()}>
                    {t('iam.totp_disable')}
                  </Button>
                )}
              </div>
            )}
          </div>
        )}

        {/* Suppression de l'utilisateur (désactivation logique) */}
        {activeId !== null && (
          <div className="pt-4 border-t border-gray-200">
            <button type="button" disabled={deleteUser.isPending}
              onClick={() => { if (confirm(t('iam.delete_user_confirm', { email }))) deleteUser.mutate() }}
              className="flex items-center gap-1.5 text-xs text-gray-400 transition-sf hover:text-danger">
              <Trash2 className="w-3.5 h-3.5" /> {t('iam.delete_user')}
            </button>
          </div>
        )}
      </div>
    </Drawer>
  )
}
