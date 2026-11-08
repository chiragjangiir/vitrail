'use client'

/**
 * Tampon global des dernières erreurs JS (pour les joindre automatiquement à un retour).
 * S'installe une seule fois côté navigateur (window.onerror + unhandledrejection) et
 * conserve les N dernières erreurs sous forme de chaînes courtes.
 */

const MAX = 10
const buffer: string[] = []
let installed = false

function push(msg: string) {
  if (!msg) return
  buffer.push(msg.slice(0, 500))
  if (buffer.length > MAX) buffer.shift()
}

export function installErrorBuffer() {
  if (installed || typeof window === 'undefined') return
  installed = true
  window.addEventListener('error', (e) => {
    const where = e.filename ? ` (${e.filename}:${e.lineno ?? 0})` : ''
    push(`${e.message}${where}`)
  })
  window.addEventListener('unhandledrejection', (e) => {
    const r = (e as PromiseRejectionEvent).reason
    push(`Unhandled rejection: ${typeof r === 'string' ? r : (r?.message ?? String(r))}`)
  })
}

export function getRecentErrors(): string[] {
  return [...buffer]
}
