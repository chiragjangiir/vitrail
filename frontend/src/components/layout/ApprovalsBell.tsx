'use client'

// Cloche des validations (retour Ed #7) — topbar CMS : visible pour les rôles
// VALIDEURS (approvals:review/approve/reject ou org-admin — le serveur répond
// is_reviewer sur /approvals/dashboard). Pastille rouge = demandes en attente ;
// clic = liste chronologique (plus ancienne d'abord) ; clic sur une demande =
// /approvals?open={id} → drawer de validation ouvert.

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Bell } from 'lucide-react'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'

interface Dashboard {
  pending_review: number
  changes_requested: number
  urgent: number
  is_reviewer: boolean
}
interface Approval {
  id_request: number
  resource_name?: string | null
  submitted_by_name?: string | null
  submitted_at: string
  due_date: string | null
}

export default function ApprovalsBell() {
  const t = useTranslations('approvals')
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  const { data: dash } = useQuery<Dashboard>({
    queryKey: ['approvals-dashboard'],
    queryFn: () => api.get<Dashboard>('/approvals/dashboard').then((r) => r.data),
    enabled: !!user && !user.id_advertiser,
    retry: false,               // 403 (pas de capacité approvals) → cloche masquée
    // Poll 15 s (retour Ed 12/07 #4 : « la cloche ne se rafraîchit pas » — 60 s
    // paraissait mort) ; jamais re-poller un compte sans capacité (403 permanent)
    refetchInterval: (query) => (query.state.status === 'error' ? false : 15_000),
    staleTime: 10_000,
  })

  const { data: pending = [] } = useQuery<Approval[]>({
    queryKey: ['approvals-bell-list'],
    queryFn: () => api.get<Approval[]>('/approvals/?status=pending_review').then((r) => r.data),
    enabled: open && !!dash?.is_reviewer,
  })

  // Fermeture au clic extérieur
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  if (!dash?.is_reviewer) return null
  const count = dash.pending_review

  // Ordre CHRONOLOGIQUE (la plus ancienne en premier — demande Ed)
  const items = [...pending].sort(
    (a, b) => a.submitted_at.localeCompare(b.submitted_at))

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={() => setOpen(!open)}
        title={t('bell_title')}
        aria-label={t('bell_title')}
        className="relative flex items-center justify-center w-8 h-8 text-gray-500 hover:text-accent rounded hover:bg-gray-100 transition-sf"
      >
        <Bell className="w-4 h-4" />
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-danger text-white text-[10px] font-semibold flex items-center justify-center">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 mt-1.5 z-50 w-80 bg-surface border border-gray-200 rounded-lg shadow-sf-card overflow-hidden">
          <p className="px-3 py-2 text-xs font-medium text-gray-500 border-b border-gray-100">
            {t('bell_header', { count })}
          </p>
          {items.length === 0 ? (
            <p className="px-3 py-3 text-sm text-gray-400">{t('bell_empty')}</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {items.map((a) => (
                <li key={a.id_request}>
                  <button
                    onClick={() => {
                      setOpen(false)
                      router.push(`/approvals?open=${a.id_request}`)
                    }}
                    className="w-full text-left px-3 py-2.5 hover:bg-canvas transition-sf"
                  >
                    <span className="block text-sm text-gray-800 truncate">
                      {a.resource_name || `#${a.id_request}`}
                    </span>
                    <span className="block text-xs text-gray-400">
                      {a.submitted_by_name || '—'} · {new Date(a.submitted_at).toLocaleDateString()}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
