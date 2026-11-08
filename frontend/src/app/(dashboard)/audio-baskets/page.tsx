'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Music, Plus, Pencil, Trash2, Volume2, ListMusic, X, CalendarClock, Play, Headphones } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import SearchInput from '@/components/ui/SearchInput'
import Drawer from '@/components/ui/Drawer'
import NumberField from '@/components/ui/NumberField'
import api from '@/lib/api'
import { formatMs } from '@/lib/formatMs'
import type { AudioBasket, BasketItem, GovernanceNode } from '@/types/api'
import MediaViewer from '../media/components/MediaViewer'
import BasketPlayer from './BasketPlayer'
import AudioPickerDrawer from './AudioPickerDrawer'

const BASKET_TYPES = ['music', 'message', 'jingle', 'ambiance', 'emergency'] as const
const BASKET_SCOPES = ['national', 'regional', 'local', 'style'] as const
// Types qui déclenchent le ducking (baissent la musique)
const DUCKING_TRIGGERS = ['message', 'jingle', 'emergency']

function typeBadge(t: string): string {
  const map: Record<string, string> = {
    music:     'bg-accent/10 dark:bg-blue-500/15 text-blue-700 dark:text-blue-300',
    message:   'bg-amber-500/10 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300',
    jingle:    'bg-purple-50 dark:bg-purple-500/15 text-purple-700 dark:text-purple-300',
    ambiance:  'bg-teal-50 dark:bg-teal-500/15 text-teal-700 dark:text-teal-300',
    emergency: 'bg-red-500/10 dark:bg-red-500/15 text-red-700 dark:text-red-300',
  }
  return map[t] ?? 'bg-gray-100 text-gray-600'
}

export default function AudioBasketsPage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<AudioBasket | null>(null)
  const [itemsBasket, setItemsBasket] = useState<AudioBasket | null>(null)
  // Écoute d'un panier (lecteur enchaîné) + picker audio — rendus AU NIVEAU PAGE :
  // un Drawer imbriqué dans un Drawer serait cassé par le transform du panneau parent.
  const [playingBasket, setPlayingBasket] = useState<AudioBasket | null>(null)
  const [pickerFor, setPickerFor] = useState<AudioBasket | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [basketType, setBasketType] = useState<string>('music')
  const [basketScope, setBasketScope] = useState<string>('local')
  const [description, setDescription] = useState('')
  const [isMandatory, setIsMandatory] = useState(false)
  const [duckingEnabled, setDuckingEnabled] = useState(false)
  const [duckingTarget, setDuckingTarget] = useState(20)
  const [fadeIn, setFadeIn] = useState(500)
  const [fadeOut, setFadeOut] = useState(1500)
  // Cadence jingle : 'tracks' (tous les N morceaux) | 'minutes' (toutes les N min)
  const [triggerMode, setTriggerMode] = useState<'tracks' | 'minutes'>('tracks')
  const [triggerValue, setTriggerValue] = useState(5)
  const [shuffle, setShuffle] = useState(false)
  // Bornes de mix (music/ambiance) — garde-fous pour l'auto-équilibrage (§XIX option C)
  const [minRatio, setMinRatio] = useState(0)
  const [maxRatio, setMaxRatio] = useState(100)
  // Rattachement à un nœud de gouvernance (§XVIII) — '' = portée globale org
  const [idNode, setIdNode] = useState<string>('')

  const { data: baskets = [], isLoading } = useQuery<AudioBasket[]>({
    queryKey: ['audio-baskets'],
    queryFn: () => api.get<AudioBasket[]>('/audio-baskets').then((r) => r.data),
  })

  const { data: govNodes = [] } = useQuery<GovernanceNode[]>({
    queryKey: ['gov-nodes'],
    queryFn: () => api.get<GovernanceNode[]>('/governance/nodes').then((r) => r.data),
  })

  function resetForm() {
    setName(''); setBasketType('music'); setBasketScope('local'); setDescription('')
    setIsMandatory(false); setDuckingEnabled(false); setDuckingTarget(20); setFadeIn(500); setFadeOut(1500)
    setTriggerMode('tracks'); setTriggerValue(5); setShuffle(false)
    setMinRatio(0); setMaxRatio(100)
    setIdNode('')
    setEditing(null)
  }

  function openCreate() {
    resetForm()
    setDrawerOpen(true)
  }

  function openEdit(b: AudioBasket) {
    setEditing(b)
    setName(b.basket_name)
    setBasketType(b.basket_type)
    setBasketScope(b.basket_scope)
    setDescription(b.description ?? '')
    setIsMandatory(b.is_mandatory)
    setDuckingEnabled(!!b.ducking_config?.enabled)
    setDuckingTarget(b.ducking_config?.target_pct ?? 20)
    setFadeIn(b.ducking_config?.fade_in_ms ?? 500)
    setFadeOut(b.ducking_config?.fade_out_ms ?? 1500)
    setTriggerMode((b.trigger_mode as 'tracks' | 'minutes') ?? 'tracks')
    setTriggerValue(b.trigger_value ?? 5)
    setShuffle(!!b.shuffle)
    setMinRatio(b.min_ratio ?? 0)
    setMaxRatio(b.max_ratio ?? 100)
    setIdNode(b.id_node != null ? String(b.id_node) : '')
    setDrawerOpen(true)
  }

  function buildBody() {
    const ducking = duckingEnabled
      ? { enabled: true, target_pct: duckingTarget, fade_in_ms: fadeIn, fade_out_ms: fadeOut }
      : {}
    return {
      basket_name: name.trim(),
      basket_type: basketType,
      basket_scope: basketScope,
      description: description.trim() || null,
      is_mandatory: isMandatory,
      ducking_config: ducking,
      trigger_mode: triggerMode,
      trigger_value: triggerValue,
      shuffle,
      min_ratio: minRatio,
      max_ratio: maxRatio,
      id_node: idNode ? Number(idNode) : null,
    }
  }

  const saveMutation = useMutation({
    mutationFn: () => editing
      ? api.put(`/audio-baskets/${editing.id_basket}`, buildBody()).then((r) => r.data)
      : api.post('/audio-baskets', buildBody()).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['audio-baskets'] })
      setDrawerOpen(false)
      resetForm()
    },
  })

  // Suppression : le serveur refuse en 409 en NOMMANT les programmes et événements qui
  // diffusent ce panier (A5, audit 29/07). On montre ce message et on ne force qu'après un
  // second consentement explicite — un « détacher quand même » ne doit jamais être le
  // comportement par défaut d'un clic sur une poubelle.
  const deleteMutation = useMutation({
    mutationFn: ({ id, force }: { id: number; force?: boolean }) =>
      api.delete(`/audio-baskets/${id}${force ? '?force=true' : ''}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['audio-baskets'] }),
    onError: (e: unknown, vars) => {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      if (err?.response?.status !== 409) return
      const detail = err.response?.data?.detail ?? ''
      if (confirm(`${detail}\n\n${t('ab.delete_force_confirm')}`)) {
        deleteMutation.mutate({ id: vars.id, force: true })
      }
    },
  })

  const filtered = search
    ? baskets.filter((b) => b.basket_name.toLowerCase().includes(search.toLowerCase()))
    : baskets

  const showDucking = DUCKING_TRIGGERS.includes(basketType)

  return (
    <>
      <Topbar title={t('ab.title')}>
        {/* CRUD paniers = audio_baskets:configure (aucun rôle non-admin ne l'a ;
            le Store Operator a 'control' = affectation aux players, ailleurs). */}
        <Can perm="audio_baskets:configure">
          <Button size="sm" onClick={openCreate}>
            <Plus className="w-4 h-4 mr-1.5" />
            {t('ab.new_basket')}
          </Button>
        </Can>
      </Topbar>

      {/* Page verrouillée au viewport : seules les vignettes défilent. */}
      <main className="flex-1 flex flex-col min-h-0">
        <div className="shrink-0 px-6 pt-6 pb-4">
          <p className="text-xs text-gray-400 mb-4">{t('ab.assignment_moved')}</p>
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('common.search')}
          />
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 pb-6">
          {isLoading ? (
            <div className="flex justify-center py-16">
              <span className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-gray-400">
              <Music className="w-10 h-10 mb-3 opacity-30" />
              <p className="text-sm">{t('ab.no_baskets')}</p>
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
              {filtered.map((b) => (
                <div key={b.id_basket} className="bg-surface rounded-lg border border-gray-200 p-4 hover:border-accent hover:shadow-sm transition-sf">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <p className="font-medium text-gray-900 text-sm truncate" title={b.basket_name}>{b.basket_name}</p>
                    <div className="flex items-center gap-1 shrink-0">
                    {/* Écouter = une LECTURE : accessible dès audio_baskets:read, hors du gate configure */}
                    {b.item_count > 0 && (
                      <button
                        onClick={() => setPlayingBasket(b)}
                        className="p-1 rounded text-gray-400 hover:text-accent hover:bg-gray-100"
                        title={t('ab.play_basket')}
                        data-testid={`play-basket-${b.id_basket}`}
                      >
                        <Play className="w-4 h-4" />
                      </button>
                    )}
                    <Can perm="audio_baskets:configure">
                      <div className="flex items-center gap-1 shrink-0">
                        <button onClick={() => setItemsBasket(b)} className="p-1 rounded text-gray-400 hover:text-accent hover:bg-gray-100" title={t('ab.manage_items')}>
                          <ListMusic className="w-4 h-4" />
                        </button>
                        <button onClick={() => openEdit(b)} className="p-1 rounded text-gray-400 hover:text-accent hover:bg-gray-100" title={t('common.edit')}>
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button onClick={() => { if (confirm(t('ab.delete_confirm'))) deleteMutation.mutate({ id: b.id_basket }) }} className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10" title={t('common.delete')}>
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </Can>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 flex-wrap mb-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${typeBadge(b.basket_type)}`}>
                      {t(`ab.type_${b.basket_type}`)}
                    </span>
                    <span className="text-xs text-gray-400">{t(`ab.scope_${b.basket_scope}`)}</span>
                    {b.is_mandatory && <span className="text-xs text-red-500 font-medium">★</span>}
                  </div>
                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <span>
                      {t('ab.item_count', { count: b.item_count })}
                      {/* Durée totale des pistes (somme des durées natives connues). */}
                      {b.total_duration_ms != null && <> · {formatMs(b.total_duration_ms)}</>}
                    </span>
                    {b.ducking_config?.enabled && (
                      <span className="inline-flex items-center gap-0.5 text-teal-600 dark:text-teal-300">
                        <Volume2 className="w-3 h-3" /> {b.ducking_config.target_pct}%
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      {/* Create / edit drawer */}
      <Drawer open={drawerOpen} onClose={() => { setDrawerOpen(false); resetForm() }} title={editing ? t('ab.edit_basket') : t('ab.new_basket')}>
        {/* Écritures paniers = audio_baskets:configure */}
        <div className="space-y-4" data-write-perm="audio_baskets:configure">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t('ab.name')}</label>
            <input value={name} onChange={(e) => setName(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('ab.type')}</label>
              <select value={basketType} onChange={(e) => setBasketType(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface">
                {BASKET_TYPES.map((bt) => <option key={bt} value={bt}>{t(`ab.type_${bt}`)}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('ab.scope')}</label>
              <select value={basketScope} onChange={(e) => setBasketScope(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface">
                {BASKET_SCOPES.map((s) => <option key={s} value={s}>{t(`ab.scope_${s}`)}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t('ab.description')}</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40" />
          </div>
          {govNodes.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t('ab.governance_node')}</label>
              <select value={idNode} onChange={(e) => setIdNode(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface">
                <option value="">{t('ab.governance_global')}</option>
                {govNodes.map((n) => (
                  <option key={n.id_node} value={n.id_node}>{'— '.repeat(n.node_level)}{n.node_name}</option>
                ))}
              </select>
              <p className="text-[10px] text-gray-400 mt-0.5">{t('ab.governance_hint')}</p>
            </div>
          )}

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" checked={isMandatory} onChange={(e) => setIsMandatory(e.target.checked)} className="accent-accent w-4 h-4" />
            <span className="text-xs text-gray-600">{t('ab.mandatory')}</span>
          </label>

          {/* Bornes de mix (music/ambiance) — garde-fous de l'auto-équilibrage des % */}
          {['music', 'ambiance'].includes(basketType) && (
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">{t('ab.min_ratio')}</label>
                <NumberField min={0} max={100} value={minRatio}
                  onCommit={(v) => setMinRatio(v ?? 0)}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">{t('ab.max_ratio')}</label>
                <NumberField min={0} max={100} value={maxRatio}
                  onCommit={(v) => setMaxRatio(v ?? 100)}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
              </div>
              <p className="col-span-2 text-[10px] text-gray-400">{t('ab.ratio_bounds_hint')}</p>
            </div>
          )}

          {/* Shuffle (lecture aléatoire) — paniers Music/Ambiance */}
          {['music', 'ambiance'].includes(basketType) && (
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input type="checkbox" checked={shuffle} onChange={(e) => setShuffle(e.target.checked)} className="accent-accent w-4 h-4" />
              <span className="text-xs text-gray-600">{t('ab.shuffle')}</span>
            </label>
          )}

          {/* Cadence jingle — récurrence automatique */}
          {basketType === 'jingle' && (
            <div className="border border-purple-200 dark:border-purple-500/30 rounded-lg p-3 space-y-2 bg-purple-500/10">
              <p className="text-xs font-medium text-gray-700">{t('ab.jingle_recurrence')}</p>
              <div className="flex rounded overflow-hidden border border-gray-200 text-xs w-max">
                {(['tracks', 'minutes'] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setTriggerMode(m)}
                    className={`px-3 py-1 font-medium transition-sf ${
                      triggerMode === m ? 'bg-accent text-white' : 'bg-surface text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {t(`ab.jingle_mode_${m}`)}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <NumberField min={1} value={triggerValue}
                  onCommit={(v) => setTriggerValue(v ?? 1)}
                  className="w-24 border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
                <span className="text-xs text-gray-500">
                  {triggerMode === 'tracks' ? t('ab.jingle_unit_tracks') : t('ab.jingle_unit_minutes')}
                </span>
              </div>
            </div>
          )}

          {/* Ducking — uniquement pour les types déclencheurs */}
          {showDucking && (
            <div className="border border-teal-200 dark:border-teal-500/30 rounded-lg p-3 space-y-3 bg-teal-50/40">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" checked={duckingEnabled} onChange={(e) => setDuckingEnabled(e.target.checked)} className="accent-accent w-4 h-4" />
                <Volume2 className="w-3.5 h-3.5 text-teal-600 dark:text-teal-300" />
                <span className="text-xs font-medium text-gray-700">{t('ab.ducking')}</span>
              </label>
              {duckingEnabled && (
                <div className="pl-4 space-y-2">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('ab.ducking_target')}</label>
                    <NumberField min={0} max={100} value={duckingTarget} onCommit={(v) => setDuckingTarget(v ?? 0)}
                      className="w-24 border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">{t('ab.ducking_fade_in')}</label>
                      <NumberField min={0} value={fadeIn} onCommit={(v) => setFadeIn(v ?? 0)}
                        className="w-full border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">{t('ab.ducking_fade_out')}</label>
                      <NumberField min={0} value={fadeOut} onCommit={(v) => setFadeOut(v ?? 0)}
                        className="w-full border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
                    </div>
                  </div>
                </div>
              )}
              <p className="text-[10px] text-teal-600 dark:text-teal-300">{t('ab.ducking_hint')}</p>
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <Button data-write-action onClick={() => saveMutation.mutate()} disabled={!name.trim() || saveMutation.isPending} className="flex-1">
              {saveMutation.isPending ? t('common.loading') : t('ab.save')}
            </Button>
            <Button variant="ghost" onClick={() => { setDrawerOpen(false); resetForm() }}>{t('ab.cancel')}</Button>
          </div>
        </div>
      </Drawer>

      {/* Items drawer — Échap ne doit fermer QUE la couche du dessus : tant que le picker
          est ouvert par-dessus, ce drawer refuse de se fermer (les deux Drawers écoutent
          Échap sur document, même leçon que la visionneuse en phase capture). */}
      <Drawer
        open={itemsBasket !== null}
        onClose={() => { if (pickerFor === null) setItemsBasket(null) }}
        title={itemsBasket?.basket_name ?? ''}
      >
        {itemsBasket && (
          <BasketItemsEditor
            basket={itemsBasket}
            onOpenPicker={() => setPickerFor(itemsBasket)}
            onPlay={() => setPlayingBasket(itemsBasket)}
          />
        )}
      </Drawer>

      {/* Picker audio (frère du drawer d'items, jamais imbriqué) */}
      <AudioPickerDrawer basket={pickerFor} onClose={() => setPickerFor(null)} />

      {/* Lecteur de panier — élevé quand il s'ouvre par-dessus le drawer d'items */}
      <BasketPlayer
        basket={playingBasket}
        onClose={() => setPlayingBasket(null)}
        elevated={itemsBasket !== null}
      />
    </>
  )
}


// ── Sous-composant : gestion des items d'un panier ───────────────────────────

function BasketItemsEditor({
  basket, onOpenPicker, onPlay,
}: {
  basket: AudioBasket
  /** Ouvre le picker audio (rendu au niveau PAGE — jamais un Drawer dans un Drawer). */
  onOpenPicker: () => void
  /** Écoute enchaînée du panier (BasketPlayer, élevé au-dessus de ce drawer). */
  onPlay: () => void
}) {
  const t = useTranslations()
  const qc = useQueryClient()
  const [ruleItem, setRuleItem] = useState<number | null>(null)  // item dont la règle est éditée
  // Écoute d'UN morceau : index dans la liste des items (visionneuse élevée).
  const [trackIdx, setTrackIdx] = useState<number | null>(null)
  // Les règles de diffusion ne concernent que les paniers programmés (pas Alert/Message).
  const rulesAllowed = ['music', 'ambiance', 'jingle'].includes(basket.basket_type)

  const { data: items = [] } = useQuery<BasketItem[]>({
    queryKey: ['basket-items', basket.id_basket],
    queryFn: () => api.get<BasketItem[]>(`/audio-baskets/${basket.id_basket}/items`).then((r) => r.data),
  })

  const removeMutation = useMutation({
    mutationFn: (id_item: number) => api.delete(`/audio-baskets/${basket.id_basket}/items/${id_item}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['basket-items', basket.id_basket] })
      qc.invalidateQueries({ queryKey: ['audio-baskets'] })
    },
  })

  const track = trackIdx !== null ? items[trackIdx] ?? null : null

  return (
    <div className="space-y-3">
      {items.length > 0 && (
        <Button size="sm" variant="secondary" onClick={onPlay} className="w-full" data-testid="items-play-basket">
          <Play className="w-4 h-4 mr-1.5" />
          {t('ab.play_basket')}
        </Button>
      )}

      {items.length === 0 && (
        <p className="text-xs text-gray-400 italic py-4 text-center">{t('ab.no_baskets')}</p>
      )}

      {items.map((it) => {
        const hasRule = !!(it.rule_days?.length || it.rule_time_start || it.rule_time_end)
        return (
        <div key={it.id_item} className="bg-gray-50 border border-gray-200 rounded px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs font-medium text-gray-800 truncate flex items-center gap-1.5">
                {it.media_name ?? `#${it.id_media}`}
                {hasRule && <CalendarClock className="w-3 h-3 text-accent shrink-0" />}
              </p>
              <p className="text-[10px] text-gray-400">
                {t('ab.weight')}: {it.weight}
                {it.duration_ms != null && <> · {Math.round(it.duration_ms / 1000)}s</>}
              </p>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={() => setTrackIdx(items.indexOf(it))}
                className="p-1 rounded text-gray-400 hover:text-accent hover:bg-gray-100"
                title={t('ab.listen')}
                data-testid={`listen-item-${it.id_item}`}
              >
                <Headphones className="w-3.5 h-3.5" />
              </button>
              {rulesAllowed && (
                <button
                  onClick={() => setRuleItem(ruleItem === it.id_item ? null : it.id_item)}
                  className={`p-1 rounded hover:bg-gray-100 ${hasRule ? 'text-accent' : 'text-gray-400 hover:text-accent'}`}
                  title={t('ab.broadcast_rule')}
                >
                  <CalendarClock className="w-3.5 h-3.5" />
                </button>
              )}
              <button onClick={() => removeMutation.mutate(it.id_item)} className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          {rulesAllowed && ruleItem === it.id_item && (
            <ItemRuleEditor basket={basket} item={it} t={t}
              onSaved={() => { qc.invalidateQueries({ queryKey: ['basket-items', basket.id_basket] }); setRuleItem(null) }} />
          )}
        </div>
        )
      })}

      {/* L'ancien picker plat (une requête sans recherche ni dossier) ne montrait que la
          première page depuis la pagination server-side de /media — remplacé par le drawer
          de recherche AudioPickerDrawer, ouvert au niveau page. */}
      <Button size="sm" variant="secondary" onClick={onOpenPicker} className="w-full" data-testid="open-audio-picker">
        <Plus className="w-4 h-4 mr-1.5" />{t('ab.add_media')}
      </Button>

      {/* Écoute d'un morceau du panier — par-dessus le drawer (portail + z-60) */}
      <MediaViewer
        item={track ? {
          id_media: track.id_media,
          media_name: track.media_name ?? `#${track.id_media}`,
          media_type: 'audio',
        } : null}
        onClose={() => setTrackIdx(null)}
        onPrev={trackIdx !== null && trackIdx > 0 ? () => setTrackIdx((i) => (i ?? 1) - 1) : undefined}
        onNext={trackIdx !== null && trackIdx < items.length - 1 ? () => setTrackIdx((i) => (i ?? 0) + 1) : undefined}
        position={trackIdx !== null && items.length > 1 ? { index: trackIdx, total: items.length } : undefined}
        elevated
      />
    </div>
  )
}


// ── Éditeur de règle de diffusion d'un item de panier (heure locale) ─────────────
const RULE_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

function ItemRuleEditor({
  basket, item, t, onSaved,
}: {
  basket: AudioBasket
  item: BasketItem
  t: ReturnType<typeof useTranslations>
  onSaved: () => void
}) {
  const [days, setDays] = useState<number[]>(item.rule_days ?? [])
  const [start, setStart] = useState((item.rule_time_start ?? '').slice(0, 5))
  const [end, setEnd] = useState((item.rule_time_end ?? '').slice(0, 5))

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch(`/audio-baskets/${basket.id_basket}/items/${item.id_item}`, body),
    onSuccess: onSaved,
  })

  const toggleDay = (d: number) =>
    setDays((prev) => prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d].sort())

  return (
    <div className="mt-2 pt-2 border-t border-gray-200 space-y-2">
      <p className="text-[10px] text-gray-400">{t('ab.rule_hint')}</p>
      <div className="flex flex-wrap gap-1">
        {RULE_DAYS.map((d, i) => (
          <button key={d} type="button" onClick={() => toggleDay(i)}
            className={`px-1.5 py-0.5 rounded text-[10px] font-medium border transition-sf ${
              days.includes(i) ? 'bg-accent text-white border-transparent' : 'bg-surface text-gray-600 border-gray-300 hover:bg-gray-50'
            }`}>
            {t(`ab.day_${d}`)}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <input type="time" value={start} onChange={(e) => setStart(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
        <span className="text-[10px] text-gray-400">→</span>
        <input type="time" value={end} onChange={(e) => setEnd(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40" />
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" loading={save.isPending}
          onClick={() => save.mutate({
            rule_days: days.length ? days : null,
            rule_time_start: start || null,
            rule_time_end: end || null,
          })}>
          {t('ab.rule_save')}
        </Button>
        <button type="button" onClick={() => save.mutate({ rule_days: null, rule_time_start: null, rule_time_end: null })}
          className="text-[10px] text-gray-400 hover:text-danger">
          {t('ab.rule_clear')}
        </button>
      </div>
    </div>
  )
}
