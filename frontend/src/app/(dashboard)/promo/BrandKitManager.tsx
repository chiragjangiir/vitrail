'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Palette, Save, Trash2 } from 'lucide-react'
import api from '@/lib/api'
import ReferencePicker from '../media/components/ReferencePicker'
import type { FontItem } from './SlotStyleControls'

export interface BrandKit {
  id_brand_kit?: number
  id_advertiser?: number | null
  advertiser_name?: string | null
  kit_name?: string
  accent?: string | null
  ink?: string | null
  paper?: string | null
  badge_bg?: string | null
  badge_ink?: string | null
  font_family?: string | null
  brand_name?: string | null
  id_logo_media?: number | null
  legal_mentions?: string | null
  tone?: string | null
}

export const COLOR_KEYS = ['accent', 'ink', 'paper', 'badge_bg', 'badge_ink'] as const
type ColorKey = (typeof COLOR_KEYS)[number]

interface Advertiser { id_advertiser: number; advertiser_name: string }

/**
 * Chartes de marque (P3.4, org-admin). Une charte par organisation + une par annonceur ; celle de
 * l'annonceur l'emporte quand un visuel est fait pour lui.
 *
 * ⚠️ Une couleur laissée VIDE ne veut pas dire « blanc » mais « la charte ne dit rien » : le
 * template garde alors la sienne. D'où la case à cocher par couleur plutôt qu'un sélecteur
 * toujours renseigné — un `<input type="color">` seul ne sait pas exprimer l'absence.
 */
export default function BrandKitManager({ fonts }: { fonts: FontItem[] }) {
  const t = useTranslations()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [scope, setScope] = useState<number | 'org'>('org')
  const [draft, setDraft] = useState<BrandKit>({ kit_name: '' })
  const [err, setErr] = useState<string | null>(null)

  const { data: kits = [] } = useQuery<BrandKit[]>({
    queryKey: ['brand-kits'],
    queryFn: () => api.get<BrandKit[]>('/promo/brand-kits').then((r) => r.data),
  })
  const { data: advertisers = [] } = useQuery<Advertiser[]>({
    queryKey: ['advertisers-for-brand-kits'],
    queryFn: () => api.get<Advertiser[]>('/campaigns/advertisers').then((r) => r.data),
  })

  const current = useMemo(
    () => kits.find((k) => (scope === 'org' ? k.id_advertiser == null : k.id_advertiser === scope)),
    [kits, scope],
  )
  // Recharge le brouillon quand on change de PORTÉE ou quand la charte chargée change d'identité.
  // ⚠️ Jamais sur la seule identité de l'objet `current` : react-query refait sa requête au retour
  // de focus fenêtre, et la réponse serveur écraserait alors une saisie en cours (même règle que
  // `useCommitField` ailleurs dans le produit). D'où le repère explicite plutôt qu'un tableau de
  // dépendances tronqué.
  const loadedKey = useRef<string | null>(null)
  const kitKey = `${scope}:${current?.id_brand_kit ?? 'none'}`
  useEffect(() => {
    if (loadedKey.current === kitKey) return
    loadedKey.current = kitKey
    setDraft(current ? { ...current } : { kit_name: '' })
    setErr(null)
  }, [kitKey, current])

  const path = scope === 'org' ? '/promo/brand-kits/org' : `/promo/brand-kits/advertiser/${scope}`
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['brand-kits'] })
    qc.invalidateQueries({ queryKey: ['brand-kit-resolved'] })
  }

  const save = useMutation({
    mutationFn: () => api.put(path, {
      kit_name: (draft.kit_name || '').trim() || t('promo.brand_default_name'),
      ...Object.fromEntries(COLOR_KEYS.map((k) => [k, draft[k] || null])),
      font_family: draft.font_family || null,
      brand_name: (draft.brand_name || '').trim() || null,
      id_logo_media: draft.id_logo_media ?? null,
      legal_mentions: (draft.legal_mentions || '').trim() || null,
      tone: (draft.tone || '').trim() || null,
    }),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setErr(typeof detail === 'string' ? detail : t('common.error'))
    },
  })
  const remove = useMutation({
    mutationFn: () => api.delete(path),
    onSuccess: invalidate,
  })

  const setColor = (key: ColorKey, value: string | null) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const field = 'w-full rounded border border-gray-200 bg-surface px-1.5 py-1 text-xs'

  return (
    <div className="rounded-lg border border-gray-200 p-2">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 text-xs font-semibold text-gray-700">
        <Palette className="h-3.5 w-3.5 text-accent" />{t('promo.brand_title')}
        {kits.length > 0 ? ` (${kits.length})` : ''}
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          <p className="text-[11px] text-gray-400">{t('promo.brand_hint')}</p>

          {/* Portée : l'organisation, ou un annonceur (sa charte l'emporte). */}
          <select value={String(scope)} className={field}
            onChange={(e) => setScope(e.target.value === 'org' ? 'org' : Number(e.target.value))}>
            <option value="org">{t('promo.brand_scope_org')}</option>
            {advertisers.map((a) => (
              <option key={a.id_advertiser} value={a.id_advertiser}>
                {t('promo.brand_scope_advertiser', { name: a.advertiser_name })}
              </option>
            ))}
          </select>

          <input value={draft.kit_name ?? ''} placeholder={t('promo.brand_name_field')}
            onChange={(e) => setDraft((d) => ({ ...d, kit_name: e.target.value }))}
            className={field} />

          {/* Couleurs — la case décide si la charte DÉCLARE cette couleur ou se tait. */}
          <div className="space-y-1">
            {COLOR_KEYS.map((key) => {
              const declared = !!draft[key]
              return (
                <label key={key} className="flex items-center gap-1.5 text-[11px] text-gray-500">
                  <input type="checkbox" checked={declared}
                    onChange={(e) => setColor(key, e.target.checked ? (draft[key] || '#2563EB') : null)} />
                  <span className="w-24 shrink-0">{t(`promo.brand_color_${key}`)}</span>
                  <input type="color" value={draft[key] || '#2563EB'} disabled={!declared}
                    onChange={(e) => setColor(key, e.target.value)}
                    className="h-5 w-8 rounded border border-gray-200 disabled:opacity-30" />
                  <span className="font-mono text-[10px] text-gray-400">
                    {declared ? draft[key] : t('promo.brand_color_inherited')}
                  </span>
                </label>
              )
            })}
          </div>

          <select value={draft.font_family ?? ''} className={field}
            onChange={(e) => setDraft((d) => ({ ...d, font_family: e.target.value || null }))}>
            <option value="">{t('promo.brand_font_inherited')}</option>
            {fonts.map((f) => <option key={f.id} value={f.family}>{f.family}</option>)}
          </select>

          <input value={draft.brand_name ?? ''} placeholder={t('promo.brand_brand_name')}
            onChange={(e) => setDraft((d) => ({ ...d, brand_name: e.target.value }))}
            className={field} />

          <div>
            <p className="mb-1 text-[11px] text-gray-500">{t('promo.brand_logo')}</p>
            <ReferencePicker maxRefs={1}
              value={draft.id_logo_media ? [draft.id_logo_media] : []}
              onChange={(ids) => setDraft((d) => ({ ...d, id_logo_media: ids[0] ?? null }))} />
          </div>

          <textarea value={draft.legal_mentions ?? ''} rows={2}
            placeholder={t('promo.brand_mentions')}
            onChange={(e) => setDraft((d) => ({ ...d, legal_mentions: e.target.value }))}
            className={field} />

          <input value={draft.tone ?? ''} placeholder={t('promo.brand_tone')}
            onChange={(e) => setDraft((d) => ({ ...d, tone: e.target.value }))}
            className={field} />
          <p className="text-[11px] text-gray-400">{t('promo.brand_tone_hint')}</p>

          {err && <p className="text-[11px] text-danger">{err}</p>}

          <div className="flex items-center gap-2">
            <button type="button" onClick={() => save.mutate()} disabled={save.isPending}
              data-testid="brand-kit-save"
              className="inline-flex items-center gap-1.5 rounded-lg border border-accent/40 px-2.5 py-1 text-xs text-accent transition-sf hover:bg-accent/10 disabled:opacity-50">
              {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              {t('common.save')}
            </button>
            {current && (
              <button type="button" onClick={() => remove.mutate()} disabled={remove.isPending}
                className="inline-flex items-center gap-1 rounded border border-gray-200 px-2 py-1 text-[11px] text-gray-500 hover:border-danger hover:text-danger">
                <Trash2 className="h-3 w-3" />{t('promo.brand_delete')}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
