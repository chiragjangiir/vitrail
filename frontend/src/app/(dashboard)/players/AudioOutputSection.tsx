'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Volume2 } from 'lucide-react'

import api from '@/lib/api'
import type { DisplayConfig, PlayerRead } from '@/types/api'

/**
 * Section « Sortie audio » du drawer player — disponible pour TOUS les players.
 * Les choix dépendent du rôle du player (§XIX) :
 *  - content : sortie HDMI / Jack / USB + mute contenu libre
 *  - audio   : sortie Jack / USB (pas de HDMI, pas de contenu → mute masqué)
 *  - mixed   : sortie Jack / USB ; son du contenu forcé muté (sortie réservée aux paniers)
 *
 * Réglages stockés dans display_config :
 *  - audio_basket_output : sortie audio de la machine (auto/hdmi/jack/usb)
 *  - content_sound       : son des contenus standards (on/muted)
 */
export default function AudioOutputSection({
  player,
  t,
  onPlayerUpdate,
}: {
  player: PlayerRead
  t: (key: string, values?: Record<string, string | number>) => string
  onPlayerUpdate?: (p: PlayerRead) => void
}) {
  const qc = useQueryClient()
  const dc: Partial<DisplayConfig> = player.display_config ?? {}
  const role = player.player_role ?? 'content'
  const hdmiAllowed = role === 'content'
  const isBS = player.player_os === 'brightsign'
  // Un player audio/mixed n'a que jack/USB : si une valeur HDMI traîne, on l'affiche comme 'auto'.
  const rawOutput = dc.audio_basket_output ?? 'auto'
  const basketOutput = !hdmiAllowed && rawOutput === 'hdmi' ? 'auto' : rawOutput
  // mixed = son contenu toujours muté (forcé serveur aussi) ; audio = pas de contenu.
  const contentMuted = role === 'mixed' ? true : (dc.content_sound ?? 'on') === 'muted'

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

  if (isBS) {
    // BrightSign : un seul roHtmlWidget rend tout → la SORTIE route le PCM du widget (pcm_audio_outputs
    // au boot → reboot au changement). Le MUTE du contenu = content_sound (player.js mute le <video>
    // HTML5, live). ⚠️ PAS de roAudioOutput pour volume/mute : incompatible avec l'audio HTML5 du widget
    // (cassait le son non-récupérable, prouvé HW). Volume HTML5 = à câbler ultérieurement (video.volume).
    const bsOutput = dc.audio_output ?? 'hdmi'
    const bsMuted = (dc.content_sound ?? 'on') === 'muted'
    return (
      <div className="space-y-2 pt-2 border-t border-gray-100">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
          <Volume2 className="w-3.5 h-3.5" />
          {t('players.audio_output.title')}
        </p>

        <label className="flex items-center justify-between gap-2 text-xs text-gray-600">
          {t('players.audio_output.bs_output')}
          <select
            value={bsOutput}
            onChange={(e) => mut.mutate({ audio_output: e.target.value as DisplayConfig['audio_output'] })}
            disabled={mut.isPending}
            className="rounded border border-gray-200 px-2 py-1 bg-surface"
          >
            <option value="hdmi">HDMI</option>
            <option value="analog">{t('players.audio_output.out_analog')}</option>
            <option value="spdif">S/PDIF</option>
            <option value="usb">USB</option>
          </select>
        </label>

        <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={bsMuted}
            disabled={mut.isPending}
            onChange={(e) => mut.mutate({ content_sound: e.target.checked ? 'muted' : 'on' })}
            className="accent-accent"
          />
          {t('players.audio_output.mute_content')}
        </label>

        <p className="text-[11px] text-gray-400">{t('players.audio_output.bs_hint')}</p>
      </div>
    )
  }

  return (
    <div className="space-y-2 pt-2 border-t border-gray-100">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
        <Volume2 className="w-3.5 h-3.5" />
        {t('players.audio_output.title')}
      </p>

      <label className="flex items-center justify-between gap-2 text-xs text-gray-600">
        {role === 'content'
          ? t('players.audio_output.basket_output')
          : t('players.audio_output.basket_output_audio')}
        <select
          value={basketOutput}
          onChange={(e) => mut.mutate({ audio_basket_output: e.target.value as DisplayConfig['audio_basket_output'] })}
          disabled={mut.isPending}
          className="rounded border border-gray-200 px-2 py-1 bg-surface"
        >
          <option value="auto">{t('players.audio_output.out_auto')}</option>
          {hdmiAllowed && <option value="hdmi">HDMI</option>}
          <option value="jack">{t('players.audio_output.out_jack')}</option>
          <option value="usb">USB</option>
        </select>
      </label>

      {/* Mute contenu : libre en 'content', verrouillé en 'mixed', masqué en 'audio' (pas de contenu) */}
      {role !== 'audio' && (
        <label
          className={`flex items-center gap-2 text-xs text-gray-600 ${role === 'mixed' ? 'opacity-70' : 'cursor-pointer'}`}
        >
          <input
            type="checkbox"
            checked={contentMuted}
            disabled={role === 'mixed' || mut.isPending}
            onChange={(e) => mut.mutate({ content_sound: e.target.checked ? 'muted' : 'on' })}
            className="accent-accent"
          />
          {t('players.audio_output.mute_content')}
        </label>
      )}

      <p className="text-[11px] text-gray-400">
        {role === 'mixed'
          ? t('players.audio_output.hint_mixed')
          : role === 'audio'
            ? t('players.audio_output.hint_audio')
            : t('players.audio_output.hint')}
      </p>
    </div>
  )
}
