'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import api from '@/lib/api'

const SCOPES = ['org', 'site', 'player_group']

/** Drawer de création d'un groupe d'utilisateurs (§II.1). Les rôles/membres se
 *  gèrent ensuite via l'API ; v1 = création du groupe. */
export default function GroupDrawer({
  open, onClose,
}: { open: boolean; onClose: () => void }) {
  const t = useTranslations()
  const qc = useQueryClient()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [scope, setScope] = useState('org')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) { setName(''); setDescription(''); setScope('org'); setError(null) }
  }, [open])

  const create = useMutation({
    mutationFn: () => api.post('/groups', {
      group_name: name.trim(), description: description.trim() || null, scope_type: scope,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['groups'] }); onClose() },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof msg === 'string' ? msg : t('iam.save_error'))
    },
  })

  return (
    <Drawer open={open} onClose={onClose} title={t('iam.new_group')}>
      <div className="space-y-4">
        <Input label={t('iam.col_group_name')} value={name}
          onChange={(e) => setName(e.target.value)} placeholder="Marketing" />
        <Input label={t('iam.col_description')} value={description}
          onChange={(e) => setDescription(e.target.value)} placeholder={t('iam.optional')} />
        <div>
          <label className="text-sm font-medium text-gray-800">{t('iam.col_scope')}</label>
          <select value={scope} onChange={(e) => setScope(e.target.value)}
            className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
            {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        {error && <p className="text-xs text-danger bg-red-500/10 dark:bg-red-500/15 rounded-md px-3 py-2">{error}</p>}
        <Button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending} size="sm">
          {t('iam.create_group')}
        </Button>
      </div>
    </Drawer>
  )
}
