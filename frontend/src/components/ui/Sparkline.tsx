'use client'

interface SparklineProps {
  data: number[]
  /** Couleur du tracé + du dégradé (ex. 'rgb(59 130 246)'). */
  color?: string
  width?: number
  height?: number
  className?: string
}

/**
 * Sparkline SVG minimaliste (aucune dépendance) — tracé lissé + aire dégradée.
 * Utilisée dans les KPI cards du dashboard « Mission Control ». Un jeu constant
 * (ou < 2 points) rend une ligne médiane plate plutôt qu'une division par zéro.
 */
export default function Sparkline({
  data,
  color = 'rgb(59 130 246)',
  width = 96,
  height = 32,
  className,
}: SparklineProps) {
  const pts = data && data.length > 0 ? data : [0, 0]
  const n = pts.length
  const max = Math.max(...pts)
  const min = Math.min(...pts)
  const span = max - min || 1
  const gid = `spark-${color.replace(/[^a-z0-9]/gi, '')}`

  const x = (i: number) => (n === 1 ? width / 2 : (i / (n - 1)) * width)
  const y = (v: number) => height - 2 - ((v - min) / span) * (height - 4)

  const line = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = `${line} L${width},${height} L0,${height} Z`

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
