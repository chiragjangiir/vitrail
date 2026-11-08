'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Globe, Lightbulb, MessageCircle, Send, Trash2 } from 'lucide-react'
import Topbar from '@/components/layout/Topbar'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { useAuthStore } from '@/store/auth'
import api from '@/lib/api'
import { fireDemoToast } from '@/lib/demo'
import { resetDismissedTips } from '@/components/layout/DemoTips'
import type { UserRead } from '@/types/api'

interface MessagingIdentity {
  id_identity: number
  channel: string
  display_name: string | null
  is_active: boolean
  last_seen_at: string | null
  created_at: string
}

interface MessagingStatus {
  configured: boolean
  bot_username: string | null
  identities: MessagingIdentity[]
  pin_set?: boolean
}

const LOCALES = [
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'Français' },
  { code: 'es', label: 'Español' },
  { code: 'pt', label: 'Português' },
  { code: 'de', label: 'Deutsch' },
]

export default function ProfilePage() {
  const t = useTranslations()
  const qc = useQueryClient()
  const { user, setAuth, accessToken, refreshToken, roles } = useAuthStore()
  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [locale, setLocale] = useState(user?.locale ?? 'en')
  const [saved, setSaved] = useState(false)
  const [linkCode, setLinkCode] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [tipsReset, setTipsReset] = useState(false)

  const { data: msgStatus } = useQuery<MessagingStatus>({
    queryKey: ['messaging-status'],
    queryFn: () => api.get<MessagingStatus>('/messaging/status').then((r) => r.data),
  })

  const linkMutation = useMutation({
    mutationFn: () => api.post<{ code: string }>('/messaging/link-code').then((r) => r.data),
    onSuccess: (d) => setLinkCode(d.code),
  })

  const unlinkMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/messaging/identities/me/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['messaging-status'] }),
  })

  // PIN actions sensibles (migr 0090) — 6 chiffres, exigé par Jeanine sur les
  // actions sensibles demandées par messagerie.
  const [pinValue, setPinValue] = useState('')
  const [pinSaved, setPinSaved] = useState(false)
  const pinMutation = useMutation({
    mutationFn: (pin: string) => api.post('/messaging/pin', { pin }),
    onSuccess: () => {
      setPinValue('')
      setPinSaved(true)
      setTimeout(() => setPinSaved(false), 2500)
      qc.invalidateQueries({ queryKey: ['messaging-status'] })
    },
  })
  const pinDeleteMutation = useMutation({
    mutationFn: () => api.delete('/messaging/pin'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['messaging-status'] }),
  })

  const copyCode = () => {
    const text = `/link ${linkCode}`
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).catch(() => {})
    } else {
      // Repli HTTP LAN (pas de secure context → pas de navigator.clipboard)
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  useEffect(() => {
    if (user) {
      setFullName(user.full_name ?? '')
      setLocale(user.locale)
    }
  }, [user])

  const saveMutation = useMutation({
    mutationFn: () =>
      api
        .patch<UserRead>('/users/me', {
          full_name: fullName || null,
          locale,
        })
        .then((r) => r.data),
    onSuccess: (updated) => {
      if (accessToken && refreshToken) {
        setAuth(updated, accessToken, refreshToken, roles, locale)
      }
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      if (updated.locale !== user?.locale) {
        // Reload to apply new locale
        window.location.reload()
      }
    },
  })

  return (
    <>
      <Topbar title={t('nav.profile')} />
      <main className="flex-1 overflow-y-auto">
        {/* Largeur de reference des pages de reglages centrees : max-w-5xl
            (arbitrage Ed 2026-07-23). Ne pas diverger page par page. */}
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">

          {/* Profile info */}
          <section className="bg-surface rounded-lg border border-gray-200 p-6 space-y-4 shadow-sf-card">
            <h2 className="font-semibold text-gray-900">{t('settings.profile')}</h2>

            <Input
              label={t('auth.email')}
              type="email"
              value={user?.email ?? ''}
              disabled
              hint={t('profile.email_hint')}
            />
            <Input
              label={t('profile.full_name')}
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder={t('profile.full_name_placeholder')}
            />
          </section>

          {/* Language */}
          <section className="bg-surface rounded-lg border border-gray-200 p-6 space-y-4 shadow-sf-card">
            <div className="flex items-center gap-2.5 mb-1">
              <Globe className="w-4 h-4 text-accent" />
              <h2 className="font-semibold text-gray-900">{t('settings.language')}</h2>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {LOCALES.map(({ code, label }) => (
                <button
                  key={code}
                  onClick={() => setLocale(code)}
                  className={`px-3 py-2 rounded-lg text-sm border transition-sf text-left ${
                    locale === code
                      ? 'bg-accent text-white border-accent font-medium'
                      : 'bg-surface text-gray-700 border-gray-200 hover:border-accent hover:text-accent'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          {/* Save (profile info + language) */}
          <div className="flex items-center gap-3">
            <Button
              onClick={() => saveMutation.mutate()}
              loading={saveMutation.isPending}
            >
              {t('common.save')}
            </Button>
            {saved && <p className="text-sm text-success">{t('common.saved')}</p>}
            {saveMutation.isError && <p className="text-sm text-danger">{t('common.error')}</p>}
          </div>

          {/* Bulles d'aide contextuelles — réactivation (fermées = mémorisées par page) */}
          <section className="bg-surface rounded-lg border border-gray-200 p-6 space-y-3 shadow-sf-card">
            <div className="flex items-center gap-2.5 mb-1">
              <Lightbulb className="w-4 h-4 text-accent" />
              <h2 className="font-semibold text-gray-900">{t('demo.tips_reset_title')}</h2>
            </div>
            <p className="text-sm text-gray-500">{t('demo.tips_reset_hint')}</p>
            <Button size="sm" variant="secondary" onClick={() => { resetDismissedTips(); setTipsReset(true); setTimeout(() => setTipsReset(false), 3000) }}>
              {t('demo.tips_reset_button')}
            </Button>
            {tipsReset && <p className="text-sm text-success">{t('demo.tips_reset_done')}</p>}
          </section>

          {/* Messaging — Jeanine (Telegram) */}
          <section className="bg-surface rounded-lg border border-gray-200 p-6 space-y-4 shadow-sf-card">
            <div className="flex items-center gap-2.5 mb-1">
              <Send className="w-4 h-4 text-accent" />
              <h2 className="font-semibold text-gray-900">{t('messaging.profile_title')}</h2>
            </div>
            <p className="text-sm text-gray-500">{t('messaging.profile_intro')}</p>

            {msgStatus && !msgStatus.configured ? (
              <p className="text-sm text-gray-400">{t('messaging.not_configured')}</p>
            ) : msgStatus ? (
              <>
                {msgStatus.identities.length > 0 && (
                  <ul className="space-y-2">
                    {msgStatus.identities.map((i) => (
                      <li
                        key={i.id_identity}
                        className="flex items-center gap-3 rounded-lg border border-gray-200 px-3 py-2"
                      >
                        <MessageCircle className="w-4 h-4 text-accent shrink-0" />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-gray-900">
                            {i.display_name || 'Telegram'}
                          </p>
                          <p className="text-xs text-gray-400">
                            {i.channel} · {t('messaging.last_seen')} :{' '}
                            {i.last_seen_at
                              ? new Date(i.last_seen_at).toLocaleString()
                              : t('messaging.never')}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            if (confirm(t('messaging.unlink_confirm'))) {
                              unlinkMutation.mutate(i.id_identity)
                            }
                          }}
                          disabled={unlinkMutation.isPending}
                          className="flex items-center gap-1 text-xs text-gray-400 hover:text-danger transition-sf"
                        >
                          <Trash2 className="w-3.5 h-3.5" /> {t('messaging.unlink')}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                {linkCode ? (
                  <div className="rounded-lg border border-accent/30 bg-accent/5 p-4 space-y-2">
                    <p className="text-sm text-gray-700">{t('messaging.code_hint')}</p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 rounded bg-gray-100 px-3 py-2 font-mono text-sm text-gray-900">
                        /link {linkCode}
                      </code>
                      <Button size="sm" variant="secondary" onClick={copyCode}>
                        {copied ? t('messaging.copied') : t('messaging.copy')}
                      </Button>
                    </div>
                    {msgStatus.bot_username && (
                      <a
                        href={`https://t.me/${msgStatus.bot_username}`}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-sm text-accent hover:underline"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        {t('messaging.open_bot', { bot: msgStatus.bot_username })}
                      </a>
                    )}
                    <p className="text-xs text-gray-400">{t('messaging.code_expires')}</p>
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <Button
                      size="sm"
                      // Compte démo : blocage CLIENT (toast direct) — sinon l'intercepteur
                      // avale la promesse et le bouton reste en spinner (retour Ed 10/07)
                      onClick={() => (user?.is_demo ? fireDemoToast() : linkMutation.mutate())}
                      loading={linkMutation.isPending}
                    >
                      {t('messaging.link_button')}
                    </Button>
                    {linkMutation.isError && (
                      <p className="text-sm text-danger">{t('common.error')}</p>
                    )}
                  </div>
                )}

                {/* PIN actions sensibles — 2e facteur du OUI par messagerie */}
                <div className="border-t border-gray-100 pt-4 space-y-2">
                  <p className="text-sm font-medium text-gray-700">
                    {t('messaging.pin_title')}
                    {msgStatus.pin_set && (
                      <span className="ml-2 px-2 py-0.5 rounded-full bg-accent/10 text-accent text-xs font-medium">
                        {t('messaging.pin_set_badge')}
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-gray-500">{t('messaging.pin_hint')}</p>
                  <div className="flex items-center gap-2">
                    <input
                      type="password"
                      inputMode="numeric"
                      maxLength={6}
                      value={pinValue}
                      onChange={(e) => setPinValue(e.target.value.replace(/\D/g, ''))}
                      placeholder="••••••"
                      className="w-28 px-3 py-2 text-sm font-mono tracking-widest border border-gray-200 rounded-lg bg-surface focus:outline-none focus:ring-2 focus:ring-accent/40"
                    />
                    <Button
                      size="sm"
                      disabled={pinValue.length !== 6}
                      loading={pinMutation.isPending}
                      onClick={() => (user?.is_demo ? fireDemoToast() : pinMutation.mutate(pinValue))}
                    >
                      {msgStatus.pin_set ? t('messaging.pin_replace') : t('messaging.pin_define')}
                    </Button>
                    {msgStatus.pin_set && (
                      <button
                        type="button"
                        onClick={() => {
                          if (user?.is_demo) { fireDemoToast(); return }
                          if (confirm(t('messaging.pin_delete_confirm'))) pinDeleteMutation.mutate()
                        }}
                        disabled={pinDeleteMutation.isPending}
                        className="flex items-center gap-1 text-xs text-gray-400 hover:text-danger transition-sf"
                      >
                        <Trash2 className="w-3.5 h-3.5" /> {t('messaging.pin_delete')}
                      </button>
                    )}
                  </div>
                  {pinSaved && <p className="text-xs text-success">{t('messaging.pin_saved')}</p>}
                  {pinMutation.isError && <p className="text-xs text-danger">{t('common.error')}</p>}
                </div>
              </>
            ) : null}
          </section>

        </div>
      </main>
    </>
  )
}
