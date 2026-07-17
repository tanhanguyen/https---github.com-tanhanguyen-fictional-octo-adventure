import type { EquityPointOut } from '../api/types'

interface Props {
  points: EquityPointOut[]
  height?: number
}

export function EquityChart({ points, height = 180 }: Props) {
  if (points.length < 2) {
    return <p className="muted">Chưa đủ dữ liệu equity để vẽ biểu đồ.</p>
  }

  const width = 640
  const values = points.map((p) => p.equity)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const pad = 8

  const path = points
    .map((p, i) => {
      const x = pad + (i / (points.length - 1)) * (width - 2 * pad)
      const y = height - pad - ((p.equity - min) / range) * (height - 2 * pad)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  const last = points[points.length - 1]
  const first = points[0]
  const up = last.equity >= first.equity

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label="Equity curve"
    >
      <path
        d={path}
        fill="none"
        stroke={up ? '#16a34a' : '#dc2626'}
        strokeWidth={2}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
