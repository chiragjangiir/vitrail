'use client'

import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Cpu, HelpCircle, RefreshCw } from 'lucide-react'

import type { PlayerRead } from '@/types/api'
import { decodeHealth, type DecodeEffective } from '@/lib/decodeHealth'

type T = (key: string, values?: Record<string, string | number>) => string

const STYLES: Record<DecodeEffective, { wrap: string; Icon: typeof Cpu }> = {
  hardware: { wrap: 'bg-green-50 dark:bg-green-500/15 text-green-700 dark:text-green-300 border-green-200 dark:border-green-500/30', Icon: Cpu },
  software: { wrap: 'bg-amber-500/10 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-400/20 dark:border-amber-500/30', Icon: AlertTriangle },
  unknown: { wrap: 'bg-gray-100 text-gray-500 border-gray-200', Icon: HelpCircle },
}

/**
 * Badge décodage (icône + couleur + libellé — design system). `compact` pour le tableau.
 * État calculé côté front depuis player.capabilities (cf. lib/decodeHealth).
 */
export function DecodeBadge({ player, t, compact = false }: { player: PlayerRead; t: T; compact?: boolean }) {
  const { effective, method } = decodeHealth(player)
  const { wrap, Icon } = STYLES[effective]
  const label = t(`players.decode.${effective}`)
  const text = compact || !method ? label : `${label} · ${method.toUpperCase()}`
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium ${wrap}`}
      title={method ? `${label} (${method})` : label}
    >
      <Icon className="w-3 h-3 shrink-0" />
      {text}
    </span>
  )
}

/** Section « Décodage vidéo » du drawer player. `onDetect` relance la détection HW côté player. */
export default function DecodeSection({ player, t, onDetect }: { player: PlayerRead; t: T; onDetect?: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [detecting, setDetecting] = useState(false)
  const caps = player.capabilities

  function handleDetect() {
    if (!onDetect || detecting) return
    setDetecting(true)
    onDetect()
    // Le player re-détecte puis remonte via heartbeat (~10 s) ; spinner de feedback ~12 s.
    window.setTimeout(() => setDetecting(false), 12000)
  }
  const health = decodeHealth(player)

  let descKey = 'players.decode.unknown_desc'
  if (health.effective === 'hardware') descKey = 'players.decode.hardware_desc'
  else if (health.effective === 'software') {
    if (caps?.sf_hw_decode === 'off') descKey = 'players.decode.off_desc'
    else if (health.capableButInactive) descKey = 'players.decode.software_desc_capable'
    else descKey = 'players.decode.software_desc'
  }
  const desc = t(descKey, { method: (health.method ?? '').toUpperCase() })

  return (
    <div className="pt-2 border-t border-gray-100">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          <Cpu className="w-3.5 h-3.5 text-gray-400" />
          {t('players.decode.title')}
        </span>
        <DecodeBadge player={player} t={t} />
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5 text-xs">
          <p className={health.severity === 'warning' ? 'text-amber-700 dark:text-amber-300' : 'text-gray-500'}>{desc}</p>
          {caps && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-gray-600">
              {(caps.gpu_model || caps.gpu_vendor) && (
                <>
                  <dt className="text-gray-400">{t('players.decode.gpu')}</dt>
                  <dd className="font-medium text-gray-700">{caps.gpu_model || caps.gpu_vendor}</dd>
                </>
              )}
              {health.method && (
                <>
                  <dt className="text-gray-400">{t('players.decode.method')}</dt>
                  <dd className="font-medium text-gray-700">{health.method.toUpperCase()}</dd>
                </>
              )}
              {caps.codecs && caps.codecs.length > 0 && (
                <>
                  <dt className="text-gray-400">{t('players.decode.codecs')}</dt>
                  <dd className="font-medium text-gray-700">{caps.codecs.map((c) => c.toUpperCase()).join(', ')}</dd>
                </>
              )}
            </dl>
          )}
          {onDetect && (
            <div className="pt-1">
              <button
                type="button"
                onClick={handleDetect}
                disabled={detecting}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-accent/30 text-accent hover:bg-accent/5 transition-sf disabled:opacity-60 disabled:cursor-default"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${detecting ? 'animate-spin' : ''}`} />
                {t(detecting ? 'players.decode.run_detect_running' : 'players.decode.run_detect')}
              </button>
              <p className="text-[11px] text-gray-400 mt-1">{t('players.decode.run_detect_hint')}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
