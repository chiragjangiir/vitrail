'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { clsx } from 'clsx'
import { X } from 'lucide-react'

interface DrawerProps {
  open: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  width?: string
}

export default function Drawer({
  open,
  onClose,
  title,
  children,
  width = 'w-[480px]',
}: DrawerProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Portail : `document` n'existe pas au rendu serveur.
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])
  if (!mounted) return null

  /**
   * 🔑 PORTAIL VERS `document.body` — indispensable, pas décoratif (trouvé le 2026-07-29 par
   * un test dont le clic était refusé).
   *
   * `DashboardShell` enferme les pages dans un `<div class="relative z-10">` et monte
   * `<DemoTips />` en FRÈRE, après. Un tiroir rendu depuis une page vivait donc DANS ce
   * contexte d'empilement : **aucun `z-index` interne n'en sort**, si bien que la bulle
   * d'aide (`fixed bottom-20 right-5 z-30`) passait AU-DESSUS du tiroir et **interceptait
   * les clics** sur tout ce qui se trouve en bas à droite — boutons de pied compris.
   *
   * Exactement le défaut qu'Ed avait signalé sur la visionneuse (« les boutons ne sont pas
   * cliquables »), corrigé là-bas de la même façon. Ici la correction vaut pour **tous** les
   * tiroirs du produit d'un seul coup, puisque `Drawer` est la brique partagée.
   */
  return createPortal(
    <>
      {/* Backdrop */}
      <div
        className={clsx(
          'fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px] transition-opacity duration-150',
          open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        )}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx(
          'fixed inset-y-0 right-0 z-50 flex flex-col bg-[#0C0D12] border-l border-white/5 shadow-[-10px_0_30px_rgba(0,0,0,0.5)] transition-transform duration-150',
          width,
          open ? 'translate-x-0' : 'translate-x-full'
        )}
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <h2 className="text-[15px] font-semibold tracking-tight text-gray-900">{title}</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 text-gray-400 hover:text-gray-800 transition-sf"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </>,
    document.body,
  )
}
