'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useAuthStore } from '@/store/auth'
import {
  Plus,
  ChevronDown,
  Upload,
  LayoutTemplate,
  ListVideo,
  Megaphone,
  Zap,
  Calendar,
} from 'lucide-react'
import { fireCreateShortcut } from '@/lib/useCreateShortcut'

interface Item {
  href: string
  labelKey: string
  /** Droit requis pour proposer le raccourci (aligne sur le POST cote serveur). */
  perm: string
  Icon: React.ComponentType<{ className?: string }>
}

// Raccourcis de création — pointent vers la page concernée (l'action de création y vit).
const ITEMS: Item[] = [
  { href: '/media', labelKey: 'topbar.new_media', Icon: Upload, perm: 'media:create' },
  { href: '/templates', labelKey: 'topbar.new_template', Icon: LayoutTemplate, perm: 'templates:create' },
  { href: '/playlists', labelKey: 'topbar.new_playlist', Icon: ListVideo, perm: 'playlists:create' },
  { href: '/campaigns', labelKey: 'topbar.new_campaign', Icon: Megaphone, perm: 'campaigns:create' },
  { href: '/events', labelKey: 'topbar.new_event', Icon: Zap, perm: 'events:create' },
  { href: '/schedules', labelKey: 'topbar.new_schedule', Icon: Calendar, perm: 'schedules:create' },
]

/** Bouton « + New » de la topbar : menu de raccourcis vers les actions de création. */
export default function NewMenu() {
  const t = useTranslations()
  const router = useRouter()
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Ouvre le drawer de création de la cible : si on y est déjà (pas de remontage) on émet
  // l'événement, sinon on navigue avec ?new=1 (la page cible ouvre au montage).
  // Un raccourci de creation qui menerait a un 403 n'est pas propose.
  const permissions = useAuthStore((st) => st.user?.permissions)
  const isAdmin = useAuthStore((st) => st.isAdmin())
  const visibleItems = ITEMS.filter((i) => isAdmin || (permissions ?? []).includes(i.perm))

  function go(href: string) {
    setOpen(false)
    if (pathname === href) fireCreateShortcut()
    else router.push(`${href}?new=1`)
  }

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Aucun droit de création : le bouton « + New » lui-même n'a plus d'objet.
  if (visibleItems.length === 0) return null

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 pl-2.5 pr-2 py-1.5 rounded-lg bg-accent text-white text-xs font-medium shadow-sf-accent hover:bg-accent-hover transition-sf"
      >
        <Plus className="w-3.5 h-3.5" />
        {t('topbar.new')}
        <ChevronDown className={`w-3.5 h-3.5 transition-sf ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div data-testid="new-menu" className="absolute right-0 mt-2 w-52 sf-panel py-1.5 z-50">
          {visibleItems.map(({ href, labelKey, Icon }) => (
            <button
              key={href}
              onClick={() => go(href)}
              className="w-full text-left flex items-center gap-2.5 px-3 py-2 text-sm text-gray-700 hover:bg-surface-hover hover:text-gray-900 transition-sf"
            >
              <Icon className="w-4 h-4 text-gray-400" />
              {t(labelKey)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
