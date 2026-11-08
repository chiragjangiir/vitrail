'use client'

import { useAuthStore } from '@/store/auth'

/**
 * Affiche ses enfants seulement si l'utilisateur détient le droit demandé.
 *
 * ⚠️ **CONFORT D'AFFICHAGE, JAMAIS UNE SÉCURITÉ.** L'autorisation réelle est
 * entièrement côté serveur (`require_permission` / `require_org_admin`) : un
 * front trafiqué ne gagne aucun accès. On masque parce qu'un bouton qui mène
 * systématiquement à un 403 est un défaut de produit — constat Ed 2026-07-20 :
 * un compte Approbateur voyait tout le CMS et pouvait remplir des formulaires
 * (« seuils d'alerte ») dont l'enregistrement était refusé sans le dire.
 *
 * Usage :
 *   <Can perm="media:create"><Button>Importer</Button></Can>
 *   <Can admin><Button>Réglages</Button></Can>
 *
 * `admin` correspond aux surfaces gatées côté serveur par le booléen
 * `require_org_admin` plutôt que par une permission granulaire (modules
 * users/groups/org_settings/api_keys et une partie de players/campaigns/
 * analytics). À remplacer par `perm` quand ces modules passeront au RBAC.
 */
export default function Can({
  perm,
  admin = false,
  fallback = null,
  children,
}: {
  perm?: string
  admin?: boolean
  /** Rendu de remplacement quand le droit manque (défaut : rien). */
  fallback?: React.ReactNode
  children: React.ReactNode
}) {
  const allowed = useCan(perm, admin)
  return <>{allowed ? children : fallback}</>
}

/** Variante hook, pour les cas où le masquage ne porte pas sur un sous-arbre JSX. */
export function useCan(perm?: string, admin = false): boolean {
  const isAdmin = useAuthStore((s) => s.isAdmin())
  // S'abonner à `permissions` (et pas seulement appeler `can`) rend le composant
  // réactif à l'arrivée de /users/me après le rendu initial.
  const permissions = useAuthStore((s) => s.user?.permissions)
  if (admin) return isAdmin
  if (!perm) return true
  return isAdmin || (permissions ?? []).includes(perm)
}
