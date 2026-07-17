import type { DecisionOut } from '../api/types'

export function DecisionLogTable({
  decisions,
  selectedId,
  onSelect,
}: {
  decisions: DecisionOut[]
  selectedId: number | null
  onSelect: (id: number) => void
}) {
  return (
    <div className="card">
      <h2>Decision log ({decisions.length})</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Bar</th>
              <th>Reason</th>
              <th>Stage</th>
              <th>Strategy</th>
              <th>Direction</th>
              <th>Trade</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr
                key={d.id}
                className="clickable"
                style={selectedId === d.id ? { background: 'var(--accent-bg)' } : undefined}
                onClick={() => onSelect(d.id)}
              >
                <td>{d.bar_ts_utc}</td>
                <td>
                  <span className={`pill ${d.reason === 'done' ? 'pass' : 'na'}`}>
                    {d.reason}
                  </span>
                </td>
                <td>{d.stage}</td>
                <td>{d.strategy ?? '—'}</td>
                <td>{d.direction ?? '—'}</td>
                <td>{d.trade_id ? `#${d.trade_id}` : '—'}</td>
              </tr>
            ))}
            {decisions.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  Chưa có decision nào.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
