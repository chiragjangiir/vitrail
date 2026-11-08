import { getRequestConfig } from 'next-intl/server'
import { cookies, headers } from 'next/headers'
import { defaultLocale, isSupportedLocale, locales, negotiateLocale, type Locale } from './negotiate'

// La liste des langues servies vit dans `negotiate.ts` (définition unique) ; on la
// ré-expose ici parce que c'est ce module que next-intl charge (`next.config.ts`).
export { locales, defaultLocale }
export type { Locale }

export default getRequestConfig(async () => {
  const cookieStore = await cookies()
  const fromCookie = cookieStore.get('locale')?.value

  // Le cookie l'emporte TOUJOURS sur l'en-tête : c'est le choix explicite de
  // l'utilisateur (profil), là où `Accept-Language` n'est qu'une préférence de
  // navigateur. La négociation ne sert donc qu'avant la première connexion.
  //
  // ⚠️ Le cookie est VALIDÉ : il vient du client, et l'ancien `as Locale` sans
  // contrôle construisait un chemin d'import inexistant ⇒ 500 sur TOUTES les
  // pages avec un cookie forgé ou périmé (mesuré avant correctif le 2026-08-06).
  const locale: Locale = isSupportedLocale(fromCookie)
    ? fromCookie
    : negotiateLocale((await headers()).get('accept-language'))

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  }
})
