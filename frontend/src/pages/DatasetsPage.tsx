import { useState } from 'react'
import { api, errorDetail } from '../api/client'
import { usePolling } from '../hooks/usePolling'

export function DatasetsPage() {
  const { data: datasets, refetch } = usePolling(() => api.listDatasets(), 1000, false)

  const [seed, setSeed] = useState(42)
  const [bars, setBars] = useState(2000)
  const [path, setPath] = useState('')
  const [symbol, setSymbol] = useState('EURUSD')
  const [nativeTf, setNativeTf] = useState('15m')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function withBusy(fn: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(errorDetail(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="card">
        <h2>Tạo dataset synthetic</h2>
        <div className="toolbar">
          <label>
            Seed{' '}
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
          </label>
          <label>
            Bars{' '}
            <input type="number" value={bars} onChange={(e) => setBars(Number(e.target.value))} />
          </label>
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              withBusy(async () => {
                await api.createDataset(seed, bars)
                await refetch()
              })
            }
          >
            Tạo
          </button>
        </div>
      </div>

      <div className="card">
        <h2>Import CSV thật</h2>
        <div className="toolbar">
          <label>
            Đường dẫn{' '}
            <input
              type="text"
              placeholder="data/csv/eurusd_15m.csv"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              style={{ width: 260 }}
            />
          </label>
          <label>
            Symbol{' '}
            <input type="text" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          </label>
          <label>
            Native TF{' '}
            <select value={nativeTf} onChange={(e) => setNativeTf(e.target.value)}>
              <option value="15m">15m</option>
              <option value="1H">1H</option>
              <option value="4H">4H</option>
              <option value="1D">1D</option>
            </select>
          </label>
          <button
            className="primary"
            disabled={busy || !path}
            onClick={() =>
              withBusy(async () => {
                await api.importCsv(path, symbol, nativeTf)
                await refetch()
              })
            }
          >
            Import
          </button>
        </div>
        {error && <p className="muted">Lỗi: {error}</p>}
      </div>

      <div className="card">
        <h2>Datasets</h2>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Kind</th>
              <th>Symbol</th>
              <th>TF</th>
              <th>Khoảng thời gian</th>
              <th>Bars</th>
              <th>Gaps</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {(datasets ?? []).map((d) => (
              <tr key={d.id}>
                <td title={d.file_sha256 ?? ''}>{d.id}</td>
                <td>{d.kind}</td>
                <td>{d.symbol ?? '—'}</td>
                <td>{d.native_tf ?? '—'}</td>
                <td>
                  {d.start_ts && d.end_ts ? `${d.start_ts} → ${d.end_ts}` : '—'}
                </td>
                <td>{d.bar_count ?? d.n_candles_15m ?? '—'}</td>
                <td>{d.gap_count ?? '—'}</td>
                <td>{d.created_at_utc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
