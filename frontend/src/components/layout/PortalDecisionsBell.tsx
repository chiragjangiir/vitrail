'use client'

// Cloche du portail annonceur (retour Ed #8) : décisions du retailer sur SES
// campagnes (approuvée / rejetée / modifications demandées / publiée). Le non-vu
// est serveur-side (submitter_seen_at, migr 0086) ; ouvrir la cloche marque tout
// comme vu (sauf compte démo — pas d'écriture). Clic sur une décision :
// modifications demandées → formulaire d'édition, sinon accueil du portail.

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCircle2, Pencil, XCircle } from 'lucide-react'
import api from '@/lib/api'
import { useAuthStore } from '@/store/auth'

interface Decision {
  id_request: number
  id_campaign: number
  campaign_name: string | null
  status: string
  decided_at: string | null
  unseen: boolean
}
interface Decisions {
  unseen_count: number
  items: Decision[]
}

const ICONS: Record<string, React.ReactNode> = {
  approved: <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />,
  published: <CheckCircle2 className="w-3.5 h-3.5 text-accent shrink-0" />,
  rejected: <XCircle className="w-3.5 h-3.5 text-danger shrink-0" />,
  changes_requested: <Pencil className="w-3.5 h-3.5 text-warning shrink-0" />,
}

export default function PortalDecisionsBell() {
  const t = useTranslations('portal')
  const router = useRouter()
  const qc = useQueryClient()
  const isDemo = !!useAuthStore((s) => s.user)?.is_demo
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery<Decisions>({
    queryKey: ['portal-decisions'],
    queryFn: () => api.get<Decisions>('/portal/decisions').then((r) => r.data),
    // Poll 15 s (retour Ed 12/07 #7 : la décision doit apparaître sans CTRL+R)
    refetchInterval: 15_000,
    staleTime: 10_000,
  })

  const markSeen = useMutation({
    mutationFn: () => api.post('/portal/decisions/seen'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portal-decisions'] }),
  })

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const count = data?.unseen_count ?? 0
  const items = data?.items ?? []

  const toggle = () => {
    const next = !open
    setOpen(next)
    // Ouvrir la cloche = tout marquer vu (compte démo : lecture seule, pas de POST)
    if (next && count > 0 && !isDemo) markSeen.mutate()
  }

  const goTo = (d: Decision) => {
    setOpen(false)
    router.push(d.status === 'changes_requested'
      ? `/portal/campaigns/${d.id_campaign}/edit`
      : '/portal')
  }

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={toggle}
        title={t('bell_title')}
        aria-label={t('bell_title')}
        className="relative p-1.5 text-gray-400 hover:text-gray-700 transition-sf"
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
            {t('bell_header')}
          </p>
          {items.length === 0 ? (
            <p className="px-3 py-3 text-sm text-gray-400">{t('bell_empty')}</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {items.map((d) => (
                <li key={d.id_request}>
                  <button
                    onClick={() => goTo(d)}
                    className={`w-full text-left px-3 py-2.5 hover:bg-canvas transition-sf ${
                      d.unseen ? 'bg-accent/5' : ''
                    }`}
                  >
                    <span className="flex items-center gap-1.5 text-sm text-gray-800">
                      {ICONS[d.status] ?? null}
                      <span className="truncate">{d.campaign_name || `#${d.id_campaign}`}</span>
                    </span>
                    <span className="block text-xs text-gray-400 mt-0.5">
                      {t(`decision_${d.status}`)}
                      {d.decided_at ? ` · ${new Date(d.decided_at).toLocaleDateString()}` : ''}
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
