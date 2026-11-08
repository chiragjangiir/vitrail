import { clsx } from 'clsx'
import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
}

// Mission Control : le primaire porte un GLOW accent ; le secondaire est une
// surface translucide hairline (verre sombre), jamais de gris opaque.
const variantCls: Record<Variant, string> = {
  primary:
    'bg-accent hover:bg-accent-hover text-white shadow-sf-accent disabled:bg-gray-200 disabled:text-gray-400 disabled:shadow-none',
  secondary:
    'bg-white/5 hover:bg-white/10 text-gray-800 border border-white/10 disabled:opacity-50',
  ghost:
    'bg-transparent hover:bg-white/5 text-gray-600 disabled:opacity-50',
  danger:
    'bg-danger hover:bg-red-500 text-white shadow-sf-glow-danger disabled:opacity-50',
}

const sizeCls: Record<Size, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-5 py-2.5 text-base',
}

export default function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className,
  disabled,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-2 font-medium rounded-lg transition-sf focus:outline-none focus:ring-2 focus:ring-accent/40 focus:ring-offset-1',
        variantCls[variant],
        sizeCls[size],
        className
      )}
    >
      {loading && (
        <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
      )}
      {children}
    </button>
  )
}
