import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { NextIntlClientProvider } from 'next-intl'
import { getLocale, getMessages } from 'next-intl/server'
import Providers from '@/components/providers'
import './globals.css'

const inter = Inter({ subsets: ['latin'], weight: ['400', '500', '600'] })

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
