import type { DecisionDetailOut } from '../api/types'

function passPill(passed: boolean | null) {
  if (passed === null) return <span className="pill na">N/A</span>
  return <span className={`pill ${passed ? 'pass' : 'blocking'}`}>{passed ? 'PASS' : 'FAIL'}</span>
}

export function DecisionDetail({ decision }: { decision: DecisionDetailOut | null }) {
  if (!decision) {
    return (
      <div className="card">
        <h2>Chi tiết decision</h2>
        <p className="muted">Chọn một dòng trong decision log để xem chi tiết.</p>
      </div>
    )
  }

  return (
    <div className="card">
      <h2>
        Decision #{decision.id} — {decision.reason} / {decision.stage}
      </h2>
      <p className="muted">{decision.detail}</p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Filter</th>
              <th>Kind</th>
              <th>Enabled</th>
              <th>Đánh giá</th>
              <th>Kết quả</th>
              <th>Chặn?</th>
              <th>Chi tiết</th>
            </tr>
          </thead>
          <tbody>
            {decision.filters.map((f) => (
              <tr key={f.id} className={f.blocking ? 'row-blocking' : undefined}>
                <td>{f.filter_id}</td>
                <td>{f.kind}</td>
                <td>{f.enabled ? 'ON' : 'OFF'}</td>
                <td>{f.evaluated ? 'yes' : 'no'}</td>
                <td>{passPill(f.passed)}</td>
                <td>{f.blocking ? <span className="pill blocking">BLOCKING</span> : ''}</td>
                <td>{f.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
