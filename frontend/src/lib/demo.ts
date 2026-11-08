/** Mode démo (§II) — détecte un refus serveur « compte démo » (403 code `demo_blocked`).
 * L'intercepteur axios affiche déjà un toast global localisé ; les composants doivent donc
 * TAIRE leur propre message d'erreur quand `isDemoBlocked(err)` est vrai (pas de double message). */
export function isDemoBlocked(err: unknown): boolean {
  const e = err as { response?: { status?: number; data?: { detail?: string } } }
  return e?.response?.status === 403 && e?.response?.data?.detail === 'demo_blocked'
}

/** Déclenche le toast « compte démo, action impossible » pour une interaction LOCALE gatée côté
 * client (ex. bouton upload, champ date d'embargo) qui n'atteint jamais le serveur. */
export function fireDemoToast(): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('sf-demo-blocked'))
}
