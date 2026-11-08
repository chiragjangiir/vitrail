'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Plus, Trash2, Maximize, ChevronUp, ChevronDown, RotateCw,
  AlignStartVertical, AlignCenterVertical, AlignEndVertical,
  AlignStartHorizontal, AlignCenterHorizontal, AlignEndHorizontal,
} from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import api from '@/lib/api'
import type { TemplateRead } from '@/types/api'

type Zone = TemplateRead['layout']['zones'][number]
type LayoutType = 'full' | 'split_h' | 'split_v' | 'sidebar_r' | 'custom'

// L'aire d'édition borne l'aperçu (le canvas réel peut être 4K/portrait/LED) : on calcule des
// dimensions d'affichage qui PRÉSERVENT le ratio du canvas dans cette boîte.
const DISP_MAX_W = 960
const DISP_MAX_H = 540
const MIN_ZONE = 40               // taille minimale d'une zone (px canvas)
const SNAP_PX = 10                // pas de la grille d'aimantation (px canvas)

const DEFAULT_W = 1920
const DEFAULT_H = 1080

// Résolutions proposées. `custom` = saisie libre (LED / écrans non standard).
const RESOLUTION_PRESETS: { w: number; h: number; label: string }[] = [
  { w: 1920, h: 1080, label: 'FHD 1920×1080' },
  { w: 1080, h: 1920, label: 'FHD portrait 1080×1920' },
  { w: 3840, h: 2160, label: '4K 3840×2160' },
  { w: 2160, h: 3840, label: '4K portrait 2160×3840' },
  { w: 1280, h: 720, label: 'HD 1280×720' },
]

const clampVal = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v))

// Normalise une zone : arrondi (+ aimantation grille optionnelle) et bornage dans le canvas
// (taille ≥ MIN_ZONE, position telle que la zone reste entièrement visible). NaN → 0/MIN_ZONE.
function clampZone(z: Zone, snap: boolean, cw: number, ch: number): Zone {
  const q = (v: number) => {
    const n = Number.isFinite(v) ? v : 0
    return snap ? Math.round(n / SNAP_PX) * SNAP_PX : Math.round(n)
  }
  const w = clampVal(q(z.w), MIN_ZONE, cw)
  const h = clampVal(q(z.h), MIN_ZONE, ch)
  const x = clampVal(q(z.x), 0, cw - w)
  const y = clampVal(q(z.y), 0, ch - h)
  return { ...z, x, y, w, h }
}

// Presets de disposition exprimés en FRACTIONS du canvas → applicables à n'importe quelle
// résolution/orientation (16:9, portrait, 4K, LED…).
const PRESET_FRACTIONS: Record<Exclude<LayoutType, 'custom'>,
  { x: number; y: number; w: number; h: number; label: string }[]> = {
  full: [{ x: 0, y: 0, w: 1, h: 1, label: 'Main' }],
  split_h: [
    { x: 0, y: 0, w: 1, h: 0.5, label: 'Top' },
    { x: 0, y: 0.5, w: 1, h: 0.5, label: 'Bottom' },
  ],
  split_v: [
    { x: 0, y: 0, w: 0.5, h: 1, label: 'Left' },
    { x: 0.5, y: 0, w: 0.5, h: 1, label: 'Right' },
  ],
  sidebar_r: [
    { x: 0, y: 0, w: 0.75, h: 1, label: 'Main' },
    { x: 0.75, y: 0, w: 0.25, h: 1, label: 'Sidebar' },
  ],
}

function presetZones(type: Exclude<LayoutType, 'custom'>, cw: number, ch: number): Zone[] {
  return PRESET_FRACTIONS[type].map((f, i) => ({
    index: i, label: f.label,
    x: Math.round(f.x * cw), y: Math.round(f.y * ch),
    w: Math.round(f.w * cw), h: Math.round(f.h * ch),
  }))
}

/**
 * Dimensions d'affichage de l'aperçu : ratio du canvas conservé, borné à la
 * place réellement disponible.
 *
 * `maxW`/`maxH` valent par défaut DISP_MAX_W×DISP_MAX_H — c'est le cas des
 * VIGNETTES de preset, qui ne veulent qu'un ratio et se re-normalisent ensuite.
 * L'aperçu principal, lui, reçoit les dimensions MESURÉES de sa colonne
 * (ResizeObserver) pour occuper tout l'espace visible : l'ancien plafond en dur
 * à 960×540 gâchait la moitié d'un écran FHD et bien plus sur un ultrawide.
 */
function fitDisplay(
  cw: number,
  ch: number,
  maxW: number = DISP_MAX_W,
  maxH: number = DISP_MAX_H,
): { dispW: number; dispH: number } {
  const aspect = cw / ch
  let dispW = maxW
  let dispH = maxW / aspect
  if (dispH > maxH) { dispH = maxH; dispW = maxH * aspect }
  return { dispW: Math.round(dispW), dispH: Math.round(dispH) }
}

const ZONE_COLORS = [
  'border-accent bg-accent/15 text-accent',
  'border-emerald-500 bg-emerald-400/15 text-emerald-600 dark:text-emerald-300',
  'border-amber-500 bg-amber-400/15 text-amber-600 dark:text-amber-300',
  'border-fuchsia-500 bg-fuchsia-400/15 text-fuchsia-600 dark:text-fuchsia-300',
  'border-sky-500 bg-sky-400/15 text-sky-600 dark:text-sky-300',
  'border-rose-500 bg-rose-400/15 text-rose-600 dark:text-rose-300',
]
const zoneColor = (i: number) => ZONE_COLORS[i % ZONE_COLORS.length]

type DragState = {
  mode: 'move' | 'resize'
  idx: number
  sx: number
  sy: number
  ox: number
  oy: number
  ow: number
  oh: number
  snap: boolean
}

// Champ numérique d'une coordonnée/dimension de zone. Saisie LIBRE (brouillon local, on ne borne
// qu'à la validation blur/Entrée → on peut taper « 214 » sans être clampé à 80 à la 1re frappe).
// Flèches ↑/↓ (clavier OU boutons ▲▼) = pas de 1 ; MAINTENUE = pas de 10. Le stepping passe par
// onStep (lit l'état courant côté parent → robuste à l'auto-répétition).
function NumField({ label, value, onCommit, onStep }: {
  label: string
  value: number
  onCommit: (n: number) => void
  onStep: (delta: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  // value ne change qu'à une validation/step → resync ; pendant la frappe (value inchangé) le
  // brouillon est préservé. Pas de flag « editing » nécessaire.
  useEffect(() => { setDraft(String(value)) }, [value])
  const commit = () => {
    const n = Math.round(Number(draft))
    if (draft.trim() !== '' && Number.isFinite(n)) { if (n !== value) onCommit(n) }
    else setDraft(String(value))
  }
  // Filet anti-perte : une valeur saisie puis quittée SANS blur (fermeture du panneau,
  // changement de zone sélectionnée) doit partir quand même — même leçon que
  // `lib/useCommitField`, mais SANS son commit débouncé : ici le clamp n'a lieu qu'à la
  // validation, donc committer à chaque frappe ramènerait « 214 » à 80 dès le « 2 ».
  // Les flèches ▲▼, elles, passent par `onStep` et s'appliquent déjà immédiatement.
  const commitRef = useRef(commit)
  commitRef.current = commit
  useEffect(() => () => { commitRef.current() }, [])
  // Boutons ▲▼ : clic = ±1 ; maintien → après 400 ms, répétition ±10 toutes les 80 ms.
  const hold = useRef<{ t?: ReturnType<typeof setTimeout>; i?: ReturnType<typeof setInterval> }>({})
  const endHold = () => {
    if (hold.current.t) clearTimeout(hold.current.t)
    if (hold.current.i) clearInterval(hold.current.i)
    hold.current = {}
  }
  const startHold = (sign: number) => {
    onStep(sign)                                   // clic immédiat = pas de 1
    hold.current.t = setTimeout(() => {            // maintien → pas de 10
      hold.current.i = setInterval(() => onStep(sign * 10), 80)
    }, 400)
  }
  useEffect(() => endHold, [])   // nettoyage si démonté en plein maintien
  return (
    <label className="text-xs text-gray-500">
      {label}
      <div className="mt-1 flex">
        <input
          type="text"
          inputMode="numeric"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.currentTarget.blur() }
            else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
              e.preventDefault()
              onStep((e.key === 'ArrowUp' ? 1 : -1) * (e.repeat ? 10 : 1))
            }
          }}
          className="flex-1 w-full border border-gray-200 rounded-l px-2 py-1 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-accent/40"
        />
        <div className="flex flex-col border border-l-0 border-gray-200 rounded-r overflow-hidden">
          {([['up', 1, ChevronUp], ['down', -1, ChevronDown]] as const).map(([k, sign, Icon]) => (
            <button
              key={k}
              type="button"
              tabIndex={-1}
              onPointerDown={(e) => { e.preventDefault(); startHold(sign) }}
              onPointerUp={endHold}
              onPointerLeave={endHold}
              className="px-1 flex-1 flex items-center text-gray-400 hover:text-accent hover:bg-gray-50 transition-sf"
            >
              <Icon className="w-3 h-3" />
            </button>
          ))}
        </div>
      </div>
    </label>
  )
}

export default function TemplateEditPage() {
  const t = useTranslations()
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const qc = useQueryClient()

  const [name, setName] = useState('')
  const [layoutType, setLayoutType] = useState<LayoutType>('full')
  const [canvasW, setCanvasW] = useState(DEFAULT_W)
  const [canvasH, setCanvasH] = useState(DEFAULT_H)
  const [zones, setZones] = useState<Zone[]>(presetZones('full', DEFAULT_W, DEFAULT_H))
  // P3.6 — ou s'affiche un spot de campagne quand ce template a PLUSIEURS zones.
  const [campaignPlacement, setCampaignPlacement] = useState<'fullscreen' | 'zone'>('fullscreen')
  const [selected, setSelected] = useState(0)
  const [saved, setSaved] = useState(false)
  const [snap, setSnap] = useState(false)
  const drag = useRef<DragState | null>(null)

  // Place réellement disponible pour l'aperçu, mesurée en continu (redimensionnement
  // de fenêtre, repli du panneau outils…). Valeur initiale = ancien plafond fixe,
  // le temps que le ResizeObserver rende sa 1re mesure.
  const [avail, setAvail] = useState({ w: DISP_MAX_W, h: DISP_MAX_H })
  const roRef = useRef<ResizeObserver | null>(null)

  // ⚠️ CALLBACK REF, et non `useRef` + `useEffect([])` : ce composant fait un
  // `return` anticipé pendant le chargement. L'effet se serait exécuté alors que
  // la ref est encore nulle, serait sorti, et **ne se serait jamais rejoué** quand
  // le vrai canvas apparaît — l'observateur n'aurait jamais été branché et
  // l'aperçu serait resté figé sur la valeur de repli 960×540 (bug vu par Ed).
  // Une callback ref se déclenche au montage RÉEL du nœud.
  const canvasAreaRef = useCallback((el: HTMLDivElement | null) => {
    roRef.current?.disconnect()
    roRef.current = null
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect
      if (!r) return
      // Planchers : sur un viewport très court, mieux vaut un aperçu petit mais
      // utilisable qu'un aperçu de hauteur nulle.
      setAvail({ w: Math.max(320, r.width), h: Math.max(180, r.height) })
    })
    ro.observe(el)
    roRef.current = ro
  }, [])

  useEffect(() => () => roRef.current?.disconnect(), [])

  const { dispW, dispH } = fitDisplay(canvasW, canvasH, avail.w, avail.h)
  const scale = canvasW / dispW   // px canvas par px d'affichage

  // Refs « valeur courante » pour les handlers de drag (identité stable, useCallback([])).
  const scaleRef = useRef(scale)
  const cwRef = useRef(canvasW)
  const chRef = useRef(canvasH)
  useEffect(() => { scaleRef.current = scale; cwRef.current = canvasW; chRef.current = canvasH },
    [scale, canvasW, canvasH])

  const { data: tmpl, isLoading } = useQuery<TemplateRead>({
    queryKey: ['template', params.id],
    queryFn: () => api.get<TemplateRead>(`/templates/${params.id}`).then((r) => r.data),
  })

  // Gouvernance §XVIII : le serveur dit s'il est réellement modifiable. On ne le déduit
  // PAS de la permission — l'utilisateur peut détenir `templates:edit` et se voir refuser
  // CE template parce qu'il appartient à un nœud qu'il n'administre pas.
  const readOnly = tmpl?.governed_readonly === true

  useEffect(() => {
    if (tmpl) {
      setName(tmpl.template_name)
      setLayoutType((tmpl.layout.layout_type as LayoutType) ?? 'full')
      const cw = tmpl.layout.canvas_width || DEFAULT_W
      const ch = tmpl.layout.canvas_height || DEFAULT_H
      setCanvasW(cw)
      setCanvasH(ch)
      const z = tmpl.layout.zones
      setZones(z && z.length ? z : presetZones('full', cw, ch))
      setCampaignPlacement(tmpl.campaign_placement === 'zone' ? 'zone' : 'fullscreen')
    }
  }, [tmpl])

  const applyPreset = (type: Exclude<LayoutType, 'custom'>) => {
    setLayoutType(type)
    setZones(presetZones(type, canvasW, canvasH))
    setSelected(0)
  }

  // Changement de résolution : on RESCALE les zones proportionnellement (préserve la disposition
  // relative ; en cas de changement d'orientation, le clamp garde tout dans le canvas).
  const setResolution = (newW: number, newH: number) => {
    const w = clampVal(Math.round(newW), 16, 16384)
    const h = clampVal(Math.round(newH), 16, 16384)
    setZones((zs) => zs.map((z) => clampZone({
      ...z,
      x: z.x * w / canvasW, y: z.y * h / canvasH,
      w: z.w * w / canvasW, h: z.h * h / canvasH,
    }, false, w, h)))
    setCanvasW(w)
    setCanvasH(h)
  }

  // Modifie une zone (saisie numérique / alignement) avec bornage canvas. Snap=false : on
  // respecte la valeur saisie (pas d'aimantation sur la frappe ou un alignement exact).
  const updateZone = (i: number, patch: Partial<Zone>) => {
    setZones((zs) => zs.map((z, j) => (j === i ? clampZone({ ...z, ...patch }, false, canvasW, canvasH) : z)))
    setLayoutType('custom')
  }

  // Incrément relatif d'un champ (flèches du NumField). Lit l'état courant via l'updater
  // fonctionnel → robuste à l'auto-répétition (pas de valeur de rendu périmée).
  const stepZone = (i: number, f: 'x' | 'y' | 'w' | 'h', delta: number) => {
    setZones((zs) => zs.map((z, j) => (j === i ? clampZone({ ...z, [f]: z[f] + delta }, false, canvasW, canvasH) : z)))
    setLayoutType('custom')
  }

  // Déplacement / redimensionnement à la souris. useCallback([]) → identité STABLE des handlers.
  // Le scale et les dims du canvas sont lus via refs (l'écouteur ne lit pas l'état courant).
  const onPointerMove = useCallback((e: PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = (e.clientX - d.sx) * scaleRef.current
    const dy = (e.clientY - d.sy) * scaleRef.current
    setZones((prev) =>
      prev.map((z, i) => {
        if (i !== d.idx) return z
        if (d.mode === 'move') return clampZone({ ...z, x: d.ox + dx, y: d.oy + dy }, d.snap, cwRef.current, chRef.current)
        return clampZone({ ...z, w: d.ow + dx, h: d.oh + dy }, d.snap, cwRef.current, chRef.current)
      }),
    )
    setLayoutType('custom')
  }, [])

  const endDrag = useCallback(() => {
    drag.current = null
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', endDrag)
  }, [onPointerMove])

  const startDrag = (e: React.PointerEvent, idx: number, mode: 'move' | 'resize') => {
    e.preventDefault()
    e.stopPropagation()
    setSelected(idx)
    const z = zones[idx]
    drag.current = { mode, idx, sx: e.clientX, sy: e.clientY, ox: z.x, oy: z.y, ow: z.w, oh: z.h, snap }
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', endDrag)
  }

  useEffect(() => endDrag, [endDrag])   // nettoyage si on quitte en plein drag

  const addZone = () => {
    const nextIndex = zones.length ? Math.max(...zones.map((z) => z.index)) + 1 : 0
    const z = clampZone({
      index: nextIndex, x: canvasW * 0.125, y: canvasH * 0.167,
      w: canvasW / 3, h: canvasH / 3, label: `Zone ${nextIndex + 1}`,
    }, false, canvasW, canvasH)
    setZones([...zones, z])
    setLayoutType('custom')
    setSelected(zones.length)
  }

  const removeZone = (i: number) => {
    if (zones.length <= 1) return
    setZones(zones.filter((_, j) => j !== i))
    setLayoutType('custom')
    setSelected((s) => (s >= i && s > 0 ? s - 1 : s))
  }

  const setLabel = (i: number, label: string) =>
    setZones(zones.map((z, j) => (j === i ? { ...z, label } : z)))

  // Zone qui recevra les spots de campagne en mode « zone principale ». Le serveur choisit
  // l'INDEX 0 (`_inject_campaign_items_multizone`), pas la premiere zone de la liste : apres
  // des ajouts/suppressions les deux peuvent differer, et si plus AUCUNE zone ne porte
  // l'index 0, le spot n'est injecte NULLE PART — en silence. On le montre donc a l'ecran.
  const mainZone = zones.find((z) => z.index === 0)
  const highlightMain = campaignPlacement === 'zone' && zones.length > 1

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put(`/templates/${params.id}`, {
        template_name: name,
        layout: { layout_type: layoutType, canvas_width: canvasW, canvas_height: canvasH, zones },
        campaign_placement: campaignPlacement,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['templates'] })
      qc.invalidateQueries({ queryKey: ['template', params.id] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  const presetLabel = (type: string) =>
    ({
      full: t('templates.layout_full'),
      split_h: t('templates.layout_split_h'),
      split_v: t('templates.layout_split_v'),
      sidebar_r: t('templates.layout_sidebar_r'),
      custom: t('templates.layout_custom'),
    }[type] ?? type)

  const sel = zones[selected]
  // Vignette de preset : boîte au ratio du canvas (max 88×50), zones depuis les fractions.
  const thumb = fitDisplay(canvasW, canvasH)
  const thumbScale = Math.min(88 / thumb.dispW, 50 / thumb.dispH)
  const thumbW = Math.round(thumb.dispW * thumbScale)
  const thumbH = Math.round(thumb.dispH * thumbScale)

  if (isLoading) {
    return (
      <>
        <Topbar title="…" />
        <main className="flex-1 flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </main>
      </>
    )
  }

  return (
    <>
      <Topbar title={name || t('templates.title')}>
        {/* Nudge lecture-seule : modifier un template = templates:edit. La barre d'action
            est HORS du <main>, elle porte donc son propre data-write-perm.
            `data-write-locked` en plus (gouvernance §XVIII) : ici l'utilisateur DÉTIENT la
            permission mais pas sur CE nœud — deux causes distinctes, deux messages. Sans
            lui, l'éditeur s'ouvrait en écriture sur une maquette nationale et le refus
            n'arrivait qu'au clic « Enregistrer » (audit du menu Templates, 2026-07-28). */}
        <div
          className="flex items-center gap-2"
          data-write-perm="templates:edit"
          {...(readOnly ? { 'data-write-locked': '1' } : {})}
        >
          {saved && <span className="text-sm text-success">{t('common.saved')}</span>}
          <Button size="sm" variant="secondary" onClick={() => router.push('/templates')}>
            <ArrowLeft className="w-3.5 h-3.5 mr-1" />
            {t('common.back')}
          </Button>
          <Button data-write-action size="sm" onClick={() => saveMutation.mutate()} loading={saveMutation.isPending} disabled={!name.trim()}>
            {t('templates.save_template')}
          </Button>
        </div>
      </Topbar>

      {/*
        Éditeur verrouillé au viewport : le panneau d'outils défile pour lui seul,
        les presets restent fixes et l'aperçu occupe tout l'espace restant.
      */}
      <main
        className="flex-1 min-h-0 flex gap-8 px-6 py-6"
        data-write-perm="templates:edit"
        {...(readOnly ? { 'data-write-locked': '1' } : {})}
      >
          {readOnly && (
            <div className="absolute left-1/2 -translate-x-1/2 top-20 z-20 text-xs text-warning bg-warning/10 border border-warning/25 rounded-lg px-3 py-1.5">
              {t('templates.governed_readonly')}
            </div>
          )}

          {/* Panneau gauche — paramètres (défilement indépendant) */}
          <aside className="w-64 shrink-0 overflow-y-auto pr-1 space-y-6">
            <Input label={t('templates.col_name')} value={name} onChange={(e) => setName(e.target.value)} />

            {/* P3.6 — Retail Media x multi-zones. N'a de sens qu'a PARTIR de 2 zones : sur un
                template plein ecran, un spot a toujours occupe tout l'ecran. Afficher le
                reglage la ferait croire a un choix qui n'existe pas. */}
            {zones.length > 1 && (
              <div className="space-y-2" data-testid="campaign-placement">
                <p className="text-sm font-medium text-gray-700">{t('templates.campaign_placement')}</p>
                <div className="space-y-1.5">
                  {(['fullscreen', 'zone'] as const).map((mode) => (
                    <label
                      key={mode}
                      className="flex items-start gap-2 text-xs text-gray-600 cursor-pointer"
                    >
                      <input
                        type="radio"
                        name="campaign_placement"
                        data-write-action
                        data-testid={`campaign-placement-${mode}`}
                        checked={campaignPlacement === mode}
                        onChange={() => setCampaignPlacement(mode)}
                        className="mt-0.5"
                      />
                      <span>
                        <span className="block text-gray-700">
                          {t(`templates.campaign_placement_${mode}`)}
                        </span>
                        <span className="block text-gray-500">
                          {t(`templates.campaign_placement_${mode}_hint`)}
                        </span>
                        {/* Nommer la zone visée : « zone principale » ne dit pas LAQUELLE. */}
                        {mode === 'zone' && campaignPlacement === 'zone' && (
                          <span
                            className="block mt-0.5 font-medium text-red-600"
                            data-testid="campaign-zone-target"
                          >
                            {mainZone
                              ? t('templates.campaign_zone_target', {
                                  zone: mainZone.label || `${t('templates.zone')} 1`,
                                })
                              : t('templates.campaign_zone_missing')}
                          </span>
                        )}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* Résolution du canvas (FHD/4K/portrait/LED custom) */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-gray-700">{t('templates.resolution')}</p>
                <button
                  type="button"
                  data-write-action
                  onClick={() => setResolution(canvasH, canvasW)}
                  title={t('templates.rotate_canvas')}
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-accent transition-sf"
                >
                  <RotateCw className="w-3.5 h-3.5" />
                </button>
              </div>
              <select
                value={`${canvasW}x${canvasH}`}
                onChange={(e) => {
                  const [w, h] = e.target.value.split('x').map(Number)
                  if (w && h) setResolution(w, h)
                }}
                className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm bg-surface text-gray-700 focus:outline-none focus:ring-1 focus:ring-accent/40"
              >
                {RESOLUTION_PRESETS.map((r) => (
                  <option key={r.label} value={`${r.w}x${r.h}`}>{r.label}</option>
                ))}
                {!RESOLUTION_PRESETS.some((r) => r.w === canvasW && r.h === canvasH) && (
                  <option value={`${canvasW}x${canvasH}`}>{t('templates.res_custom')} {canvasW}×{canvasH}</option>
                )}
              </select>
              <div className="grid grid-cols-2 gap-2">
                <NumField label={t('templates.res_width')} value={canvasW} onCommit={(n) => setResolution(n, canvasH)} onStep={(d) => setResolution(canvasW + d, canvasH)} />
                <NumField label={t('templates.res_height')} value={canvasH} onCommit={(n) => setResolution(canvasW, n)} onStep={(d) => setResolution(canvasW, canvasH + d)} />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-gray-700">Zones</p>
                <Button data-write-action size="sm" variant="secondary" onClick={addZone}>
                  <Plus className="w-3.5 h-3.5 mr-1" />
                  {t('templates.add_zone')}
                </Button>
              </div>
              {zones.map((z, i) => (
                <div
                  key={i}
                  onClick={() => setSelected(i)}
                  className={`px-3 py-2 rounded border text-xs cursor-pointer transition-sf ${zoneColor(z.index)} ${
                    selected === i ? 'ring-2 ring-offset-1 ring-accent/40' : ''
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{t('templates.zone')} {z.index + 1}</span>
                    {zones.length > 1 && (
                      <button
                        data-write-action
                        onClick={(e) => { e.stopPropagation(); removeZone(i) }}
                        className="text-gray-400 hover:text-danger transition-sf"
                        title={t('templates.remove_zone')}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  <input
                    value={z.label}
                    onChange={(e) => setLabel(i, e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    placeholder={t('templates.zone_label')}
                    className="mt-1.5 w-full bg-white/70 border border-gray-200 rounded-lg px-1.5 py-0.5 text-xs text-gray-700 focus:outline-none focus:ring-1 focus:ring-accent/40"
                  />
                  <p className="text-gray-500 mt-1">{z.w} × {z.h} · ({z.x}, {z.y})</p>
                </div>
              ))}
            </div>

            {/* Propriétés de la zone sélectionnée : nom + coordonnées/dimensions + alignement */}
            {sel && (
              <div className="space-y-3 border-t border-gray-100 pt-4">
                <p className="text-sm font-medium text-gray-700">
                  {t('templates.zone_props')} — {t('templates.zone')} {sel.index + 1}
                </p>
                <Input
                  label={t('templates.zone_label')}
                  value={sel.label}
                  onChange={(e) => setLabel(selected, e.target.value)}
                />
                <div className="grid grid-cols-2 gap-2">
                  {(['x', 'y', 'w', 'h'] as const).map((f) => (
                    <NumField
                      key={f}
                      label={f.toUpperCase()}
                      value={sel[f]}
                      onCommit={(n) => updateZone(selected, { [f]: n } as Partial<Zone>)}
                      onStep={(d) => stepZone(selected, f, d)}
                    />
                  ))}
                </div>
                <div className="space-y-1.5">
                  <p className="text-xs text-gray-400">{t('templates.align')}</p>
                  <div className="flex flex-wrap gap-1">
                    {([
                      { Icon: AlignStartVertical, title: t('templates.align_left'), patch: { x: 0 } },
                      { Icon: AlignCenterVertical, title: t('templates.align_hcenter'), patch: { x: Math.round((canvasW - sel.w) / 2) } },
                      { Icon: AlignEndVertical, title: t('templates.align_right'), patch: { x: canvasW - sel.w } },
                      { Icon: AlignStartHorizontal, title: t('templates.align_top'), patch: { y: 0 } },
                      { Icon: AlignCenterHorizontal, title: t('templates.align_vmiddle'), patch: { y: Math.round((canvasH - sel.h) / 2) } },
                      { Icon: AlignEndHorizontal, title: t('templates.align_bottom'), patch: { y: canvasH - sel.h } },
                      { Icon: Maximize, title: t('templates.fill_canvas'), patch: { x: 0, y: 0, w: canvasW, h: canvasH } },
                    ] as const).map((tool, k) => (
                      <button
                        key={k}
                        type="button"
                        data-write-action
                        onClick={() => updateZone(selected, tool.patch)}
                        title={tool.title}
                        className="p-1.5 rounded border border-gray-200 text-gray-500 hover:border-accent hover:text-accent transition-sf"
                      >
                        <tool.Icon className="w-4 h-4" />
                      </button>
                    ))}
                  </div>
                </div>
                <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer select-none">
                  <input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)} className="w-3.5 h-3.5 rounded border-gray-300" />
                  {t('templates.snap_grid', { px: SNAP_PX })}
                </label>
              </div>
            )}
          </aside>

          {/* Canvas WYSIWYG — drag pour déplacer, coin pour redimensionner */}
          <div className="flex-1 min-w-0 flex flex-col min-h-0">
            {/* Bloc figé : modèles de base + informations de canvas */}
            <div className="shrink-0">
            {/* Modèles de base : vignettes graphiques côte à côte (rendu mini des zones) */}
            <p className="text-sm font-medium text-gray-700 mb-2">{t('templates.presets')}</p>
            <div className="flex flex-wrap gap-3 mb-5">
              {(Object.keys(PRESET_FRACTIONS) as Array<Exclude<LayoutType, 'custom'>>).map((type) => (
                <button
                  key={type}
                  type="button"
                  data-write-action
                  onClick={() => applyPreset(type)}
                  className={`flex flex-col items-center gap-1.5 p-2 rounded-lg border transition-sf ${
                    layoutType === type ? 'border-accent bg-accent/5' : 'border-gray-200 hover:border-accent'
                  }`}
                >
                  <div className="relative bg-canvas-dark rounded overflow-hidden flex items-center justify-center" style={{ width: 88, height: 50 }}>
                    <div className="relative" style={{ width: thumbW, height: thumbH }}>
                      {PRESET_FRACTIONS[type].map((z, zi) => (
                        <div
                          key={zi}
                          className={`absolute border ${zoneColor(zi)}`}
                          style={{
                            left: `${z.x * 100}%`, top: `${z.y * 100}%`,
                            width: `${z.w * 100}%`, height: `${z.h * 100}%`,
                          }}
                        />
                      ))}
                    </div>
                  </div>
                  <span className={`text-xs font-medium ${layoutType === type ? 'text-accent' : 'text-gray-600'}`}>
                    {presetLabel(type)}
                  </span>
                </button>
              ))}
            </div>

            <p className="text-xs text-gray-400 mb-1">{canvasW} × {canvasH} px — {t('templates.zone_count', { count: zones.length })}</p>
            <p className="text-xs text-gray-400 mb-3">{t('templates.zones_hint')}</p>
            </div>

            {/* Aperçu : occupe tout l'espace restant, ratio du canvas conservé */}
            <div ref={canvasAreaRef} className="flex-1 min-h-0 flex items-start justify-center">
            <div
              className="relative bg-canvas-dark rounded-lg overflow-hidden border border-gray-200 select-none touch-none"
              style={{ width: dispW, height: dispH }}
            >
              {zones.map((zone, i) => (
                <div
                  key={i}
                  data-write-action
                  onPointerDown={(e) => startDrag(e, i, 'move')}
                  data-testid={`zone-${zone.index}`}
                  className={`absolute border-2 flex flex-col items-center justify-center gap-1 cursor-move ${zoneColor(zone.index)} ${
                    selected === i ? 'z-10 shadow-lg' : ''
                  } ${
                    // Liseré rouge = la zone qui recevra les spots de campagne (index 0).
                    highlightMain && zone.index === 0
                      ? 'outline outline-2 outline-red-500 outline-offset-[-2px]'
                      : ''
                  }`}
                  style={{
                    left: `${(zone.x / canvasW) * 100}%`,
                    top: `${(zone.y / canvasH) * 100}%`,
                    width: `${(zone.w / canvasW) * 100}%`,
                    height: `${(zone.h / canvasH) * 100}%`,
                  }}
                >
                  {highlightMain && zone.index === 0 && (
                    <span className="absolute top-1 left-1 rounded bg-red-500 px-1.5 py-0.5 text-[10px] font-semibold text-white pointer-events-none">
                      {t('templates.campaign_zone_badge')}
                    </span>
                  )}
                  <span className="text-sm font-semibold pointer-events-none">{t('templates.zone')} {zone.index + 1}</span>
                  <span className="text-xs opacity-70 pointer-events-none truncate max-w-full px-1">{zone.label}</span>
                  {/* Poignée de redimensionnement (coin bas-droit) */}
                  <div
                    onPointerDown={(e) => startDrag(e, i, 'resize')}
                    className="absolute bottom-0 right-0 w-3.5 h-3.5 bg-surface border border-gray-400 rounded-tl cursor-nwse-resize"
                  />
                </div>
              ))}
            </div>
            </div>
          </div>
      </main>
    </>
  )
}
