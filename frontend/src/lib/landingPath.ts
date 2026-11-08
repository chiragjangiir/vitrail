/**
 * Première page RÉELLEMENT utilisable par l'utilisateur.
 *
 * Pourquoi ça existe : après connexion, tout le monde atterrissait sur
 * `/dashboard`. Or ses données sont gatées org-admin. Un rôle métier y voyait
 * donc des cartes vides, des compteurs à « — » et surtout des affirmations
 * FAUSSES — « No players yet », « No media yet » — alors que l'organisation a
 * bien des players et des médias : l'API répondait 403 et l'UI interprétait
 * l'absence de données comme un parc vide. Constaté par Ed le 2026-07-20.
 *
 * On envoie donc chacun vers la première surface qu'il peut lire, dans un ordre
 * qui suit son métier. Le profil ferme la marche : il est accessible à tous, donc
 * la fonction renvoie toujours quelque chose.
 *
 * ⚠️ Doit rester ALIGNÉE sur les `perm` de la barre latérale (Sidebar.tsx) :
 * envoyer quelqu'un sur une page absente de son menu serait aussi déroutant que
 * le tableau de bord vide qu'on corrige ici.
 */
const ORDER: { path: string; perm: string }[] = [
  { path: '/approvals', perm: 'approvals:review' },
  { path: '/campaigns', perm: 'campaigns:read' },
  { path: '/schedules', perm: 'schedules:read' },
  { path: '/events', perm: 'events:read' },
  { path: '/playlists', perm: 'playlists:read' },
  { path: '/media', perm: 'media:read' },
  { path: '/templates', perm: 'templates:read' },
  { path: '/audio-baskets', perm: 'audio_baskets:read' },
  { path: '/vod', perm: 'vod:read' },
  { path: '/players', perm: 'players:read' },
  { path: '/reports/executive', perm: 'reports:read' },
]

export function landingPath(opts: {
  isAdvertiser?: boolean
  isSuperAdmin?: boolean
  isAdmin: boolean
  permissions?: string[]
}): string {
  // Un compte annonceur n'a rien à faire dans le CMS (S7 B2).
  if (opts.isAdvertiser) return '/portal'
  // Super-admin : sa surface est la CONSOLE DE PROVISIONNEMENT, pas un tableau de
  // bord. Le dashboard est scopé à `id_org`, or son rattachement à une organisation
  // n'est qu'une formalité de schéma (cf. scripts/create_super_admin.py) : il y
  // verrait les chiffres d'une marque arbitraire comme s'ils étaient les siens —
  // le même mensonge d'affichage que ce fichier corrige pour les rôles métier.
  if (opts.isSuperAdmin) return '/settings/orgs'
  // Org-admin : le tableau de bord lui est destiné et fonctionne.
  if (opts.isAdmin) return '/dashboard'
  const perms = opts.permissions ?? []
  return ORDER.find((e) => perms.includes(e.perm))?.path ?? '/settings/profile'
}

export default landingPath
