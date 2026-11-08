'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import SearchInput from '@/components/ui/SearchInput'
import api from '@/lib/api'
import { roleLabel } from '@/lib/roleLabel'
import type { PermissionRead, RoleRead } from '@/types/api'

/**
 * Éditeur des permissions d'un rôle.
 *
 * Comble le trou de l'audit du 2026-07-20 : `POST /roles` créait un rôle vierge
 * qu'AUCUN endpoint ne pouvait ensuite garnir — il restait donc sans effet à
 * vie, et le seul rôle custom utilisable était une copie d'un rôle système, au
 * jeu de droits figé.
 *
 * Les rôles SYSTÈME sont affichés en lecture seule : ils portent `id_org = NULL`
 * et sont partagés par toutes les organisations.
 */
export default function RolePermissionsDrawer({
  role, onClose,
}: { role: RoleRead | null; onClose: () => void }) {
  const t = useTranslations()
  const qc = useQueryClient()
  const open = role !== null
  const readOnly = !!role?.is_system

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [q, setQ] = useState('')
  const [error, setError] = useState<string | null>(null)

  const { data: catalog = [] } = useQuery<PermissionRead[]>({
    queryKey: ['permissions'],
    queryFn: () => api.get<PermissionRead[]>('/permissions').then((r) => r.data),
    enabled: open,
  })

  // ⚠️ PAS de valeur par défaut `= []` ici : ce drawer reste MONTÉ en permanence sur
  // /settings/iam (rendu avec role={null}), donc la requête est désactivée et `data`
  // vaut `undefined`. Un défaut `= []` fabriquerait un tableau NEUF à chaque rendu,
  // que l'effet ci-dessous prendrait pour un changement — boucle de rendu infinie
  // ("Maximum update depth exceeded"), main thread sature, et la navigation Next
  // ne s'engage plus : depuis /settings/iam, plus aucun lien de menu ne repondait
  // (constate par Ed le 2026-07-22, reproduit et corrige le 2026-07-23).
  const { data: current } = useQuery<string[]>({
    queryKey: ['role-permissions', role?.id_role],
    queryFn: () => api.get<string[]>(`/roles/${role!.id_role}/permissions`).then((r) => r.data),
    enabled: open,
  })

  // Les droits du rôle arrivent APRÈS l'ouverture du drawer : sans cette
  // synchronisation, l'éditeur s'ouvrirait sur une sélection vide et un
  // enregistrement effacerait tout.
  // Le garde `open` sert aussi a re-synchroniser a chaque REouverture : react-query
  // sert alors la meme reference depuis son cache, donc seule la bascule de `open`
  // rejoue l'effet (sinon on rouvrirait sur une selection modifiee non enregistree).
  useEffect(() => {
    if (!open) return
    setSelected(new Set(current ?? []))
  }, [open, current])
  useEffect(() => { if (open) { setQ(''); setError(null) } }, [open])

  const save = useMutation({
    mutationFn: () =>
      api.put(`/roles/${role!.id_role}/permissions`, { permissions: [...selected] }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['role-permissions', role?.id_role] })
      qc.invalidateQueries({ queryKey: ['users', 'me'] })
      onClose()
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof msg === 'string' ? msg : t('iam.save_error'))
    },
  })

  /** Regroupé par module : 71 cases à plat seraient illisibles. */
  const grouped = useMemo(() => {
    const ql = q.trim().toLowerCase()
    const out = new Map<string, PermissionRead[]>()
    for (const p of catalog) {
      const key = `${p.module}:${p.operation}`
      if (ql && !key.includes(ql)) continue
      if (!out.has(p.module)) out.set(p.module, [])
      out.get(p.module)!.push(p)
    }
    return [...out.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [catalog, q])

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function toggleModule(perms: PermissionRead[], on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev)
      for (const p of perms.filter((x) => x.available)) {
        const key = `${p.module}:${p.operation}`
        if (on) next.add(key)
        else next.delete(key)
      }
      return next
    })
  }

  if (!role) return null

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={`${t('iam.permissions_of')} ${roleLabel(role, t)}`}
    >
      <div className="space-y-4">
        {readOnly && (
          <p className="flex items-start gap-2 rounded border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            <Lock className="w-4 h-4 shrink-0 mt-0.5" />
            {t('iam.system_role_readonly')}
          </p>
        )}

        <SearchInput
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('common.search')}
          wrapperClassName="max-w-none"
        />

        <p className="text-xs text-gray-400">
          {t('iam.permissions_selected', { count: selected.size })}
        </p>

        <div className="space-y-3">
          {grouped.map(([module, perms]) => {
            const usable = perms.filter((p) => p.available)
            const allOn = usable.length > 0 && usable.every((p) => selected.has(`${p.module}:${p.operation}`))
            return (
              <div key={module} className="border border-gray-200 rounded">
                <div className="flex items-center justify-between px-2.5 py-2 border-b border-gray-100">
                  <span className="text-sm font-medium text-gray-700">{module}</span>
                  {!readOnly && usable.length > 0 && (
                    <button
                      type="button"
                      onClick={() => toggleModule(perms, !allOn)}
                      className="text-[11px] text-accent hover:underline"
                    >
                      {allOn ? t('iam.unselect_all') : t('iam.select_all')}
                    </button>
                  )}
                </div>
                <div className="p-1.5 space-y-0.5">
                  {perms.map((p) => {
                    const key = `${p.module}:${p.operation}`
                    return (
                      <label
                        key={key}
                        title={!p.available ? t('iam.permission_unavailable') : p.description ?? key}
                        className={`flex items-center gap-2 px-1.5 py-1 rounded ${
                          p.available && !readOnly
                            ? 'hover:bg-gray-50 cursor-pointer'
                            : 'opacity-50 cursor-not-allowed'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={selected.has(key)}
                          disabled={readOnly || !p.available}
                          onChange={() => toggle(key)}
                          className="rounded-lg border-gray-300 text-accent focus:ring-accent/40"
                        />
                        <span className="text-sm text-gray-800 flex-1">{p.operation}</span>
                        {!p.available && (
                          <span className="text-[10px] uppercase tracking-wide text-gray-400">
                            {t('iam.coming_soon')}
                          </span>
                        )}
                      </label>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>

        {error && <p className="text-sm text-danger">{error}</p>}

        {!readOnly && (
          <Button onClick={() => save.mutate()} loading={save.isPending} className="w-full">
            {t('common.save')}
          </Button>
        )}
      </div>
    </Drawer>
  )
}
