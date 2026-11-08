import { clsx } from 'clsx'
import type { InputHTMLAttributes } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  hint?: string
}

export default function Input({ label, error, hint, className, id, ...props }: InputProps) {
  const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-')

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label htmlFor={inputId} className="text-sm font-medium text-gray-800">
          {label}
        </label>
      )}
      <input
        id={inputId}
        {...props}
        className={clsx(
          'w-full px-3 py-2 text-sm rounded-lg border bg-surface text-gray-900 placeholder-gray-400',
          'transition-sf focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent',
          error
            ? 'border-danger focus:ring-danger'
            : 'border-gray-200 hover:border-gray-400',
          props.disabled && 'opacity-50 cursor-not-allowed',
          className
        )}
      />
      {error && <p className="text-xs text-danger">{error}</p>}
      {hint && !error && <p className="text-xs text-gray-400">{hint}</p>}
    </div>
  )
}
