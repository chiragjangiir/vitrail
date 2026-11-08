'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlayCircle, Plus, Trash2, Search, X, AlertTriangle, Film, Image as ImageIcon, FileText, Play, Repeat, Square, ChevronDown, ChevronRight, MonitorPlay, Volume2, VolumeX, MapPin } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Can from '@/components/auth/Can'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import Input from '@/components/ui/Input'
import SearchInput from '@/components/ui/SearchInput'
import api from '@/lib/api'
import NodeSelect from '@/components/governance/NodeSelect'
import ContentPickerDrawer from '@/components/content/ContentPickerDrawer'
import TargetMapDrawer from '@/components/targets/TargetMapDrawer'
import { isDemoBlocked } from '@/lib/demo'
import { useOpenShortcut } from '@/lib/useOpenShortcut'
import type { MediaListItem, PlayerRead, Site, VodConfig, VodTargetMode } from '@/types/api'

// Visuels pré-cachés + pointeur « entrée HDMI » (switch ON/OFF de la source, BrightSign XT).
const VISUAL_TYPES = ['video', 'image', 'document', 'hdmi_input']

function mediaIcon(type: string | null) {
  if (type === 'image') return ImageIcon
  if (type === 'document') return FileText
  if (type === 'hdmi_input') return MonitorPlay
  return Film
}

/** Modèles BrightSign à entrée HDMI (miroir de players/page.tsx `bsHasHdmiInput` + serveur
 *  `_player_has_hdmi_input`) : gamme XT, 4K1142/4K1242, XD1230 — HD/LS exclus. */
function bsHasHdmiInput(model?: string | null): boolean {
  const m = (model || '').toUpperCase()
  return /^XT\d/.test(m) || /^4K1[12]\d\d/.test(m) || m === 'XD1230'
}

function playerHasHdmiInput(p: PlayerRead): boolean {
  return p.player_os === 'brightsign' && bsHasHdmiInput(p.capabilities?.bs_model)
}

/** /24 de l'IP LAN (heuristique, pas un vrai netmask) — sanity-check réseau du LAN Sync. */
function subnet24(ip: string | null): string | null {
  if (!ip) return null
  const m = ip.match(/^(\d+)\.(\d+)\.(\d+)\.\d+$/)
  return m ? `${m[1]}.${m[2]}.${m[3]}` : null
}

export default function VodPage() {
  const t = useTranslations()
  const qc = useQueryClient()

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [search, setSearch] = useState('')

  // Form state
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [pickedMedia, setPickedMedia] = useState<number[]>([])
  const [pickedPlayers, setPickedPlayers] = useState<number[]>([])
  // Ciblage : liste figée de players, ou SITE entier (cible dynamique, migr 0096).
  const [targetMode, setTargetMode] = useState<VodTargetMode>('players')
  const [pickedSite, setPickedSite] = useState<number | null>(null)
  const [mediaSearch, setMediaSearch] = useState('')
  // Briques partagées (audit 2026-07-29) : même tiroir de contenu et même carte que les
  // événements, les playlists et les paniers audio.
  const [contentPickerOpen, setContentPickerOpen] = useState(false)
  const [mapOpen, setMapOpen] = useState(false)
  // Noms des médias retenus, RENDUS PAR LE TIROIR : un contenu trouvé par recherche peut
  // être absent de la liste chargée d'avance — c'est précisément ce que le tiroir permet.
  const [pickedNames, setPickedNames] = useState<Record<number, string>>({})
  const [mutateError, setMutateError] = useState<string | null>(null)
  const [govNode, setGovNode] = useState<number | null>(null)
  const [playFeedback, setPlayFeedback] = useState<string | null>(null)
  // Sections repliables (pliées par défaut)
  const [playersOpen, setPlayersOpen] = useState(false)
  const [mediasOpen, setMediasOpen] = useState(false)
  // Players cibles du déclenchement (sous-ensemble des players de la config)
  const [playTargets, setPlayTargets] = useState<number[]>([])
  // Son du takeover, choisi À CHAQUE déclenchement (décision Ed 2026-07-19) : la
  // programmation peut être muette (content_sound) alors qu'on veut être entendu — ou
  // l'inverse. Le player ducke la musique de fond seulement si le média a une piste audio.
  const [playWithSound, setPlayWithSound] = useState(true)

  const { data: configs = [], isLoading } = useQuery<VodConfig[]>({
    queryKey: ['vod'],
    queryFn: () => api.get<VodConfig[]>('/vod').then((r) => r.data),
  })

  const { data: allPlayers = [] } = useQuery<PlayerRead[]>({
    queryKey: ['players'],
    queryFn: () => api.get<PlayerRead[]>('/players/').then((r) => r.data),
    enabled: drawerOpen,
  })

  const { data: allSites = [] } = useQuery<Site[]>({
    queryKey: ['sites'],
    queryFn: () => api.get<Site[]>('/sites').then((r) => r.data),
    enabled: drawerOpen,
  })

  const { data: allMedia = [] } = useQuery<MediaListItem[]>({
    queryKey: ['media-visual'],
    queryFn: () => api.get<MediaListItem[]>('/media/').then((r) => r.data),
    enabled: drawerOpen,
  })

  const visualMedia = useMemo(
    () => allMedia.filter((m) => VISUAL_TYPES.includes(m.media_type)),
    [allMedia],
  )

  // Un média « Entrée HDMI » dans la sélection restreint les players de la config aux seuls
  // modèles à entrée HDMI physique (demande Ed : ne LISTER que les compatibles).
  const hasHdmiMedia = useMemo(
    () => pickedMedia.some((id) => allMedia.find((m) => m.id_media === id)?.media_type === 'hdmi_input'),
    [pickedMedia, allMedia],
  )
  const selectablePlayers = useMemo(
    () => (hasHdmiMedia ? allPlayers.filter(playerHasHdmiInput) : allPlayers),
    [hasHdmiMedia, allPlayers],
  )
  // Purge les players déjà cochés devenus incompatibles quand un média HDMI est ajouté.
  useEffect(() => {
    if (!hasHdmiMedia || allPlayers.length === 0) return
    setPickedPlayers((prev) => prev.filter((id) => {
      const p = allPlayers.find((x) => x.id_player === id)
      return p !== undefined && playerHasHdmiInput(p)
    }))
  }, [hasHdmiMedia, allPlayers])

  function resetForm() {
    setName(''); setDescription(''); setPickedMedia([]); setPickedPlayers([])
    setTargetMode('players'); setPickedSite(null); setGovNode(null)
    setMediaSearch(''); setMutateError(null); setPlayFeedback(null)
    setPlayersOpen(false); setMediasOpen(false); setPlayTargets([]); setPlayWithSound(true)
  }
  function openCreate() { resetForm(); setEditId(null); setPlayersOpen(true); setMediasOpen(true); setDrawerOpen(true) }
  function openEdit(c: VodConfig) {
    setName(c.vod_name); setDescription(c.description ?? '')
    setPickedMedia(c.medias.map((m) => m.id_media))
    // En ciblage site, `players` est la cible RÉSOLUE (pas une liste éditable) : on ne la
    // recopie pas dans les cases à cocher, elles ne sont pas affichées dans ce mode.
    setTargetMode(c.target_mode); setPickedSite(c.id_site)
    setGovNode(c.id_governance_node ?? null)
    setPickedPlayers(c.target_mode === 'site' ? [] : c.players.map((p) => p.id_player))
    setPlayTargets(c.players.map((p) => p.id_player))   // cibles par défaut = tous les players
    setMediaSearch(''); setMutateError(null); setPlayFeedback(null)
    setPlayersOpen(false); setMediasOpen(false)
    setEditId(c.id_vod); setDrawerOpen(true)
  }
  function closeDrawer() { setDrawerOpen(false); setEditId(null); resetForm() }

  // Contrainte « même site » : les players cochés doivent partager le même id_site.
  const selectedPlayerObjs = allPlayers.filter((p) => pickedPlayers.includes(p.id_player))
  const distinctSites = new Set(selectedPlayerObjs.map((p) => p.id_site))
  const mixedSite = distinctSites.size > 1
  // Le site cible (si cohérent) restreint les players sélectionnables aux mêmes-site.
  const targetSite = distinctSites.size === 1 ? [...distinctSites][0] : undefined

  // Sanity-check réseau (avertissement uniquement) : on ne compare QUE les sous-réseaux LAN
  // /24 des players dont l'IP est connue. Un player sans IP LAN (ex. ChromeOS = navigateur) est
  // ignoré (on ne peut rien en déduire) ; on ne compare PAS les wan_ip (un player connecté via
  // WAN aurait un wan_ip différent → faux positif). Warn seulement si ≥2 subnets LAN distincts.
  const networkWarn = useMemo(() => {
    if (mixedSite) return false
    const subnets = new Set(selectedPlayerObjs.map((p) => subnet24(p.ip_address)).filter(Boolean))
    return subnets.size > 1
  }, [selectedPlayerObjs, mixedSite])

  function togglePlayer(id: number) {
    setPickedPlayers((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
  }
  function toggleMedia(id: number) {
    setPickedMedia((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      // `id_governance_node` : nœud propriétaire (§XVIII migr 0112) — null = config d'org.
      const common = {
        vod_name: name, description: description || null,
        id_medias: pickedMedia, id_governance_node: govNode,
      }
      const body = targetMode === 'site'
        ? { ...common, target_mode: 'site', id_site: pickedSite }
        : { ...common, target_mode: 'players', id_players: pickedPlayers }
      if (editId === null) await api.post('/vod', body)
      else await api.put(`/vod/${editId}`, body)
    },
    onSuccess: async () => { await qc.refetchQueries({ queryKey: ['vod'] }); closeDrawer() },
    onError: (e: unknown) => {
      if (isDemoBlocked(e)) return  // toast global démo → pas de message dans le drawer
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMutateError(typeof detail === 'string' ? detail : t('common.error'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/vod/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vod'] }),
  })

  // Trigger CLOUD play_now (§Phase 2) : diffuse un média sur les players CIBLES sélectionnés.
  const playMutation = useMutation({
    mutationFn: (v: { id_media: number; mode: 'once' | 'loop' | 'stop' | 'start' }) =>
      api.post<{ dispatched: number[] }>(`/vod/${editId}/play`,
        { ...v, id_players: playTargets, with_sound: playWithSound }).then((r) => r.data),
    onSuccess: (data, v) => {
      setPlayFeedback(
        v.mode === 'stop'
          ? t('vod.broadcast_stopped', { count: data.dispatched.length })
          : v.mode === 'start'
            ? t('vod.switched_on', { count: data.dispatched.length })
            : t('vod.broadcast_sent', { count: data.dispatched.length }))
      setTimeout(() => setPlayFeedback(null), 4000)
    },
    onError: () => { setPlayFeedback(t('common.error')); setTimeout(() => setPlayFeedback(null), 4000) },
  })

  // Recherche globale -> `/vod?open=<id>` : la page n'a pas de barre locale, on ouvre la fiche.
  const [pendingOpen, setPendingOpen] = useState<number | null>(null)
  useOpenShortcut(setPendingOpen)
  useEffect(() => {
    if (pendingOpen === null || configs.length === 0) return
    const target = configs.find((c) => c.id_vod === pendingOpen)
    if (target) openEdit(target)
    setPendingOpen(null)
  }, [pendingOpen, configs])   // eslint-disable-line react-hooks/exhaustive-deps

  const editedConfig = editId !== null ? configs.find((c) => c.id_vod === editId) : undefined
  const filtered = configs.filter((c) => !search || c.vod_name.toLowerCase().includes(search.toLowerCase()))
  const filteredMedia = visualMedia.filter((m) => !mediaSearch || m.media_name.toLowerCase().includes(mediaSearch.toLowerCase()))
  // Players du site ciblé — aperçu de la cible résolue (le serveur fait foi, cf. players_for_target).
  const sitePlayers = useMemo(
    () => (pickedSite === null ? [] : allPlayers.filter((p) => p.id_site === pickedSite)),
    [pickedSite, allPlayers],
  )
  // En ciblage site, la cible n'est pas une liste cochée : elle exige juste un site valide.
  const targetOk = targetMode === 'site' ? pickedSite !== null : (pickedPlayers.length > 0 && !mixedSite)
  const canSave = !!name && pickedMedia.length > 0 && targetOk

  return (
    <>
      <Topbar title={t('vod.title')}>
        <Can perm="vod:create">
          <Button size="sm" onClick={openCreate}>
            <Plus className="w-4 h-4 mr-1" />{t('vod.new')}
          </Button>
        </Can>
      </Topbar>

      {/* Page verrouillée au viewport : seules les vignettes défilent. */}
      <main className="flex-1 flex flex-col min-h-0">
        <div className="shrink-0 px-6 pt-8 pb-4 space-y-4">
          <p className="text-sm text-gray-500">{t('vod.intro')}</p>
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('common.search')}
          />
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 pb-8">
          {isLoading ? (
            <p className="text-sm text-gray-400">{t('common.loading')}</p>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-400">
              <PlayCircle className="w-10 h-10" />
              <p className="text-sm">{t('vod.empty')}</p>
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
              {filtered.map((c) => (
                <div
                  key={c.id_vod}
                  role="button" tabIndex={0}
                  onClick={() => openEdit(c)}
                  onKeyDown={(e) => { if (e.key === 'Enter') openEdit(c) }}
                  className="bg-surface border border-gray-200 rounded-lg p-4 cursor-pointer transition-sf hover:border-accent shadow-sf-card"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <PlayCircle className="w-4 h-4 text-accent shrink-0" />
                      <span className="text-sm font-medium text-gray-900 truncate" title={c.vod_name}>{c.vod_name}</span>
                    </div>
                    <Can perm="vod:delete">
                      <button
                        onClick={(e) => { e.stopPropagation(); if (confirm(t('vod.delete_confirm'))) deleteMutation.mutate(c.id_vod) }}
                        className="p-1 text-gray-300 hover:text-danger transition-sf shrink-0"
                        title={t('common.delete')}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </Can>
                  </div>
                  {c.site_name && <p className="text-xs text-gray-400 truncate mt-1">{c.site_name}</p>}
                  <div className="flex items-center gap-3 mt-3 text-[11px] text-gray-500">
                    <span className="inline-flex items-center gap-1"><Film className="w-3 h-3" />{c.medias.length} {t('vod.medias_count')}</span>
                    <span className="inline-flex items-center gap-1"><PlayCircle className="w-3 h-3" />{c.players.length} {t('vod.players_count')}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      <Drawer open={drawerOpen} onClose={closeDrawer} title={editId !== null ? t('vod.edit') : t('vod.new')} width="w-[560px]">
        {/* Nudge lecture-seule : édition de la config = vod:edit, création = vod:create.
            La section « Diffuser » plus bas porte son propre data-write-perm=vod:trigger. */}
        <div className="space-y-5" data-write-perm={editId !== null ? 'vod:edit' : 'vod:create'}>
          <Input label={t('vod.name_label')} value={name} onChange={(e) => setName(e.target.value)} />
          <Input label={t('vod.description_label')} value={description} onChange={(e) => setDescription(e.target.value)} />

          {/* Gouvernance §XVIII : masqué si l'org n'a aucun nœud. Rattacher une config la
              confie à l'administrateur du nœud (et à ses ancêtres). */}
          <NodeSelect value={govNode} onChange={setGovNode} />

          {/* Players (contrainte même-site) — repliable */}
          <div className="space-y-1.5">
            <button type="button" onClick={() => setPlayersOpen((v) => !v)}
              className="flex items-center gap-1.5 w-full text-left text-sm font-medium text-gray-700">
              {playersOpen ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
              {t('vod.players_label')}
              <span className="text-xs text-gray-400 font-normal">
                ({targetMode === 'site' ? sitePlayers.length : pickedPlayers.length})
              </span>
            </button>
            {playersOpen && <>
            {/* Mode de ciblage : liste figée de players, ou SITE entier (cible dynamique). */}
            <div className="flex gap-1.5">
              {(['players', 'site'] as VodTargetMode[]).map((m) => (
                <button
                  key={m} type="button" onClick={() => setTargetMode(m)}
                  className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                    targetMode === m
                      ? 'bg-accent/10 border-accent/40 text-accent'
                      : 'border-gray-200 text-gray-500 hover:bg-surface-hover'}`}
                >
                  {t(m === 'site' ? 'vod.mode_site' : 'vod.mode_players')}
                </button>
              ))}
            </div>

            {targetMode === 'site' ? <>
              <p className="text-xs text-gray-400">{t('vod.site_hint')}</p>
              <select
                value={pickedSite ?? ''}
                onChange={(e) => setPickedSite(e.target.value ? Number(e.target.value) : null)}
                className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
              >
                <option value="">{t('vod.site_placeholder')}</option>
                {allSites.map((s) => (
                  <option key={s.id_site} value={s.id_site}>{s.site_name}</option>
                ))}
              </select>
              {pickedSite !== null && (
                <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-52 overflow-y-auto">
                  {sitePlayers.map((p) => (
                    <div key={p.id_player} className="flex items-center gap-2 px-3 py-2 text-sm">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${p.status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
                      <span className="text-gray-700 truncate flex-1">{p.player_name}</span>
                    </div>
                  ))}
                  {sitePlayers.length === 0 && (
                    <p className="text-xs text-gray-400 px-3 py-2">{t('vod.site_no_players')}</p>
                  )}
                </div>
              )}
              {/* Un média HDMI + ciblage site : le serveur ne retiendra que les players capables. */}
              {hasHdmiMedia && (
                <p className="text-xs text-amber-600 dark:text-amber-300 flex items-center gap-1.5">
                  <MonitorPlay className="w-3.5 h-3.5 shrink-0" />{t('vod.hdmi_site_hint')}
                </p>
              )}
            </> : <>
            <p className="text-xs text-gray-400">{t('vod.players_hint')}</p>
            {hasHdmiMedia && (
              <p className="text-xs text-amber-600 dark:text-amber-300 flex items-center gap-1.5">
                <MonitorPlay className="w-3.5 h-3.5 shrink-0" />{t('vod.hdmi_players_hint')}
              </p>
            )}
            <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-52 overflow-y-auto">
              {selectablePlayers.map((p) => {
                const sameSiteOk = targetSite === undefined || p.id_site === targetSite || pickedPlayers.includes(p.id_player)
                return (
                  <label key={p.id_player} className={`flex items-center gap-2 px-3 py-2 text-sm cursor-pointer ${sameSiteOk ? 'hover:bg-gray-50' : 'opacity-40 cursor-not-allowed'}`}>
                    <input
                      type="checkbox" checked={pickedPlayers.includes(p.id_player)}
                      disabled={!sameSiteOk}
                      onChange={() => togglePlayer(p.id_player)}
                      className="rounded-lg border-gray-300 text-accent focus:ring-accent/40"
                    />
                    <span className={`w-2 h-2 rounded-full shrink-0 ${p.status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
                    <span className="text-gray-700 truncate flex-1">{p.player_name}</span>
                    {p.id_site === null && <span className="text-[10px] text-gray-400">{t('vod.no_site')}</span>}
                  </label>
                )
              })}
              {selectablePlayers.length === 0 && <p className="text-xs text-gray-400 px-3 py-2">{t('vod.no_players')}</p>}
            </div>
            {mixedSite && (
              <p className="text-sm text-danger flex items-center gap-1.5"><AlertTriangle className="w-4 h-4 shrink-0" />{t('vod.mixed_site_error')}</p>
            )}
            {networkWarn && !mixedSite && (
              <p className="text-xs text-amber-600 dark:text-amber-300 flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5 shrink-0" />{t('vod.network_warn')}</p>
            )}
            </>}
            </>}
            {/* Erreur site mixte toujours visible même replié (mode players uniquement) */}
            {!playersOpen && mixedSite && targetMode === 'players' && (
              <p className="text-sm text-danger flex items-center gap-1.5"><AlertTriangle className="w-4 h-4 shrink-0" />{t('vod.mixed_site_error')}</p>
            )}
          </div>

          {/* Médias visuels (pré-cache) — repliable */}
          {/* Choisir les écrans SUR LA CARTE — même brique que les événements, avec la
              contrainte propre de la VOD conservée (tous du même site). */}
          {targetMode === 'players' && (
            <button type="button" data-testid="vod-target-map"
                    onClick={() => setMapOpen(true)}
                    className="text-xs text-accent hover:underline inline-flex items-center gap-1">
              <MapPin className="w-3.5 h-3.5" />
              {t('target_map.title')}
            </button>
          )}

          <div className="space-y-1.5">
            <button type="button" data-testid="vod-medias-section"
              onClick={() => setMediasOpen((v) => !v)}
              className="flex items-center gap-1.5 w-full text-left text-sm font-medium text-gray-700">
              {mediasOpen ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
              {t('vod.medias_label')}
              <span className="text-xs text-gray-400 font-normal">({pickedMedia.length})</span>
            </button>
            {mediasOpen && <>
            <p className="text-xs text-gray-400">{t('vod.medias_hint')}</p>
            {pickedMedia.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {pickedMedia.map((id) => {
                  const m = visualMedia.find((x) => x.id_media === id)
                  return (
                    <span key={id} className="inline-flex items-center gap-1 bg-accent/10 text-accent text-xs rounded px-2 py-1">
                      {m?.media_name ?? pickedNames[id] ?? `#${id}`}
                      <button onClick={() => toggleMedia(id)} className="hover:text-danger"><X className="w-3 h-3" /></button>
                    </span>
                  )
                })}
              </div>
            )}
            {/* 🔴 La liste plafonnée + la recherche NAVIGATEUR ont disparu (audit
                2026-07-29) : `/media/` était appelé sans paramètre, donc au plafond serveur
                de 500, et le champ filtrait cette liste DÉJÀ TRONQUÉE — au-delà, un contenu
                existait sans être trouvable. Même tiroir partagé que les événements, les
                playlists et les paniers audio : une seule façon de choisir un contenu. */}
            <Button size="sm" variant="secondary" className="w-full"
                    data-testid="vod-content-select"
                    onClick={() => setContentPickerOpen(true)}>
              <Plus className="w-4 h-4 mr-1.5" />{t('vod.medias_label')}
            </Button>
            </>}
          </div>

          {mutateError && <p className="text-sm text-danger">{mutateError}</p>}
          <div className="flex gap-2">
            <Button data-write-action onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !canSave}>
              {saveMutation.isPending ? t('common.saving') : t('common.save')}
            </Button>
            <Button variant="secondary" onClick={closeDrawer}>{t('common.cancel')}</Button>
          </div>

          {/* Diffuser maintenant (trigger cloud) — config enregistrée uniquement.
              Déclencher = vod:trigger côté serveur, distinct de l'édition de la config. */}
          {editedConfig && editedConfig.medias.length > 0 && (
            <div className="border-t border-gray-100 pt-4 space-y-2" data-write-perm="vod:trigger">
              <label className="text-sm font-medium text-gray-700">{t('vod.broadcast_label')}</label>
              <p className="text-xs text-gray-400">{t('vod.broadcast_target_hint')}</p>
              {/* Cibles : players de la config (par défaut tous). On diffuse sur les cochés. */}
              <div className="flex flex-wrap gap-1.5">
                {editedConfig.players.map((p) => {
                  const on = playTargets.includes(p.id_player)
                  return (
                    <button key={p.id_player} type="button"
                      onClick={() => setPlayTargets((prev) => on ? prev.filter((x) => x !== p.id_player) : [...prev, p.id_player])}
                      className={`inline-flex items-center gap-1.5 text-xs rounded-full px-2.5 py-1 border transition-sf ${on ? 'bg-accent/10 text-accent border-accent' : 'bg-surface text-gray-500 border-gray-200'}`}>
                      <span className={`w-2 h-2 rounded-full shrink-0 ${p.player_status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
                      {p.player_name ?? `#${p.id_player}`}
                    </button>
                  )
                })}
              </div>
              <div className="flex gap-2 text-xs">
                <button type="button" className="text-accent hover:underline" onClick={() => setPlayTargets(editedConfig.players.map((p) => p.id_player))}>{t('vod.target_all')}</button>
                <button type="button" className="text-gray-400 hover:underline" onClick={() => setPlayTargets([])}>{t('vod.target_none')}</button>
              </div>
              {/* Son du takeover — décidé ici, au moment du déclenchement : la programmation
                  peut être muette alors qu'on veut être entendu (ou l'inverse). Le player
                  ne baisse la musique de fond que si le média a réellement une piste audio. */}
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer pt-1">
                <input
                  type="checkbox" checked={playWithSound}
                  onChange={(e) => setPlayWithSound(e.target.checked)}
                  className="rounded border-gray-300 text-accent focus:ring-accent/40"
                />
                {playWithSound
                  ? <Volume2 className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                  : <VolumeX className="w-3.5 h-3.5 text-gray-400 shrink-0" />}
                <span>{t('vod.play_with_sound')}</span>
              </label>
              <p className="text-xs text-gray-400">{t('vod.play_sound_hint')}</p>
              <div className="space-y-1.5 pt-1">
                {editedConfig.medias.map((m) => {
                  const Icon = mediaIcon(m.media_type)
                  // Entrée HDMI : pas de once/loop — un SWITCH de source (ON jusqu'au OFF,
                  // reprise de la playlist au wall-clock ; auto-OFF à la coupure écran du site).
                  if (m.media_type === 'hdmi_input') {
                    return (
                      <div key={m.id_media} className="flex items-center gap-2 bg-gray-50 rounded px-2 py-1.5">
                        <Icon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                        <span className="text-sm text-gray-700 truncate flex-1">{m.media_name ?? `#${m.id_media}`}</span>
                        <Button data-write-action size="sm" variant="secondary" disabled={playMutation.isPending || playTargets.length === 0}
                          onClick={() => playMutation.mutate({ id_media: m.id_media, mode: 'start' })}>
                          <MonitorPlay className="w-3.5 h-3.5 mr-1" />{t('vod.switch_on')}
                        </Button>
                        <Button data-write-action size="sm" variant="secondary" disabled={playMutation.isPending || playTargets.length === 0}
                          onClick={() => playMutation.mutate({ id_media: m.id_media, mode: 'stop' })}>
                          <Square className="w-3.5 h-3.5 mr-1" />{t('vod.switch_off')}
                        </Button>
                      </div>
                    )
                  }
                  return (
                    <div key={m.id_media} className="flex items-center gap-2 bg-gray-50 rounded px-2 py-1.5">
                      <Icon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                      <span className="text-sm text-gray-700 truncate flex-1">{m.media_name ?? `#${m.id_media}`}</span>
                      <Button data-write-action size="sm" variant="secondary" disabled={playMutation.isPending || playTargets.length === 0}
                        onClick={() => playMutation.mutate({ id_media: m.id_media, mode: 'once' })}>
                        <Play className="w-3.5 h-3.5 mr-1" />{t('vod.play_once')}
                      </Button>
                      <Button data-write-action size="sm" variant="secondary" disabled={playMutation.isPending || playTargets.length === 0}
                        onClick={() => playMutation.mutate({ id_media: m.id_media, mode: 'loop' })}>
                        <Repeat className="w-3.5 h-3.5 mr-1" />{t('vod.play_loop')}
                      </Button>
                    </div>
                  )
                })}
              </div>
              <Button data-write-action size="sm" variant="secondary" disabled={playMutation.isPending || playTargets.length === 0}
                onClick={() => playMutation.mutate({ id_media: editedConfig.medias[0].id_media, mode: 'stop' })}>
                <Square className="w-3.5 h-3.5 mr-1" />{t('vod.stop')}
              </Button>
              {playFeedback && <p className="text-xs text-accent">{playFeedback}</p>}
            </div>
          )}
        </div>
      </Drawer>

      {/* Briques partagées, montées AU NIVEAU PAGE (jamais dans un Drawer : son panneau
          porte un `transform`, qui devient le bloc conteneur de tout `fixed` descendant). */}
      <ContentPickerDrawer
        open={contentPickerOpen}
        onClose={() => setContentPickerOpen(false)}
        mediaTypes={['video', 'image', 'document', 'hdmi_input']}
        alreadySelected={new Set(pickedMedia)}
        onPick={(pick) => {
          setPickedMedia((prev) => [...prev, ...pick.medias.filter((id) => !prev.includes(id))])
        }}
      />

      <TargetMapDrawer
        open={mapOpen}
        onClose={() => setMapOpen(false)}
        mode="player"
        // ⚠️ La contrainte de la VOD est PRÉSERVÉE : tous les écrans d'un même site.
        // `id_site` est la clé du domaine de confiance du déclenchement LAN et la portée du
        // panneau magasin — harmoniser la présentation ne doit pas relâcher la sémantique.
        constraint="single-site"
        sites={allSites.map((s) => ({
          id_site: s.id_site, site_name: s.site_name,
          latitude: s.latitude ?? null, longitude: s.longitude ?? null,
          screen_count: allPlayers.filter((p) => p.id_site === s.id_site).length,
        }))}
        players={allPlayers.map((p) => ({
          id_player: p.id_player, player_name: p.player_name, id_site: p.id_site ?? null,
        }))}
        value={pickedPlayers}
        onApply={(ids) => setPickedPlayers(ids)}
      />
    </>
  )
}
