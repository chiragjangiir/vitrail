/**
 * Durée en millisecondes → libellé compact pour l'affichage : « 42s », « 3m20s »,
 * « 2h05m » (au-delà de l'heure, les secondes n'apportent rien — cas des paniers
 * musicaux qui totalisent plusieurs heures). Affichage seulement : aucun aller-retour
 * vers le serveur ne passe par ici (cf. lib/eventDuration.ts pour la saisie).
 */
export function formatMs(ms: number | null | undefined): string {
  if (!ms) return '—'
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m${s % 60}s`
  return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`
}
