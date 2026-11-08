'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, UserPlus, Trash2, PauseCircle } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import TabBar from '@/components/ui/TabBar'
import DataTable, { type Column } from '@/components/ui/DataTable'
import Button from '@/components/ui/Button'
import SearchInput from '@/components/ui/SearchInput'
import StatusBadge from '@/components/ui/StatusBadge'
import api from '@/lib/api'
import { roleLabel } from '@/lib/roleLabel'
import DeletionImpactDrawer from '@/components/admin/DeletionImpactDrawer'
import { useAuthStore } from '@/store/auth'
import type { UserRead, GroupRead, RoleRead } from '@/types/api'
import UserDrawer from './components/UserDrawer'
import GroupDrawer from './components/GroupDrawer'
import RoleDrawer from './components/RoleDrawer'
import RolePermissionsDrawer from './components/RolePermissionsDrawer'

type Tab = 'users' | 'groups' | 'roles'


/** Date courte locale. `created_at` n'a besoin que du jour ; la dernière connexion gagne
 *  l'heure — savoir si quelqu'un s'est connecté « ce matin » ou « il y a trois semaines »
 *  ne se lit pas de la même façon. */
function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export default function IamPage() {
  const t = useTranslations()
  const [tab, setTab] = useState<Tab>('users')
  const [search, setSearch] = useState('')
  const [userDrawer, setUserDrawer] = useState<{ open: boolean; editId: number | null }>({ open: false, editId: null })
  const [groupOpen, setGroupOpen] = useState(false)
  const [roleOpen, setRoleOpen] = useState(false)
  // Rôle dont on édite les permissions (null = drawer fermé).
  const [permRole, setPermRole] = useState<RoleRead | null>(null)

  const { data: users = [], isLoading: loadingUsers } = useQuery<UserRead[]>({
    queryKey: ['users'],
    queryFn: () => api.get<UserRead[]>('/users').then((r) => r.data),
  })

  // Chargés au montage (pas de gating par onglet) → les badges de compteurs (Groupes/Rôles) sont
  // corrects dès l'arrivée sur la page, sans attendre l'ouverture de l'onglet.
  const { data: groups = [], isLoading: loadingGroups } = useQuery<GroupRead[]>({
    queryKey: ['groups'],
    queryFn: () => api.get<GroupRead[]>('/groups').then((r) => r.data),
  })

  const { data: roles = [], isLoading: loadingRoles } = useQuery<RoleRead[]>({
    queryKey: ['roles'],
    queryFn: () => api.get<RoleRead[]>('/roles').then((r) => r.data),
  })

  const qc = useQueryClient()
  const meId = useAuthStore((s) => s.user?.id_user)
  // P3.3 — le bouton s'appelait « Supprimer » et DÉSACTIVAIT. Les deux gestes sont
  // désormais distincts : la corbeille désactive (réversible, l'email reste pris),
  // et le tiroir d'impact porte la suppression RÉELLE, qui refuse en nommant.
  const [purgeUser, setPurgeUser] = useState<UserRead | null>(null)
  const deleteUser = useMutation({
    mutationFn: (id: number) => api.delete(`/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })
  const deleteGroup = useMutation({
    mutationFn: (id: number) => api.delete(`/groups/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['groups'] }),
  })
  const deleteRole = useMutation({
    mutationFn: (id: number) => api.delete(`/roles/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['roles'] }),
  })

  const userColumns: Column<UserRead>[] = [
    {
      key: 'email',
      header: t('iam.col_email'),
      render: (u) => <span className="font-medium text-gray-900">{u.email}</span>,
    },
    {
      key: 'full_name',
      header: t('iam.col_name'),
      render: (u) => u.full_name ?? <span className="text-gray-400">—</span>,
    },
    {
      key: 'totp_enabled',
      header: '2FA',
      render: (u) =>
        u.totp_enabled ? (
          <StatusBadge status="done" label={t('iam.2fa_on')} />
        ) : (
          <StatusBadge status="offline" label={t('iam.2fa_off')} />
        ),
    },
    {
      key: 'is_active',
      header: t('iam.col_status'),
      render: (u) =>
        u.is_active ? (
          <StatusBadge status="online" label={t('iam.status_active')} />
        ) : (
          <StatusBadge status="offline" label={t('iam.status_inactive')} />
        ),
    },
    // Demande d'Ed (31/07) : ces deux dates étaient DÉJÀ servies par l'API (`UserRead`),
    // seul l'affichage manquait. Elles répondent aux deux questions qu'on se pose devant
    // une liste de comptes : « depuis quand existe-t-il ? » et surtout « s'en sert-il
    // encore ? » — un compte actif jamais reconnecté est un accès à fermer.
    {
      key: 'created_at',
      header: t('iam.col_created'),
      render: (u) => <span className="text-gray-500 tabular-nums">{fmtDate(u.created_at)}</span>,
    },
    {
      key: 'last_login_at',
      header: t('iam.col_last_login'),
      render: (u) => u.last_login_at
        ? <span className="text-gray-500 tabular-nums">{fmtDate(u.last_login_at)}</span>
        // « Jamais » est une INFORMATION, pas une absence : on la nomme au lieu d'un tiret.
        : <span className="text-gray-400 italic">{t('iam.never_logged_in')}</span>,
    },
    {
      key: 'actions',
      header: '',
      render: (u) => u.id_user === meId ? null : (
        <div className="flex items-center gap-2">
          {/* Désactiver : geste NORMAL et réversible. Nommé pour ce qu'il fait. */}
          {u.is_active && (
            <button type="button" title={t('iam.deactivate_user')}
              onClick={(e) => { e.stopPropagation(); if (confirm(t('iam.deactivate_user_confirm', { email: u.email }))) deleteUser.mutate(u.id_user) }}
              className="p-0.5 text-gray-300 transition-sf hover:text-warning">
              <PauseCircle className="w-4 h-4" />
            </button>
          )}
          {/* Supprimer définitivement : ouvre le rapport d'impact plutôt que d'échouer. */}
          <button type="button" title={t('iam.purge_user')}
            onClick={(e) => { e.stopPropagation(); setPurgeUser(u) }}
            className="p-0.5 text-gray-300 transition-sf hover:text-danger"
            data-testid={`purge-user-${u.id_user}`}>
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      ),
    },
  ]

  const groupColumns: Column<GroupRead>[] = [
    {
      key: 'group_name',
      header: t('iam.col_group_name'),
      render: (g) => <span className="font-medium">{g.group_name}</span>,
    },
    {
      key: 'description',
      header: t('iam.col_description'),
      render: (g) => g.description ?? <span className="text-gray-400">—</span>,
    },
    {
      key: 'scope_type',
      header: t('iam.col_scope'),
      render: (g) => <span className="capitalize">{g.scope_type}</span>,
    },
    {
      key: 'actions',
      header: '',
      render: (g) => (
        <button type="button" title={t('common.delete')}
          onClick={(e) => { e.stopPropagation(); if (confirm(t('iam.delete_group_confirm', { name: g.group_name }))) deleteGroup.mutate(g.id_group) }}
          className="p-0.5 text-gray-300 transition-sf hover:text-danger">
          <Trash2 className="w-4 h-4" />
        </button>
      ),
    },
  ]

  const roleColumns: Column<RoleRead>[] = [
    {
      key: 'role_key',
      header: t('iam.col_role_key'),
      render: (r) => (
        <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{r.role_key}</code>
      ),
    },
    {
      key: 'label',
      header: t('iam.col_label'),
      render: (r) => <span className="font-medium">{roleLabel(r, t)}</span>,
    },
    {
      key: 'is_system',
      header: t('iam.col_type'),
      render: (r) =>
        r.is_system ? (
          <StatusBadge status="info" label={t('iam.role_system')} />
        ) : (
          <StatusBadge status="pending" label={t('iam.role_custom')} />
        ),
    },
    {
      key: 'actions',
      header: '',
      render: (r) => r.is_system ? null : (
        <button type="button" title={t('common.delete')}
          onClick={(e) => { e.stopPropagation(); if (confirm(t('iam.delete_role_confirm', { name: r.label }))) deleteRole.mutate(r.id_role) }}
          className="p-0.5 text-gray-300 transition-sf hover:text-danger">
          <Trash2 className="w-4 h-4" />
        </button>
      ),
    },
  ]

  const tabs = [
    { key: 'users',  label: t('iam.users_tab'),  count: users.length },
    { key: 'groups', label: t('iam.groups_tab'), count: groups.length },
    { key: 'roles',  label: t('iam.roles_tab'),  count: roles.length },
  ]

  // La recherche porte sur l'onglet COURANT plutôt que sur les seuls utilisateurs :
  // une barre placée au-dessus des onglets qui resterait inerte sur 2 des 3 onglets
  // se lirait comme un bug. Les compteurs des onglets restent les totaux réels.
  const q = search.trim().toLowerCase()
  const usersShown = q
    ? users.filter((u) =>
        (u.full_name ?? '').toLowerCase().includes(q) || u.email.toLowerCase().includes(q))
    : users
  const groupsShown = q
    ? groups.filter((g) => g.group_name.toLowerCase().includes(q))
    : groups
  const rolesShown = q
    ? roles.filter((r) => r.label.toLowerCase().includes(q) || r.role_key.toLowerCase().includes(q))
    : roles

  return (
    <>
      <Topbar title={t('nav.iam')} />
      {/* Page verrouillée au viewport : recherche + onglets + bouton d'action
          restent fixes, seule la liste défile. */}
      <main className="flex-1 flex flex-col min-h-0 w-full px-6 pt-5">
        <div className="shrink-0">
          <div className="mb-4">
            <SearchInput
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('common.search')}
            />
          </div>
          <div className="flex items-center justify-between mb-4">
            <TabBar tabs={tabs} active={tab} onChange={(k) => setTab(k as Tab)} />
            <div className="flex gap-2">
              {tab === 'users' && (
                <Button size="sm" onClick={() => setUserDrawer({ open: true, editId: null })}>
                  <UserPlus className="w-3.5 h-3.5" />
                  {t('iam.invite_user')}
                </Button>
              )}
              {tab === 'groups' && (
                <Button size="sm" onClick={() => setGroupOpen(true)}>
                  <Plus className="w-3.5 h-3.5" />
                  {t('iam.create_group')}
                </Button>
              )}
              {tab === 'roles' && (
                <Button size="sm" onClick={() => setRoleOpen(true)}>
                  <Plus className="w-3.5 h-3.5" />
                  {t('iam.create_role')}
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* La table prend toute la hauteur restante et défile en interne, sous des
            en-têtes collants (patron /settings/messaging validé par Ed) — la page
            elle-même ne défile jamais. */}
        <div className="flex-1 min-h-0 pb-5">
          {tab === 'users' && (
            <DataTable<UserRead>
              fill
              columns={userColumns}
              data={usersShown}
              loading={loadingUsers}
              rowKey={(u) => u.id_user}
              onRowClick={(u) => setUserDrawer({ open: true, editId: u.id_user })}
              emptyMessage={t('iam.no_users')}
            />
          )}
          {tab === 'groups' && (
            <DataTable<GroupRead>
              fill
              columns={groupColumns}
              data={groupsShown}
              loading={loadingGroups}
              rowKey={(g) => g.id_group}
              emptyMessage={t('iam.no_groups')}
            />
          )}
          {tab === 'roles' && (
            <DataTable<RoleRead>
              fill
              columns={roleColumns}
              data={rolesShown}
              loading={loadingRoles}
              rowKey={(r) => r.id_role}
              onRowClick={(r) => setPermRole(r)}
              emptyMessage={t('iam.no_roles')}
            />
          )}
        </div>
      </main>

      <UserDrawer open={userDrawer.open} editId={userDrawer.editId}
        onClose={() => setUserDrawer({ open: false, editId: null })} />
      <GroupDrawer open={groupOpen} onClose={() => setGroupOpen(false)} />
      <RoleDrawer open={roleOpen} onClose={() => setRoleOpen(false)} />
      <RolePermissionsDrawer role={permRole} onClose={() => setPermRole(null)} />
      {purgeUser && (
        <DeletionImpactDrawer
          open
          onClose={() => setPurgeUser(null)}
          label={purgeUser.email}
          impactUrl={`/users/${purgeUser.id_user}/deletion-impact`}
          onPurge={() => api.delete(`/users/${purgeUser.id_user}?purge=true`)}
          onSoftAction={purgeUser.is_active
            ? () => api.delete(`/users/${purgeUser.id_user}`)
            : undefined}
          softActionLabel={t('iam.deactivate_user')}
          invalidate={['users']}
        />
      )}
    </>
  )
}
