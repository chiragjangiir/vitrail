import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { jwtDecode } from 'jwt-decode'
import type { UserRead } from '@/types/api'

/**
 * Rôles dérivés du token d'accès COURANT (localStorage, mis à jour à chaque refresh).
 * C'est la source de vérité serveur pour le gating (menus). On NE se fie pas au tableau
 * `roles` persisté dans le store : il date du dernier LOGIN et devient périmé si un rôle a
 * été (dé)assigné depuis (un refresh de token ne met pas à jour le store). Retourne null si
 * pas de token / illisible → l'appelant retombe alors sur les rôles persistés.
 */
function rolesFromActiveToken(): string[] | null {
  if (typeof window === 'undefined') return null
  const token = localStorage.getItem('sf_access_token')
  if (!token) return null
  try {
    const payload = jwtDecode<{ roles?: string[] }>(token)
    return Array.isArray(payload.roles) ? payload.roles : []
  } catch {
    return null
  }
}

/** SSR-safe localStorage wrapper — returns no-op storage on the server. */
const safeLocalStorage = createJSONStorage(() => {
  if (typeof window === 'undefined') {
    return {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    }
  }
  return localStorage
})

interface AuthState {
  user: UserRead | null
  accessToken: string | null
  refreshToken: string | null
  roles: string[]
  _hasHydrated: boolean
  setHasHydrated: (v: boolean) => void
  setAuth: (user: UserRead, accessToken: string, refreshToken: string, roles: string[], locale: string) => void
  clearAuth: () => void
  hasRole: (role: string) => boolean
  isAdmin: () => boolean
  /**
   * Droit effectif `module:operation` de l'utilisateur courant.
   *
   * ⚠️ CONFORT D'AFFICHAGE UNIQUEMENT — sert à masquer les entrées de menu et
   * les boutons qui échoueraient de toute façon en 403. L'autorisation réelle
   * est côté serveur (`require_permission` / `require_org_admin`) : trafiquer
   * ce store ne donne accès à rien.
   *
   * Les org/super-admins passent d'office (ils portent tout le catalogue).
   */
  can: (perm: string) => boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      roles: [],
      _hasHydrated: false,
      setHasHydrated: (v) => set({ _hasHydrated: v }),

      setAuth: (user, accessToken, refreshToken, roles, locale) => {
        if (typeof window !== 'undefined') {
          localStorage.setItem('sf_access_token', accessToken)
          localStorage.setItem('sf_refresh_token', refreshToken)
          document.cookie = `locale=${locale}; path=/; max-age=31536000; SameSite=Lax`
        }
        set({ user, accessToken, refreshToken, roles })
      },

      clearAuth: () => {
        if (typeof window !== 'undefined') {
          localStorage.removeItem('sf_access_token')
          localStorage.removeItem('sf_refresh_token')
        }
        set({ user: null, accessToken: null, refreshToken: null, roles: [] })
      },

      // Gating autoritaire sur le token courant (vérité serveur), repli sur les rôles persistés.
      hasRole: (role) => (rolesFromActiveToken() ?? get().roles).includes(role),

      isAdmin: () =>
        (rolesFromActiveToken() ?? get().roles).some(
          (r) => r === 'CMS_SUPER_ADMIN' || r === 'CMS_ORG_ADMIN'
        ),

      can: (perm) => {
        if (get().isAdmin()) return true
        // Tant que /users/me n'a pas répondu, `permissions` est indéfini : on
        // n'affiche RIEN plutôt que de faire clignoter des menus qui vont
        // disparaître (et on ne montre jamais par défaut ce qui est refusé).
        return (get().user?.permissions ?? []).includes(perm)
      },
    }),
    {
      name: 'sf-auth',
      storage: safeLocalStorage,
      partialize: (s) => ({
        user: s.user,
        accessToken: s.accessToken,
        refreshToken: s.refreshToken,
        roles: s.roles,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)
