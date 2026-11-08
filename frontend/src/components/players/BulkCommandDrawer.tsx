'use client'

/**
 * Commandes players EN MASSE (migr 0097).
 *
 * Cible canonique (org | site | site_group | group | player) résolue côté SERVEUR par
 * `targeting.players_for_targets` ; l'aperçu ci-dessous est calculé côté client à partir
 * des mêmes données pour montrer QUI sera touché AVANT d'agir — c'est un aperçu, pas la
 * décision : le serveur reste la source de vérité.
 *
 * Les commandes destructives exigent un PIN + une confirmation explicite. À l'échelle d'un
 * parc, l'erreur n'est pas rattrapable : on ne compte pas sur l'attention de l'utilisateur.
 */

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, ShieldAlert } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import api from '@/lib/api'
import { isDemoBlocked } from '@/lib/demo'
import type { PlayerGroupRead, PlayerRead, Site, SiteGroupRead } from '@/types/api'

/** Miroir EXACT de `services/pin_guard.PIN_REQUIRED_BULK_COMMANDS` (backend = autorité). */
const PIN_COMMANDS = new Set([
  'reboot_os', 'restart', 'reset_config', 'quit_app',
  'maintenance', 'hdmi_input', 'set_timezone', 'display_command',
])

/** Commandes proposées en masse (sous-ensemble utile de PlayerCommandRequest). */
const COMMANDS = [
  'screenshot', 'detect_capabilities', 'toggle_overlay',
  'restart', 'reboot_os', 'quit_app', 'maintenance',
] as const
type BulkCommand = (typeof COMMANDS)[number]

type TargetType = 'org' | 'site' | 'site_group' | 'group' | 'player'

interface Props {
  open: boolean
  onClose: () => void
  players: PlayerRead[]
  onSent: (count: number, command: string) => void
}

export default function BulkCommandDrawer({ open, onClose, players, onSent }: Props) {
  const t = useTranslations()

  const [command, setCommand] = useState<BulkCommand>('screenshot')
  const [targetType, setTargetType] = useState<TargetType>('site')
  const [targetId, setTargetId] = useState<number | null>(null)
  const [pin, setPin] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: sites = [] } = useQuery<Site[]>({
    queryKey: ['sites'], enabled: open,
    queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
  })
  const { data: siteGroups = [] } = useQuery<SiteGroupRead[]>({
    queryKey: ['site-groups'], enabled: open,
    queryFn: () => api.get<SiteGroupRead[]>('/site-groups/').then((r) => r.data),
  })
  const { data: groups = [] } = useQuery<PlayerGroupRead[]>({
    queryKey: ['player-groups'], enabled: open,
    queryFn: () => api.get<PlayerGroupRead[]>('/player-groups/').then((r) => r.data),
  })

  const needsPin = PIN_COMMANDS.has(command)

  /** Aperçu de la cible — même logique que players_for_target, côté client. */
  const affected = useMemo<PlayerRead[]>(() => {
    if (targetType === 'org') return players
    if (targetId === null) return []
    if (targetType === 'site') return players.filter((p) => p.id_site === targetId)
    if (targetType === 'player') return players.filter((p) => p.id_player === targetId)
    if (targetType === 'group') {
      const ids = new Set(groups.find((g) => g.id_group === targetId)?.player_ids ?? [])
      return players.filter((p) => ids.has(p.id_player))
    }
    // site_group : sites du groupe → players de ces sites
    const siteIds = new Set(siteGroups.find((g) => g.id_site_group === targetId)?.site_ids ?? [])
    return players.filter((p) => p.id_site !== null && siteIds.has(p.id_site))
  }, [targetType, targetId, players, groups, siteGroups])

  const options = useMemo(() => {
    if (targetType === 'site') return sites.map((s) => ({ id: s.id_site, label: s.site_name }))
    if (targetType === 'site_group') return siteGroups.map((g) => ({ id: g.id_site_group, label: g.group_name }))
    if (targetType === 'group') return groups.map((g) => ({ id: g.id_group, label: g.group_name }))
    if (targetType === 'player') return players.map((p) => ({ id: p.id_player, label: p.player_name }))
    return []
  }, [targetType, sites, siteGroups, groups, players])

  function reset() {
    setCommand('screenshot'); setTargetType('site'); setTargetId(null)
    setPin(''); setConfirmed(false); setError(null)
  }
  function close() { reset(); onClose() }

  const sendMutation = useMutation({
    mutationFn: () => api.post<{ count: number; command: string }>('/players/commands', {
      command,
      targets: [targetType === 'org'
        ? { target_type: 'org' }
        : { target_type: targetType, target_id: targetId }],
      ...(needsPin ? { pin } : {}),
    }).then((r) => r.data),
    onSuccess: (data) => { onSent(data.count, data.command); close() },
    onError: (e: unknown) => {
      if (isDemoBlocked(e)) return
      const res = (e as { response?: { status?: number; data?: { detail?: string } } })?.response
      // 412 = aucun PIN au profil : message d'action, pas « PIN incorrect ».
      if (res?.status === 412) return setError(t('players.bulk_pin_missing'))
      setError(typeof res?.data?.detail === 'string' ? res.data.detail : t('common.error'))
    },
  })

  const targetOk = targetType === 'org' || targetId !== null
  const canSend = targetOk && affected.length > 0
    && (!needsPin || (pin.length >= 4 && confirmed))
    && !sendMutation.isPending

  return (
    <Drawer open={open} onClose={close} title={t('players.bulk_title')} width="w-[520px]">
      <div className="space-y-5">
        <p className="text-xs text-gray-400">{t('players.bulk_hint')}</p>

        {/* Commande */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-gray-800">{t('players.bulk_command_label')}</label>
          <select
            value={command}
            onChange={(e) => { setCommand(e.target.value as BulkCommand); setConfirmed(false); setError(null) }}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
          >
            {COMMANDS.map((c) => (
              <option key={c} value={c}>{t(`players.bulk_cmd_${c}`)}</option>
            ))}
          </select>
        </div>

        {/* Cible */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-gray-800">{t('players.bulk_target_label')}</label>
          <div className="flex gap-1.5 flex-wrap">
            {(['org', 'site', 'site_group', 'group', 'player'] as TargetType[]).map((tt) => (
              <button
                key={tt} type="button"
                onClick={() => { setTargetType(tt); setTargetId(null) }}
                className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                  targetType === tt
                    ? 'bg-accent/10 border-accent/40 text-accent'
                    : 'border-gray-200 text-gray-500 hover:bg-surface-hover'}`}
              >
                {t(`players.bulk_target_${tt}`)}
              </button>
            ))}
          </div>
          {targetType !== 'org' && (
            <select
              value={targetId ?? ''}
              onChange={(e) => setTargetId(e.target.value ? Number(e.target.value) : null)}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
            >
              <option value="">{t('players.bulk_target_placeholder')}</option>
              {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          )}
        </div>

        {/* Aperçu : QUI va être touché, avant d'agir */}
        {targetOk && (
          <div className="rounded-lg border border-gray-200 bg-surface">
            <div className="px-3 py-2 border-b border-gray-100 text-sm text-gray-700">
              {t('players.bulk_affected', { count: affected.length })}
            </div>
            <div className="max-h-40 overflow-y-auto divide-y divide-gray-100">
              {affected.map((p) => (
                <div key={p.id_player} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${p.status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
                  <span className="text-gray-700 truncate">{p.player_name}</span>
                </div>
              ))}
              {affected.length === 0 && (
                <p className="px-3 py-2 text-xs text-gray-400">{t('players.bulk_no_target')}</p>
              )}
            </div>
          </div>
        )}

        {/* Garde des commandes destructives */}
        {needsPin && (
          <div className="space-y-3 rounded-lg border border-warning/40 bg-warning/5 p-3">
            <p className="text-sm text-amber-600 dark:text-amber-300 flex items-start gap-1.5">
              <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
              {t('players.bulk_destructive_warn', { count: affected.length })}
            </p>
            <label className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="checkbox" checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                className="mt-0.5 rounded border-gray-300 text-accent focus:ring-accent/40"
              />
              <span>{t('players.bulk_confirm', { count: affected.length })}</span>
            </label>
            <Input
              label={t('players.bulk_pin_label')}
              type="password" inputMode="numeric" autoComplete="off"
              value={pin} onChange={(e) => setPin(e.target.value)}
              hint={t('players.bulk_pin_hint')}
            />
          </div>
        )}

        {error && (
          <p className="text-sm text-danger flex items-start gap-1.5">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />{error}
          </p>
        )}

        <div className="flex gap-2">
          <Button onClick={() => sendMutation.mutate()} disabled={!canSend}>
            {sendMutation.isPending ? t('common.saving') : t('players.bulk_send')}
          </Button>
          <Button variant="secondary" onClick={close}>{t('common.cancel')}</Button>
        </div>
      </div>
    </Drawer>
  )
}
