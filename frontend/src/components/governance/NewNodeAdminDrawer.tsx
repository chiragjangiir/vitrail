'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation } from '@tanstack/react-query'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import { roleLabel } from '@/lib/roleLabel'
import type { RoleRead, UserRead } from '@/types/api'

// Rôles proposés en tête : ceux qui ont un sens pour un responsable de nœud (migr 0101).
// Les autres restent accessibles, ils ne sont simplement pas mis en avant.
const SUGGESTED = ['CMS_GOVERNANCE_MANAGER', 'CMS_SITE_PROGRAMMER', 'CMS_DESIGNER', 'CMS_APPROVER']

/**
 * Créer un administrateur de nœud en un geste : compte → rôles → assignation au nœud.
 *
 * Demande d'Ed (2026-07-26). Avant, il fallait aller dans /settings/iam créer l'utilisateur,
 * lui poser ses rôles, puis revenir dans /governance le rattacher — en trois pages.
 *
 * 🔑 **Nuance de modèle affichée à l'écran, et pas seulement ici en commentaire** : le rôle dit
 * ce que la personne peut FAIRE (éditer des playlists, programmer) ; c'est l'assignation au
 * nœud qui dit OÙ. Un `CMS_SITE_PROGRAMMER` sans assignation ne cantonne personne à son
 * magasin — croire l'inverse est le genre d'erreur qui ouvre un parc entier.
 *
 * Les trois appels sont ceux de l'IAM, inchangés : les gardes d'escalade fermées le 20/07
 * (on n'accorde que ce qu'on détient) s'appliquent donc telles quelles.
 */
export default function NewNodeAdminDrawer({
  nodeId, nodeName, onClose, onCreated,
}: {
  nodeId: number
  nodeName: string
  onClose: () => void
  onCreated: () => void
}) {
  const t = useTranslations('governance')
  // `roleLabel` lit `iam.role_labels.*` : il lui faut le traducteur RACINE,
  // pas celui du namespace `governance`.
  const tRoot = useTranslations()
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [locale, setLocale] = useState('fr')
  const [roleIds, setRoleIds] = useState<number[]>([])
  const [error, setError] = useState<string | null>(null)

  const { data: roles = [] } = useQuery<RoleRead[]>({
    queryKey: ['roles'], queryFn: () => api.get<RoleRead[]>('/roles').then((r) => r.data),
  })
  // CMS_SUPER_ADMIN n'est jamais proposé (décision du 20/07), pas plus ici qu'ailleurs.
  const offered = roles
    .filter((r) => r.is_active && r.role_key !== 'CMS_SUPER_ADMIN')
    .sort((a, b) => {
      const ia = SUGGESTED.indexOf(a.role_key), ib = SUGGESTED.indexOf(b.role_key)
      if (ia !== ib) return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
      return a.role_key.localeCompare(b.role_key)
    })

  const create = useMutation({
    mutationFn: async () => {
      const user = (await api.post<UserRead>('/users', {
        email: email.trim(), password, full_name: fullName.trim() || null, locale,
      })).data
      // Rôles PUIS assignation : si un rôle est refusé (on n'accorde que ce qu'on détient),
      // mieux vaut échouer avant d'avoir donné les clés du nœud.
      for (const id_role of roleIds) {
        await api.post(`/users/${user.id_user}/roles`, { id_role })
      }
      await api.post(`/governance/nodes/${nodeId}/admins`, { id_user: user.id_user })
    },
    onSuccess: () => { setError(null); onCreated(); onClose() },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof msg === 'string' && msg ? msg : t('admin_create_error'))
    },
  })

  const field = 'w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-surface'
  const ready = email.trim().length > 3 && password.length >= 8

  return (
    <Drawer open onClose={onClose} title={t('admin_create_title', { node: nodeName })}>
      <div className="p-5 space-y-4">
        <p className="text-[11px] text-gray-400">{t('admin_create_hint')}</p>

        <label className="block">
          <span className="block text-xs text-gray-400 mb-1">{t('admin_email')}</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)}
                 type="email" autoComplete="off" className={field} />
        </label>
        <label className="block">
          <span className="block text-xs text-gray-400 mb-1">{t('admin_full_name')}</span>
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} className={field} />
        </label>
        <label className="block">
          <span className="block text-xs text-gray-400 mb-1">{t('admin_password')}</span>
          <input value={password} onChange={(e) => setPassword(e.target.value)}
                 type="text" autoComplete="new-password" className={field} />
          <span className="block text-[11px] text-gray-400 mt-1">{t('admin_password_hint')}</span>
        </label>
        <label className="block">
          <span className="block text-xs text-gray-400 mb-1">{t('admin_locale')}</span>
          <select value={locale} onChange={(e) => setLocale(e.target.value)} className={field}>
            {['fr', 'en', 'es', 'pt', 'de'].map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>

        <div>
          <span className="block text-xs text-gray-400 mb-1">{t('admin_roles')}</span>
          {/* La distinction rôle / périmètre est la seule chose qu'on puisse mal comprendre
              ici, et elle se paie cher : on l'écrit. */}
          <p className="text-[11px] text-amber-600 dark:text-amber-300 mb-1.5">
            {t('admin_roles_scope_warning')}
          </p>
          <div className="max-h-52 overflow-y-auto rounded-md border border-gray-200 divide-y divide-gray-100">
            {offered.map((r) => (
              <label key={r.id_role} className="flex items-center gap-2 px-2.5 py-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={roleIds.includes(r.id_role)}
                  onChange={(e) => setRoleIds((ids) =>
                    e.target.checked ? [...ids, r.id_role] : ids.filter((x) => x !== r.id_role))}
                  className="accent-accent"
                />
                <span className="text-sm text-gray-700">{roleLabel(r, tRoot)}</span>
                {SUGGESTED.includes(r.role_key) && (
                  <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-accent/10 text-accent">
                    {t('admin_role_suggested')}
                  </span>
                )}
              </label>
            ))}
          </div>
        </div>

        {error && <p className="text-[11px] text-danger">{error}</p>}

        <div className="flex items-center gap-2">
          <Button size="sm" disabled={!ready} loading={create.isPending}
                  onClick={() => create.mutate()}>
            {t('admin_create_submit')}
          </Button>
          <Button size="sm" variant="secondary" onClick={onClose}>{t('cancel_action')}</Button>
        </div>
      </div>
    </Drawer>
  )
}
