'use client'

// S7 B2 — layout du PORTAIL ANNONCEUR : chrome minimal white-label (branding
// rapports §24.3 : barre couleur, logo, nom org), SANS la sidebar ni les widgets
// du CMS. Auth commune (décision Ed) : guard = token requis + compte annonceur ;
// un retailer qui atterrit ici est renvoyé vers le CMS.

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Globe, HelpCircle, LogOut, Megaphone } from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import api from '@/lib/api'
import DemoMode from '@/components/layout/DemoMode'
import DemoTips, { resetDismissedTips } from '@/components/layout/DemoTips'
import PortalDecisionsBell from '@/components/layout/PortalDecisionsBell'
import type { UserRead } from '@/types/api'

// Langues de l'interface (mêmes 5 locales que le profil CMS)
const LOCALES = [
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'Français' },
  { code: 'es', label: 'Español' },
  { code: 'pt', label: 'Português' },
  { code: 'de', label: 'Deutsch' },
]

interface PortalBranding {
  org_name: string
  advertiser_name: string | null
  primary_color: string
  report_title: string | null
  logo_url: string | null
}

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations('portal')
  const { accessToken, user, refreshToken, roles, setAuth, clearAuth, _hasHydrated } = useAuthStore()
  const router = useRouter()
  const qc = useQueryClient()
  const isAdvertiser = !!user?.id_advertiser

  // Choix de langue (5 locales) — même mécanique que le profil CMS : PATCH /users/me
  // (whitelisté pour un compte démo) + cookie via setAuth + reload pour appliquer.
  const changeLocale = useMutation({
    mutationFn: (locale: string) =>
      api.patch<UserRead>('/users/me', { locale }).then((r) => r.data),
    onSuccess: (updated) => {
      if (accessToken && refreshToken) {
        setAuth(updated, accessToken, refreshToken, roles, updated.locale)
      }
      window.location.reload()
    },
  })

  useEffect(() => {
    if (!_hasHydrated) return
    if (!accessToken) router.replace('/login')
    else if (!isAdvertiser) router.replace('/dashboard')
  }, [accessToken, isAdvertiser, _hasHydrated, router])

  const { data: branding } = useQuery<PortalBranding>({
    queryKey: ['portal-branding'],
    queryFn: () => api.get<PortalBranding>('/portal/branding').then((r) => r.data),
    enabled: !!accessToken && isAdvertiser,
    staleTime: 5 * 60 * 1000,
  })

  const logout = async () => {
    try { await api.post('/auth/revoke', { refresh_token: refreshToken }) } catch { /* */ }
    clearAuth()
    qc.clear()
    delete api.defaults.headers.common.Authorization
    window.location.href = '/login'
  }

  if (!_hasHydrated || !accessToken || !isAdvertiser) return null

  return (
    <div className="h-screen overflow-hidden bg-canvas flex flex-col relative">
      {/* Fond dot-grid (cohérence avec le CMS) — fixe, sous le contenu */}
      <div
        className="sf-dotted fixed inset-0 z-0 pointer-events-none opacity-[0.35]"
        style={{
          maskImage: 'linear-gradient(180deg, rgba(0,0,0,0.9), transparent 35%, transparent 65%, rgba(0,0,0,0.6))',
          WebkitMaskImage: 'linear-gradient(180deg, rgba(0,0,0,0.9), transparent 35%, transparent 65%, rgba(0,0,0,0.6))',
        }}
        aria-hidden="true"
      />
      {/* Aurora ambiante (Mission Control) — discrète, sous le contenu */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-30 overflow-hidden" aria-hidden="true">
        <div className="sf-aurora" />
      </div>
      {/* Compte annonceur DÉMO : bannière lecture seule + bulles d'infos contextuelles */}
      <DemoMode />
      {/* Barre white-label (même code couleur que la page /share) */}
      <div className="h-1.5 w-full relative z-10" style={{ background: branding?.primary_color ?? '#2563EB' }} />
      {/* ⚠️ z-30 et non z-10 : l'en-tête porte des menus DÉROULANTS (cloche des
          décisions, sélecteur de langue) rendus en `absolute`. Leur `z-50` ne
          vaut qu'à l'INTÉRIEUR du contexte d'empilement créé ici par
          `relative z-10` — il ne les fait donc pas passer au-dessus du `<main>`,
          lui aussi `z-10` et PLUS BAS dans le DOM, donc peint par-dessus.
          Conséquence vécue : un annonceur cliquait une décision de sa cloche et
          touchait la page en dessous (l'en-tête de section interceptait le clic).
          Constaté par un test e2e le 2026-07-20. */}
      <header className="bg-canvas/60 backdrop-blur-xl border-b border-white/5 relative z-30 shrink-0">
        <div className="w-[90%] max-w-[2100px] mx-auto px-6 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            {branding?.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={branding.logo_url} alt="" className="h-9 w-auto object-contain" />
            ) : (
              <div className="w-9 h-9 rounded-lg flex items-center justify-center"
                   style={{ background: branding?.primary_color ?? '#2563EB' }}>
                <Megaphone className="w-5 h-5 text-white" />
              </div>
            )}
            <div className="min-w-0">
              {/* Titre = NOM DE L'ORG (retour Ed #1 : report_title = titre des rapports
                  white-label §24.3, ex. « Rapport Direction » — pas le titre du portail) */}
              <p className="text-sm font-semibold text-gray-900 truncate">
                {branding?.org_name || ''}
              </p>
              <p className="text-xs text-gray-400 truncate">{t('subtitle')}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {branding?.advertiser_name && (
              <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-accent/10 text-accent-hover border border-accent/20">
                {branding.advertiser_name}
              </span>
            )}
            {/* Cloche des décisions du retailer (Ed #8) */}
            <PortalDecisionsBell />
            {/* Réafficher les bulles d'aide fermées (comptes classiques ; un démo ne peut pas les fermer) */}
            <button
              onClick={resetDismissedTips}
              className="p-1.5 text-gray-400 hover:text-gray-700 transition-sf"
              title={t('show_tips')}
            >
              <HelpCircle className="w-4 h-4" />
            </button>
            <div className="relative inline-flex items-center">
              <Globe className="absolute left-2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
              <select
                value={user?.locale ?? 'en'}
                onChange={(e) => changeLocale.mutate(e.target.value)}
                disabled={changeLocale.isPending}
                aria-label={t('language')}
                className="pl-7 pr-2 py-1.5 text-xs border border-gray-200 rounded-lg bg-surface text-gray-600 focus:outline-none focus:ring-2 focus:ring-accent/40"
              >
                {LOCALES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
            </div>
            <button
              onClick={logout}
              className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-sf"
            >
              <LogOut className="w-4 h-4" />{t('logout')}
            </button>
          </div>
        </div>
      </header>

      {/* Zone bornée (pas de scroll de page entière) : chaque page gère son propre
          défilement. La home remplit exactement la hauteur (scroll INTERNE aux campagnes) ;
          les pages form/rapport défilent dans ce conteneur `overflow-y-auto`. */}
      <main className="flex-1 relative z-10 min-h-0">
        <div className="w-[90%] max-w-[2100px] mx-auto px-6 py-6 h-full overflow-y-auto">{children}</div>
      </main>

      <footer className="py-2 text-center text-[11px] text-gray-400 shrink-0 relative z-10">
        {t('footer')}
      </footer>
      <DemoTips />
    </div>
  )
}
