'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import { roleLabel } from '@/lib/roleLabel'
import type { RoleRead } from '@/types/api'

/** Drawer de création d'un rôle custom (§II.1) — vierge, ou copié (avec ses
 *  permissions) depuis un rôle système/custom existant. */
export default function RoleDrawer({
  open, onClose,
}: { open: boolean; onClose: () => void }) {
  const t = useTranslations()
  const qc = useQueryClient()

  const [roleKey, setRoleKey] = useState('')
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [copyFrom, setCopyFrom] = useState('')
  const [error, setError] = useState<string | null>(null)

  const { data: roles = [] } = useQuery<RoleRead[]>({
    queryKey: ['roles'],
    queryFn: () => api.get<RoleRead[]>('/roles').then((r) => r.data),
    enabled: open,
  })

  useEffect(() => {
    if (open) { setRoleKey(''); setLabel(''); setDescription(''); setCopyFrom(''); setError(null) }
  }, [open])

  const create = useMutation({
    mutationFn: () => {
      const body = { role_key: roleKey.trim(), label: label.trim(), description: description.trim() || null }
      return copyFrom
        ? api.post(`/roles/${copyFrom}/copy`, body)
        : api.post('/roles', body)
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['roles'] }); onClose() },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof msg === 'string' ? msg : t('iam.save_error'))
    },
  })

  return (
    <Drawer open={open} onClose={onClose} title={t('iam.new_role')}>
      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium text-gray-800">{t('iam.copy_from')}</label>
          <select value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)}
            className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
            <option value="">{t('iam.copy_none')}</option>
            {/* CMS_SUPER_ADMIN exclu : la copie duplique les PERMISSIONS de la
                source, donc cloner le super-admin fabriquerait un rôle portant
                tout le catalogue — assignable sans restriction, lui. Le serveur
                refuse désormais (403 « Rôle plateforme non copiable »).
                CMS_PLAYER / CMS_API_USER exclus : rôles morts, 0 permission. */}
            {roles
              .filter((r) => !['CMS_SUPER_ADMIN', 'CMS_PLAYER', 'CMS_API_USER'].includes(r.role_key))
              .map((r) => <option key={r.id_role} value={r.id_role}>{roleLabel(r, t)} ({r.role_key})</option>)}
          </select>
          <p className="text-xs text-gray-400 mt-1">{t('iam.copy_hint')}</p>
        </div>
        <Input label={t('iam.col_role_key')} value={roleKey}
          onChange={(e) => setRoleKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))}
          placeholder="CUSTOM_MANAGER" />
        <Input label={t('iam.col_label')} value={label}
          onChange={(e) => setLabel(e.target.value)} placeholder="Custom Manager" />
        <Input label={t('iam.col_description')} value={description}
          onChange={(e) => setDescription(e.target.value)} placeholder={t('iam.optional')} />
        {error && <p className="text-xs text-danger bg-red-500/10 dark:bg-red-500/15 rounded-md px-3 py-2">{error}</p>}
        <Button onClick={() => create.mutate()}
          disabled={!roleKey.trim() || !label.trim() || create.isPending} size="sm">
          {t('iam.create_role')}
        </Button>
      </div>
    </Drawer>
  )
}
