import { useState } from 'react'
import { api } from '../api/client'
import { OpenTradesTable } from '../components/OpenTradesTable'
import { usePolling } from '../hooks/usePolling'

export function TradesPage() {
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [symbolFilter, setSymbolFilter] = useState<string>('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [snapshotTradeId, setSnapshotTradeId] = useState<number | null>(null)

  const { data: config } = usePolling(() => api.getConfig(), 60_000, true)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const symbols: string[] = (config?.config.symbols ?? []).map((s: any) => s.symbol)

  const { data: trades } = usePolling(
    () => api.listTrades(statusFilter || undefined, symbolFilter || undefined),
    2000,
    true,
    [statusFilter, symbolFilter],
  )
  const { data: detail } = usePolling(
    () => (selectedId ? api.getTrade(selectedId) : Promise.resolve(null)),
    2000,
    selectedId !== null,
    [selectedId],
  )

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="toolbar">
        {['', 'PENDING', 'OPEN', 'CLOSED', 'CANCELLED'].map((s) => (
          <button
            key={s || 'ALL'}
            className={statusFilter === s ? 'primary' : ''}
            onClick={() => setStatusFilter(s)}
          >
            {s || 'ALL'}
          </button>
        ))}
      </div>
      {symbols.length > 1 && (
        <div className="toolbar">
          <button className={symbolFilter === '' ? 'primary' : ''} onClick={() => setSymbolFilter('')}>
            ALL symbols
          </button>
          {symbols.map((s) => (
            <button
              key={s}
              className={symbolFilter === s ? 'primary' : ''}
              onClick={() => setSymbolFilter(s)}
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <OpenTradesTable
        trades={trades ?? []}
        onSelect={setSelectedId}
        onOpenSnapshot={setSnapshotTradeId}
      />

      {detail && (
        <div className="card">
          <h2>Trade #{detail.id} — {detail.strategy} {detail.direction}</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Time</th>
                  <th>Price</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {detail.trade_events.map((e) => (
                  <tr key={e.id}>
                    <td>{e.event_type}</td>
                    <td>{e.ts_utc}</td>
                    <td>{e.price ?? '—'}</td>
                    <td>{e.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {snapshotTradeId !== null && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setSnapshotTradeId(null)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            className="card"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '95vw', maxHeight: '95vh', overflow: 'auto' }}
          >
            <div className="toolbar" style={{ justifyContent: 'space-between' }}>
              <h2>Chart trade #{snapshotTradeId}</h2>
              <button onClick={() => setSnapshotTradeId(null)}>Đóng</button>
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <div>
                <div className="muted">Mở lệnh</div>
                <img
                  src={api.tradeSnapshotUrl(snapshotTradeId, 'open')}
                  alt="open snapshot"
                  style={{ maxWidth: '46vw', display: 'block' }}
                  onError={(e) => {
                    e.currentTarget.style.display = 'none'
                  }}
                />
              </div>
              <div>
                <div className="muted">Đóng lệnh</div>
                <img
                  src={api.tradeSnapshotUrl(snapshotTradeId, 'close')}
                  alt="close snapshot"
                  style={{ maxWidth: '46vw', display: 'block' }}
                  onError={(e) => {
                    e.currentTarget.style.display = 'none'
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
