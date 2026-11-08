'use client'

// S6 Retail Media — import de campagne par fichier JSON (ordre d'insertion
// annonceur, format docs/FORMAT_IMPORT_CAMPAGNE.md). Flux : fichier → dry-run
// (aperçu + occupation SOV) → confirmation → création draft + download des
// créatifs en tâche de fond → publish manuel.

import { useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Copy, FileJson, KeyRound, Plus, Trash2, Upload, XCircle } from 'lucide-react'
import Button from '@/components/ui/Button'
import Drawer from '@/components/ui/Drawer'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'

interface ResolvedTarget { type: string; name: string | null; target_id: number | null; error: string | null }
interface ResolvedCreative { url: string; media_name: string; media_type: string | null; error: string | null }
interface DryRun {
  ok: boolean
  errors: string[]
  advertiser_name: string
  advertiser_matched: boolean
  targets: ResolvedTarget[]
  target_player_count: number
  creatives: ResolvedCreative[]
  occupancy: { blocked: boolean; warning: boolean; max_projected_pct: number } | null
}

export default function ImportOrderDrawer({
  open, onClose, onImported,
}: {
  open: boolean
  onClose: () => void
  onImported: (id_campaign: number) => void
}) {
  const t = useTranslations()
  const fileRef = useRef<HTMLInputElement>(null)
  const [order, setOrder] = useState<Record<string, unknown> | null>(null)
  const [fileName, setFileName] = useState('')
  const [dry, setDry] = useState<DryRun | null>(null)
  const [parseErr, setParseErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [importErr, setImportErr] = useState('')

  const reset = () => {
    setOrder(null); setFileName(''); setDry(null); setParseErr(''); setImportErr('')
    if (fileRef.current) fileRef.current.value = ''
  }
  const close = () => { reset(); onClose() }

  const onFile = async (f: File | null) => {
    reset()
    if (!f) return
    setFileName(f.name)
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(await f.text())
    } catch {
      setParseErr(t('campaigns.import_invalid_json'))
      return
    }
    setOrder(parsed)
    setBusy(true)
    try {
      const r = await api.post<DryRun>('/campaigns/import/dry-run', parsed)
      setDry(r.data)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setParseErr(typeof detail === 'string' ? detail : t('campaigns.import_schema_error'))
    } finally {
      setBusy(false)
    }
  }

  const doImport = async () => {
    if (!order) return
    setBusy(true); setImportErr('')
    try {
      const r = await api.post<{ id_campaign: number }>('/campaigns/import', order)
      onImported(r.data.id_campaign)
      close()
    } catch {
      setImportErr(t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const chip = (ok: boolean) => ok
    ? <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />
    : <XCircle className="w-3.5 h-3.5 text-danger shrink-0" />

  return (
    <Drawer open={open} onClose={close} title={t('campaigns.import_title')} width="w-[560px]">
      <div className="space-y-4">
        <p className="text-xs text-gray-400">{t('campaigns.import_hint')}</p>

        <div>
          <input ref={fileRef} type="file" accept=".json,application/json" className="hidden"
                 onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="w-full flex items-center justify-center gap-2 border-2 border-dashed border-gray-200 rounded-xl px-4 py-6 text-sm text-gray-500 hover:border-accent hover:text-accent transition-sf"
          >
            <FileJson className="w-5 h-5" />
            {fileName || t('campaigns.import_pick_file')}
          </button>
        </div>

        {parseErr && <p className="text-sm text-danger">{parseErr}</p>}
        {busy && !dry && <p className="text-sm text-gray-400">{t('common.loading')}</p>}

        {dry && (
          <div className="space-y-3">
            {/* Annonceur */}
            <div className="bg-surface border border-gray-200 rounded-lg p-3 shadow-sf-card space-y-1">
              <p className="text-xs font-medium text-gray-500">{t('campaigns.advertiser')}</p>
              <p className="text-sm text-gray-800 flex items-center gap-2">
                {dry.advertiser_name}
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                  dry.advertiser_matched
                    ? 'bg-accent/10 dark:bg-blue-500/15 text-blue-700 dark:text-blue-300'
                    : 'bg-green-50 dark:bg-green-500/15 text-green-700 dark:text-green-300'}`}>
                  {dry.advertiser_matched ? t('campaigns.import_adv_matched') : t('campaigns.import_adv_new')}
                </span>
              </p>
            </div>

            {/* Cibles résolues */}
            <div className="bg-surface border border-gray-200 rounded-lg p-3 shadow-sf-card space-y-1.5">
              <p className="text-xs font-medium text-gray-500">
                {t('campaigns.target')} · {t('campaigns.target_players_pill', { count: dry.target_player_count })}
              </p>
              {dry.targets.map((tg, i) => (
                <p key={i} className="text-sm text-gray-700 flex items-center gap-2">
                  {chip(!tg.error)}
                  <span className="truncate">
                    {t(`campaigns.target_${tg.type}`)}
                    {tg.name ? ` · ${tg.name}` : ''}
                  </span>
                  {tg.error && <span className="text-xs text-danger truncate">{tg.error}</span>}
                </p>
              ))}
            </div>

            {/* Créatifs */}
            <div className="bg-surface border border-gray-200 rounded-lg p-3 shadow-sf-card space-y-1.5">
              <p className="text-xs font-medium text-gray-500">{t('campaigns.creatives')}</p>
              {dry.creatives.map((c, i) => (
                <p key={i} className="text-sm text-gray-700 flex items-center gap-2">
                  {chip(!c.error)}
                  <span className="truncate" title={c.url}>{c.media_name}</span>
                  {c.media_type && <span className="text-[10px] text-gray-400 uppercase shrink-0">{c.media_type}</span>}
                  {c.error && <span className="text-xs text-danger truncate">{c.error}</span>}
                </p>
              ))}
              <p className="text-[11px] text-gray-400">{t('campaigns.import_download_note')}</p>
            </div>

            {/* Occupation projetée */}
            {dry.occupancy && (dry.occupancy.warning || dry.occupancy.blocked) && (
              <div className={`rounded-lg px-3 py-2.5 text-sm flex items-start gap-2 ${dry.occupancy.blocked
                ? 'bg-red-500/10 text-danger dark:bg-red-500/15 dark:text-red-300'
                : 'bg-orange-500/15 text-warning dark:bg-orange-500/15 dark:text-orange-300'}`}>
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>
                  {dry.occupancy.blocked ? t('campaigns.occupancy_blocked') : t('campaigns.occupancy_warning')}
                  {' '}({dry.occupancy.max_projected_pct}%) — {t('campaigns.import_occupancy_note')}
                </span>
              </div>
            )}

            {dry.errors.length > 0 && (
              <div className="rounded-lg bg-red-500/10 dark:bg-red-500/15 px-3 py-2.5 space-y-0.5">
                {dry.errors.map((e, i) => (
                  <p key={i} className="text-xs text-danger dark:text-red-300">{e}</p>
                ))}
              </div>
            )}

            {importErr && <p className="text-sm text-danger">{importErr}</p>}
            <div className="flex gap-2">
              <Button onClick={doImport} disabled={!dry.ok || busy} loading={busy}>
                <Upload className="w-4 h-4 mr-1" />{t('campaigns.import_confirm')}
              </Button>
              <Button variant="secondary" onClick={close}>{t('common.cancel')}</Button>
            </div>
          </div>
        )}

        {/* Import PAR API (v2, 12/07) : clés machine sfi_ — org-admin seulement */}
        <ImportKeysSection open={open} />
      </div>
    </Drawer>
  )
}

// ── Clés d'import `sfi_` (org-admin) — l'agence pousse ses ordres par API ──────

interface ImportKey {
  id_key: number; key_prefix: string; label: string | null
  last_used_at: string | null; expires_at: string | null; created_at: string
  key?: string | null
}

function ImportKeysSection({ open }: { open: boolean }) {
  const t = useTranslations()
  const qc = useQueryClient()
  const isAdmin = useAuthStore((s) => s.isAdmin)
  const [label, setLabel] = useState('')
  const [created, setCreated] = useState<ImportKey | null>(null)
  const [copied, setCopied] = useState(false)

  const admin = isAdmin()
  const { data: keys = [] } = useQuery<ImportKey[]>({
    queryKey: ['campaign-import-keys'],
    queryFn: () => api.get<ImportKey[]>('/campaigns/import-keys').then((r) => r.data),
    enabled: open && admin,
    retry: false,
  })
  const createKey = useMutation({
    mutationFn: () => api.post<ImportKey>('/campaigns/import-keys',
      { label: label.trim() || null }).then((r) => r.data),
    onSuccess: (d) => {
      setCreated(d); setLabel('')
      qc.invalidateQueries({ queryKey: ['campaign-import-keys'] })
    },
  })
  const revokeKey = useMutation({
    mutationFn: (id: number) => api.delete(`/campaigns/import-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaign-import-keys'] }),
  })
  if (!admin) return null

  return (
    <div className="border-t border-gray-100 pt-4 space-y-2">
      <p className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
        <KeyRound className="w-4 h-4 text-gray-400" />{t('campaigns.import_keys_title')}
      </p>
      <p className="text-xs text-gray-400">{t('campaigns.import_keys_hint')}</p>
      <div className="space-y-1">
        {keys.map((k) => (
          <div key={k.id_key}
               className="flex items-center justify-between gap-2 text-xs bg-gray-50 rounded-lg px-2 py-1.5">
            <span className="truncate text-gray-700 font-mono">{k.key_prefix}…</span>
            <span className="truncate text-gray-500">{k.label}</span>
            <span className="inline-flex items-center gap-2 shrink-0 text-gray-400">
              {k.last_used_at
                ? k.last_used_at.slice(0, 10)
                : t('campaigns.import_key_never_used')}
              <button onClick={() => {
                        if (confirm(t('campaigns.import_key_revoke_confirm'))) revokeKey.mutate(k.id_key)
                      }}
                      className="p-0.5 text-gray-300 hover:text-danger transition-sf"
                      title={t('common.delete')}>
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </span>
          </div>
        ))}
        {keys.length === 0 && <p className="text-xs text-gray-400 px-1">{t('campaigns.import_keys_none')}</p>}
      </div>
      {created?.key && (
        <div className="rounded-lg bg-accent/10 px-3 py-2.5 space-y-1">
          <p className="text-xs font-medium text-accent">{t('campaigns.import_key_once')}</p>
          <p className="text-sm font-mono text-gray-800 break-all">{created.key}</p>
          <button onClick={() => {
                    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(created.key!).catch(() => {})
                    setCopied(true); setTimeout(() => setCopied(false), 2000)
                  }}
                  className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
            <Copy className="w-3 h-3" />{copied ? t('common.copied') : t('common.copy')}
          </button>
        </div>
      )}
      <div className="flex items-center gap-2">
        <input value={label} onChange={(e) => setLabel(e.target.value)}
               placeholder={t('campaigns.import_key_label_ph')}
               className="flex-1 px-3 py-1.5 text-xs border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40" />
        <Button size="sm" onClick={() => createKey.mutate()} loading={createKey.isPending}>
          <Plus className="w-3.5 h-3.5 mr-1" />{t('campaigns.import_key_create')}
        </Button>
      </div>
    </div>
  )
}
