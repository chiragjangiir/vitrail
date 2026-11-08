'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { KeyRound } from 'lucide-react'
import axios from 'axios'
import { jwtDecode } from 'jwt-decode'
import { useAuthStore } from '@/store/auth'
import api from '@/lib/api'
import { landingPath } from '@/lib/landingPath'
import { syncThemeFromServer } from '@/lib/useTheme'
import { getQueryClient } from '@/lib/query-client'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import type { TokenResponse, UserRead } from '@/types/api'

type Step = 'credentials' | 'totp' | 'setup_required' | 'enrol' | 'enrolled'

interface TotpSetup {
  secret: string
  qr_b64: string
  backup_codes: string[]
}

interface JwtPayload {
  sub: string
  org: number
  roles: string[]
  locale: string
  type: string
}

export default function LoginPage() {
  const t = useTranslations()
  const router = useRouter()
  const { setAuth } = useAuthStore()

  const [step, setStep] = useState<Step>('credentials')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // Enrôlement 2FA : jeton à portée réduite délivré par /auth/login à un compte à qui le
  // second facteur est obligatoire et qui ne l'a pas encore. Sans ce parcours, un tel compte
  // ne pouvait RIEN faire : l'écran affichait « configurez la 2FA » et un bouton Retour.
  const [enrolmentToken, setEnrolmentToken] = useState('')
  const [setup, setSetup] = useState<TotpSetup | null>(null)

  async function submitCredentials(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      const { data } = await api.post<TokenResponse>('/auth/login', { email, password })
      await finalizeLogin(data)
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const status = err.response?.status
        const detail = err.response?.data?.detail

        if (status === 401 && typeof detail === 'string' && detail.includes('TOTP')) {
          setStep('totp')
        } else if (status === 403 && detail?.force_2fa_setup) {
          setEnrolmentToken(detail.enrolment_token ?? '')
          setStep('setup_required')
        } else if (typeof detail === 'string') {
          setError(detail)
        } else {
          setError(t('auth.login_error'))
        }
      } else {
        setError(t('common.error'))
      }
    } finally {
      setLoading(false)
    }
  }

  async function submitTotp(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      const { data } = await api.post<TokenResponse>('/auth/login', {
        email,
        password,
        totp_code: totpCode,
      })
      await finalizeLogin(data)
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail
        setError(typeof detail === 'string' ? detail : t('auth.login_error'))
      } else {
        setError(t('common.error'))
      }
    } finally {
      setLoading(false)
    }
  }

  /**
   * Les deux appels d'enrôlement passent par axios NU, pas par l'instance `api`.
   *
   * Deux raisons, toutes deux vécues ailleurs : l'intercepteur de requête injecterait le
   * jeton d'accès résiduel du localStorage à la place du jeton d'enrôlement ; et
   * l'intercepteur de réponse, sur un 401, tenterait un rafraîchissement puis appellerait
   * `clearAuthAndRedirect()` — c'est-à-dire qu'il quitterait l'écran de connexion au moment
   * précis où l'utilisateur est en train de s'y enrôler.
   */
  const enrolHeaders = { headers: { Authorization: `Bearer ${enrolmentToken}` } }

  async function startEnrolment() {
    setLoading(true)
    setError('')
    try {
      const { data } = await axios.post<TotpSetup>(
        `${api.defaults.baseURL}/auth/totp/setup`, null, enrolHeaders,
      )
      setSetup(data)
      setTotpCode('')
      setStep('enrol')
    } catch {
      setError(t('auth.setup_2fa_error'))
    } finally {
      setLoading(false)
    }
  }

  async function submitEnrolment(e: React.FormEvent) {
    e.preventDefault()
    if (!setup) return
    setLoading(true)
    setError('')
    try {
      await axios.post(
        `${api.defaults.baseURL}/auth/totp/verify`,
        { secret: setup.secret, code: totpCode },
        enrolHeaders,
      )
      setTotpCode('')
      setStep('enrolled')
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null
      setError(typeof detail === 'string' ? detail : t('auth.setup_2fa_error'))
    } finally {
      setLoading(false)
    }
  }

  async function finalizeLogin(tokens: TokenResponse) {
    // Défense : repartir d'un cache React Query vide (si on atteint /login sans rechargement
    // complet, le cache pourrait contenir les données d'un compte précédent). Le token explicite
    // ci-dessous garantit que /users/me est résolu pour le NOUVEAU compte, jamais un défaut résiduel.
    getQueryClient().clear()
    const payload = jwtDecode<JwtPayload>(tokens.access_token)
    const { data: me } = await api.get<UserRead>('/users/me', {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    })
    // Réconcilie le thème depuis le serveur (cross-device) avant de naviguer.
    syncThemeFromServer(me.theme)
    setAuth(me, tokens.access_token, tokens.refresh_token, payload.roles, tokens.locale)
    // Redirect par rôle (S7 B2, décision Ed : auth commune) : un compte annonceur
    // atterrit sur SON portail ; un rôle métier sur sa première surface UTILISABLE
    // (le tableau de bord est gaté org-admin — y envoyer un approbateur lui montrait
    // un écran vide affirmant « aucun player », cf. `landingPath`).
    router.replace(landingPath({
      isAdvertiser: !!me.id_advertiser,
      isSuperAdmin: payload.roles.includes('CMS_SUPER_ADMIN'),
      isAdmin: payload.roles.some((r) => r === 'CMS_ORG_ADMIN' || r === 'CMS_SUPER_ADMIN'),
      permissions: me.permissions,
    }))
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm">
        {/* Marque : logo Vitrail + nom. */}
        <div className="flex items-center justify-center gap-3 mb-8">
          {/* eslint-disable-next-line @next/next/no-img-element -- SVG statique, rien à optimiser */}
          <img src="/brand/vitrail-logo.svg" alt="" aria-hidden width={48} height={48} />
          <span className="text-xl font-semibold text-gray-900">Vitrail</span>
        </div>

        <div className="bg-surface rounded-xl border border-gray-200 shadow-sm p-7">
          {step === 'credentials' && (
            <>
              <h1 className="text-lg font-semibold text-gray-900 mb-5">{t('auth.login')}</h1>
              {/* autoComplete désactivé : on veut les champs VIDES à l'ouverture (pas de
                  pré-remplissage navigateur). new-password sur le mot de passe = l'astuce la
                  plus fiable pour empêcher Chrome/Edge d'injecter un identifiant enregistré. */}
              <form onSubmit={submitCredentials} className="space-y-4" autoComplete="off">
                <Input
                  label={t('auth.email')}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="off"
                  required
                />
                <Input
                  label={t('auth.password')}
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                />
                {error && <p className="text-sm text-danger">{error}</p>}
                <Button type="submit" loading={loading} className="w-full mt-2">
                  {t('auth.login')}
                </Button>
              </form>
            </>
          )}

          {step === 'totp' && (
            <>
              <div className="flex items-center gap-3 mb-5">
                <div className="w-9 h-9 rounded-lg bg-accent/10 dark:bg-blue-500/15 flex items-center justify-center">
                  <KeyRound className="w-4 h-4 text-info" />
                </div>
                <h1 className="text-base font-semibold text-gray-900">{t('auth.totp_code')}</h1>
              </div>
              <form onSubmit={submitTotp} className="space-y-4">
                <Input
                  label={t('auth.totp_code')}
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                  autoFocus
                  required
                />
                {error && <p className="text-sm text-danger">{error}</p>}
                <div className="flex gap-3">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => { setStep('credentials'); setError(''); setTotpCode('') }}
                    className="flex-1"
                  >
                    {t('common.back')}
                  </Button>
                  <Button type="submit" loading={loading} className="flex-1">
                    {t('common.confirm')}
                  </Button>
                </div>
              </form>
            </>
          )}

          {step === 'setup_required' && (
            <div className="text-center space-y-4 py-2">
              <div className="w-12 h-12 rounded-full bg-orange-500/15 dark:bg-orange-500/15 flex items-center justify-center mx-auto">
                <KeyRound className="w-5 h-5 text-warning" />
              </div>
              <h2 className="font-semibold text-gray-900">{t('auth.setup_2fa')}</h2>
              <p className="text-sm text-gray-600">{t('auth.setup_2fa_required_hint')}</p>
              {error && <p className="text-sm text-danger">{error}</p>}
              {/* Sans jeton d'enrôlement (serveur antérieur au 2026-08-04), l'écran reste ce
                  qu'il était : une impasse. Avec, il devient la porte. */}
              {enrolmentToken && (
                <Button loading={loading} onClick={startEnrolment} className="w-full">
                  {t('auth.setup_2fa_start')}
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={() => { setStep('credentials'); setError('') }}
                className="w-full"
              >
                {t('common.back')}
              </Button>
            </div>
          )}

          {step === 'enrol' && setup && (
            <>
              <div className="flex items-center gap-3 mb-4">
                <div className="w-9 h-9 rounded-lg bg-accent/10 dark:bg-blue-500/15 flex items-center justify-center">
                  <KeyRound className="w-4 h-4 text-info" />
                </div>
                <h1 className="text-base font-semibold text-gray-900">{t('auth.setup_2fa')}</h1>
              </div>
              <p className="text-sm text-gray-600 mb-4">{t('auth.setup_2fa_scan')}</p>
              {/* eslint-disable-next-line @next/next/no-img-element -- data: URI, aucun hôte
                  distant à déclarer et rien à optimiser. */}
              <img
                src={`data:image/png;base64,${setup.qr_b64}`}
                alt=""
                className="mx-auto mb-4 h-44 w-44 rounded-lg bg-white p-2"
              />
              <p className="text-xs text-gray-500 mb-1">{t('auth.setup_2fa_manual')}</p>
              <code className="mb-4 block break-all rounded bg-gray-100 px-2 py-1.5 text-center text-xs tracking-wider text-gray-700">
                {setup.secret}
              </code>
              <form onSubmit={submitEnrolment} className="space-y-4">
                <Input
                  label={t('auth.totp_code')}
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                  autoFocus
                  required
                />
                {error && <p className="text-sm text-danger">{error}</p>}
                <Button type="submit" loading={loading} className="w-full">
                  {t('auth.setup_2fa_enable')}
                </Button>
              </form>
            </>
          )}

          {step === 'enrolled' && setup && (
            <div className="space-y-4 py-1">
              <h2 className="text-center font-semibold text-gray-900">
                {t('auth.setup_2fa_enabled')}
              </h2>
              <p className="text-sm font-medium text-gray-700">{t('auth.setup_2fa_backup_title')}</p>
              <p className="text-xs text-gray-500">{t('auth.setup_2fa_backup_hint')}</p>
              <ul className="grid grid-cols-2 gap-1.5 rounded-lg bg-gray-100 p-3">
                {setup.backup_codes.map((c) => (
                  <li key={c} className="text-center font-mono text-xs tracking-wider text-gray-700">
                    {c}
                  </li>
                ))}
              </ul>
              {/* On repasse par /auth/login avec un NOUVEAU code : ce chemin porte les
                  compteurs anti-force brute, l'horodatage de dernière connexion et l'entrée
                  de journal. Il ne doit y avoir qu'une seule façon d'entrer. */}
              <Button
                onClick={() => { setStep('totp'); setError(''); setEnrolmentToken('') }}
                className="w-full"
              >
                {t('auth.setup_2fa_continue')}
              </Button>
            </div>
          )}
        </div>
      </div>
    </main>
  )
}
