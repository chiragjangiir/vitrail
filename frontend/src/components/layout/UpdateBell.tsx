'use client'

// Cloche « une MAJ serveur est disponible » (self-hosted). Visible pour l'ORG-ADMIN
// (= l'exploitant sur une install client). Le serveur ne répond enabled/available
// que si SIGNFLOW_UPDATE_BELL est actif ET qu'une version épinglée plus récente est
// publiée dans le manifeste : un build source ("dev") ou une prod multi-tenant reste
// muet. La cloche N'EXÉCUTE RIEN — une MAJ serveur = migrations + brève coupure,
// donc toujours humaine : on affiche la commande à copier.

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpCircle, ShieldAlert, Copy, Check } from 'lucide-react'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'

interface Release {
  version: string
  date?: string | null
  security?: boolean
  notes?: string | null
}
interface UpdateStatus {
  enabled: boolean
  current: string
  latest?: string
  update_available: boolean
  security?: boolean
  releases?: Release[]
}

export default function UpdateBell() {
  const t = useTranslations('update')
  const user = useAuthStore((s) => s.user)
  const isOrgAdmin = useAuthStore((s) => s.hasRole('CMS_ORG_ADMIN'))
  const isSuperAdmin = useAuthStore((s) => s.hasRole('CMS_SUPER_ADMIN'))
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery<UpdateStatus>({
    queryKey: ['update-status'],
    queryFn: () => api.get<UpdateStatus>('/meta/update').then((r) => r.data),
    // Réservé aux exploitants ; jamais pour un compte annonceur.
    enabled: !!user && !user.id_advertiser && (isOrgAdmin || isSuperAdmin),
    retry: false, // 403 (non-admin) → cloche masquée
    // Une MAJ serveur n'arrive pas à la seconde ; sondage horaire (le backend
    // cache le manifeste 6 h de son côté).
    refetchInterval: (query) => (query.state.status === 'error' ? false : 3_600_000),
    staleTime: 30 * 60_000,
  })

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  if (!data?.enabled || !data.update_available) return null
  const latest = data.latest || ''
  const command = `cd /opt/signflow && bash update.sh ${latest}`

  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* presse-papier indisponible (HTTP non-secure) — l'utilisateur copie à la main */
    }
  }

  const security = !!data.security

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={() => setOpen(!open)}
        title={t('bell_title')}
        aria-label={t('bell_title')}
        className={`relative flex items-center justify-center w-8 h-8 rounded-lg transition-sf ${
          security ? 'text-danger hover:bg-red-500/10' : 'text-success hover:bg-emerald-500/10'
        }`}
      >
        <ArrowUpCircle className="w-4 h-4" />
        <span
          className={`absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-canvas ${
            security ? 'bg-danger sf-glow-danger animate-pulse' : 'bg-success sf-glow-success'
          }`}
        />
      </button>
      {open && (
        <div className="absolute right-0 mt-1.5 z-50 w-80 bg-surface border border-white/10 rounded-lg shadow-sf-card overflow-hidden">
          <div className="px-3 py-2.5 border-b border-white/5">
            <p className="text-sm font-semibold text-gray-900">{t('title')}</p>
            <p className="text-xs text-gray-400">
              {t('version_line', { current: data.current, latest })}
            </p>
          </div>

          {security && (
            <div className="flex items-start gap-2 px-3 py-2 bg-danger/10 border-b border-danger/20">
              <ShieldAlert className="w-4 h-4 text-danger shrink-0 mt-0.5" />
              <p className="text-xs text-danger">{t('security_warning')}</p>
            </div>
          )}

          {(data.releases?.length ?? 0) > 0 && (
            <ul className="max-h-56 overflow-y-auto divide-y divide-white/5">
              {data.releases!.map((r) => (
                <li key={r.version} className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-800">{r.version}</span>
                    {r.security && (
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-danger">
                        {t('security_tag')}
                      </span>
                    )}
                    {r.date && <span className="text-xs text-gray-400 ml-auto">{r.date}</span>}
                  </div>
                  {r.notes && <p className="mt-0.5 text-xs text-gray-500">{r.notes}</p>}
                </li>
              ))}
            </ul>
          )}

          <div className="px-3 py-2.5 border-t border-white/5">
            <p className="text-xs text-gray-400 mb-1.5">{t('command_hint')}</p>
            <div className="flex items-center gap-1.5">
              <code className="flex-1 px-2 py-1.5 rounded bg-canvas border border-white/5 text-[11px] text-gray-700 font-mono truncate">
                {command}
              </code>
              <button
                onClick={copyCommand}
                title={t('copy')}
                className="flex items-center justify-center w-7 h-7 shrink-0 rounded text-gray-400 hover:text-accent hover:bg-white/5 transition-sf"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
            <p className="mt-1.5 text-[11px] text-gray-400">{t('downtime_note')}</p>
          </div>
        </div>
      )}
    </div>
  )
}
