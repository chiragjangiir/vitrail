'use client'

import { clsx } from 'clsx'

export interface Column<T> {
  key: string
  header: string
  render?: (row: T) => React.ReactNode
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  loading?: boolean
  onRowClick?: (row: T) => void
  emptyMessage?: string
  rowKey: (row: T) => string | number
  /**
   * `true` : la table occupe toute la hauteur que lui donne son parent et défile
   * en interne, **en-têtes de colonnes collants**. À utiliser dans une page
   * verrouillée au viewport (le parent doit porter `flex-1 min-h-0`).
   *
   * ⚠️ En mode collant, l'en-tête passe d'un fond translucide (`bg-black/20`) à un
   * fond OPAQUE : par-dessus des lignes qui défilent, un fond translucide laisse
   * voir le texte glisser dessous.
   */
  fill?: boolean
}

export default function DataTable<T>({
  columns,
  data,
  loading = false,
  onRowClick,
  emptyMessage = 'No data',
  rowKey,
  fill = false,
}: DataTableProps<T>) {
  return (
    <div
      className={clsx(
        'rounded-xl border border-white/5 shadow-sf-card',
        fill ? 'h-full min-h-0 overflow-auto' : 'overflow-x-auto'
      )}
    >
      <table className="w-full text-sm">
        <thead
          className={clsx(
            'border-b border-white/5',
            fill ? 'sticky top-0 z-10 bg-surface-hover' : 'bg-black/20'
          )}
        >
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={clsx(
                  'px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wide',
                  col.className
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-surface divide-y divide-white/5">
          {loading ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-gray-400">
                <span className="inline-flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                  Loading...
                </span>
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-gray-400">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={() => onRowClick?.(row)}
                className={clsx(
                  'transition-sf',
                  onRowClick && 'cursor-pointer hover:bg-white/[0.03]'
                )}
              >
                {columns.map((col) => (
                  <td key={col.key} className={clsx('px-4 py-3 text-gray-800', col.className)}>
                    {col.render ? col.render(row) : ''}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
