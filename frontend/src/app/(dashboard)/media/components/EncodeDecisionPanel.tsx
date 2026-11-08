'use client'

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { AlertTriangle, Play, Minimize2 } from 'lucide-react'
import api from '@/lib/api'
import Button from '@/components/ui/Button'
import type { EncodeDecision } from '@/types/api'
import { formatEta } from './EncodeProgressBar'

/**
 * L'encodage a été mesuré trop long : on rend la main à l'utilisateur (décision Ed).
 *
 * 🔑 Le point de ce panneau n'est pas d'annoncer un refus, c'est d'offrir une SORTIE.
 * « 4 h 20 » tout seul est une impasse ; « 4 h 20, ou 26 min en 1080p » est une décision
 * que quelqu'un peut prendre. C'est pour ça que les replis portent leur propre estimation.
 *
 * Rien ne se lance sans un geste : le média reste visible et compté dans la médiathèque
 * (avec un badge et un filtre dédiés) plutôt que de disparaître ou de partir tout seul.
 */
export default function EncodeDecisionPanel({
  idMedia, decision, isOrgAdmin,
}: {
  idMedia: number
  decision: EncodeDecision
  /** Seul un org-admin peut passer outre au-delà de la limite haute. */
  isOrgAdmin: boolean
}) {
  const t = useTranslations('media')
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const decide = useMutation({
    mutationFn: async (body: { action: 'proceed' | 'downscale'; profile?: string }) =>
      (await api.post(`/media/${idMedia}/encode-decision`, body)).data,
    onSuccess: () => {
      setError(null)
      void qc.invalidateQueries({ queryKey: ['media'] })
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? t('enc_decision_failed'))
    },
  })

  const blocked = decision.band === 'refuse' && !isOrgAdmin
  const eta = (s: number) => formatEta(s, t as unknown as (k: string, v?: Record<string, string | number>) => string)

  return (
    <div className="rounded-lg border border-warning/30 bg-orange-500/5 p-3 space-y-3">
      <div className="flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="text-xs font-semibold text-gray-800">
            {decision.band === 'refuse' ? t('enc_decision_title_refuse') : t('enc_decision_title_confirm')}
          </p>
          <p className="text-[11px] text-gray-600 mt-0.5">
            {t('enc_decision_estimate', { time: eta(decision.estimate_s) })}
            {decision.width && decision.height ? ` · ${decision.width}×${decision.height}` : ''}
            {decision.encoder ? ` · ${decision.encoder}` : ''}
          </p>
          {/* La mesure elle-même, pour qui veut comprendre d'où sort le chiffre. */}
          {typeof decision.measured_speed === 'number' && (
            <p className="text-[11px] text-gray-500 mt-0.5">
              {t('enc_decision_measured', { speed: decision.measured_speed.toFixed(2) })}
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {decision.downscale.map((opt) => (
          <Button
            key={opt.profile}
            variant="secondary"
            className="text-xs"
            disabled={decide.isPending}
            data-write-action
            onClick={() => decide.mutate({ action: 'downscale', profile: opt.profile })}
          >
            <Minimize2 className="w-3.5 h-3.5 mr-1.5" />
            {t('enc_decision_downscale', {
              profile: opt.profile === 'fhd' ? '1080p' : '720p',
              time: eta(opt.estimate_s),
            })}
          </Button>
        ))}
        <Button
          className="text-xs"
          disabled={decide.isPending || blocked}
          data-write-action
          title={blocked ? t('enc_decision_admin_only') : undefined}
          onClick={() => decide.mutate({ action: 'proceed' })}
        >
          <Play className="w-3.5 h-3.5 mr-1.5" />
          {t('enc_decision_proceed', { time: eta(decision.estimate_s) })}
        </Button>
      </div>

      {blocked && <p className="text-[11px] text-gray-500">{t('enc_decision_admin_only')}</p>}
      {error && <p className="text-[11px] text-danger">{error}</p>}
      <p className="text-[11px] text-gray-500">{t('enc_decision_delete_hint')}</p>
    </div>
  )
}
