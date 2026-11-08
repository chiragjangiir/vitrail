import axios from 'axios'

const BASE_URL = `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/api/v1`

const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined' && !config.headers.Authorization) {
    const token = localStorage.getItem('sf_access_token')
    if (token) config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let isRefreshing = false
let failedQueue: Array<{ resolve: (v: string) => void; reject: (e: unknown) => void }> = []

function processQueue(error: unknown, token: string | null) {
  failedQueue.forEach(({ resolve, reject }) => (error ? reject(error) : resolve(token!)))
  failedQueue = []
}

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const orig = error.config
    // Mode démo : écriture bloquée par le serveur (§II) → SEUL le toast « compte démo »
    // s'affiche. On ne REJETTE PAS l'erreur : un reject ferait tirer les ~60 onError
    // locaux (messages rouges dans les drawers) en plus du toast. Promesse jamais
    // résolue ; DemoMode purge le MutationCache (~400 ms) → les useMutation reviennent
    // à idle (pas de spinner fantôme), aucun onError/onSuccess ne tire.
    if (error.response?.status === 403 && error.response?.data?.detail === 'demo_blocked') {
      if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('sf-demo-blocked'))
      return new Promise(() => {})
    }
    const isAuthEndpoint = orig.url?.includes('/auth/login') || orig.url?.includes('/auth/refresh')
    if (error.response?.status !== 401 || orig._retry || isAuthEndpoint) return Promise.reject(error)

    if (isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        failedQueue.push({ resolve, reject })
      }).then((token) => {
        orig.headers.Authorization = `Bearer ${token}`
        return api(orig)
      })
    }

    orig._retry = true
    isRefreshing = true

    const refreshToken = typeof window !== 'undefined' ? localStorage.getItem('sf_refresh_token') : null
    if (!refreshToken) {
      isRefreshing = false
      clearAuthAndRedirect()
      return Promise.reject(error)
    }

    try {
      const { data } = await axios.post(`${BASE_URL}/auth/refresh`, { refresh_token: refreshToken })
      localStorage.setItem('sf_access_token', data.access_token)
      // NE PAS poser de header par défaut collant (api.defaults.headers.common) : il survivrait à
      // un logout/login → requêtes émises avec l'ANCIEN token (fuite d'identité cross-user). Le
      // token courant est toujours lu depuis localStorage par l'intercepteur de requête ci-dessus ;
      // la requête rejouée et les requêtes en file reçoivent le token explicitement (orig.headers).
      processQueue(null, data.access_token)
      orig.headers.Authorization = `Bearer ${data.access_token}`
      return api(orig)
    } catch (refreshError) {
      processQueue(refreshError, null)
      clearAuthAndRedirect()
      return Promise.reject(refreshError)
    } finally {
      isRefreshing = false
    }
  }
)

function clearAuthAndRedirect() {
  if (typeof window === 'undefined') return
  localStorage.removeItem('sf_access_token')
  localStorage.removeItem('sf_refresh_token')
  // Purge tout header d'auth résiduel sur l'instance axios (défense : aucune requête ne doit
  // repartir avec un token périmé). Le rechargement complet ci-dessous réinitialise de toute
  // façon l'ensemble des singletons (store, cache React Query, defaults axios).
  delete api.defaults.headers.common.Authorization
  window.location.href = '/login'
}

export default api
