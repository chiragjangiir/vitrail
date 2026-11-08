'use client'

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { Smartphone, RefreshCw, Ban, Copy, Check, RotateCcw, AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react'

import api from '@/lib/api'
import type { LocalControlProfile, PlayerBasketConfig, PlayerRead } from '@/types/api'
import NumberField from '@/components/ui/NumberField'

/**
 * Section « Contrôle local (Store Control Panel) » du drawer player (§19.3).
 * Affichée pour les players linux/rpi/windows (le serveur HTTP local embarqué
 * existe sur ces plateformes). Toggle d'activation + génération du profil/QR.
 */
export default function LocalControlSection({
  player,
  t,
  onPlayerUpdate,
}: {
  player: PlayerRead
  t: (key: string, values?: Record<string, string | number>) => string
  /** Remonte le player mis à jour pour rafraîchir le drawer (selected). */
  onPlayerUpdate?: (p: PlayerRead) => void
}) {
  const qc = useQueryClient()
  const enabled = player.display_config?.local_control_enabled === true
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)  // replié par défaut

  // Génération
  const [validity, setValidity] = useState(4)
  const [canRatio, setCanRatio] = useState(false)
  const [canVolume, setCanVolume] = useState(true)
  const [canEvent, setCanEvent] = useState(false)

  const toggleMut = useMutation({
    mutationFn: (on: boolean) =>
      api
        .put<PlayerRead>(`/players/${player.id_player}`, {
          display_config: { ...(player.display_config ?? {}), local_control_enabled: on },
        })
        .then((r) => r.data),
    onSuccess: (updated) => {
      onPlayerUpdate?.(updated) // rafraîchit selected → le toggle reflète le nouvel état
      qc.invalidateQueries({ queryKey: ['players'] })
    },
  })

  const { data: profile } = useQuery<LocalControlProfile | null>({
    queryKey: ['local-control', player.id_player],
    queryFn: () =>
      api.get<LocalControlProfile | null>(`/players/${player.id_player}/local-control/profile`).then((r) => r.data),
    enabled,
  })

  // Overrides opérateur (réglages locaux faits depuis le Store Control Panel)
  const { data: overrides = [] } = useQuery<PlayerBasketConfig[]>({
    queryKey: ['player-baskets', player.id_player],
    queryFn: () =>
      api.get<PlayerBasketConfig[]>(`/players/${player.id_player}/baskets`).then((r) => r.data),
  })

  const resetMut = useMutation({
    mutationFn: () => api.put(`/players/${player.id_player}/baskets`, []),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['player-baskets', player.id_player] }),
  })

  // Seed le formulaire depuis le profil existant (pour qu'une régénération parte de l'état courant).
  useEffect(() => {
    if (profile) {
      setCanRatio(profile.can_edit_ratio)
      setCanVolume(profile.can_set_volume)
      setCanEvent(profile.can_trigger_event)
    }
  }, [profile])

  const genMut = useMutation({
    mutationFn: () =>
      api
        .post(`/players/${player.id_player}/local-control/profile`, {
          validity_hours: validity,
          can_edit_ratio: canRatio,
          can_set_volume: canVolume,
          can_trigger_event: canEvent,
          allowed_basket_ids: null,
        })
        .then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['local-control', player.id_player] }),
  })

  const revokeMut = useMutation({
    mutationFn: () => api.delete(`/players/${player.id_player}/local-control/profile`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['local-control', player.id_player] }),
  })

  function copyUrl(url: string) {
    const flash = () => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
    // navigator.clipboard n'existe qu'en contexte sécurisé (HTTPS/localhost).
    // La CMS est servie en HTTP sur le LAN → fallback execCommand (textarea hors écran).
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(url).then(flash).catch(() => fallbackCopy(url) && flash())
      return
    }
    if (fallbackCopy(url)) flash()
  }

  return (
    <div className="space-y-3 pt-2 border-t border-gray-100">
      <div className="flex items-center justify-between">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5 hover:text-gray-700"
        >
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          <Smartphone className="w-3.5 h-3.5" />
          {t('players.local_control.title')}
        </button>
        {/* Toggle d'activation */}
        <button
          role="switch"
          aria-checked={enabled}
          onClick={() => toggleMut.mutate(!enabled)}
          disabled={toggleMut.isPending}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            enabled ? 'bg-accent' : 'bg-gray-300'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-surface transition-transform ${
              enabled ? 'translate-x-4' : 'translate-x-0.5'
            }`}
          />
        </button>
      </div>

      {/* Indicateur de réglage local actif (overrides opérateur) + reset serveur */}
      {overrides.length > 0 && (
        <div className="flex items-start gap-2 bg-amber-500/10 dark:bg-amber-500/15 border border-amber-400/20 dark:border-amber-500/30 rounded-md px-3 py-2">
          <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-xs text-amber-700 dark:text-amber-300 font-medium">{t('players.local_control.override_active')}</p>
            <button
              onClick={() => { if (confirm(t('players.local_control.reset_confirm'))) resetMut.mutate() }}
              disabled={resetMut.isPending}
              className="mt-1 inline-flex items-center gap-1.5 text-xs text-accent hover:underline"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              {t('players.local_control.reset_override')}
            </button>
          </div>
        </div>
      )}

      {expanded && !enabled && (
        <p className="text-xs text-gray-400 italic">{t('players.local_control.disabled_hint')}</p>
      )}

      {expanded && enabled && (
        <div className="space-y-3">
          {/* QR + révocation — uniquement si un profil actif existe */}
          {profile && (
            <div className="flex flex-col items-center gap-2 bg-canvas rounded-lg p-4 border border-gray-100">
              {profile.lan_url ? (
                <>
                  <div className="bg-surface p-2 rounded-md">
                    <QRCodeSVG value={profile.lan_url} size={148} level="M" />
                  </div>
                  <div className="flex items-center gap-2 w-full">
                    <code className="text-[11px] text-gray-600 truncate flex-1 bg-surface rounded px-2 py-1 border border-gray-200">
                      {profile.lan_url}
                    </code>
                    <button
                      onClick={() => copyUrl(profile.lan_url!)}
                      className="text-accent hover:text-accent/80 shrink-0"
                      title={t('players.local_control.copy')}
                    >
                      {copied ? <Check className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
                    </button>
                  </div>
                </>
              ) : (
                <p className="text-xs text-amber-600 dark:text-amber-300 text-center">{t('players.local_control.no_ip')}</p>
              )}
              {profile.expires_at && new Date(profile.expires_at) < new Date() ? (
                <div className="flex items-start gap-1.5 text-[11px] text-red-600 dark:text-red-300 bg-red-500/10 dark:bg-red-500/15 border border-red-400/20 dark:border-red-500/30 rounded-md px-2 py-1.5 w-full">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
                  <span>{t('players.local_control.expired', { date: new Date(profile.expires_at).toLocaleString() })}</span>
                </div>
              ) : (
                <p className="text-[11px] text-gray-400">
                  {profile.expires_at
                    ? t('players.local_control.expires_at', { date: new Date(profile.expires_at).toLocaleString() })
                    : t('players.local_control.permanent')}
                </p>
              )}
              <button
                onClick={() => {
                  if (confirm(t('players.local_control.revoke_confirm'))) revokeMut.mutate()
                }}
                disabled={revokeMut.isPending}
                className="flex items-center gap-1.5 text-xs text-red-500 hover:underline"
              >
                <Ban className="w-3.5 h-3.5" />
                {t('players.local_control.revoke')}
              </button>
            </div>
          )}

          {/* Options (toujours visibles quand activé) — pilotent génération ET régénération */}
          <div className="space-y-3 bg-canvas rounded-lg p-3 border border-gray-100">
            <label className="flex items-center justify-between text-xs text-gray-600">
              {t('players.local_control.validity_hours')}
              <NumberField
                min={0}
                max={8760}
                value={validity}
                onCommit={(v) => setValidity(v ?? 0)}
                className="w-16 text-right rounded border border-gray-200 px-2 py-1"
              />
            </label>
            <p className="text-[11px] text-gray-400 -mt-1">{t('players.local_control.validity_hint')}</p>

            <div className="space-y-1.5">
              <Check2 label={t('players.local_control.can_set_volume')} checked={canVolume} onChange={setCanVolume} />
              <Check2 label={t('players.local_control.can_edit_ratio')} checked={canRatio} onChange={setCanRatio} />
              <Check2 label={t('players.local_control.can_trigger_event')} checked={canEvent} onChange={setCanEvent} />
            </div>

            <button
              onClick={() => genMut.mutate()}
              disabled={genMut.isPending}
              className="w-full flex items-center justify-center gap-1.5 bg-accent hover:bg-accent/80 text-white text-sm font-medium rounded-md py-2 disabled:opacity-50"
            >
              {profile && <RefreshCw className="w-3.5 h-3.5" />}
              {profile ? t('players.local_control.regenerate') : t('players.local_control.generate')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Copie via execCommand pour les contextes non sécurisés (HTTP LAN) où navigator.clipboard est absent. */
function fallbackCopy(text: string): boolean {
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

function Check2({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-accent" />
      {label}
    </label>
  )
}
