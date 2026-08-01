import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { usePolling } from '../hooks/usePolling'

export function SweepsPage() {
  const { data: sweeps } = usePolling(() => api.listSweeps(), 5000, true)

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="card">
        <h2>Sweeps</h2>
        <p className="muted">
          Sweep được chạy từ CLI (một sweep là hàng trăm run, không hợp với một request HTTP):{' '}
          <code>python -m bot.cli sweep --config sweeps/&lt;spec&gt;.yaml</code> hoặc{' '}
          <code>python -m bot.cli walkforward --config sweeps/&lt;spec&gt;.yaml</code>. Trang này
          chỉ đọc kết quả.
        </p>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Tên</th>
                <th>Loại</th>
                <th>Symbol</th>
                <th>TF</th>
                <th>Tổ hợp / cửa sổ</th>
                <th>Số run</th>
                <th>Trạng thái</th>
                <th>Tạo lúc (UTC)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(sweeps ?? []).map((s) => (
                <tr key={s.id}>
                  <td>{s.id}</td>
                  <td>{s.name}</td>
                  <td>{s.kind === 'walkforward' ? 'walk-forward' : 'grid'}</td>
                  <td>{s.symbol}</td>
                  <td>{s.timeframe}</td>
                  <td>{s.n_combos}</td>
                  <td>{s.n_runs}</td>
                  <td>
                    {s.status === 'FAILED' ? (
                      <span className="pill loss" title={s.error ?? ''}>
                        FAILED
                      </span>
                    ) : (
                      s.status
                    )}
                  </td>
                  <td>{s.created_at_utc}</td>
                  <td>
                    <Link to={`/sweeps/${s.id}`}>Xem kết quả</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(sweeps ?? []).length === 0 && <p className="muted">Chưa có sweep nào trong DB.</p>}
      </div>
    </div>
  )
}
