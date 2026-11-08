'use client'

import { useEffect, useMemo, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { BookOpen, Search } from 'lucide-react'
import { clsx } from 'clsx'
import Topbar from '@/components/layout/Topbar'

/*
 * Manuel utilisateur — rend le markdown statique `public/help/manual.<locale>.md`
 * (servi live après git pull, sans rebuild). Renderer maison volontairement borné
 * (zéro dépendance) : #/##/###, paragraphes, listes -/1., citations >, **gras**,
 * `code`, et images `![légende](/help/img/x.webp)` SEULES sur leur ligne (captures
 * d'écran de l'UI, cliquables pour ouvrir en pleine taille). Le contenu du manuel
 * n'utilise QUE cette syntaxe.
 */

// ── Inline : **gras** et `code` ───────────────────────────────────────────────
function renderInline(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = []
  // Découpe en conservant les segments **…** et `…`
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  parts.forEach((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      out.push(<strong key={i} className="font-semibold text-gray-900">{part.slice(2, -2)}</strong>)
    } else if (part.startsWith('`') && part.endsWith('`')) {
      out.push(
        <code key={i} className="px-1 py-0.5 rounded bg-gray-100 text-[13px] text-gray-800">
          {part.slice(1, -1)}
        </code>
      )
    } else if (part) {
      out.push(part)
    }
  })
  return out
}

interface Section {
  id: string
  title: string
  lines: string[]     // corps markdown de la section (## exclu)
}

function slugify(s: string): string {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
}

// Découpe le manuel en sections par titre `## ` (le `# ` de tête est ignoré — le
// titre de page vient de l'i18n).
function parseSections(md: string): Section[] {
  const sections: Section[] = []
  let current: Section | null = null
  for (const raw of md.split('\n')) {
    if (raw.startsWith('## ')) {
      if (current) sections.push(current)
      const title = raw.slice(3).trim()
      current = { id: slugify(title), title, lines: [] }
    } else if (current && !raw.startsWith('# ')) {
      current.lines.push(raw)
    }
  }
  if (current) sections.push(current)
  return sections
}

// ── Bloc : rend le corps d'une section ────────────────────────────────────────
function SectionBody({ lines }: { lines: string[] }) {
  const blocks: React.ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let key = 0

  const flushList = () => {
    if (!list) return
    const items = list.items.map((it, i) => (
      <li key={i} className="leading-relaxed">{renderInline(it)}</li>
    ))
    blocks.push(
      list.ordered ? (
        <ol key={key++} className="list-decimal pl-5 space-y-1 text-sm text-gray-700">{items}</ol>
      ) : (
        <ul key={key++} className="list-disc pl-5 space-y-1 text-sm text-gray-700">{items}</ul>
      )
    )
    list = null
  }

  for (const line of lines) {
    const trimmed = line.trim()
    const mUl = /^- (.*)$/.exec(trimmed)
    const mOl = /^\d+\. (.*)$/.exec(trimmed)
    if (mUl || mOl) {
      const ordered = !!mOl
      const item = (mUl?.[1] ?? mOl?.[1]) as string
      if (!list || list.ordered !== ordered) {
        flushList()
        list = { ordered, items: [] }
      }
      list.items.push(item)
      continue
    }
    flushList()
    if (!trimmed) continue
    const mImg = /^!\[([^\]]*)\]\(([^)\s]+)\)$/.exec(trimmed)
    if (mImg) {
      const [, alt, src] = mImg
      blocks.push(
        <figure key={key++} className="mt-3 mb-1">
          <a href={src} target="_blank" rel="noreferrer" title={alt}
            className="block rounded-xl overflow-hidden border border-gray-200 shadow-sf-card transition-sf hover:border-accent/50">
            {/* Capture d'écran statique servie depuis public/ — <img> volontaire (pas next/image). */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={src} alt={alt} loading="lazy" className="w-full block" />
          </a>
          {alt && (
            <figcaption className="mt-1.5 text-xs text-gray-500">{alt}</figcaption>
          )}
        </figure>
      )
      continue
    }
    if (trimmed.startsWith('### ')) {
      blocks.push(
        <h4 key={key++} className="text-sm font-semibold text-gray-900 mt-4">
          {renderInline(trimmed.slice(4))}
        </h4>
      )
    } else if (trimmed.startsWith('> ')) {
      blocks.push(
        <div key={key++}
          className="border-l-2 border-accent/50 bg-accent/5 rounded-r-lg px-3 py-2 text-sm text-gray-700">
          {renderInline(trimmed.slice(2))}
        </div>
      )
    } else {
      blocks.push(
        <p key={key++} className="text-sm text-gray-700 leading-relaxed">{renderInline(trimmed)}</p>
      )
    }
  }
  flushList()
  return <div className="space-y-2.5">{blocks}</div>
}

export default function HelpPage() {
  const t = useTranslations('help')
  const locale = useLocale()
  const [md, setMd] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [query, setQuery] = useState('')
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      // Manuel de la locale du profil ; repli anglais si absent.
      for (const loc of [locale, 'en']) {
        try {
          const res = await fetch(`/help/manual.${loc}.md`)
          if (res.ok) {
            const textBody = await res.text()
            if (!cancelled) setMd(textBody)
            return
          }
        } catch {
          // réseau — on tente le repli
        }
      }
      if (!cancelled) setFailed(true)
    }
    load()
    return () => { cancelled = true }
  }, [locale])

  const sections = useMemo(() => (md ? parseSections(md) : []), [md])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return sections
    return sections.filter(
      (s) => s.title.toLowerCase().includes(q) || s.lines.join('\n').toLowerCase().includes(q)
    )
  }, [sections, query])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <Topbar title={t('title')} />
      <main className="flex-1 min-h-0 p-6">
        <div className="flex h-full min-h-0 gap-6 max-w-6xl mx-auto">
          {/* Sommaire */}
          <aside className="w-64 shrink-0 hidden lg:flex flex-col min-h-0 bg-surface border border-gray-200 rounded-xl shadow-sf-card">
            <div className="p-3 border-b border-gray-200">
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t('search')}
                  className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-gray-200 bg-canvas focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
              </div>
            </div>
            <nav className="flex-1 min-h-0 overflow-y-auto p-2 space-y-0.5">
              {visible.map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  onClick={() => setActiveId(s.id)}
                  className={clsx(
                    'block px-3 py-1.5 rounded-lg text-[13px] transition-sf',
                    activeId === s.id
                      ? 'bg-accent/10 text-accent font-medium'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                  )}
                >
                  {s.title}
                </a>
              ))}
            </nav>
          </aside>

          {/* Contenu */}
          <div id="help-content"
            className="flex-1 min-h-0 overflow-y-auto bg-surface border border-gray-200 rounded-xl shadow-sf-card scroll-smooth">
            {md === null && !failed && (
              <p className="p-6 text-sm text-gray-500">…</p>
            )}
            {failed && (
              <p className="p-6 text-sm text-gray-500">{t('unavailable')}</p>
            )}
            {md !== null && (
              <div className="p-6 lg:p-8 space-y-8">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
                    <BookOpen className="w-5 h-5 text-accent" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">{t('title')}</h2>
                    <p className="text-xs text-gray-500">{t('subtitle')}</p>
                  </div>
                </div>
                {visible.length === 0 && (
                  <p className="text-sm text-gray-500">{t('no_result')}</p>
                )}
                {visible.map((s) => (
                  <section key={s.id} id={s.id} className="scroll-mt-4">
                    <h3 className="text-base font-semibold text-gray-900 mb-2.5 pb-2 border-b border-gray-200">
                      {s.title}
                    </h3>
                    <SectionBody lines={s.lines} />
                  </section>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
