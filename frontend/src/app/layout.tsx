import type { Metadata } from 'next'
import localFont from 'next/font/local'
import { NextIntlClientProvider } from 'next-intl'
import { getLocale, getMessages } from 'next-intl/server'
import Providers from '@/components/providers'
import './globals.css'

// Inter servie depuis le dépôt (OFL, cf. public/fonts/promo/OFL.txt) : `next/font/google`
// la téléchargeait chez Google AU BUILD — build impossible hors ligne, et CI instable.
const inter = localFont({
  src: [
    { path: '../../public/fonts/promo/inter-400.woff2', weight: '400', style: 'normal' },
    { path: '../../public/fonts/promo/inter-500.woff2', weight: '500', style: 'normal' },
    { path: '../../public/fonts/promo/inter-600.woff2', weight: '600', style: 'normal' },
  ],
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Vitrail',
  description: 'Digital Signage Management Platform',
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale()
  const messages = await getMessages()

  return (
    // Dark only (refonte Mission Control 2026-07-17) : .dark posée en dur pour
    // que toutes les variantes dark: existantes s'appliquent.
    <html lang={locale} className="dark" suppressHydrationWarning>
      <body className={`${inter.className} bg-canvas text-gray-900 antialiased`}>
        <NextIntlClientProvider messages={messages}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  )
}
