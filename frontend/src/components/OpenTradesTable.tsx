import type { TradeOut } from '../api/types'

function resultPill(trade: TradeOut) {
  if (!trade.result) return <span className="pill na">—</span>
  const cls = trade.result === 'WIN' ? 'win' : trade.result === 'LOSS' ? 'loss' : 'breakeven'
  return <span className={`pill ${cls}`}>{trade.result}</span>
}

export function OpenTradesTable({
  trades,
  onSelect,
}: {
  trades: TradeOut[]
  onSelect?: (id: number) => void
}) {
  return (
    <div className="card">
      <h2>Lệnh ({trades.length})</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Chiến lược</th>
              <th>Hướng</th>
              <th>Trạng thái</th>
              <th>Entry</th>
              <th>SL</th>
              <th>TP1</th>
              <th>Lot</th>
              <th>PnL (R)</th>
              <th>Kết quả</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id} className="clickable" onClick={() => onSelect?.(t.id)}>
                <td>#{t.id}</td>
                <td>{t.strategy}</td>
                <td>{t.direction}</td>
                <td>{t.status}</td>
                <td>{t.entry_price?.toFixed(5) ?? '—'}</td>
                <td>{t.sl_price?.toFixed(5) ?? '—'}</td>
                <td>{t.tp1_price?.toFixed(5) ?? '—'}</td>
                <td>{t.lot_size?.toFixed(2) ?? '—'}</td>
                <td>{t.pnl_r != null ? t.pnl_r.toFixed(2) : '—'}</td>
                <td>{resultPill(t)}</td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan={10} className="muted">
                  Chưa có lệnh nào.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
