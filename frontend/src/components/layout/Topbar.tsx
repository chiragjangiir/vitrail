'use client'

import type { ReactNode } from 'react'
import { LogOut, User, Building2, Sparkles, MessageSquarePlus } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@/store/auth'
import { useWidgetPanels } from '@/store/widgets'
import api from '@/lib/api'
import ApprovalsBell from '@/components/layout/ApprovalsBell'
import UpdateBell from '@/components/layout/UpdateBell'
import NewMenu from '@/components/layout/NewMenu'
import GlobalSearch from '@/components/layout/GlobalSearch'

interface TopbarProps {
  title?: string
  children?: ReactNode
}

export default function Topbar({ title, children }: TopbarProps) {
  const t = useTranslations()
  const qc = useQueryClient()
  const { user, refreshToken, clearAuth } = useAuthStore()
  const isSuperAdmin = useAuthStore((s) => s.hasRole('CMS_SUPER_ADMIN'))
  // Déclencheurs des deux panneaux flottants (déplacés des FAB bas-droite vers la
  // topbar — retour Ed 21/07 : les FAB masquaient les boutons d'action des drawers).
  const assistantOpen = useWidgetPanels((s) => s.assistantOpen)
  const feedbackOpen = useWidgetPanels((s) => s.feedbackOpen)
  const toggleAssistant = useWidgetPanels((s) => s.toggleAssistant)
  const toggleFeedback = useWidgetPanels((s) => s.toggleFeedback)

  async function handleLogout() {
    if (refreshToken) {
      try {
        await api.post('/auth/revoke', { refresh_token: refreshToken })
      } catch {
        // silencieux — on déconnecte côté client de toute façon
      }
    }
    clearAuth()
    // Frontière d'auth : on ne se contente pas d'un router.replace (navigation client qui laisse
    // survivre les singletons JS = fuite d'état entre comptes). On purge le cache React Query +
    // tout header d'auth résiduel, puis on force un RECHARGEMENT COMPLET → store, cache et
    // instance axios repartent de zéro pour le prochain login.
    qc.clear()
    delete api.defaults.headers.common.Authorization
    window.location.href = '/login'
  }

  return (
    <header className="h-16 shrink-0 flex items-center gap-4 px-6 bg-canvas/60 backdrop-blur-xl border-b border-white/5 relative z-30">
      <h1 className="text-[15px] font-semibold tracking-tight text-gray-900 shrink-0">{title}</h1>

      {/* Recherche globale — occupe l'espace central */}
      <div className="flex-1 flex justify-center">
        <GlobalSearch />
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {children}
        {/* Raccourcis de creation. MASQUE au super-admin : le menu ne propose que des
            objets d'ORGANISATION (medias, playlists, campagnes, programmations...) dont
            un compte plateforme n'a pas l'usage -- il provisionne des organisations, il
            ne produit pas de contenu. Demande Ed 2026-07-23. */}
        {!isSuperAdmin && <NewMenu />}
        {/* Assistant IA + Retour — déclencheurs déplacés ici (plus de FAB flottant) */}
        <button
          type="button"
          onClick={toggleAssistant}
          title={`${t('assistant.title')} (Ctrl+Shift+A)`}
          aria-label={t('assistant.title')}
          className={`flex h-8 w-8 items-center justify-center rounded-lg transition-sf ${
            assistantOpen ? 'bg-accent/15 text-accent' : 'text-gray-400 hover:bg-white/5 hover:text-accent'
          }`}
        >
          <Sparkles className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={toggleFeedback}
          title={t('feedback.button')}
          aria-label={t('feedback.button')}
          className={`flex h-8 w-8 items-center justify-center rounded-lg transition-sf ${
            feedbackOpen ? 'bg-accent/15 text-accent' : 'text-gray-400 hover:bg-white/5 hover:text-accent'
          }`}
        >
          <MessageSquarePlus className="w-4 h-4" />
        </button>
        {/* Cloche « MAJ serveur disponible » — visible pour l'org-admin exploitant */}
        <UpdateBell />
        {/* Cloche des validations (Ed #7) — visible pour les rôles valideurs */}
        <ApprovalsBell />
        {isSuperAdmin ? (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-300 text-xs font-medium">
            <Building2 className="w-3.5 h-3.5" />
            {t('orgs.platform_admin')}
          </span>
        ) : user?.org_name && (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-accent/10 text-accent text-xs font-medium"
            title={t('nav.organizations')}>
            <Building2 className="w-3.5 h-3.5" />
            {user.org_name}
          </span>
        )}
        {user && (
          <span className="flex items-center gap-2 text-sm text-gray-600">
            <User className="w-4 h-4" />
            {user.full_name ?? user.email}
          </span>
        )}
        <button
          onClick={handleLogout}
          title={t('auth.logout')}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:text-danger rounded hover:bg-red-500/10 transition-sf"
        >
          <LogOut className="w-3.5 h-3.5" />
          {t('auth.logout')}
        </button>
      </div>
    </header>
  )
}
