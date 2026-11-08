'use client'

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, Trash2 } from 'lucide-react'

import api from '@/lib/api'
import type { DisplayConfig, PlayerRead } from '@/types/api'

/**
 * Section « Signature Proof of Play » du drawer player.
 *
 * Trois familles de players selon leur renderer :
 *  - Electron (linux / windows) : signent nativement en Ed25519, TOUJOURS → read-only « toujours actif ».
 *  - Gatés par display_config.pop_sign → toggle : renderer web (brightsign, chromeos, chrome_extension,
 *    via signflow.js/SFEd25519) ET Android natif (BouncyCastle, PopSigner.kt lit pop_sign du sync).
 *    HD1024 (BrightSign), Acer (ChromeOS), extension Chrome, Minix (Android).
 *  - Autres types non portés (tizen/webos…) : message d'indisponibilité.
 *
 * Activer le flag en cours de route est sans danger : le backend fixe la clé publique du device au 1er lot
 * signé (TOFU) puis accepte les preuves signées ; les lots non signés antérieurs restent valides.
 */
export default function PopSignSection({
  player,
  t,
  onPlayerUpdate,
}: {
  player: PlayerRead
  t: (key: string, values?: Record<string, string | number>) => string
  onPlayerUpdate?: (p: PlayerRead) => void
}) {
  const qc = useQueryClient()
  const os = (player.player_os ?? '').toLowerCase()
  const isFlagGated =
    os === 'brightsign' || /^chromeos/.test(os) || os === 'chrome_extension' || /^android/.test(os)
  const isElectronNative = /^linux/.test(os) || /^windows/.test(os)

  const dc: Partial<DisplayConfig> = player.display_config ?? {}
  const signing = dc.pop_sign === true

  const mut = useMutation({
    mutationFn: (patch: Partial<DisplayConfig>) =>
      api
        .put<PlayerRead>(`/players/${player.id_player}`, { display_config: { ...dc, ...patch } })
        .then((r) => r.data),
    onSuccess: (updated) => {
      onPlayerUpdate?.(updated)
      qc.invalidateQueries({ queryKey: ['players'] })
    },
  })

  const [purgeMsg, setPurgeMsg] = useState<string | null>(null)
  const purge = useMutation({
    mutationFn: () =>
      api.delete<{ deleted: number }>(`/pop/players/${player.id_player}`).then((r) => r.data),
    onSuccess: (d) => setPurgeMsg(t('players.pop_purge.done', { count: d.deleted })),
  })
  const onPurge = () => {
    if (!confirm(t('players.pop_purge.confirm', { name: player.player_name }))) return
    setPurgeMsg(null)
    purge.mutate()
  }

  return (
    <div className="space-y-2 pt-2 border-t border-gray-100">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
        <ShieldCheck className="w-3.5 h-3.5" />
        {t('players.pop_sign.title')}
      </p>

      {isElectronNative ? (
        <p className="text-[11px] text-gray-500 flex items-center gap-1.5">
          <ShieldCheck className="w-3.5 h-3.5 text-green-500" />
          {t('players.pop_sign.electron_native')}
        </p>
      ) : isFlagGated ? (
        <>
          <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={signing}
              disabled={mut.isPending}
              onChange={(e) => mut.mutate({ pop_sign: e.target.checked })}
              className="accent-accent"
            />
            {t('players.pop_sign.toggle')}
          </label>
          <p className="text-[11px] text-gray-400">{t('players.pop_sign.hint')}</p>
        </>
      ) : (
        <p className="text-[11px] text-gray-400">{t('players.pop_sign.unsupported')}</p>
      )}

      <div className="pt-2">
        <button
          type="button"
          onClick={onPurge}
          disabled={purge.isPending}
          className="inline-flex items-center gap-1.5 text-xs text-danger hover:underline disabled:opacity-50"
        >
          <Trash2 className="w-3.5 h-3.5" />
          {purge.isPending ? t('common.loading') : t('players.pop_purge.button')}
        </button>
        {purgeMsg && <p className="text-[11px] text-gray-500 mt-1">{purgeMsg}</p>}
      </div>
    </div>
  )
}
