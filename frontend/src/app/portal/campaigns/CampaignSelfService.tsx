'use client'

// S7 C2 — self-service annonceur : création/édition d'un BROUILLON de campagne
// (sites sur la carte, SOV ou Exclusif, devis + dispo agrégée), upload des
// créatifs (quotas 20/512 MiB, nés « en attente »), soumission au retailer (§21).

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Clapperboard, Send, Trash2, Upload } from 'lucide-react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import StatusBadge from '@/components/ui/StatusBadge'
import NumberField from '@/components/ui/NumberField'
import SiteMapSelector, { type MapSite } from '@/components/maps/SiteMapSelector'
import api from '@/lib/api'
import { fireDemoToast } from '@/lib/demo'
import { useAuthStore } from '@/store/auth'

interface PortalCreative {
  id_creative: number; id_media: number; media_name: string; media_type: string
  duration_ms: number | null; approval_status: string
}
interface PortalCampaign {
  id_campaign: number; campaign_name: string; status: string
  starts_on: string; ends_on: string; sov_percent: number
  campaign_kind?: string; spots_per_hour?: number | null
  targets: { target_type: string; target_id: number | null }[]
  approval_request?: { id_request: number; status: string } | null
}
interface OccupancyResult {
  availability: 'ok' | 'tight' | 'full'
  price: { estimated_price: number; priced_players: number; unpriced_players: number; days: number } | null
  // SOV max réalisable (visuel) / spots/h max réalisables (audio) — agrégats strippés
  achievable_sov_pct: number | null
  achievable_spots_per_hour: number | null
}
interface RequestComment {
  id_comment: number; comment_text: string; action: string | null
  created_at: string; user_name?: string | null
}
interface SiteList { id_list: number; list_name: string; site_ids: number[] }

export default function CampaignSelfService({ id }: { id?: number }) {
  const t = useTranslations('portal')
  const tc = useTranslations('campaigns')
  const tg = useTranslations('common')
  const router = useRouter()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  // Compte démo : toast client sur toute action (l'intercepteur avale la promesse
  // sinon → spinner infini, leçon Telegram S7)
  const isDemo = !!useAuthStore((s) => s.user)?.is_demo

  const [name, setName] = useState('')
  const [startsOn, setStartsOn] = useState('')
  const [endsOn, setEndsOn] = useState('')
  const [sov, setSov] = useState(10)
  const [exclusive, setExclusive] = useState(false)
  // S3 audio : type de campagne + cadence en spots/heure (miroir du CMS)
  const [kind, setKind] = useState<'visual' | 'audio'>('visual')
  const [spotsPerHour, setSpotsPerHour] = useState(6)
  const isAudio = kind === 'audio'
  const [selected, setSelected] = useState<Set<number>>(new Set())
  // Sélection PAR ÉCRAN (0089, si le réglage org l'autorise) : sites PARTIELS —
  // {id_site: [id_player…]}. Un site est soit entier (selected), soit partiel (ici).
  const [pickedPlayers, setPickedPlayers] = useState<Record<number, number[]>>({})
  const [expandedSite, setExpandedSite] = useState<number | null>(null)
  const [createdId, setCreatedId] = useState<number | null>(id ?? null)
  const [err, setErr] = useState('')
  const campaignId = createdId

  // Édition : charge le brouillon existant (liste scopée B1 → le sien seulement)
  const { data: existing } = useQuery<PortalCampaign[]>({
    queryKey: ['portal-campaigns'],
    queryFn: () => api.get<PortalCampaign[]>('/campaigns/').then((r) => r.data),
    enabled: id != null,
  })
  // `kind` filtre les players/écrans par capacité côté serveur (retour Ed 21/07).
  const { data: sites = [] } = useQuery<MapSite[]>({
    queryKey: ['portal-sites', kind],
    queryFn: () => api.get<MapSite[]>(`/portal/sites?kind=${kind}`).then((r) => r.data),
  })

  const current = id != null ? existing?.find((c) => c.id_campaign === id) : undefined
  const loadedRef = useRef(false)
  useEffect(() => {
    if (!current || loadedRef.current) return
    // Les cibles PLAYER se regroupent par site via /portal/sites → attendre les sites
    const hasPlayerTargets = current.targets.some(
      (tg) => tg.target_type === 'player' && tg.target_id != null)
    if (hasPlayerTargets && sites.length === 0) return
    loadedRef.current = true
    setName(current.campaign_name)
    setStartsOn(current.starts_on)
    setEndsOn(current.ends_on)
    setKind(current.campaign_kind === 'audio' ? 'audio' : 'visual')
    if (current.spots_per_hour) setSpotsPerHour(current.spots_per_hour)
    setExclusive(Number(current.sov_percent) >= 100)
    setSov(Number(current.sov_percent) >= 100 ? 10 : Number(current.sov_percent))
    setSelected(new Set(current.targets
      .filter((tg) => tg.target_type === 'site' && tg.target_id != null)
      .map((tg) => tg.target_id as number)))
    if (hasPlayerTargets) {
      const byQuery: Record<number, number[]> = {}
      for (const tg of current.targets) {
        if (tg.target_type !== 'player' || tg.target_id == null) continue
        const site = sites.find((s) => (s.players ?? []).some(
          (p) => p.id_player === tg.target_id))
        if (site) byQuery[site.id_site] = [...(byQuery[site.id_site] ?? []), tg.target_id]
      }
      setPickedPlayers(byQuery)
    }
  }, [current, sites])

  // Dispo agrégée + devis (déclenché quand le formulaire est complet, débouncé)
  const [check, setCheck] = useState<OccupancyResult | null>(null)
  const effSov = exclusive ? 100 : sov
  const playerIds = Object.values(pickedPlayers).flat()
  const pickedKey = JSON.stringify(pickedPlayers)
  useEffect(() => {
    setCheck(null)
    if (!startsOn || !endsOn || endsOn < startsOn) return
    if (selected.size === 0 && playerIds.length === 0) return
    const timer = setTimeout(() => {
      api.post<OccupancyResult>('/portal/occupancy-check', {
        starts_on: startsOn, ends_on: endsOn, sov_percent: effSov,
        site_ids: Array.from(selected), player_ids: playerIds,
        exclude_id_campaign: campaignId,
        campaign_kind: kind,
        spots_per_hour: isAudio ? spotsPerHour : undefined,
      }).then((r) => setCheck(r.data)).catch(() => setCheck(null))
    }, 400)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startsOn, endsOn, effSov, selected, pickedKey, campaignId, kind, spotsPerHour])

  const onApiError = (e: unknown) => setErr(
    (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('error'))

  const save = useMutation({
    mutationFn: () => {
      const body = {
        campaign_name: name, starts_on: startsOn, ends_on: endsOn,
        exclusive, sov_percent: sov,  // ignoré si exclusive (backend force 100)
        site_ids: Array.from(selected),
        player_ids: playerIds,
        campaign_kind: kind,
        spots_per_hour: isAudio ? spotsPerHour : undefined,
      }
      return campaignId
        ? api.put<PortalCampaign>(`/portal/campaigns/${campaignId}`, body)
        : api.post<PortalCampaign>('/portal/campaigns', body)
    },
    onSuccess: ({ data }) => {
      setCreatedId(data.id_campaign)
      setErr('')
      qc.invalidateQueries({ queryKey: ['portal-campaigns'] })
    },
    onError: onApiError,
  })

  // Listes de sites enregistrées (Ed #11) : rappel de sélection + upsert par nom
  const { data: siteLists = [] } = useQuery<SiteList[]>({
    queryKey: ['portal-site-lists'],
    queryFn: () => api.get<SiteList[]>('/portal/site-lists').then((r) => r.data),
  })
  const [listChoice, setListChoice] = useState('')
  const [saveListOpen, setSaveListOpen] = useState(false)
  const [listName, setListName] = useState('')
  const saveList = useMutation({
    mutationFn: () => api.post('/portal/site-lists', {
      list_name: listName.trim(), site_ids: Array.from(selected),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portal-site-lists'] })
      setSaveListOpen(false)
      setListName('')
      setErr('')
    },
    onError: onApiError,
  })
  const deleteList = useMutation({
    mutationFn: (idList: number) => api.delete(`/portal/site-lists/${idList}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portal-site-lists'] })
      setListChoice('')
    },
    onError: onApiError,
  })

  // Quotas/réglages de l'org (configurables /campaigns/settings)
  const { data: limits } = useQuery<{
    max_creatives: number; creative_max_mb: number
    creative_max_duration_s: number | null; player_selection: boolean
    allowed_kinds: string[]
  }>({
    queryKey: ['portal-limits'],
    queryFn: () => api.get<{
      max_creatives: number; creative_max_mb: number
      creative_max_duration_s: number | null; player_selection: boolean
      allowed_kinds: string[]
    }>('/portal/limits').then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  })
  const maxCreatives = limits?.max_creatives ?? 20
  const maxMb = limits?.creative_max_mb ?? 1024
  const playerSelection = limits?.player_selection ?? false
  const allowedKinds = limits?.allowed_kinds ?? ['visual']
  // Création : cale le type par défaut sur le 1er type autorisé (ex. annonceur audio-only)
  const kindInit = useRef(false)
  useEffect(() => {
    if (id != null || kindInit.current || !limits) return
    kindInit.current = true
    if (!allowedKinds.includes(kind)) setKind(allowedKinds[0] as 'visual' | 'audio')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limits, id])

  // Créatifs (une fois le brouillon créé)
  const { data: creatives = [] } = useQuery<PortalCreative[]>({
    queryKey: ['portal-creatives', campaignId],
    queryFn: () => api.get<PortalCreative[]>(
      `/portal/campaigns/${campaignId}/creatives`).then((r) => r.data),
    enabled: campaignId != null,
  })
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return api.post(`/portal/campaigns/${campaignId}/creatives`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portal-creatives', campaignId] })
      setErr('')
    },
    onError: onApiError,
  })
  const removeCreative = useMutation({
    mutationFn: (idCreative: number) =>
      api.delete(`/portal/campaigns/${campaignId}/creatives/${idCreative}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portal-creatives', campaignId] }),
    onError: onApiError,
  })

  const submit = useMutation({
    mutationFn: () => api.post(`/portal/campaigns/${campaignId}/submit`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portal-campaigns'] })
      router.push('/portal')
    },
    onError: onApiError,
  })
  const resubmit = useMutation({
    mutationFn: (idRequest: number) => api.post(`/approvals/${idRequest}/resubmit`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portal-campaigns'] })
      router.push('/portal')
    },
    onError: onApiError,
  })

  // « Modifications demandées » : la timeline de la demande (le retailer y a mis le motif)
  const reqInfo = current?.approval_request
  const { data: reqDetail } = useQuery<{ comments: RequestComment[] }>({
    queryKey: ['portal-request', reqInfo?.id_request],
    queryFn: () => api.get<{ comments: RequestComment[] }>(
      `/approvals/${reqInfo!.id_request}`).then((r) => r.data),
    enabled: reqInfo != null,
  })

  const canSave = name.trim() && startsOn && endsOn
    && (selected.size > 0 || playerIds.length > 0)

  // Site ENTIER (chip/carte) ⟷ site PARTIEL (écrans cochés) : exclusifs par site
  const toggleSite = (sid: number) => {
    if (inReview) return
    setPickedPlayers((prev) => {
      if (!(sid in prev)) return prev
      const next = { ...prev }
      delete next[sid]
      return next
    })
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(sid)) next.delete(sid)
      else next.add(sid)
      return next
    })
  }
  const togglePlayer = (sid: number, pid: number) => {
    if (inReview) return
    setSelected((prev) => {
      if (!prev.has(sid)) return prev
      const next = new Set(prev)
      next.delete(sid)  // passer en partiel retire le site entier
      return next
    })
    setPickedPlayers((prev) => {
      const cur = new Set(prev[sid] ?? [])
      if (cur.has(pid)) cur.delete(pid)
      else cur.add(pid)
      const next = { ...prev }
      if (cur.size) next[sid] = [...cur]
      else delete next[sid]
      return next
    })
  }
  const inReview = reqInfo?.status === 'pending_review'
  const changesRequested = reqInfo?.status === 'changes_requested'
  const placedCount = sites.filter((s) => s.latitude != null).length

  return (
    <div className="w-full space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">
            {id ? t('edit_campaign') : t('new_campaign')}
          </h1>
          <p className="text-sm text-gray-400">{t('new_campaign_hint')}</p>
        </div>
        {reqInfo && (
          <StatusBadge
            status={reqInfo.status === 'changes_requested' ? 'warning' : 'pending'}
            label={t(reqInfo.status === 'changes_requested' ? 'st_changes_requested' : 'st_in_review')} />
        )}
      </div>

      {/* Motif du retailer quand des modifications sont demandées */}
      {changesRequested && (reqDetail?.comments ?? []).length > 0 && (
        <div className="bg-amber-500/10 border border-amber-400/20 rounded-lg px-3 py-2.5 text-sm text-gray-800">
          <p className="text-xs font-medium text-warning mb-1">{t('reviewer_feedback')}</p>
          {(reqDetail?.comments ?? [])
            .filter((c) => c.action === 'changes_requested' || c.action === 'rejected' || !c.action)
            .slice(-3).map((c) => (
              <p key={c.id_comment} className="whitespace-pre-wrap">
                <span className="text-gray-500">{c.user_name || '—'} :</span> {c.comment_text}
              </p>
            ))}
        </div>
      )}

      {/* 2 colonnes (dès xl) : paramètres à gauche, sélection des sites à droite —
          le formulaire occupe la largeur au lieu d'une colonne étroite centrée. */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 items-start">
      {/* ── Colonne gauche : paramètres ─────────────────────────────────────── */}
      <div className="bg-surface border border-gray-200 rounded-xl shadow-sf-card p-4 space-y-4">
        <Input label={t('campaign_name')} value={name}
               onChange={(e) => setName(e.target.value)} disabled={inReview} autoFocus={!id} />
        {/* Type de campagne — seulement si l'annonceur a les 2 droits ; verrouillé en
            édition (le type est immuable après création). */}
        {allowedKinds.length > 1 && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('kind_label')}</label>
            <div className="flex gap-1.5">
              {(['visual', 'audio'] as const).filter((k) => allowedKinds.includes(k)).map((k) => {
                const locked = id != null || inReview
                return (
                  <button key={k} type="button" disabled={locked}
                          onClick={() => setKind(k)}
                          className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-sf ${
                            kind === k ? 'bg-accent text-white border-accent'
                              : 'bg-surface text-gray-600 border-gray-200 hover:bg-canvas'
                          } ${locked ? 'opacity-60 cursor-not-allowed' : ''}`}>
                    {t(k === 'audio' ? 'kind_audio' : 'kind_visual')}
                  </button>
                )
              })}
            </div>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Input label={t('starts_on')} type="date" value={startsOn} disabled={inReview}
                 onChange={(e) => setStartsOn(e.target.value)} />
          <Input label={t('ends_on')} type="date" value={endsOn} disabled={inReview}
                 onChange={(e) => setEndsOn(e.target.value)} />
        </div>
        {isAudio ? (
          <div className="grid grid-cols-2 gap-3">
            <NumberField label={t('spots_per_hour_label')} min={1} max={60}
                   value={spotsPerHour ?? 1} disabled={inReview}
                   onCommit={(v) => setSpotsPerHour(v ?? 1)} />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 items-end">
              <NumberField label={t('sov_label')} min={1} max={99}
                     value={sov ?? 1} disabled={exclusive || inReview}
                     onCommit={(v) => setSov(v ?? 1)} />
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer pb-2.5">
                <input type="checkbox" checked={exclusive} disabled={inReview}
                       onChange={(e) => setExclusive(e.target.checked)} />
                {t('exclusive_label')}
              </label>
            </div>
            {exclusive && <p className="text-xs text-gray-400 -mt-2">{t('exclusive_hint')}</p>}
          </>
        )}
      </div>

      {/* ── Colonne droite : sélection des sites (carte + chips) ─────────────── */}
      <div className="bg-surface border border-gray-200 rounded-xl shadow-sf-card p-4 space-y-3">
        {/* Sites : carte + liste (les sites sans coordonnées restent cochables) */}
        <div>
          <div className="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
            <p className="text-sm font-medium text-gray-700">{t('choose_sites')}</p>
            {/* Listes de sites enregistrées (Ed #11) */}
            <div className="flex items-center gap-1.5">
              {siteLists.length > 0 && (
                <>
                  <select
                    value={listChoice}
                    onChange={(e) => {
                      const v = e.target.value
                      setListChoice(v)
                      const l = siteLists.find((x) => String(x.id_list) === v)
                      // Une liste enregistrée peut contenir un site devenu exclu (#10)
                      if (l && !inReview) {
                        const ids = l.site_ids.filter(
                          (sid) => !sites.find((s) => s.id_site === sid)?.excluded)
                        setSelected(new Set(ids))
                        // liste = sites ENTIERS → purge les sélections partielles
                        setPickedPlayers((prev) => {
                          const next = { ...prev }
                          ids.forEach((sid) => delete next[sid])
                          return next
                        })
                      }
                    }}
                    className="text-xs border border-gray-200 rounded-lg px-2 py-1 bg-surface text-gray-600 focus:outline-none focus:ring-2 focus:ring-accent/40"
                  >
                    <option value="">{t('site_lists_pick')}</option>
                    {siteLists.map((l) => (
                      <option key={l.id_list} value={l.id_list}>
                        {l.list_name} ({l.site_ids.length})
                      </option>
                    ))}
                  </select>
                  {listChoice && !inReview && (
                    <button type="button"
                            onClick={() => (isDemo ? fireDemoToast() : deleteList.mutate(Number(listChoice)))}
                            className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf"
                            title={tg('delete')}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </>
              )}
              {selected.size > 0 && !inReview && (saveListOpen ? (
                <span className="flex items-center gap-1.5">
                  <input value={listName} onChange={(e) => setListName(e.target.value)}
                         placeholder={t('site_lists_name')} autoFocus
                         className="text-xs border border-gray-200 rounded-lg px-2 py-1 w-36 bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40" />
                  <Button size="sm" variant="secondary" disabled={!listName.trim()}
                          loading={saveList.isPending}
                          onClick={() => (isDemo ? fireDemoToast() : saveList.mutate())}>
                    {tg('save')}
                  </Button>
                </span>
              ) : (
                <button type="button" onClick={() => setSaveListOpen(true)}
                        className="text-xs text-accent hover:underline">
                  {t('site_lists_save')}
                </button>
              ))}
            </div>
          </div>
          {placedCount > 0 && (
            <SiteMapSelector sites={sites} selected={selected} heightClass="h-[420px]"
                             searchable searchPlaceholder={tc('target_map_search')}
                             onFocusSite={(idSite) => { if (playerSelection) setExpandedSite(idSite) }}
                             onToggle={toggleSite} />
          )}
          <div className="flex items-center gap-1.5 flex-wrap mt-2">
            {sites.map((s) => {
              /* Exclusion concurrentielle #10 : site fermé à cet annonceur = grisé.
                 Sélection par écran (0089) : chevron = déplier les écrans du site. */
              const partial = (pickedPlayers[s.id_site] ?? []).length
              const expandable = playerSelection && !s.excluded && (s.players ?? []).length > 0
              return (
                <span key={s.id_site} className="inline-flex items-center">
                  <button type="button" disabled={inReview || s.excluded}
                          onClick={() => toggleSite(s.id_site)}
                          title={s.excluded
                            ? t('site_excluded')
                            : t('site_screens', { n: s.screen_count ?? 0 })}
                          className={`px-2.5 py-1 text-xs border transition-sf ${
                            expandable ? 'rounded-l-full' : 'rounded-full'
                          } ${
                            s.excluded
                              ? 'bg-gray-50 text-gray-300 border-gray-100 line-through cursor-not-allowed'
                              : selected.has(s.id_site)
                                ? 'bg-accent text-white border-accent'
                                : partial > 0
                                  ? 'bg-accent/10 text-accent border-accent/40'
                                  : 'bg-surface text-gray-600 border-gray-200 hover:bg-canvas'
                          }`}>
                    {s.site_name}
                    {!s.excluded && (partial > 0
                      ? <span className="opacity-80"> · {partial}/{s.players?.length ?? 0}</span>
                      : s.screen_count != null && <span className="opacity-70"> · {s.screen_count}</span>)}
                  </button>
                  {expandable && (
                    <button type="button" disabled={inReview}
                            onClick={() => setExpandedSite(
                              expandedSite === s.id_site ? null : s.id_site)}
                            title={t('pick_screens')}
                            className={`px-1.5 py-1 text-xs border border-l-0 rounded-r-full transition-sf ${
                              expandedSite === s.id_site
                                ? 'bg-canvas text-gray-700 border-gray-200'
                                : 'bg-surface text-gray-400 border-gray-200 hover:bg-canvas'
                            }`}>
                      ▾
                    </button>
                  )}
                </span>
              )
            })}
          </div>
          {/* Écrans du site déplié : cocher des écrans précis = site PARTIEL
              (le devis par écran suit — un écran premium coûte plus cher) */}
          {expandedSite != null && (() => {
            const s = sites.find((x) => x.id_site === expandedSite)
            if (!s || !(s.players ?? []).length) return null
            const picked = new Set(pickedPlayers[s.id_site] ?? [])
            return (
              <div className="mt-2 bg-canvas border border-gray-100 rounded-lg px-3 py-2.5">
                <p className="text-xs font-medium text-gray-500 mb-1.5">
                  {t('pick_screens_in', { site: s.site_name })}
                </p>
                <div className="flex items-center gap-x-4 gap-y-1.5 flex-wrap">
                  <label className="flex items-center gap-1.5 text-xs text-gray-700 cursor-pointer">
                    <input type="checkbox" checked={selected.has(s.id_site)}
                           disabled={inReview}
                           onChange={() => toggleSite(s.id_site)} />
                    {t('whole_site')}
                  </label>
                  {(s.players ?? []).map((p) => (
                    <label key={p.id_player}
                           className="flex items-center gap-1.5 text-xs text-gray-700 cursor-pointer">
                      <input type="checkbox"
                             checked={selected.has(s.id_site) || picked.has(p.id_player)}
                             disabled={inReview || selected.has(s.id_site)}
                             onChange={() => togglePlayer(s.id_site, p.id_player)} />
                      {p.player_name}
                    </label>
                  ))}
                </div>
              </div>
            )
          })()}
        </div>
      </div>
      </div>

      {/* ── Dispo + actions (pleine largeur sous les 2 colonnes) ─────────────── */}
      <div className="bg-surface border border-gray-200 rounded-xl shadow-sf-card p-4 space-y-4">
        {/* Dispo agrégée + devis (jamais le détail des concurrents) */}
        {check && (
          <div className={`rounded-lg px-3 py-2 text-sm border ${
            check.availability === 'full' ? 'bg-red-500/10 text-danger border-red-400/20'
              : check.availability === 'tight' ? 'bg-amber-500/10 text-warning border-amber-400/20'
                : 'bg-accent/10 text-accent border-accent/20'
          }`}>
            {t(`availability_${check.availability}`)}
            {check.price && (
              <span> · {t('quote', { price: check.price.estimated_price, days: check.price.days })}</span>
            )}
          </div>
        )}

        {/* SOV réalisable (anti-martèlement) : au-delà, la campagne serait sous-servie.
            Masqué en Exclusif (privatisation = intention différente, SOV forcée 100) */}
        {check && !exclusive && check.achievable_sov_pct != null
          && sov > check.achievable_sov_pct && (() => {
          const suggested = check.achievable_sov_pct >= 2
            ? Math.floor(check.achievable_sov_pct) : check.achievable_sov_pct
          return (
            <div className="rounded-lg px-3 py-2 text-sm border bg-amber-500/10 text-warning border-amber-400/20">
              {t('sov_achievable_warning', { sov, max: check.achievable_sov_pct })}
              {suggested > 0 && (
                <button type="button" onClick={() => setSov(suggested)}
                        className="ml-2 text-xs font-medium underline hover:no-underline">
                  {t('sov_achievable_use', { pct: suggested })}
                </button>
              )}
            </div>
          )
        })()}

        {/* Spots/h réalisables (audio) : au-delà du plafond restant du pire écran, la
            campagne serait sous-servie — équivalent audio du « SOV réalisable ». */}
        {check && isAudio && check.achievable_spots_per_hour != null
          && spotsPerHour > check.achievable_spots_per_hour && (
          <div className="rounded-lg px-3 py-2 text-sm border bg-amber-500/10 text-warning border-amber-400/20">
            {t('spots_achievable_warning', { spots: spotsPerHour, max: check.achievable_spots_per_hour })}
            {check.achievable_spots_per_hour > 0 && (
              <button type="button" onClick={() => setSpotsPerHour(check.achievable_spots_per_hour!)}
                      className="ml-2 text-xs font-medium underline hover:no-underline">
                {t('spots_achievable_use', { n: check.achievable_spots_per_hour })}
              </button>
            )}
          </div>
        )}

        {err && <p className="text-xs text-danger">{err}</p>}
        {/* Annuler/Retour toujours disponible (retour Ed : impossible d'annuler
            la création) — le brouillon éventuel reste modifiable depuis l'accueil */}
        <div className="flex items-center gap-2">
          {!inReview && (
            <Button onClick={() => (isDemo ? fireDemoToast() : save.mutate())}
                    disabled={!canSave} loading={save.isPending}>
              {campaignId ? t('save_draft') : t('create_draft')}
            </Button>
          )}
          <Button variant="secondary" onClick={() => router.push('/portal')}>
            {tg(campaignId ? 'back' : 'cancel')}
          </Button>
        </div>
      </div>

      {/* Créatifs — visibles dès que le brouillon existe */}
      {campaignId != null && (
        <div className="bg-surface border border-gray-200 rounded-xl shadow-sf-card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
              <Clapperboard className="w-4 h-4 text-gray-400" />{t('creatives_title')}
              <span className="px-2 py-0.5 rounded-full bg-accent/10 text-accent text-xs font-medium">
                {creatives.length}/{maxCreatives}
              </span>
            </p>
            {!inReview && (
              <>
                <input ref={fileRef} type="file" className="hidden"
                       accept={isAudio
                         ? 'audio/mpeg,audio/mp3,audio/ogg,audio/wav,audio/aac,audio/mp4,audio/x-m4a'
                         : 'image/jpeg,image/png,image/gif,image/webp,video/mp4,video/quicktime,video/webm'}
                       onChange={(e) => {
                         const f = e.target.files?.[0]
                         if (f) upload.mutate(f)
                         e.target.value = ''
                       }} />
                <Button size="sm" variant="secondary" loading={upload.isPending}
                        onClick={() => (isDemo ? fireDemoToast() : fileRef.current?.click())}>
                  <Upload className="w-3.5 h-3.5 mr-1" />{t('upload_creative')}
                </Button>
              </>
            )}
          </div>
          <p className="text-xs text-gray-400">
            {t('upload_hint', { size: maxMb, count: maxCreatives })}
            {limits?.creative_max_duration_s != null && (
              <> {t('upload_duration_hint', { s: limits.creative_max_duration_s })}</>
            )}
          </p>
          {creatives.map((cr) => (
            <div key={cr.id_creative}
                 className="flex items-center justify-between gap-2 px-3 py-2 bg-canvas rounded-lg text-sm">
              <span className="truncate text-gray-800">
                {cr.media_name}
                {cr.duration_ms != null && (
                  <span className="text-gray-400 ml-1">· {Math.round(cr.duration_ms / 1000)}s</span>
                )}
              </span>
              <div className="flex items-center gap-1.5 shrink-0">
                {cr.approval_status !== 'approved' && (
                  <StatusBadge status={cr.approval_status === 'pending' ? 'pending' : 'offline'}
                               label={tc(cr.approval_status === 'pending'
                                 ? 'creative_pending' : 'creative_rejected')} />
                )}
                {!inReview && (
                  <button onClick={() => (isDemo ? fireDemoToast() : removeCreative.mutate(cr.id_creative))}
                          className="p-1 rounded text-gray-400 hover:text-danger hover:bg-red-500/10 transition-sf">
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
          ))}

          {/* Soumission / resoumission */}
          {!inReview && (
            <div className="pt-2 border-t border-gray-100">
              {changesRequested && reqInfo ? (
                <Button onClick={() => (isDemo ? fireDemoToast() : resubmit.mutate(reqInfo.id_request))}
                        disabled={creatives.length === 0} loading={resubmit.isPending}>
                  <Send className="w-3.5 h-3.5 mr-1" />{t('resubmit')}
                </Button>
              ) : (
                <Button onClick={() => (isDemo ? fireDemoToast() : submit.mutate())}
                        disabled={creatives.length === 0} loading={submit.isPending}>
                  <CheckCircle2 className="w-3.5 h-3.5 mr-1" />{t('submit_for_review')}
                </Button>
              )}
              <p className="text-xs text-gray-400 mt-1.5">{t('submit_hint')}</p>
            </div>
          )}
          {inReview && <p className="text-xs text-gray-500">{t('in_review_hint')}</p>}
        </div>
      )}
    </div>
  )
}
