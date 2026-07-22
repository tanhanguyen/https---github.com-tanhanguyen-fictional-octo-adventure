import { useState } from 'react'
import { api, errorDetail } from '../api/client'
import { FilterConfigPanel } from '../components/FilterConfigPanel'
import { usePolling } from '../hooks/usePolling'

function NewsEventsCard() {
  // Plan 06 §4: show UPCOMING events relative to the active run's clock (its last
  // processed bar). No active run / no bars processed -> fall back to all events.
  const { data: clockPoints } = usePolling(() => api.getEquity(1), 5000, false)
  const clockTs =
    clockPoints && clockPoints.length > 0
      ? clockPoints[clockPoints.length - 1].bar_ts_utc
      : undefined
  const { data: events, refetch } = usePolling(
    () => api.listNews(clockTs),
    5000,
    false,
    [clockTs],
  )
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function doImport() {
    setBusy(true)
    setError(null)
    try {
      await api.importNews(path)
      await refetch()
    } catch (err) {
      setError(errorDetail(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2>Lịch tin tức (filter news)</h2>
      <p className="muted">
        {clockTs
          ? `Sự kiện sắp tới kể từ clock của run hiện tại (${clockTs}).`
          : 'Chưa có run đang chạy — hiển thị toàn bộ sự kiện đã import.'}
      </p>
      <div className="toolbar">
        <label>
          Đường dẫn CSV chuẩn hoá{' '}
          <input
            type="text"
            placeholder="data/news/calendar_2024.csv"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            style={{ width: 280 }}
          />
        </label>
        <button className="primary" disabled={busy || !path} onClick={() => void doImport()}>
          Import
        </button>
      </div>
      {error && <p className="muted">Lỗi: {error}</p>}
      <p className="muted">
        Dùng <code>scripts/convert_news.py</code> để đổi file ForexFactory sang format chuẩn
        (ts_utc, currency, impact, title) trước khi import.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Thời gian (UTC)</th>
              <th>Currency</th>
              <th>Impact</th>
              <th>Sự kiện</th>
            </tr>
          </thead>
          <tbody>
            {(events ?? []).map((e) => (
              <tr key={e.id}>
                <td>{e.ts_utc}</td>
                <td>{e.currency}</td>
                <td>{e.impact}</td>
                <td>{e.title}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function ConfigPage() {
  const { data: schema } = usePolling(() => api.getConfigSchema(), 60_000, false)
  const { data: config, refetch: refetchConfig } = usePolling(() => api.getConfig(), 60_000, false)
  const { data: versions, refetch: refetchVersions } = usePolling(
    () => api.listConfigVersions(),
    60_000,
    false,
    [config?.id],
  )

  function refreshAll() {
    void refetchConfig()
    void refetchVersions()
  }

  return (
    <div className="grid" style={{ gap: 16 }}>
      {schema && config ? (
        <FilterConfigPanel schema={schema} config={config} onChanged={refreshAll} />
      ) : (
        <p className="muted">Đang tải cấu hình...</p>
      )}

      <NewsEventsCard />

      <div className="card">
        <h2>Lịch sử phiên bản config</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>Active</th>
                <th>Created</th>
                <th>Note</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(versions ?? []).map((v) => (
                <tr key={v.id}>
                  <td>v{v.version}</td>
                  <td>{v.is_active ? '✓' : ''}</td>
                  <td>{v.created_at_utc}</td>
                  <td>{v.note}</td>
                  <td>
                    {!v.is_active && (
                      <button
                        onClick={async () => {
                          await api.activateConfigVersion(v.id)
                          refreshAll()
                        }}
                      >
                        Activate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
