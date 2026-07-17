import { useState } from 'react'
import { api } from '../api/client'
import { OpenTradesTable } from '../components/OpenTradesTable'
import { usePolling } from '../hooks/usePolling'

export function TradesPage() {
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: trades } = usePolling(
    () => api.listTrades(statusFilter || undefined),
    2000,
    true,
    [statusFilter],
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
      <OpenTradesTable trades={trades ?? []} onSelect={setSelectedId} />

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
    </div>
  )
}
