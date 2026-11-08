import api from '@/lib/api'

/** Types pointeurs sans fichier téléchargeable (feed / page web / entrée HDMI). */
const NON_DOWNLOADABLE = new Set(['feed_display', 'url_display', 'hdmi_input'])

/** Un média est téléchargeable s'il a un fichier (≠ pointeur feed/page web). */
export function isMediaDownloadable(mediaType: string): boolean {
  return !NON_DOWNLOADABLE.has(mediaType)
}

/**
 * Récupère une URL pré-signée de téléchargement (Content-Disposition attachment + nom
 * d'origine fixés côté backend/MinIO) puis déclenche le téléchargement navigateur.
 */
export async function downloadMedia(idMedia: number): Promise<void> {
  try {
    const { data } = await api.get<{ url: string }>(`/media/${idMedia}/download`)
    const a = document.createElement('a')
    a.href = data.url
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
  } catch {
    // Erreur déjà signalée par l'intercepteur (ex. toast « compte démo » sur un 403 demo_blocked).
  }
}
