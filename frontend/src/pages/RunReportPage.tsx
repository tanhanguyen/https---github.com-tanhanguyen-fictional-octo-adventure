import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { EquityPointOut, RunReportOut, TradeStatsOut } from '../api/types'
import { EquityChart } from '../components/EquityChart'

function fmt(x: number | null, digits = 2, suffix = ''): string {
  return x == null ? '—' : `${x.toFixed(digits)}${suffix}`
}

function pct(x: number | null): string {
  return x == null ? '—' : `${(x * 100).toFixed(1)}%`
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-row">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  )
}

function RHistogram({ stats }: { stats: TradeStatsOut }) {
  const bins = stats.r_histogram
  const max = Math.max(1, ...bins.map((b) => b.count))
  const barW = 40
  const height = 140
  const width = bins.length * barW
  return (
    <div className="table-scroll">
      <svg width={width} height={height + 34} role="img" aria-label="R-multiple histogram">
        {bins.map((b, i) => {
          const h = (b.count / max) * height
          const negative = b.hi != null && b.hi <= 0
          return (
            <g key={b.label}>
              <rect
                x={i * barW + 4}
                y={height - h}
                width={barW - 8}
                height={h}
                fill={negative ? '#dc2626' : '#16a34a'}
                opacity={b.count === 0 ? 0.15 : 0.9}
              />
              {b.count > 0 && (
                <text x={i * barW + barW / 2} y={height - h - 4} textAnchor="middle" fontSize={11}>
                  {b.count}
                </text>
              )}
              <text
                x={i * barW + barW / 2}
                y={height + 14}
                textAnchor="middle"
                fontSize={9}
                transform={`rotate(35 ${i * barW + barW / 2} ${height + 14})`}
              >
                {b.label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function DrawdownChart({ points, startingEquity }: { points: EquityPointOut[]; startingEquity: number }) {
  if (points.length < 2) return <p className="muted">Chưa đủ dữ liệu.</p>
  const width = 640
  const height = 120
  const pad = 8
  let peak = startingEquity
  const dd = points.map((p) => {
    peak = Math.max(peak, p.equity)
    return peak > 0 ? ((peak - p.equity) / peak) * 100 : 0
  })
  const maxDd = Math.max(...dd, 0.0001)
  const path = dd
    .map((v, i) => {
      const x = pad + (i / (dd.length - 1)) * (width - 2 * pad)
      const y = pad + (v / maxDd) * (height - 2 * pad)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label="Drawdown %"
    >
      <path d={path} fill="none" stroke="#dc2626" strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function TradeStatsCells({ stats }: { stats: TradeStatsOut }) {
  return (
    <>
      <td>{stats.n_total}</td>
      <td>
        {stats.n_win}/{stats.n_loss}/{stats.n_breakeven}
      </td>
      <td>{pct(stats.win_rate)}</td>
      <td>{fmt(stats.profit_factor)}</td>
      <td>{fmt(stats.expectancy_r, 3, 'R')}</td>
      <td>{fmt(stats.avg_win)}</td>
      <td>{fmt(stats.avg_loss)}</td>
      <td>{fmt(stats.avg_holding_hours, 1, 'h')}</td>
    </>
  )
}

export function RunReportPage() {
  const { id } = useParams()
  const runId = Number(id)
  const [report, setReport] = useState<RunReportOut | null>(null)
  const [equity, setEquity] = useState<EquityPointOut[]>([])
  const [startingEquity, setStartingEquity] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [rep, eq, runs] = await Promise.all([
          api.getRunReport(runId),
          api.getRunEquity(runId),
          api.listRuns(),
        ])
        if (cancelled) return
        setReport(rep)
        setEquity(eq)
        setStartingEquity(runs.find((r) => r.id === runId)?.starting_equity ?? 0)
        setError(null)
      } catch {
        if (!cancelled) setError(`Không tải được report của run #${runId}.`)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [runId])

  if (error) {
    return (
      <div className="card">
        <p className="pill loss">{error}</p>
        <p>
          <Link to="/runs">← Quay lại danh sách runs</Link>
        </p>
      </div>
    )
  }
  if (!report) return <p className="muted">Đang tải report…</p>

  const o = report.overall
  const s = report.series
  const blocked = Object.entries(report.filter_block_counts).sort((x, y) => y[1] - x[1])

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="toolbar">
        <Link to="/runs">← Runs</Link>
        <h2 style={{ margin: 0 }}>Report — run #{runId}</h2>
      </div>

      <div className="grid grid-3">
        <div className="card">
          <h2>Tổng quan lệnh</h2>
          <Stat label="Số lệnh đóng" value={String(o.n_total)} />
          <Stat label="WIN / LOSS / BE" value={`${o.n_win} / ${o.n_loss} / ${o.n_breakeven}`} />
          <Stat label="Win rate (BE tính như thua, D8)" value={pct(o.win_rate)} />
          <Stat label="Profit factor" value={fmt(o.profit_factor)} />
          <Stat label="Expectancy" value={fmt(o.expectancy_r, 3, 'R')} />
          <Stat label="Giữ lệnh trung bình" value={fmt(o.avg_holding_hours, 1, 'h')} />
        </div>
        <div className="card">
          <h2>Lãi / lỗ</h2>
          <Stat label="Avg win" value={fmt(o.avg_win)} />
          <Stat label="Max win" value={fmt(o.max_win)} />
          <Stat label="Avg loss" value={fmt(o.avg_loss)} />
          <Stat label="Max loss" value={fmt(o.max_loss)} />
        </div>
        <div className="card">
          <h2>Chuỗi equity</h2>
          <Stat label="Equity cuối" value={s.final_equity.toFixed(2)} />
          <Stat label="Return tổng" value={`${s.total_return_pct.toFixed(2)}%`} />
          <Stat
            label="Max drawdown"
            value={`${s.max_drawdown_abs.toFixed(2)} (${s.max_drawdown_pct.toFixed(2)}%)`}
          />
          <Stat label="Drawdown dài nhất" value={`${s.longest_drawdown_bars} bar`} />
          <Stat label="Sharpe (so sánh tương đối)" value={fmt(s.sharpe)} />
          <Stat label="Số bar" value={String(s.n_bars)} />
        </div>
      </div>

      <div className="card">
        <h2>Per-strategy</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Lệnh</th>
                <th>W/L/BE</th>
                <th>Win rate</th>
                <th>PF</th>
                <th>Expectancy</th>
                <th>Avg win</th>
                <th>Avg loss</th>
                <th>Giữ TB</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Tất cả</td>
                <TradeStatsCells stats={o} />
              </tr>
              {Object.entries(report.per_strategy).map(([strat, stats]) => (
                <tr key={strat}>
                  <td>{strat}</td>
                  <TradeStatsCells stats={stats} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h2>Phân bố R-multiple</h2>
          <RHistogram stats={o} />
        </div>
        <div className="card">
          <h2>Filter nào chặn bao nhiêu signal</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Filter</th>
                  <th>Số lần chặn</th>
                </tr>
              </thead>
              <tbody>
                {blocked.map(([fid, count]) => (
                  <tr key={fid}>
                    <td>{fid}</td>
                    <td>{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {blocked.length === 0 && <p className="muted">Không có filter nào chặn signal.</p>}
        </div>
      </div>

      <div className="card">
        <h2>Equity</h2>
        <EquityChart points={equity} />
        <h2>Drawdown %</h2>
        <DrawdownChart points={equity} startingEquity={startingEquity} />
      </div>

      <div className="card">
        <h2>Histogram reason</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Reason</th>
                <th>Số bar</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(report.reason_histogram)
                .sort((x, y) => y[1] - x[1])
                .map(([reason, count]) => (
                  <tr key={reason}>
                    <td>{reason}</td>
                    <td>{count}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
