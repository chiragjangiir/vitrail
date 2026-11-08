'use client'

import { useMemo, useState } from 'react'
import { Grid3x3, Save, X } from 'lucide-react'
import type { PlayerRead, WallConfig } from '@/types/api'
import NumberField from '@/components/ui/NumberField'

/**
 * Éditeur de mur d'écrans (video wall) au niveau d'un groupe LAN Sync. Écrit
 * `display_config.wall` sur chaque membre (grille + cellule + bezels) ; la compensation de
 * bezel est calculée serveur (services/video_wall.py) et appliquée par le renderer (mpv
 * video-zoom/align — validé HW). Groupe supposé HOMOGÈNE (mêmes dalle/bezels) → une seule
 * saisie de dalle/bezels ; seule la cellule varie par player.
 */

export type WallSave = {
  rows: number
  cols: number
  mode: 'overscan' | 'crop'
  panel_w_mm: number
  panel_h_mm: number
  bezel_left_mm: number
  bezel_right_mm: number
  bezel_top_mm: number
  bezel_bottom_mm: number
  gap_scale: number
  assignments: Record<number, { row: number; col: number }>
}

interface Props {
  members: PlayerRead[]
  onSave: (cfg: WallSave) => void
  onDisable: () => void
  isSaving: boolean
  t: (key: string, values?: Record<string, string | number>) => string
}

const N = (v: unknown, d: number): number => {
  const f = Number(v)
  return Number.isFinite(f) ? f : d
}

export default function WallEditor({ members, onSave, onDisable, isSaving, t }: Props) {
  // État initial depuis le 1er membre déjà configuré (homogène) — sinon défauts terrain.
  const seed = members.find((m) => m.display_config?.wall)?.display_config?.wall as
    | WallConfig
    | undefined
  const enabled = !!seed

  // EDID prefill : à la 1re config (pas de wall existant), pré-remplir la dalle depuis la taille
  // physique remontée par un membre (capabilities.panel_mm, lue via xrandr/wlr-randr/WMI). Groupe
  // homogène → un seul membre suffit. Repli défauts terrain 528×297 si aucun ne la remonte.
  const edidMm = members.find((m) => m.capabilities?.panel_mm?.w && m.capabilities?.panel_mm?.h)
    ?.capabilities?.panel_mm

  const [open, setOpen] = useState(false)
  const [cols, setCols] = useState(N(seed?.cols, 2))
  const [rows, setRows] = useState(N(seed?.rows, 1))
  const [mode, setMode] = useState<'overscan' | 'crop'>(seed?.mode === 'crop' ? 'crop' : 'overscan')
  const [panelW, setPanelW] = useState(N(seed?.panel_w_mm, N(edidMm?.w, 528)))
  const [panelH, setPanelH] = useState(N(seed?.panel_h_mm, N(edidMm?.h, 297)))
  // Bezels par côté (mm) : certains écrans non-videowall ont un bezel inégal (ex. bas plus
  // grand). Le serveur calcule l'overscan par axe depuis les bords INTÉRIEURS de chaque écran.
  const [bezelL, setBezelL] = useState(N(seed?.bezel_left_mm, 4.5))
  const [bezelR, setBezelR] = useState(N(seed?.bezel_right_mm, 4.5))
  const [bezelT, setBezelT] = useState(N(seed?.bezel_top_mm, 4.5))
  const [bezelB, setBezelB] = useState(N(seed?.bezel_bottom_mm, 4.5))
  const [gapScale, setGapScale] = useState(N(seed?.gap_scale, 1))

  // Assignations cellule par player : init depuis la config existante, sinon ordre row-major.
  const [assign, setAssign] = useState<Record<number, { row: number; col: number }>>(() => {
    const a: Record<number, { row: number; col: number }> = {}
    members.forEach((m, i) => {
      const c = m.display_config?.wall?.cell
      a[m.id_player] = c
        ? { row: N(c.row, 0), col: N(c.col, 0) }
        : { row: Math.floor(i / N(seed?.cols, 2)), col: i % N(seed?.cols, 2) }
    })
    return a
  })

  // video-zoom résultant (lecture) par axe pour un écran à 1 bezel intérieur (cas bord) :
  // horizontal depuis le bezel droit, vertical depuis le bas (les côtés intérieurs typiques).
  const zoomH = useMemo(
    () => (panelW > 0 ? Math.log2(1 + (bezelR / panelW) * gapScale) : 0),
    [panelW, bezelR, gapScale],
  )
  const zoomV = useMemo(
    () => (panelH > 0 ? Math.log2(1 + (bezelB / panelH) * gapScale) : 0),
    [panelH, bezelB, gapScale],
  )

  const setCell = (id: number, key: 'row' | 'col', val: number) =>
    setAssign((a) => ({ ...a, [id]: { ...a[id], [key]: val } }))

  const save = () =>
    onSave({
      rows, cols, mode, panel_w_mm: panelW, panel_h_mm: panelH,
      bezel_left_mm: bezelL, bezel_right_mm: bezelR, bezel_top_mm: bezelT, bezel_bottom_mm: bezelB,
      gap_scale: gapScale, assignments: assign,
    })

  return (
    <div className="px-4 py-2 border-t border-gray-100 bg-purple-500/10">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900"
      >
        <Grid3x3 className="w-3.5 h-3.5 text-purple-500" />
        {t('players.wall.title')}
        {enabled && (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300">
            {t('players.wall.active', { rows: seed!.rows, cols: seed!.cols })}
          </span>
        )}
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          {/* Grille + mode */}
          <div className="flex flex-wrap items-end gap-3">
            <NumField label={t('players.wall.cols')} value={cols} min={1} max={6} onChange={setCols} />
            <NumField label={t('players.wall.rows')} value={rows} min={1} max={6} onChange={setRows} />
            <label className="flex flex-col gap-1 text-[11px] text-gray-500">
              {t('players.wall.mode')}
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as 'overscan' | 'crop')}
                className="rounded border border-gray-200 px-2 py-1 text-xs bg-surface text-gray-700"
              >
                <option value="overscan">{t('players.wall.mode_b')}</option>
                <option value="crop">{t('players.wall.mode_a')}</option>
              </select>
            </label>
          </div>

          {/* Dalle (homogène) */}
          <div className="flex flex-wrap items-end gap-3">
            <NumField label={t('players.wall.panel_w')} value={panelW} min={1} step={1} onChange={setPanelW} />
            <NumField label={t('players.wall.panel_h')} value={panelH} min={1} step={1} onChange={setPanelH} />
          </div>

          {/* Bezels par côté (mm) — gérer les écrans à bezel inégal (ex. bas plus grand) */}
          <div>
            <p className="text-[11px] font-medium text-gray-500 mb-1">{t('players.wall.bezels')}</p>
            <div className="flex flex-wrap items-end gap-3">
              <NumField label={t('players.wall.bezel_top')} value={bezelT} min={0} step={0.1} onChange={setBezelT} />
              <NumField label={t('players.wall.bezel_bottom')} value={bezelB} min={0} step={0.1} onChange={setBezelB} />
              <NumField label={t('players.wall.bezel_left')} value={bezelL} min={0} step={0.1} onChange={setBezelL} />
              <NumField label={t('players.wall.bezel_right')} value={bezelR} min={0} step={0.1} onChange={setBezelR} />
            </div>
          </div>

          {/* Compensation (gap_scale) + lecture video-zoom */}
          <div className="space-y-1">
            <label className="flex items-center justify-between text-[11px] text-gray-500">
              <span>{t('players.wall.gap_scale')}</span>
              <span className="font-mono text-gray-700">
                ×{gapScale.toFixed(2)} → zoom H {zoomH.toFixed(4)} · V {zoomV.toFixed(4)}
              </span>
            </label>
            <input
              type="range"
              min={1}
              max={2.5}
              step={0.01}
              value={gapScale}
              onChange={(e) => setGapScale(Number(e.target.value))}
              className="w-full accent-purple-500"
            />
            <p className="text-[10px] text-gray-400">{t('players.wall.gap_scale_hint')}</p>
          </div>

          {/* Assignation des cellules */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium text-gray-500">{t('players.wall.assign')}</p>
            {members.map((m) => (
              <div key={m.id_player} className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate text-gray-700">{m.player_name}</span>
                <div className="flex items-center gap-1.5 shrink-0">
                  <CellSelect label="L" value={assign[m.id_player]?.row ?? 0} count={rows} onChange={(v) => setCell(m.id_player, 'row', v)} />
                  <CellSelect label="C" value={assign[m.id_player]?.col ?? 0} count={cols} onChange={(v) => setCell(m.id_player, 'col', v)} />
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between pt-1">
            {enabled ? (
              <button
                onClick={onDisable}
                disabled={isSaving}
                className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-danger disabled:opacity-50"
              >
                <X className="w-3.5 h-3.5" />
                {t('players.wall.disable')}
              </button>
            ) : (
              <span />
            )}
            <button
              onClick={save}
              disabled={isSaving}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-purple-600 hover:bg-purple-700 text-white text-xs font-medium disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" />
              {t('players.wall.save')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function NumField({
  label, value, onChange, min, max, step = 1,
}: { label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number }) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-gray-500">
      {label}
      <NumberField
        value={value}
        min={min}
        max={max}
        step={step}
        onCommit={(v) => onChange(v ?? min ?? 0)}
        className="w-20 rounded border border-gray-200 px-2 py-1 text-xs bg-surface text-gray-700"
      />
    </label>
  )
}

function CellSelect({
  label, value, count, onChange,
}: { label: string; value: number; count: number; onChange: (v: number) => void }) {
  return (
    <label className="flex items-center gap-1 text-[10px] text-gray-400">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded border border-gray-200 px-1.5 py-1 text-xs bg-surface text-gray-700"
      >
        {Array.from({ length: Math.max(1, count) }, (_, i) => (
          <option key={i} value={i}>{i}</option>
        ))}
      </select>
    </label>
  )
}
