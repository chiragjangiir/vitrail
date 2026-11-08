'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import {
  Search,
  X,
  Film,
  ListVideo,
  Megaphone,
  Monitor,
  MapPin,
  LayoutTemplate,
  Zap,
  Briefcase,
  Loader2,
} from 'lucide-react'
import api from '@/lib/api'
import { fireSearchPrefill } from '@/lib/useSearchPrefill'
import type { SearchResponse } from '@/types/api'

const KIND_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  media: Film, playlist: ListVideo, campaign: Megaphone, player: Monitor,
  site: MapPin, template: LayoutTemplate, event: Zap, advertiser: Briefcase,
}
const KIND_NAV: Record<string, string> = {
  media: 'nav.media', playlist: 'nav.playlists', campaign: 'nav.campaigns',
  player: 'nav.players', site: 'nav.sites', template: 'nav.templates', event: 'nav.events',
  advertiser: 'nav.advertisers',
}

/** Recherche globale de la topbar : média/playlist/campagne/player/site/template/event.
 *  Débounce 250 ms, résultats groupés en dropdown, Ctrl/Cmd+K pour focus, Échap pour fermer. */
export default function GlobalSearch() {
  const t = useTranslations()
  const router = useRouter()
  const pathname = usePathname()
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 250)
    return () => clearTimeout(id)
  }, [q])

  const { data, isFetching } = useQuery<SearchResponse>({
    queryKey: ['global-search', debounced],
    queryFn: () => api.get<SearchResponse>(`/search?q=${encodeURIComponent(debounced)}`).then((r) => r.data),
    enabled: debounced.length >= 2,
    staleTime: 15000,
  })

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); inputRef.current?.focus(); setOpen(true)
      }
      if (e.key === 'Escape') { setOpen(false); inputRef.current?.blur() }
    }
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [])

  const groups = (data?.groups ?? []).filter((g) => g.items.length > 0)
  const hasResults = groups.length > 0

  function go(href: string) {
    setOpen(false)
    setQ('')
    // Si la cible est la page COURANTE, Next ne remonte pas le composant → le hook de
    // pré-remplissage ne se rejouerait jamais : on lui passe le terme par événement.
    const [path, search] = href.split('?')
    const term = new URLSearchParams(search ?? '').get('q')
    if (term && path === pathname) {
      fireSearchPrefill(term)
      return
    }
    router.push(href)
  }

  return (
    <div ref={ref} className="relative flex-1 max-w-md">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
      <input
        ref={inputRef}
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        placeholder={t('topbar.search_placeholder')}
        className="w-full h-9 pl-9 pr-8 rounded-lg bg-surface border border-white/5 text-sm text-gray-800 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent/40 transition-sf"
      />
      {q && (
        <button
          onClick={() => { setQ(''); inputRef.current?.focus() }}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-900"
          aria-label="clear"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}

      {open && debounced.length >= 2 && (
        <div className="absolute left-0 right-0 mt-2 sf-panel max-h-[70vh] overflow-y-auto py-1.5 z-50">
          {isFetching && !hasResults && (
            <p className="flex items-center justify-center gap-2 text-xs text-gray-500 py-4">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t('common.loading')}
            </p>
          )}
          {!isFetching && !hasResults && (
            <p className="text-xs text-gray-500 text-center py-4">{t('topbar.search_no_results')}</p>
          )}
          {groups.map((g) => {
            const Icon = KIND_ICON[g.kind] ?? Film
            return (
              <div key={g.kind} className="py-1">
                <p className="px-3 py-1 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                  {t(KIND_NAV[g.kind] ?? 'nav.media')}
                </p>
                {g.items.map((h) => (
                  <button
                    key={`${g.kind}-${h.id}`}
                    onClick={() => go(h.href)}
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-800 hover:bg-surface-hover text-left transition-sf"
                  >
                    <Icon className="w-4 h-4 text-gray-400 shrink-0" />
                    <span className="truncate">{h.label}</span>
                    {h.sublabel && (
                      <span className="ml-auto pl-2 text-xs text-gray-500 truncate shrink-0">
                        {h.sublabel}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
