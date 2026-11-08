'use client'

// Bulles d'infos contextuelles (demandes Ed 2026-07-10, règles v2) :
//  - compte DÉMO (standard ou annonceur) : bulle TOUJOURS affichée, pas de croix —
//    un prospect ne peut pas les perdre.
//  - compte CLASSIQUE (CMS ou portail) : fermable (mémorisé par page en localStorage,
//    persiste entre sessions) + RÉACTIVABLES : bouton « Réafficher les bulles d'aide »
//    (profil CMS / bouton « ? » du header portail) → resetDismissedTips().
// Un seul point d'intégration par shell (DashboardShell + layout /portal).

import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { Lightbulb, Minus, X } from 'lucide-react'
import { useAuthStore } from '@/store/auth'

// Pathname (préfixe le plus LONG gagne) → clé i18n demo.tips.<key>_*
const TIPS: [string, string][] = [
  ['/portal/campaigns/new', 'portal_new'],
  ['/portal/campaigns', 'portal_report'],
  ['/portal', 'portal_home'],
  ['/campaigns/advertisers', 'advertisers'],
  ['/campaigns', 'campaigns'],
  ['/approvals', 'approvals'],
  ['/dashboard', 'dashboard'],
  ['/settings/players/provisioning', 'provisioning'],
  ['/players', 'players'],
  ['/studio', 'studio'],
  ['/promo', 'promo'],
  ['/url-display', 'url_display'],
  ['/feeds', 'feeds'],
  ['/media/tags', 'tags'],
  ['/media', 'media'],
  ['/templates', 'templates'],
  ['/playlists', 'playlists'],
  ['/audio-baskets', 'audio_baskets'],
  ['/schedules', 'schedules'],
  ['/events', 'events'],
  ['/vod', 'vod'],
  ['/sites', 'sites'],
  ['/governance', 'governance'],
  ['/reports', 'reports'],
  ['/settings/iam', 'iam'],
  ['/settings/updates', 'updates'],
  ['/settings/notifications', 'notifications'],
  ['/settings/messaging', 'messaging'],
  ['/settings/ai-keys', 'ai_keys'],
  ['/settings/security', 'security'],
  ['/settings/profile', 'profile'],
]

const STORAGE_PREFIX = 'sf-tip:'
const RESET_EVENT = 'sf-tips-reset'

function tipKeyFor(pathname: string): string | null {
  for (const [prefix, key] of TIPS) {
    if (pathname === prefix || pathname.startsWith(prefix + '/')) return key
  }
  return null
}

/** Réaffiche toutes les bulles fermées (comptes classiques) — profil CMS + « ? » portail. */
export function resetDismissedTips() {
  try {
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith(STORAGE_PREFIX)) localStorage.removeItem(k)
    }
  } catch { /* */ }
  window.dispatchEvent(new CustomEvent(RESET_EVENT))
}

export default function DemoTips() {
  const t = useTranslations('demo')
  const user = useAuthStore((s) => s.user)
  const isDemo = !!user?.is_demo
  const pathname = usePathname()
  const key = tipKeyFor(pathname ?? '')
  const [dismissed, setDismissed] = useState(true)
  // Replié = rangé, pas fermé (cf. le bloc de rendu). Volontairement NON persisté : la bulle
  // réapparaît dépliée à la page suivante, sinon on la « range » une fois et l'aide disparaît.
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    setCollapsed(false)   // changement de page ⇒ nouvelle bulle, dépliée
    if (!key) return
    const readState = () => {
      if (isDemo) { setDismissed(false); return }   // démo : jamais fermée
      try {
        setDismissed(localStorage.getItem(`${STORAGE_PREFIX}${key}`) === '1')
      } catch { setDismissed(false) }
    }
    readState()
    window.addEventListener(RESET_EVENT, readState)
    return () => window.removeEventListener(RESET_EVENT, readState)
  }, [key, isDemo])

  if (!user || !key || dismissed) return null

  const dismiss = () => {
    try { localStorage.setItem(`${STORAGE_PREFIX}${key}`, '1') } catch { /* */ }
    setDismissed(true)
  }

  // 🔑 REPLIABLE (2026-08-10). Le commentaire d'origine affirmait « la bulle ne doit jamais masquer
  // une action » — c'était vrai des TIROIRS (z-50), pas du contenu de la page (z-10) : l'audit de
  // toutes les pages a mesuré 9 éléments réellement irrécupérables sous elle (les liens d'activité
  // du dashboard, les icônes d'édition d'un programme, « Modifier les hypothèses », « Détails »
  // d'un déploiement). Une bulle opaque de 384 x 110 px posée en bas à droite d'une page
  // VERROUILLÉE au viewport ne se contourne pas en faisant défiler : ce qui est dessous est perdu.
  // Repliée, elle occupe la zone déjà réservée aux boutons flottants. ⛔ Replier n'est PAS fermer :
  // le compte démo garde sa visite guidée (aucune croix), il peut seulement la ranger le temps
  // d'un clic — sans quoi « corriger » l'obstruction reviendrait à supprimer l'aide.
  if (collapsed) {
    return (
      <button type="button" onClick={() => setCollapsed(false)} title={t(`tips.${key}_title`)}
        aria-label={t(`tips.${key}_title`)} data-testid="tip-pill"
        className="fixed bottom-20 right-5 z-30 w-10 h-10 rounded-full bg-surface border border-amber-300 dark:border-amber-500/40 shadow-sf-card-hover flex items-center justify-center transition-sf hover:scale-105">
        <Lightbulb className="w-4 h-4 text-amber-600 dark:text-amber-300" />
      </button>
    )
  }

  // z-30 : SOUS les drawers (z-50) et leur voile (z-40) ; bottom-20 : au-dessus des boutons
  // assistant/feedback (bottom-5).
  return (
    // 🔑 `pointer-events-none` sur la CARTE, `auto` sur ses seuls boutons : sans cela, replier
    // n'était qu'un remède que l'utilisateur devait deviner — mesuré après déploiement, l'audit
    // trouvait toujours 22 éléments incliquables, parce que la bulle s'ouvre dépliée. Un clic
    // traverse désormais la bulle et atteint ce qui est dessous ; il ne reste que le masquage
    // VISUEL, que le bouton « Ranger » enlève.
    <div data-testid="tip-bubble"
      className="pointer-events-none fixed bottom-20 right-5 z-30 max-w-sm bg-surface border border-amber-300 dark:border-amber-500/40 rounded-xl shadow-sf-card-hover p-4">
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-amber-100 dark:bg-amber-500/20 flex items-center justify-center shrink-0">
          <Lightbulb className="w-4 h-4 text-amber-600 dark:text-amber-300" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900">{t(`tips.${key}_title`)}</p>
          <p className="text-xs text-gray-500 mt-1">{t(`tips.${key}_text`)}</p>
        </div>
        {/* `auto` sur les BOUTONS, pas sur leur conteneur : sinon la gouttière entre eux
            continuerait d'avaler des clics destinés à la page. */}
        <div className="flex shrink-0 items-center gap-0.5">
          <button onClick={() => setCollapsed(true)} data-testid="tip-collapse"
                  className="pointer-events-auto p-1 text-gray-300 hover:text-gray-600 transition-sf"
                  title={t('tip_collapse')} aria-label={t('tip_collapse')}>
            <Minus className="w-4 h-4" />
          </button>
          {/* Compte démo : pas de croix — la bulle fait partie de la visite guidée */}
          {!isDemo && (
            <button onClick={dismiss} className="pointer-events-auto p-1 text-gray-300 hover:text-gray-600 transition-sf"
                    title={t('tip_dismiss')} aria-label={t('tip_dismiss')}>
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
