import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { RunCompareOut } from '../api/types'
import { usePolling } from '../hooks/usePolling'

const METRIC_LABELS: Record<string, string> = {
  n_total: 'Số lệnh',
  win_rate: 'Win rate',
  profit_factor: 'Profit factor',
  expectancy_r: 'Expectancy (R)',
  final_equity: 'Equity cuối',
  total_return_pct: 'Return %',
  max_drawdown_pct: 'Max drawdown %',
  sharpe: 'Sharpe',
}

function fmt(x: number | null, digits = 2): string {
  return x == null ? '—' : x.toFixed(digits)
}

function CompareTable({ cmp }: { cmp: RunCompareOut }) {
  return (
    <div className="card">
      <h2>
        So sánh run #{cmp.run_a} vs #{cmp.run_b}
      </h2>
      <p className="muted">
        Dataset: {cmp.same_dataset ? 'giống nhau' : `KHÁC (${cmp.dataset_a} vs ${cmp.dataset_b})`}{' '}
        · Config version:{' '}
        {cmp.same_config_version
          ? 'giống nhau'
          : `KHÁC (v${cmp.config_version_a} vs v${cmp.config_version_b})`}
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Run A (#{cmp.run_a})</th>
              <th>Run B (#{cmp.run_b})</th>
              <th>Δ (B−A)</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(cmp.metrics).map(([key, d]) => (
              <tr key={key}>
                <td>{METRIC_LABELS[key] ?? key}</td>
                <td>{fmt(d.a)}</td>
                <td>{fmt(d.b)}</td>
                <td>{fmt(d.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>Diff histogram reason</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Reason</th>
              <th>A</th>
              <th>B</th>
              <th>Δ</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(cmp.reason_histogram).map(([reason, d]) => (
              <tr key={reason}>
                <td>{reason}</td>
                <td>{d.a}</td>
                <td>{d.b}</td>
                <td>{d.delta}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function RunsPage() {
  const { data: runs, refetch } = usePolling(() => api.listRuns(), 3000, true)
  const [selected, setSelected] = useState<number[]>([])
  const [compare, setCompare] = useState<RunCompareOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  function toggle(id: number) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev.slice(-1), id],
    )
  }

  async function doCompare() {
    if (selected.length !== 2) return
    try {
      setCompare(await api.compareRuns(selected[0], selected[1]))
      setError(null)
    } catch {
      setError('Không so sánh được hai run này.')
    }
  }

  async function doDelete(id: number) {
    if (!window.confirm(`Xoá run #${id}? Toàn bộ trade/decision/equity của run sẽ mất.`)) return
    try {
      await api.deleteRun(id)
      setSelected((prev) => prev.filter((x) => x !== id))
      setCompare(null)
      setError(null)
      void refetch()
    } catch {
      setError(`Không xoá được run #${id} (run đang active không xoá được).`)
    }
  }

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="card">
        <h2>Runs</h2>
        <div className="toolbar">
          <button className="primary" disabled={selected.length !== 2} onClick={doCompare}>
            So sánh 2 run đã chọn
          </button>
          {error && <span className="pill loss">{error}</span>}
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th />
                <th>ID</th>
                <th>Tạo lúc (UTC)</th>
                <th>Dataset</th>
                <th>Config</th>
                <th>Symbol</th>
                <th>Trạng thái</th>
                <th>Bars</th>
                <th>Lệnh đóng</th>
                <th>Equity cuối</th>
                <th>Report</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(runs ?? []).map((r) => (
                <tr key={r.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.includes(r.id)}
                      onChange={() => toggle(r.id)}
                    />
                  </td>
                  <td>{r.id}</td>
                  <td>{r.created_at_utc}</td>
                  <td title={r.dataset_id}>{r.dataset_id.slice(0, 8)}…</td>
                  <td>v{r.config_version}</td>
                  <td>{r.symbol}</td>
                  <td>
                    {r.is_active ? <span className="pill pass">active</span> : r.status}
                  </td>
                  <td>{r.bars_processed}</td>
                  <td>{r.closed_trades}</td>
                  <td>{r.final_equity == null ? '—' : r.final_equity.toFixed(2)}</td>
                  <td>
                    <Link to={`/runs/${r.id}/report`}>Xem report</Link>
                  </td>
                  <td>
                    <button disabled={r.is_active} onClick={() => void doDelete(r.id)}>
                      Xoá
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(runs ?? []).length === 0 && <p className="muted">Chưa có run nào trong DB.</p>}
      </div>
      {compare && <CompareTable cmp={compare} />}
    </div>
  )
}
