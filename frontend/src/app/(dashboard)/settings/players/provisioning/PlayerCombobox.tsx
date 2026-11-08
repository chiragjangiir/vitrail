'use client'

import { useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { Search, X } from 'lucide-react'
import api from '@/lib/api'
import type { PlayerRead } from '@/types/api'

/**
 * Combobox de sélection d'un player existant (ré-attache) — un seul champ, liste flottante
 * en surimpression (hauteur bornée, scrollable — ne déforme jamais le drawer parent).
 * Recherche nom / #id / os / statut ; non-online d'abord (on ré-attache presque toujours
 * une machine éteinte). `osFilter` restreint la liste à un OS (ex. drawer BrightSign).
 */
export default function PlayerCombobox({
  value, onChange, osFilter, enabled = true,
}: {
  value: string
  onChange: (id: string) => void
  osFilter?: string
  enabled?: boolean
}) {
  const t = useTranslations('provisioning')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)

  const { data: players } = useQuery({
    queryKey: ['players-for-reattach'],
    queryFn: async () => (await api.get<PlayerRead[]>('/players/')).data,
    enabled,
  })

  const label = (p: PlayerRead) => `${p.player_name} (#${p.id_player})`

  // Quand le champ affiche le libellé du player DÉJÀ sélectionné, on montre la liste
  // complète (ré-ouvrir le combobox ne doit pas filtrer sur le libellé).
  const filtered = useMemo(() => {
    const all = (players ?? []).filter((p) => !osFilter || p.player_os === osFilter)
    const sel = all.find((p) => String(p.id_player) === value)
    const q = sel && search === label(sel) ? '' : search.trim().toLowerCase()
    const hit = q
      ? all.filter((p) =>
          p.player_name.toLowerCase().includes(q)
          || String(p.id_player).includes(q.replace(/^#/, ''))
          || (p.player_os ?? '').toLowerCase().includes(q)
          || p.status.toLowerCase().includes(q))
      : all
    const rank = (s: string) => (s === 'online' ? 1 : 0)
    return [...hit].sort(
      (a, b) => rank(a.status) - rank(b.status) || a.player_name.localeCompare(b.player_name))
  }, [players, search, value, osFilter])

  return (
    <div className="relative">
      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
      <input
        value={search}
        onChange={(e) => { setSearch(e.target.value); onChange(''); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}
        placeholder={t('payload_target_search')}
        className="w-full px-3 py-2 pl-8 pr-8 text-sm rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-accent/40 bg-surface"
      />
      {(value || search) && (
        <button
          type="button"
          onMouseDown={(e) => { e.preventDefault(); onChange(''); setSearch(''); setOpen(true) }}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
      {open && (
        <div className="absolute z-20 mt-1 w-full max-h-60 overflow-y-auto rounded-md border border-gray-200 bg-surface shadow-lg">
          {filtered.length === 0 ? (
            <p className="px-3 py-2 text-xs text-gray-400">{t('payload_target_none')}</p>
          ) : (
            filtered.map((p) => (
              <div
                key={p.id_player}
                role="button"
                tabIndex={0}
                onMouseDown={(e) => {
                  // onMouseDown + preventDefault : le blur du champ fermerait la liste
                  // AVANT que le clic n'atteigne l'option.
                  e.preventDefault()
                  onChange(String(p.id_player))
                  setSearch(label(p))
                  setOpen(false)
                }}
                className={`px-3 py-1.5 text-sm cursor-pointer hover:bg-accent/5 flex items-center gap-2 ${
                  String(p.id_player) === value ? 'bg-accent/10 text-accent' : 'text-gray-700'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${p.status === 'online' ? 'bg-green-500' : 'bg-gray-400'}`} />
                <span className="truncate">
                  {p.player_name}{' '}
                  <span className="text-gray-400">#{p.id_player} · {p.player_os ?? '?'} · {p.status}</span>
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
