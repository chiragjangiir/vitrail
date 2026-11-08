'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Lock } from 'lucide-react'
import { useAuthStore } from '@/store/auth'

/**
 * Nudge « lecture seule » — GÉNÉRIQUE pour tout rôle sans droit d'écriture.
 *
 * POURQUOI
 * Masquer les boutons de création/suppression (via `Can`) ne suffit pas : un rôle
 * en lecture peut ouvrir un drawer pour CONSULTER (ex. l'Approbateur regarde une
 * playlist) et y trouver des champs éditables. Il tape, rien ne s'enregistre, et
 * le message d'erreur — s'il y en a un — arrive après coup, côté serveur. On veut
 * le même confort que le mode démo : capter l'interaction et afficher un message
 * en bas de page, sans jamais laisser croire qu'une modification a été prise.
 *
 * COMMENT (aucune modification par drawer, un seul attribut)
 * On marque une zone éditable d'un attribut `data-write-perm="module:op"`. Cet
 * unique écouteur global, en phase CAPTURE, intercepte toute interaction avec un
 * CHAMP éditable (input/textarea/select/contenteditable) ou un bouton marqué
 * `data-write-action` à l'intérieur d'une telle zone, POUR PEU que l'utilisateur
 * ne détienne pas la permission. Il bloque l'action et affiche le message. La
 * navigation (onglets, fermeture, défilement, boutons non marqués) reste libre.
 *
 * VERROU NON LIÉ À LA PERMISSION (`data-write-locked`)
 * Certaines zones sont en lecture seule alors que l'utilisateur DÉTIENT la permission :
 * contenu gouverné §XVIII (playlist/média d'un nœud qu'il n'administre pas — il le voit
 * pour comprendre ce qui passe au-dessus de lui, mais le serveur refuse toute mutation).
 * Une zone portant `data-write-locked` est bloquée quels que soient les droits, avec un
 * message distinct : « ce n'est pas votre rôle qui bloque, c'est le propriétaire ».
 *
 * ⚠️ CONFORT D'AFFICHAGE, JAMAIS UNE SÉCURITÉ. L'écriture est refusée côté serveur
 * de toute façon (`require_permission` / `user_can_edit_node`). Ceci évite juste
 * l'illusion d'éditer. Un admin ou un porteur de la permission passe sans aucune gêne.
 */

const EDIT_SELECTOR =
  'input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=reset]),' +
  'textarea,select,[contenteditable="true"],[data-write-action]'

// Touches qui ne MODIFIENT pas la valeur : on les laisse passer (navigation, copie).
const NAV_KEYS = new Set([
  'Tab', 'Escape', 'Enter', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Home', 'End', 'PageUp', 'PageDown', 'Shift', 'Control', 'Alt', 'Meta',
])

export default function ReadOnlyNudge() {
  const t = useTranslations()
  const permissions = useAuthStore((s) => s.user?.permissions)
  const isAdmin = useAuthStore((s) => s.isAdmin())
  // null = pas de message ; 'perm' = rôle insuffisant ; 'locked' = zone verrouillée
  // par son propriétaire (contenu gouverné) alors que la permission est détenue.
  const [toast, setToast] = useState<null | 'perm' | 'locked'>(null)

  // Refs pour que l'écouteur (stable) lise toujours les droits courants sans se
  // ré-attacher à chaque rendu.
  const permsRef = useRef<string[] | undefined>(permissions)
  const adminRef = useRef(isAdmin)
  permsRef.current = permissions
  adminRef.current = isAdmin

  useEffect(() => {
    const can = (perm: string) => {
      if (adminRef.current) return true
      const perms = permsRef.current
      // Tant que /users/me n'a pas répondu (perms indéfini), on NE bloque PAS : un
      // éditeur légitime ne doit jamais être gêné pendant l'hydratation.
      if (perms === undefined) return true
      return perms.includes(perm)
    }

    const handle = (e: Event) => {
      const el = e.target as HTMLElement | null
      if (!el || typeof el.closest !== 'function') return
      const region = el.closest('[data-write-perm],[data-write-locked]')
      if (!region) return
      const locked = region.hasAttribute('data-write-locked')
      if (!locked) {
        const perm = region.getAttribute('data-write-perm') || ''
        if (can(perm)) return // droit d'écrire → on ne gêne pas
      }
      if (!el.closest(EDIT_SELECTOR)) return // interaction avec du non-éditable (texte, onglet, défilement) → OK

      // Au clavier, on laisse la navigation et la copie (Ctrl/Cmd+C/A/X).
      if (e.type === 'keydown') {
        const ke = e as KeyboardEvent
        if (NAV_KEYS.has(ke.key)) return
        if ((ke.ctrlKey || ke.metaKey) && ['c', 'a', 'x'].includes(ke.key.toLowerCase())) return
      }

      e.preventDefault()
      e.stopPropagation()
      setToast(locked ? 'locked' : 'perm')
    }

    // Phase capture : on précède les gestionnaires React (montés à la racine).
    const opts = { capture: true }
    document.addEventListener('pointerdown', handle, opts)
    document.addEventListener('keydown', handle, opts)
    document.addEventListener('click', handle, opts)
    return () => {
      document.removeEventListener('pointerdown', handle, opts)
      document.removeEventListener('keydown', handle, opts)
      document.removeEventListener('click', handle, opts)
    }
  }, [])

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(id)
  }, [toast])

  if (!toast) return null
  return (
    // ⚠️ Fond en HEX explicite : la rampe de gris est INVERSÉE en thème sombre
    // (bg-gray-900 = clair) → un fond sombre garanti + texte blanc, lisible.
    <div className="fixed bottom-6 left-1/2 z-[100] flex -translate-x-1/2 items-center gap-2 rounded-lg border border-white/10 bg-[#1A1D2B] px-4 py-2.5 text-sm text-white shadow-lg ring-1 ring-black/40">
      <Lock className="h-4 w-4 text-amber-400" />
      {t(toast === 'locked' ? 'readonly.locked' : 'readonly.blocked')}
    </div>
  )
}
