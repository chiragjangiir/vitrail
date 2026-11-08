import { clsx } from 'clsx'
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Loader2,
  Info,
  Wrench,
} from 'lucide-react'

type Status =
  | 'online'
  | 'offline'
  | 'warning'
  | 'pending'
  | 'processing'
  | 'done'
  | 'error'
  | 'info'
  | 'maintenance'
  | 'critical'

interface StatusBadgeProps {
  status: Status
  label: string
  className?: string
}

// Liseré ton-sur-ton très léger (polish aidesigner 2026-07-09) — même recette que
// les classes .badge-* de globals.css.
const config: Record<Status, { icon: React.ComponentType<{ className?: string }>; cls: string }> = {
  online:      { icon: CheckCircle2,  cls: 'bg-green-50  text-success border-green-600/10  dark:bg-green-500/15  dark:text-green-300  dark:border-green-400/20' },
  done:        { icon: CheckCircle2,  cls: 'bg-green-50  text-success border-green-600/10  dark:bg-green-500/15  dark:text-green-300  dark:border-green-400/20' },
  offline:     { icon: XCircle,       cls: 'bg-red-500/10    text-danger  border-red-600/10    dark:bg-red-500/15    dark:text-red-300    dark:border-red-400/20' },
  error:       { icon: XCircle,       cls: 'bg-red-500/10    text-danger  border-red-600/10    dark:bg-red-500/15    dark:text-red-300    dark:border-red-400/20' },
  critical:    { icon: AlertTriangle, cls: 'bg-red-500/10    text-danger  border-red-600/10    dark:bg-red-500/15    dark:text-red-300    dark:border-red-400/20' },
  warning:     { icon: AlertTriangle, cls: 'bg-orange-500/15 text-warning border-orange-600/10 dark:bg-orange-500/15 dark:text-orange-300 dark:border-orange-400/20' },
  maintenance: { icon: Wrench,        cls: 'bg-accent/10   text-info    border-blue-600/10   dark:bg-blue-500/15   dark:text-blue-300   dark:border-blue-400/20' },
  pending:     { icon: Clock,         cls: 'bg-gray-100  text-gray-600 border-gray-200' },
  processing:  { icon: Loader2,       cls: 'bg-accent/10   text-info    border-blue-600/10   dark:bg-blue-500/15   dark:text-blue-300   dark:border-blue-400/20' },
  info:        { icon: Info,          cls: 'bg-accent/10   text-info    border-blue-600/10   dark:bg-blue-500/15   dark:text-blue-300   dark:border-blue-400/20' },
}

export default function StatusBadge({ status, label, className }: StatusBadgeProps) {
  const { icon: Icon, cls } = config[status]
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-medium border',
        cls,
        className
      )}
    >
      <Icon className={clsx('w-3 h-3', status === 'processing' && 'animate-spin')} />
      {label}
    </span>
  )
}
