'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { HardDriveDownload, Pin, PinOff, Trash2, Upload } from 'lucide-react'

import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import api from '@/lib/api'

interface FirmwareVersion {
  id_version: number
  version: string
  model_family: string | null
  channel: string
  is_pinned: boolean
  file_size: number | null
  original_filename: string | null
  sha256_checksum: string | null
  created_at: string
}

function fmtSize(bytes: number | null): string {
  if (!bytes) return '—'
  const mb = bytes / (1024 * 1024)
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} Go` : `${mb.toFixed(1)} Mo`
}

/** Détail d'erreur API garanti STRING (FastAPI 422 renvoie une LISTE d'objets → ne jamais rendre tel quel). */
function errDetail(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

export default function FirmwarePage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [version, setVersion] = useState('')
  const [family, setFamily] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Gate EXPLOITANT du serveur : le serveur filtre (`require_server_operator`), la page
  // explique au non-exploitant au lieu d'afficher un 403.
  const { data: op } = useQuery<{ is_operator: boolean }>({
    queryKey: ['server-operator'],
    queryFn: async () => (await api.get('/meta/operator')).data,
    retry: false,
  })

  const { data: versions = [], isLoading } = useQuery<FirmwareVersion[]>({
    queryKey: ['firmware-versions'],
    queryFn: () => api.get<FirmwareVersion[]>('/firmware/versions').then((r) => r.data),
    enabled: op?.is_operator === true,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['firmware-versions'] })

  const uploadMutation = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append('file', file as File)
      fd.append('version', version.trim())
      fd.append('model_family', family.trim())
      // L'axios `api` a un Content-Type JSON par défaut → il FAUT forcer multipart (sinon la
      // FormData est sérialisée en JSON → 422). Même pattern que MediaUploader/ReferencePicker.
      return api.post('/firmware/versions', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    },
    onSuccess: () => { setFile(null); setVersion(''); setFamily(''); setError(null); invalidate() },
    onError: (e: unknown) => setError(errDetail(e, t('firmware.upload_error'))),
  })

  const pinMutation = useMutation({
    mutationFn: (id: number) => api.post(`/firmware/versions/${id}/pin`),
    onSuccess: invalidate,
  })
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/firmware/versions/${id}`),
    onSuccess: invalidate,
    onError: (e: unknown) => setError(errDetail(e, t('firmware.delete_error'))),
  })

  const canUpload = !!file && !!version.trim() && !!family.trim() && !uploadMutation.isPending

  return (
    <div className="flex flex-col h-full">
      <Topbar title={t('nav.firmware')} />
      <div className="flex-1 overflow-y-auto p-6">
        {/* Contenu CENTRE, comme Organisations / Feedback / Profil (homogeneite
            des pages de reglages, arbitrage Ed 2026-07-23).
            Largeur de reference des pages de reglages centrees : max-w-5xl. */}
        <div className="mx-auto max-w-5xl space-y-6">
        {op && !op.is_operator ? (
          <div className="rounded-lg border border-gray-200 bg-surface p-5 shadow-sf-card">
            <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <HardDriveDownload className="w-4 h-4 text-gray-400" /> {t('nav.firmware')}
            </h2>
            <p className="mt-2 text-sm text-gray-600">{t('firmware.holder_only')}</p>
          </div>
        ) : (
          <>
        <p className="text-sm text-gray-500">{t('firmware.intro')}</p>

        {/* Upload */}
        <div className="rounded-lg border border-gray-200 bg-surface p-4 space-y-3 shadow-sf-card">
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <Upload className="w-4 h-4 text-gray-400" /> {t('firmware.upload_title')}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="text-xs text-gray-500">
              {t('firmware.file')}
              <input
                type="file" accept=".bsfw"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="mt-1 block w-full text-xs"
              />
            </label>
            <label className="text-xs text-gray-500">
              {t('firmware.version')}
              <input
                type="text" value={version} onChange={(e) => setVersion(e.target.value)}
                placeholder="9.1.132"
                className="mt-1 block w-full px-2 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-accent/40"
              />
            </label>
            <label className="text-xs text-gray-500">
              {t('firmware.family')}
              <input
                type="text" value={family} onChange={(e) => setFamily(e.target.value)}
                placeholder="malibu"
                className="mt-1 block w-full px-2 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-accent/40"
              />
            </label>
          </div>
          <p className="text-[11px] text-gray-400">{t('firmware.family_hint')}</p>
          <Button onClick={() => uploadMutation.mutate()} disabled={!canUpload}>
            {uploadMutation.isPending ? t('firmware.uploading') : t('firmware.upload_btn')}
          </Button>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        {/* Liste */}
        <div className="rounded-lg border border-gray-200 bg-surface divide-y divide-gray-100 shadow-sf-card">
          {isLoading && <p className="p-4 text-sm text-gray-400">{t('common.loading')}</p>}
          {!isLoading && versions.length === 0 && (
            <p className="p-4 text-sm text-gray-400">{t('firmware.empty')}</p>
          )}
          {versions.map((v) => (
            <div key={v.id_version} className="p-4 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <HardDriveDownload className="w-4 h-4 text-gray-400 shrink-0" />
                  <span className="font-medium text-gray-800 text-sm">{v.version}</span>
                  <span className="text-xs text-gray-400">· {v.model_family}</span>
                  {v.is_pinned && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-50 text-green-700 border border-green-200 dark:bg-green-500/15 dark:text-green-300 dark:border-green-500/30">
                      <Pin className="w-3 h-3" /> {t('firmware.pinned_badge')}
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-gray-400 mt-0.5 truncate">
                  {fmtSize(v.file_size)} · {v.original_filename}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {!v.is_pinned && (
                  <button
                    type="button" onClick={() => pinMutation.mutate(v.id_version)}
                    disabled={pinMutation.isPending}
                    title={t('firmware.pin')}
                    className="p-1.5 rounded border border-accent/30 text-accent hover:bg-accent/5 disabled:opacity-50"
                  >
                    <Pin className="w-4 h-4" />
                  </button>
                )}
                {v.is_pinned && (
                  <span className="p-1.5 text-gray-300" title={t('firmware.pinned_badge')}>
                    <PinOff className="w-4 h-4" />
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => { if (confirm(t('firmware.delete_confirm', { version: v.version }))) deleteMutation.mutate(v.id_version) }}
                  disabled={deleteMutation.isPending || v.is_pinned}
                  title={v.is_pinned ? t('firmware.unpin_first') : t('firmware.delete')}
                  className="p-1.5 rounded border border-red-400/20 text-red-500 hover:bg-red-500/10 disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
          </>
        )}
        </div>
      </div>
    </div>
  )
}
