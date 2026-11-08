'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Clock, RefreshCw, Trash2, X } from 'lucide-react'
import Drawer from '@/components/ui/Drawer'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import NumberField from '@/components/ui/NumberField'
import api from '@/lib/api'
import type { FeedDisplayConfig, FeedDisplayMode, FeedItemRead, FeedRead, FeedType } from '@/types/api'
import MediaTagsEditor from './MediaTagsEditor'
import DeleteMediaDialog from './DeleteMediaDialog'
import QuarantineSection from './QuarantineSection'

const DEFAULT_CONFIG: FeedDisplayConfig = {
  item_duration_s: 8,
  transition: 'slide',
  show_image: true,
  show_date: true,
  show_description: true,
  grid_columns: 3,
  grid_rows: 2,
  split_side: 'left',
  scroll_speed_px_s: 80,
  separator: ' ◆ ',
  show_play_icon: true,
  show_source: true,
  caption_max_chars: 140,
  chart_type: 'bars',
  show_change: true,
}

const MODE_LABELS: Record<FeedDisplayMode, string> = {
  ticker: 'feeds.mode_ticker',
  card_carousel: 'feeds.mode_carousel',
  card_grid: 'feeds.mode_grid',
  full_item: 'feeds.mode_full',
  split_layout: 'feeds.mode_split',
  compact_list: 'feeds.mode_compact',
  video_feed: 'feeds.mode_video',
  social_wall: 'feeds.mode_social_wall',
  data_chart: 'feeds.mode_chart',
}

// Modes autorisés par type (miroir de la matrice §25.3 / backend mode_allowed).
const STD_MODES: FeedDisplayMode[] = ['ticker', 'card_carousel', 'card_grid', 'full_item', 'split_layout', 'compact_list']
const TYPE_MODES: Record<FeedType, FeedDisplayMode[]> = {
  rss: STD_MODES,
  atom: STD_MODES,
  google_news: ['ticker', 'compact_list'],
  youtube_channel: ['card_carousel', 'card_grid', 'compact_list', 'video_feed'],
  instagram: ['card_grid', 'card_carousel', 'full_item', 'split_layout', 'social_wall'],
  facebook_page: ['card_grid', 'card_carousel', 'full_item', 'split_layout', 'social_wall'],
  twitter_x: ['ticker', 'card_grid', 'card_carousel', 'full_item', 'compact_list', 'social_wall'],
  linkedin: ['ticker', 'card_grid', 'card_carousel', 'full_item', 'compact_list', 'social_wall'],
  tiktok: ['card_grid', 'card_carousel', 'compact_list', 'social_wall'],
  crypto: ['ticker', 'card_grid', 'compact_list', 'data_chart'],
  financial: ['ticker', 'card_grid', 'compact_list', 'data_chart'],
  weather_widget: ['ticker', 'card_grid', 'compact_list', 'data_chart'],
}
// Types résolus par signflow-feed-proxy (source = paramètres au lieu d'une URL de flux).
const PROXY_TYPES: FeedType[] = [
  'instagram', 'facebook_page', 'twitter_x', 'linkedin', 'tiktok',
  'crypto', 'financial', 'weather_widget',
]
const SOCIAL_OAUTH_TYPES: FeedType[] = ['instagram', 'facebook_page', 'twitter_x', 'linkedin', 'tiktok']
// Les socials propriétaires sont câblés côté chaîne (renderer social_wall, modération, offline) MAIS
// le connecteur API de chaque plateforme n'est pas codé (`_social()` → not_implemented) et requiert
// une app dev + token (décision business, cf. EVOLUTIONS). On masque donc ces types du sélecteur tant
// qu'ils ne remontent rien — code conservé, juste non-sélectionnable. Repasser à true pour réactiver.
const SOCIAL_OAUTH_ENABLED: boolean = false

/** Pastille de statut de modération (icône + couleur + libellé — règle design system). */
function StatusBadge({ t, status }: { t: ReturnType<typeof useTranslations>; status: string }) {
  const map = {
    pending: { Icon: Clock, cls: 'text-warning bg-amber-500/10 dark:bg-amber-500/15', key: 'feeds.status_pending' },
    approved: { Icon: Check, cls: 'text-success bg-green-50 dark:bg-green-500/15', key: 'feeds.status_approved' },
    rejected: { Icon: X, cls: 'text-danger bg-red-500/10 dark:bg-red-500/15', key: 'feeds.status_rejected' },
  } as const
  const m = map[status as keyof typeof map] ?? map.pending
  const { Icon } = m
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${m.cls}`}>
      <Icon className="w-3 h-3" />
      {t(m.key)}
    </span>
  )
}

/** Drawer de création / édition d'un Feed (RSS/Atom). Un feed = source pollable + média
 *  feed_display pointeur. editId=null → création ; editId=<id_feed> → édition. */
export default function FeedDrawer({
  open, editId, onClose,
}: { open: boolean; editId: number | null; onClose: () => void }) {
  const t = useTranslations()
  const qc = useQueryClient()

  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  // Paramètres de source des feeds proxy (account/query/coins/currency/location).
  const [src, setSrc] = useState<{ account: string; query: string; coins: string; currency: string; location: string }>(
    { account: '', query: '', coins: '', currency: '', location: '' })
  const [feedType, setFeedType] = useState<FeedType>('rss')
  const [mode, setMode] = useState<FeedDisplayMode>('ticker')
  const [config, setConfig] = useState<FeedDisplayConfig>(DEFAULT_CONFIG)
  const [polling, setPolling] = useState(900)
  const [maxItems, setMaxItems] = useState(10)
  const [moderation, setModeration] = useState(false)
  const [aiSummary, setAiSummary] = useState(false)
  const [mutateError, setMutateError] = useState<string | null>(null)
  const [showDelete, setShowDelete] = useState(false)

  const { data: item } = useQuery<FeedRead>({
    queryKey: ['feeds', editId],
    queryFn: () => api.get<FeedRead>(`/feeds/${editId}`).then((r) => r.data),
    enabled: open && editId !== null,
  })

  const { data: items = [] } = useQuery<FeedItemRead[]>({
    queryKey: ['feeds', editId, 'items'],
    queryFn: () => api.get<FeedItemRead[]>(`/feeds/${editId}/items?limit=10`).then((r) => r.data),
    enabled: open && editId !== null,
    refetchInterval: open && editId !== null ? 5000 : false,  // l'aperçu se peuple après le fetch
  })

  useEffect(() => {
    if (!open) return
    setMutateError(null)
    setShowDelete(false)
    if (editId === null) {
      setName(''); setUrl(''); setFeedType('rss'); setMode('ticker')
      setSrc({ account: '', query: '', coins: '', currency: '', location: '' })
      setConfig(DEFAULT_CONFIG); setPolling(900); setMaxItems(10); setModeration(false); setAiSummary(false)
    } else if (item) {
      const loadedMode = (item.display_mode ?? 'ticker') as FeedDisplayMode
      const allowed = TYPE_MODES[item.feed_type] ?? STD_MODES
      const cfg = (item.config ?? {}) as Record<string, unknown>
      setName(item.feed_name); setUrl(item.url ?? ''); setFeedType(item.feed_type)
      setSrc({
        account: String(cfg.account ?? ''), query: String(cfg.query ?? ''),
        coins: Array.isArray(cfg.coins) ? (cfg.coins as string[]).join(', ') : String(cfg.coins ?? ''),
        currency: String(cfg.currency ?? ''), location: String(cfg.location ?? ''),
      })
      // Coercition d'un mode legacy incompatible vers le 1er mode autorisé pour ce type.
      setMode(allowed.includes(loadedMode) ? loadedMode : allowed[0])
      setConfig({ ...DEFAULT_CONFIG, ...item.display_config })
      setPolling(item.polling_interval_s); setMaxItems(item.max_items)
      setModeration(item.moderation_enabled)
      setAiSummary(item.ai_summary_enabled ?? false)
    }
  }, [open, editId, item])

  function setCfg<K extends keyof FeedDisplayConfig>(k: K, v: FeedDisplayConfig[K]) {
    setConfig((prev) => ({ ...prev, [k]: v }))
  }
  function setSrcField(k: keyof typeof src, v: string) { setSrc((p) => ({ ...p, [k]: v })) }

  const isProxy = PROXY_TYPES.includes(feedType)
  const availableModes = (TYPE_MODES[feedType] ?? STD_MODES).map((value) => ({ value, key: MODE_LABELS[value] }))

  function changeFeedType(v: FeedType) {
    setFeedType(v)
    const allowed = TYPE_MODES[v] ?? STD_MODES
    if (!allowed.includes(mode)) setMode(allowed[0])   // bascule vers un mode valide pour le type
  }

  const httpOk = /^https?:\/\//i.test(url.trim())
  // Source valide : URL http(s) pour les flux directs ; paramètre pertinent pour les types proxy.
  const sourceValid = isProxy
    ? (feedType === 'crypto' ? !!src.coins.trim()
      : feedType === 'financial' ? !!src.query.trim()
      : feedType === 'weather_widget' ? !!src.location.trim()
      : !!src.account.trim())   // socials : @handle / page
    : httpOk
  const canSave = !!name.trim() && sourceValid

  // Config source envoyée au backend selon le type.
  function buildConfig(): Record<string, unknown> {
    if (!isProxy) return { url: url.trim() }
    if (feedType === 'crypto') return { coins: src.coins.split(',').map((s) => s.trim()).filter(Boolean), currency: src.currency.trim() || undefined }
    if (feedType === 'financial') return { query: src.query.trim(), currency: src.currency.trim() || undefined }
    if (feedType === 'weather_widget') return { location: src.location.trim() }
    return { account: src.account.trim() }   // socials
  }

  function invalidate() {
    qc.invalidateQueries({ queryKey: ['feeds'] })
    qc.invalidateQueries({ queryKey: ['media'] })  // feed_display = média → médiathèque
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = {
        feed_name: name, feed_type: feedType, config: buildConfig(),
        polling_interval_s: polling, display_mode: mode, display_config: config,
        max_items: maxItems, moderation_enabled: moderation, ai_summary_enabled: aiSummary,
      }
      if (editId === null) await api.post('/feeds', body)
      else await api.put(`/feeds/${editId}`, body)
    },
    onSuccess: () => { invalidate(); onClose() },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMutateError(typeof detail === 'string' ? detail : t('common.error'))
    },
  })

  const fetchMutation = useMutation({
    mutationFn: () => api.post(`/feeds/${editId}/fetch`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['feeds', editId, 'items'] }) },
  })

  const moderateMutation = useMutation({
    mutationFn: (vars: { item_ids: number[]; action: 'approve' | 'reject' }) =>
      api.post(`/feeds/${editId}/moderate`, vars),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['feeds', editId, 'items'] }) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/feeds/${id}`),
    onSuccess: () => { invalidate(); onClose() },
  })

  if (showDelete && editId !== null) {
    return (
      <Drawer open={open} onClose={onClose} title={t('media.delete_title')} width="w-[560px]">
        <DeleteMediaDialog
          name={name}
          impactUrl={`/feeds/${editId}/deletion-impact`}
          queryKey={['feed-deletion-impact', editId]}
          isPending={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(editId)}
          onCancel={() => setShowDelete(false)}
        />
      </Drawer>
    )
  }

  return (
    <Drawer open={open} onClose={onClose} title={editId !== null ? t('feeds.edit') : t('feeds.new')} width="w-[560px]">
      {/* Nudge lecture-seule : édition/modération/fetch = media:edit, création = media:create (feed.py). */}
      <div className="space-y-5" data-write-perm={editId !== null ? 'media:edit' : 'media:create'}>
        <Input label={t('feeds.name_label')} value={name} onChange={(e) => setName(e.target.value)} />
        {!isProxy ? (
          <div>
            <Input label={t('feeds.url_label')} value={url} onChange={(e) => setUrl(e.target.value)}
              placeholder={feedType === 'youtube_channel' ? 'https://www.youtube.com/@chaine' : 'https://feeds.bbci.co.uk/news/rss.xml'} />
            {feedType === 'youtube_channel' && <p className="text-xs text-gray-400 mt-1">{t('feeds.youtube_url_hint')}</p>}
            {url.trim() !== '' && !httpOk && <p className="text-xs text-danger mt-1">{t('feeds.url_invalid')}</p>}
          </div>
        ) : (
          <div className="space-y-3">
            {SOCIAL_OAUTH_TYPES.includes(feedType) && (
              <p className="text-xs text-warning bg-amber-500/10 dark:bg-amber-500/15 rounded-md px-3 py-2">{t('feeds.social_oauth_hint')}</p>
            )}
            {feedType === 'crypto' && (<>
              <Input label={t('feeds.coins_label')} value={src.coins} onChange={(e) => setSrcField('coins', e.target.value)} placeholder="bitcoin, ethereum, solana" />
              <Input label={t('feeds.currency_label')} value={src.currency} onChange={(e) => setSrcField('currency', e.target.value)} placeholder="EUR" />
            </>)}
            {feedType === 'financial' && (<>
              <Input label={t('feeds.symbols_label')} value={src.query} onChange={(e) => setSrcField('query', e.target.value)} placeholder="aapl.us, msft.us" />
              <Input label={t('feeds.currency_label')} value={src.currency} onChange={(e) => setSrcField('currency', e.target.value)} placeholder="USD" />
            </>)}
            {feedType === 'weather_widget' && (
              <Input label={t('feeds.location_label')} value={src.location} onChange={(e) => setSrcField('location', e.target.value)} placeholder="Paris" />
            )}
            {SOCIAL_OAUTH_TYPES.includes(feedType) && (
              <Input label={t('feeds.account_label')} value={src.account} onChange={(e) => setSrcField('account', e.target.value)} placeholder="@brand" />
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-sm font-medium text-gray-800">{t('feeds.type_label')}</label>
            <select value={feedType} onChange={(e) => changeFeedType(e.target.value as FeedType)}
              className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
              <optgroup label={t('feeds.group_news')}>
                <option value="rss">RSS</option>
                <option value="atom">Atom</option>
                <option value="google_news">Google News</option>
              </optgroup>
              <optgroup label={t('feeds.group_video')}>
                <option value="youtube_channel">YouTube</option>
              </optgroup>
              {SOCIAL_OAUTH_ENABLED && (
                <optgroup label={t('feeds.group_social')}>
                  <option value="instagram">Instagram</option>
                  <option value="facebook_page">Facebook</option>
                  <option value="twitter_x">X (Twitter)</option>
                  <option value="linkedin">LinkedIn</option>
                  <option value="tiktok">TikTok</option>
                </optgroup>
              )}
              <optgroup label={t('feeds.group_data')}>
                <option value="crypto">Crypto</option>
                <option value="financial">{t('feeds.type_financial')}</option>
                <option value="weather_widget">{t('feeds.type_weather')}</option>
              </optgroup>
            </select>
          </div>
          <div>
            <label className="text-sm font-medium text-gray-800">{t('feeds.mode_label')}</label>
            <select value={mode} onChange={(e) => setMode(e.target.value as FeedDisplayMode)}
              className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
              {availableModes.map((m) => (
                <option key={m.value} value={m.value}>{t(m.key)}</option>
              ))}
            </select>
            {feedType === 'google_news' && (
              <p className="text-xs text-gray-400 mt-1">{t('feeds.google_news_no_image')}</p>
            )}
          </div>
        </div>

        {/* Options du mode d'affichage (chaque mode lit ce qui le concerne) */}
        <div className="space-y-3 border-t border-gray-100 pt-4">
          {mode === 'ticker' ? (
            <>
              <NumberField label={t('feeds.scroll_speed_label')} min={10}
                value={config.scroll_speed_px_s ?? 80}
                onCommit={(v) => setCfg('scroll_speed_px_s', v ?? 80)} />
              <Input label={t('feeds.separator_label')} value={config.separator}
                onChange={(e) => setCfg('separator', e.target.value)} />
            </>
          ) : mode === 'data_chart' ? (
            <>
              <div>
                <label className="text-sm font-medium text-gray-800">{t('feeds.chart_type_label')}</label>
                <select value={config.chart_type ?? 'bars'} onChange={(e) => setCfg('chart_type', e.target.value as 'bars' | 'line' | 'gauge')}
                  className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
                  <option value="bars">{t('feeds.chart_bars')}</option>
                  <option value="line">{t('feeds.chart_line')}</option>
                  <option value="gauge">{t('feeds.chart_gauge')}</option>
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={config.show_change !== false} onChange={(e) => setCfg('show_change', e.target.checked)}
                  className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                {t('feeds.show_change')}
              </label>
            </>
          ) : (
            <>
              {mode !== 'compact_list' && (
                <NumberField label={(mode === 'card_grid' || mode === 'video_feed' || mode === 'social_wall') ? t('feeds.page_duration_label') : t('feeds.item_duration_label')}
                  min={2} value={config.item_duration_s ?? 8}
                  onCommit={(v) => setCfg('item_duration_s', v ?? 8)} />
              )}
              {(mode === 'card_grid' || mode === 'video_feed' || mode === 'social_wall') && (
                <div className="grid grid-cols-2 gap-3">
                  <NumberField label={t('feeds.grid_columns_label')} min={1} max={6}
                    value={config.grid_columns ?? 3}
                    onCommit={(v) => setCfg('grid_columns', v ?? 3)} />
                  <NumberField label={t('feeds.grid_rows_label')} min={1} max={4}
                    value={config.grid_rows ?? 2}
                    onCommit={(v) => setCfg('grid_rows', v ?? 2)} />
                </div>
              )}
              {mode === 'social_wall' && (
                <NumberField label={t('feeds.caption_max_label')} min={0} max={400}
                  value={config.caption_max_chars ?? 140}
                  onCommit={(v) => setCfg('caption_max_chars', v ?? 140)} />
              )}
              {mode === 'video_feed' && (
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input type="checkbox" checked={config.show_play_icon !== false}
                    onChange={(e) => setCfg('show_play_icon', e.target.checked)}
                    className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                  {t('feeds.show_play_icon')}
                </label>
              )}
              {(mode === 'card_carousel' || mode === 'full_item' || mode === 'split_layout') && (
                <div>
                  <label className="text-sm font-medium text-gray-800">{t('feeds.transition_label')}</label>
                  <select value={config.transition} onChange={(e) => setCfg('transition', e.target.value as 'slide' | 'fade')}
                    className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
                    <option value="slide">{t('feeds.transition_slide')}</option>
                    <option value="fade">{t('feeds.transition_fade')}</option>
                  </select>
                </div>
              )}
              {mode === 'split_layout' && (
                <div>
                  <label className="text-sm font-medium text-gray-800">{t('feeds.split_side_label')}</label>
                  <select value={config.split_side} onChange={(e) => setCfg('split_side', e.target.value as 'left' | 'right')}
                    className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40">
                    <option value="left">{t('feeds.split_left')}</option>
                    <option value="right">{t('feeds.split_right')}</option>
                  </select>
                </div>
              )}
              {mode !== 'compact_list' && mode !== 'video_feed' && (
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input type="checkbox" checked={config.show_image} onChange={(e) => setCfg('show_image', e.target.checked)}
                    className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                  {t('feeds.show_image')}
                </label>
              )}
              {(mode === 'full_item' || mode === 'split_layout') && (
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input type="checkbox" checked={config.show_description} onChange={(e) => setCfg('show_description', e.target.checked)}
                    className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                  {t('feeds.show_description')}
                </label>
              )}
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={config.show_date} onChange={(e) => setCfg('show_date', e.target.checked)}
                  className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
                {t('feeds.show_date')}
              </label>
            </>
          )}
          <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
            <input type="checkbox" checked={config.show_source} onChange={(e) => setCfg('show_source', e.target.checked)}
              className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
            {t('feeds.show_source')}
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <NumberField label={t('feeds.max_items_label')} min={1}
            value={maxItems} onCommit={(v) => setMaxItems(v ?? 10)} />
          <NumberField label={t('feeds.polling_label')} min={30}
            value={polling} onCommit={(v) => setPolling(v ?? 900)} />
        </div>

        {/* Modération §XXI — si activée, les items arrivent « en attente » et ne sont diffusés
            qu'une fois approuvés ci-dessous. */}
        <div>
          <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
            <input type="checkbox" checked={moderation} onChange={(e) => setModeration(e.target.checked)}
              className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
            {t('feeds.moderation_label')}
          </label>
          <p className="mt-1 ml-6 text-xs text-gray-400">{t('feeds.moderation_hint')}</p>
        </div>

        {/* Résumé IA §XXV.3 — LiteLLM condense chaque item en une phrase (affichée en mode
            full_item / split_layout, repli sur la description d'origine si indisponible). */}
        <div>
          <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
            <input type="checkbox" checked={aiSummary} onChange={(e) => setAiSummary(e.target.checked)}
              className="rounded-lg border-gray-300 text-accent focus:ring-accent/40" />
            {t('feeds.ai_summary_label')}
          </label>
          <p className="mt-1 ml-6 text-xs text-gray-400">{t('feeds.ai_summary_hint')}</p>
        </div>

        {/* Statut + aperçu / file de modération des items (édition) */}
        {editId !== null && item && (
          <div className="space-y-2 border-t border-gray-100 pt-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-700">
                {t('feeds.items_count', { count: item.item_count })}
              </span>
              <button type="button" data-write-action onClick={() => fetchMutation.mutate()} disabled={fetchMutation.isPending}
                className="flex items-center gap-1 text-xs text-accent hover:underline disabled:opacity-50">
                <RefreshCw className={`w-3.5 h-3.5 ${fetchMutation.isPending ? 'animate-spin' : ''}`} />
                {t('feeds.fetch_now')}
              </button>
            </div>
            {item.last_error && <p className="text-xs text-danger">{item.last_error}</p>}
            {item.moderation_enabled && (
              <p className="text-xs text-gray-500">
                {t('feeds.pending_count', { count: items.filter((i) => i.moderation_status === 'pending').length })}
              </p>
            )}
            {items.length > 0 && (
              <ul className="max-h-52 overflow-y-auto divide-y divide-gray-50">
                {items.slice(0, 12).map((it) => (
                  <li key={it.id_item} className="flex items-center gap-2 py-1.5">
                    {item.moderation_enabled && <StatusBadge t={t} status={it.moderation_status} />}
                    <span className="flex-1 truncate text-xs text-gray-600" title={it.title ?? ''}>{it.title}</span>
                    {item.moderation_enabled && (
                      <span className="flex items-center gap-1">
                        {it.moderation_status !== 'approved' && (
                          <button type="button" data-write-action disabled={moderateMutation.isPending}
                            onClick={() => moderateMutation.mutate({ item_ids: [it.id_item], action: 'approve' })}
                            className="p-1 text-gray-300 hover:text-success transition-sf disabled:opacity-40"
                            title={t('feeds.moderate_approve')}>
                            <Check className="w-3.5 h-3.5" />
                          </button>
                        )}
                        {it.moderation_status !== 'rejected' && (
                          <button type="button" data-write-action disabled={moderateMutation.isPending}
                            onClick={() => moderateMutation.mutate({ item_ids: [it.id_item], action: 'reject' })}
                            className="p-1 text-gray-300 hover:text-danger transition-sf disabled:opacity-40"
                            title={t('feeds.moderate_reject')}>
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Tags (§XVII) — feed_display = média → tags natifs */}
        {editId !== null && item?.id_media != null && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">{t('media.tags')}</label>
            <MediaTagsEditor idMedia={item.id_media} mediaType="feed_display" />
          </div>
        )}

        {/* Quarantaine / kill-switch (§ Q5) — feed_display = média → mêmes règles */}
        {editId !== null && item?.id_media != null && (
          <QuarantineSection idMedia={item.id_media} />
        )}

        <p className="text-xs text-gray-400">{t('feeds.schedule_hint')}</p>
        {mutateError && <p className="text-sm text-danger">{mutateError}</p>}
        <div className="flex items-center justify-between">
          <div className="flex gap-2">
            <Button data-write-action onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !canSave}>
              {saveMutation.isPending ? t('common.saving') : t('common.save')}
            </Button>
            <Button variant="secondary" onClick={onClose}>{t('common.cancel')}</Button>
          </div>
          {editId !== null && (
            <Can perm="media:delete">
              <button onClick={() => setShowDelete(true)}
                className="p-2 text-gray-300 hover:text-danger transition-sf" title={t('common.delete')}>
                <Trash2 className="w-4 h-4" />
              </button>
            </Can>
          )}
        </div>
      </div>
    </Drawer>
  )
}
