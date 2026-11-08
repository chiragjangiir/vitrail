'use client'

import { clsx } from 'clsx'

export interface Tab {
  key: string
  label: string
  count?: number
}

interface TabBarProps {
  tabs: Tab[]
  active: string
  onChange: (key: string) => void
  className?: string
}

export default function TabBar({ tabs, active, onChange, className }: TabBarProps) {
  return (
    <div className={clsx('flex border-b border-white/5', className)}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={clsx(
            'relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-sf',
            active === tab.key
              ? 'border-accent-hover text-accent-hover'
              : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-white/20'
          )}
        >
          {/* Halo sous l'onglet actif (Mission Control) */}
          {active === tab.key && (
            <span
              className="absolute bottom-0 left-0 right-0 h-3 bg-accent/20 blur-md pointer-events-none"
              aria-hidden="true"
            />
          )}
          {tab.label}
          {tab.count !== undefined && (
            <span
              className={clsx(
                'px-1.5 py-0.5 text-xs rounded-full',
                active === tab.key ? 'bg-accent text-white' : 'bg-white/10 text-gray-600'
              )}
            >
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}
