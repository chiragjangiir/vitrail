'use client'

import { useState } from 'react'
import Image from 'next/image'
import { Search, ExternalLink, Download } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AxiosError } from 'axios'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import api from '@/lib/api'
import type { StockSearchResult, MediaRead } from '@/types/api'

type Provider = 'unsplash' | 'pexels'

interface StockSearchProps {
  onImported: (media: MediaRead) => void
}

export default function StockSearch({ onImported }: StockSearchProps) {
  const t = useTranslations('media')
  const qc = useQueryClient()
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [provider, setProvider] = useState<Provider>('unsplash')
  const [importing, setImporting] = useState<string | null>(null)

  const { data, isFetching, error } = useQuery<StockSearchResult[]>({
    queryKey: ['stock', submitted, provider],
    queryFn: () =>
      api
        .get<StockSearchResult[]>('/media/stock/search', { params: { q: submitted, provider } })
        .then((r) => r.data),
    enabled: submitted.length > 1,
    staleTime: 120_000,
    retry: false,
  })

  const providerUnconfigured =
    error instanceof AxiosError && error.response?.status === 503

  const importMutation = useMutation({
    mutationFn: (item: StockSearchResult) =>
      api
        .post<MediaRead>('/media/stock/import', {
          provider: item.provider,
          provider_id: item.provider_id,
          full_url: item.full_url,
          preview_url: item.preview_url,
          attribution_text: item.attribution_text,
          photographer: item.photographer,
          title: item.title,
          width: item.width,
          height: item.height,
        })
        .then((r) => r.data),
    onSuccess: (media) => {
      setImporting(null)
      qc.invalidateQueries({ queryKey: ['media'] })
      onImported(media)
    },
    onError: () => setImporting(null),
  })

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (query.trim().length < 2) return
    setSubmitted(query.trim())
  }

  function handleImport(item: StockSearchResult) {
    setImporting(item.provider_id)
    importMutation.mutate(item)
  }

  return (
    <div className="space-y-5">
      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="flex-1">
          <Input
            type="search"
            placeholder={t('search_placeholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex rounded border border-gray-200 overflow-hidden text-sm">
          {(['unsplash', 'pexels'] as Provider[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setProvider(p)}
              className={`px-3 py-2 font-medium transition-sf ${
                provider === p ? 'bg-accent text-white' : 'bg-surface text-gray-600 hover:bg-gray-50'
              }`}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
        <Button type="submit" loading={isFetching} aria-label="Search">
          <Search className="w-4 h-4" />
        </Button>
      </form>

      {/* Results */}
      {isFetching && (
        <div className="flex justify-center py-10">
          <span className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {providerUnconfigured && !isFetching && (
        <p className="text-center text-sm text-amber-600 dark:text-amber-300 bg-amber-500/10 dark:bg-amber-500/15 border border-amber-400/20 dark:border-amber-500/30 rounded-lg py-6 px-4">
          {t('stock_not_configured', { provider: provider.charAt(0).toUpperCase() + provider.slice(1) })}
        </p>
      )}

      {data && !isFetching && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {data.map((item) => (
            <div
              key={`${item.provider}-${item.provider_id}`}
              className="group relative bg-surface rounded-lg border border-gray-200 overflow-hidden hover:border-accent transition-sf shadow-sf-card"
            >
              <div className="aspect-video bg-gray-50 relative overflow-hidden">
                <Image
                  src={item.preview_url}
                  alt={item.title ?? item.photographer}
                  fill
                  className="object-cover"
                  sizes="(max-width: 640px) 50vw, 25vw"
                  unoptimized
                />
              </div>
              <div className="p-2.5">
                <p className="text-xs text-gray-500 truncate">
                  {t('by')} {item.photographer}
                </p>
                {item.photographer_url && (
                  <a
                    href={item.photographer_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 text-xs text-accent hover:underline mt-0.5"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ExternalLink className="w-3 h-3" />
                    {item.provider}
                  </a>
                )}
              </div>
              <div className="px-2.5 pb-2.5">
                <Button
                  size="sm"
                  className="w-full"
                  loading={importing === item.provider_id}
                  onClick={() => handleImport(item)}
                >
                  <Download className="w-3.5 h-3.5" />
                  {t('import')}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {data?.length === 0 && !isFetching && submitted && (
        <p className="text-center text-sm text-gray-400 py-8">{t('no_results')}</p>
      )}
    </div>
  )
}
