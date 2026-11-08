'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Film, Loader2, X } from 'lucide-react'
import api from '@/lib/api'

interface GenJob {
  id_job: number
  kind: string
  status: string
  error_detail: string | null
}

/** Suivi des générations vidéo asynchrones : poll tant qu'il y a des jobs actifs,
 *  rafraîchit la médiathèque quand un job aboutit, signale les échecs. */
export default function GenerationJobsBanner() {
  const t = useTranslations()
  const qc = useQueryClient()
  const seen = useRef<Record<number, string>>({})
  const [failure, setFailure] = useState<string | null>(null)

  const { data: jobs = [] } = useQuery<GenJob[]>({
    queryKey: ['generation-jobs'],
    queryFn: () => api.get<GenJob[]>('/generation').then((r) => r.data),
    refetchInterval: (q) => {
      const d = q.state.data as GenJob[] | undefined
      return d && d.some((j) => j.status === 'pending' || j.status === 'processing') ? 4000 : false
    },
  })

  useEffect(() => {
    let newlyReady = false
    for (const j of jobs) {
      const was = seen.current[j.id_job]
      if (was && was !== j.status) {
        if (j.status === 'ready') newlyReady = true
        if (j.status === 'failed') setFailure(j.error_detail || t('generation.error'))
      }
      seen.current[j.id_job] = j.status
    }
    if (newlyReady) qc.invalidateQueries({ queryKey: ['media'] })
  }, [jobs, qc, t])

  const active = jobs.filter((j) => j.status === 'pending' || j.status === 'processing')
  if (!active.length && !failure) return null

  return (
    <div className="mb-4 space-y-2">
      {active.length > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5 text-sm text-gray-700">
          <Loader2 className="h-4 w-4 animate-spin text-accent" />
          <Film className="h-4 w-4 text-accent" />
          {t('generation.jobs_active', { count: active.length })}
        </div>
      )}
      {failure && (
        <div className="flex items-start justify-between gap-3 rounded-lg border border-red-300 dark:border-red-500/40 bg-red-500/10 dark:bg-red-500/15 px-4 py-2.5 text-sm text-red-700 dark:text-red-300">
          <span>{t('generation.jobs_failed')} : {failure}</span>
          <button type="button" onClick={() => setFailure(null)} className="shrink-0">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  )
}
