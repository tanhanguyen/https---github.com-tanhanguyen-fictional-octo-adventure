import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, errorDetail } from '../api/client'
import type {
  SweepDetailOut,
  SweepEquityPointOut,
  SweepResultOut,
  SweepWindowOut,
} from '../api/types'

/** Columns of the result table, in display order. `null` renders as an em dash. */
const METRIC_COLUMNS: { key: string; label: string; digits: number }[] = [
  { key: 'n_trades', label: 'Lệnh', digits: 0 },
  { key: 'profit_factor', label: 'PF', digits: 3 },
  { key: 'expectancy_r', label: 'Expectancy (R)', digits: 3 },
  { key: 'win_rate', label: 'Win rate', digits: 3 },
  { key: 'max_drawdown_pct', label: 'Max DD %', digits: 2 },
  { key: 'total_return_pct', label: 'Return %', digits: 2 },
  { key: 'sharpe', label: 'Sharpe', digits: 2 },
]

function fmt(x: number | null | undefined, digits = 2): string {
  return x == null ? '—' : x.toFixed(digits)
}

function shortParam(path: string): string {
  return path.split('.').slice(-1)[0]
}

function paramsLabel(params: Record<string, unknown> | null): string {
  if (!params) return '—'
  return Object.entries(params)
    .map(([k, v]) => `${shortParam(k)}=${String(v)}`)
    .join('  ')
}

/** Green→red scale for the heatmap; `t` is the value's rank in [0,1]. */
function heatColor(t: number): string {
  const hue = 8 + t * 112 // 8 = red, 120 = green
  return `hsl(${hue} 62% 45%)`
}

function Heatmap({ axes, rows, metric }: { axes: string[]; rows: SweepResultOut[]; metric: string }) {
  const [xAxis, yAxis] = axes
  // Sorted by PARAMETER value, not by metric: the rows arrive in the table's sort order,
  // and a heatmap whose axes jump around is unreadable.
  const axisValues = (axis: string) =>
    [...new Set(rows.map((r) => String(r.params[axis])))].sort((a, b) => {
      const na = Number(a)
      const nb = Number(b)
      return Number.isNaN(na) || Number.isNaN(nb) ? a.localeCompare(b) : na - nb
    })
  const xs = axisValues(xAxis)
  const ys = axisValues(yAxis)
  const byCell = new Map(rows.map((r) => [`${r.params[xAxis]}|${r.params[yAxis]}`, r]))
  const values = rows.map((r) => r.metric_value).filter((v): v is number => v != null)
  const min = Math.min(...values)
  const max = Math.max(...values)

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>
              {shortParam(yAxis)} \ {shortParam(xAxis)}
            </th>
            {xs.map((x) => (
              <th key={x}>{x}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ys.map((y) => (
            <tr key={y}>
              <th>{y}</th>
              {xs.map((x) => {
                const cell = byCell.get(`${x}|${y}`)
                const v = cell?.metric_value ?? null
                const t = v == null || max === min ? 0 : (v - min) / (max - min)
                return (
                  <td
                    key={x}
                    title={
                      cell
                        ? `run #${cell.run_id} · ${metric}=${fmt(v, 3)} · ${
                            cell.eligible ? 'đạt ràng buộc' : cell.ineligible_reason
                          }`
                        : 'không có'
                    }
                    style={{
                      background: v == null ? 'transparent' : heatColor(t),
                      color: v == null ? undefined : '#fff',
                      opacity: cell && !cell.eligible ? 0.35 : 1,
                      textAlign: 'center',
                    }}
                  >
                    {cell ? <Link to={`/runs/${cell.run_id}/report`}>{fmt(v, 3)}</Link> : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OosEquityChart({ points }: { points: SweepEquityPointOut[] }) {
  if (points.length < 2) return <p className="muted">Chưa đủ dữ liệu OOS để vẽ.</p>
  const width = 640
  const height = 180
  const pad = 8
  const values = points.map((p) => p.equity)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const path = points
    .map((p, i) => {
      const x = pad + (i / (points.length - 1)) * (width - 2 * pad)
      const y = height - pad - ((p.equity - min) / range) * (height - 2 * pad)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  const up = points[points.length - 1].equity >= points[0].equity
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label="Equity out-of-sample nối"
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

/** Where the winner sat inside the spread of ALL combos of that window. */
function DistributionBar({ w }: { w: SweepWindowOut }) {
  const d = w.distribution
  if (d.min == null || d.max == null || w.is_metric == null) return <span className="muted">—</span>
  const span = d.max - d.min || 1
  const pos = ((w.is_metric - d.min) / span) * 100
  const p25 = (((d.p25 ?? d.min) - d.min) / span) * 100
  const p75 = (((d.p75 ?? d.max) - d.min) / span) * 100
  return (
    <div
      title={`min ${fmt(d.min, 3)} · p25 ${fmt(d.p25, 3)} · median ${fmt(d.median, 3)} · p75 ${fmt(
        d.p75,
        3,
      )} · max ${fmt(d.max, 3)}`}
      style={{ position: 'relative', height: 14, minWidth: 120, background: '#e5e7eb' }}
    >
      <div
        style={{
          position: 'absolute',
          left: `${p25}%`,
          width: `${Math.max(p75 - p25, 1)}%`,
          top: 0,
          bottom: 0,
          background: '#9ca3af',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: `calc(${pos}% - 1px)`,
          top: -2,
          bottom: -2,
          width: 3,
          background: '#2563eb',
        }}
      />
    </div>
  )
}

export function SweepDetailPage() {
  const { id } = useParams()
  const sweepId = Number(id)
  const [sweep, setSweep] = useState<SweepDetailOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<string>('metric')
  const [sortAsc, setSortAsc] = useState(false)
  const [windowFilter, setWindowFilter] = useState<number | 'all'>('all')

  useEffect(() => {
    let cancelled = false
    api
      .getSweep(sweepId)
      .then((s) => !cancelled && setSweep(s))
      .catch((err) => !cancelled && setError(errorDetail(err)))
    return () => {
      cancelled = true
    }
  }, [sweepId])

  const metric = sweep?.selection?.metric ?? 'profit_factor'

  const visible = useMemo(() => {
    if (!sweep) return []
    const rows = sweep.results.filter(
      (r) => windowFilter === 'all' || r.window_index === windowFilter,
    )
    const value = (r: SweepResultOut) =>
      sortKey === 'metric' ? r.metric_value : (r.metrics[sortKey] ?? null)
    return [...rows].sort((a, b) => {
      const va = value(a)
      const vb = value(b)
      if (va == null && vb == null) return a.combo_index - b.combo_index
      if (va == null) return 1
      if (vb == null) return -1
      return sortAsc ? va - vb : vb - va
    })
  }, [sweep, sortKey, sortAsc, windowFilter])

  if (error) {
    return (
      <div className="card">
        <p className="pill loss">{error}</p>
        <p>
          <Link to="/sweeps">← Quay lại danh sách sweeps</Link>
        </p>
      </div>
    )
  }
  if (!sweep) return <p className="muted">Đang tải sweep…</p>

  const isWalkforward = sweep.kind === 'walkforward'
  const graded = sweep.windows.filter((w) => w.degradation != null)
  const avgDegradation = graded.length
    ? graded.reduce((acc, w) => acc + (w.degradation ?? 0), 0) / graded.length
    : null
  const totalCombosTried = isWalkforward
    ? sweep.windows.reduce((acc, w) => acc + w.n_combos, 0)
    : sweep.n_combos

  function sortBy(key: string) {
    if (key === sortKey) setSortAsc((prev) => !prev)
    else {
      setSortKey(key)
      setSortAsc(false)
    }
  }

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="toolbar">
        <Link to="/sweeps">← Sweeps</Link>
        <h2 style={{ margin: 0 }}>
          {sweep.name} — sweep #{sweep.id} ({isWalkforward ? 'walk-forward' : 'grid'})
        </h2>
      </div>

      <div className="card">
        <h2>Thiết lập</h2>
        <div className="stat-row">
          <span className="label">Dataset / symbol / TF</span>
          <span className="value">
            {sweep.dataset_id.slice(0, 8)}… · {sweep.symbol} · {sweep.timeframe}
          </span>
        </div>
        <div className="stat-row">
          <span className="label">Trục tham số</span>
          <span className="value">{sweep.axes.join(', ')}</span>
        </div>
        <div className="stat-row">
          <span className="label">Metric chọn tham số (❓2)</span>
          <span className="value">
            {metric} · max DD ≤ {sweep.selection.max_drawdown_pct}% · số lệnh ≥{' '}
            {sweep.selection.min_trades}
          </span>
        </div>
        <div className="stat-row">
          <span className="label">Tổng số tổ hợp đã thử (mẫu số của selection bias)</span>
          <span className="value">{totalCombosTried}</span>
        </div>
        <div className="stat-row">
          <span className="label">Trạng thái</span>
          <span className="value">
            {sweep.status}
            {sweep.error ? ` — ${sweep.error}` : ''}
          </span>
        </div>
      </div>

      {isWalkforward && (
        <div className="card">
          <h2>Báo cáo overfit — IS vs OOS theo cửa sổ</h2>
          <p className="muted">
            Cột <b>phân bố IS</b> vẽ khoảng [min, max] của metric trên TOÀN BỘ tổ hợp của cửa
            sổ (vùng xám = p25–p75); vạch xanh là tổ hợp thắng. Vạch nằm sát median ⇒ tổ hợp
            thắng chỉ là nhiễu.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>IS</th>
                  <th>OOS</th>
                  <th>Đạt ràng buộc</th>
                  <th>Tham số được chọn</th>
                  <th>IS {metric}</th>
                  <th>OOS {metric}</th>
                  <th>Suy giảm</th>
                  <th>Phân bố IS</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {sweep.windows.map((w) => (
                  <tr key={w.window_index}>
                    <td>{w.window_index}</td>
                    <td>
                      {w.is_from.slice(0, 10)} → {w.is_to.slice(0, 10)}
                    </td>
                    <td>
                      {w.oos_from.slice(0, 10)} → {w.oos_to.slice(0, 10)}
                    </td>
                    <td>
                      {w.n_eligible}/{w.n_combos}
                    </td>
                    <td>{paramsLabel(w.selected_params)}</td>
                    <td>{fmt(w.is_metric, 3)}</td>
                    <td>{fmt(w.oos_metric, 3)}</td>
                    <td
                      className={
                        w.degradation != null && w.degradation < -0.5 ? 'pill loss' : undefined
                      }
                    >
                      {w.degradation == null ? '—' : `${(w.degradation * 100).toFixed(1)}%`}
                    </td>
                    <td>
                      <DistributionBar w={w} />
                    </td>
                    <td>
                      {w.oos_run_id ? (
                        <Link to={`/runs/${w.oos_run_id}/report`}>OOS #{w.oos_run_id}</Link>
                      ) : (
                        <span className="muted">không có tổ hợp đạt</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="stat-row">
            <span className="label">Suy giảm IS→OOS trung bình</span>
            <span className="value">
              {avgDegradation == null ? '—' : `${(avgDegradation * 100).toFixed(1)}%`}
            </span>
          </div>
          <div className="stat-row">
            <span className="label">Cửa sổ có tổ hợp đạt ràng buộc</span>
            <span className="value">
              {sweep.windows.filter((w) => w.oos_run_id != null).length}/{sweep.windows.length}
            </span>
          </div>
          <h2>Equity out-of-sample nối</h2>
          <OosEquityChart points={sweep.oos_equity} />
        </div>
      )}

      {sweep.axes.length === 2 && (
        <div className="card">
          <h2>Heatmap {metric}</h2>
          {isWalkforward && windowFilter === 'all' ? (
            // One cell per (x, y) — with every window merged, the last window silently
            // overwrites the others. Make the user pick one instead of lying quietly.
            <p className="muted">
              Walk-forward có nhiều cửa sổ trên cùng một lưới tham số. Chọn MỘT cửa sổ ở
              bảng bên dưới để xem heatmap của cửa sổ đó.
            </p>
          ) : (
            <Heatmap
              axes={sweep.axes}
              rows={visible.filter((r) => r.phase === 'is')}
              metric={metric}
            />
          )}
        </div>
      )}

      <div className="card">
        <h2>Kết quả từng tổ hợp</h2>
        <div className="toolbar">
          {isWalkforward && (
            <label>
              Cửa sổ:{' '}
              <select
                value={String(windowFilter)}
                onChange={(e) =>
                  setWindowFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))
                }
              >
                <option value="all">tất cả</option>
                {sweep.windows.map((w) => (
                  <option key={w.window_index} value={w.window_index}>
                    #{w.window_index} ({w.is_from.slice(0, 10)})
                  </option>
                ))}
              </select>
            </label>
          )}
          <span className="muted">Click tiêu đề cột để sắp xếp.</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {isWalkforward && <th>Cửa sổ</th>}
                {isWalkforward && <th>Phase</th>}
                <th>Tham số</th>
                <th style={{ cursor: 'pointer' }} onClick={() => sortBy('metric')}>
                  {metric} (chọn)
                </th>
                {METRIC_COLUMNS.map((c) => (
                  <th key={c.key} style={{ cursor: 'pointer' }} onClick={() => sortBy(c.key)}>
                    {c.label}
                  </th>
                ))}
                <th>Đạt ràng buộc</th>
                <th>Run</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr
                  key={r.id}
                  style={r.selected ? { fontWeight: 600, background: 'rgba(37,99,235,0.08)' } : undefined}
                >
                  {isWalkforward && <td>{r.window_index}</td>}
                  {isWalkforward && <td>{r.phase.toUpperCase()}</td>}
                  <td>{paramsLabel(r.params)}</td>
                  <td>{fmt(r.metric_value, 3)}</td>
                  {METRIC_COLUMNS.map((c) => (
                    <td key={c.key}>{fmt(r.metrics[c.key], c.digits)}</td>
                  ))}
                  <td>
                    {r.eligible ? (
                      <span className="pill pass">đạt</span>
                    ) : (
                      <span className="muted" title={r.ineligible_reason}>
                        {r.ineligible_reason || 'không'}
                      </span>
                    )}
                  </td>
                  <td>
                    <Link to={`/runs/${r.run_id}/report`}>#{r.run_id}</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {visible.length === 0 && <p className="muted">Sweep chưa có dòng kết quả nào.</p>}
      </div>
    </div>
  )
}
