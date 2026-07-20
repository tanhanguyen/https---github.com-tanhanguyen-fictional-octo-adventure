import { useState } from 'react'
import { api } from '../api/client'
import { DecisionDetail } from '../components/DecisionDetail'
import { DecisionLogTable } from '../components/DecisionLogTable'
import { usePolling } from '../hooks/usePolling'

export function DecisionsPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [symbolFilter, setSymbolFilter] = useState<string>('')

  const { data: config } = usePolling(() => api.getConfig(), 60_000, true)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const symbols: string[] = (config?.config.symbols ?? []).map((s: any) => s.symbol)

  const { data: decisions } = usePolling(
    () => api.listDecisions({ limit: 100, symbol: symbolFilter || undefined }),
    2000,
    true,
    [symbolFilter],
  )
  const { data: stats } = usePolling(() => api.getDecisionStats(), 2000, true)
  const { data: detail } = usePolling(
    () => (selectedId ? api.getDecision(selectedId) : Promise.resolve(null)),
    2000,
    selectedId !== null,
    [selectedId],
  )

  return (
    <div className="grid" style={{ gap: 16 }}>
      {symbols.length > 1 && (
        <div className="toolbar">
          <button className={symbolFilter === '' ? 'primary' : ''} onClick={() => setSymbolFilter('')}>
            ALL
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
      <div className="card">
        <h2>Vì sao không có lệnh? (histogram)</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Reason</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats?.histogram ?? {})
                .sort((a, b) => b[1] - a[1])
                .map(([reason, count]) => (
                  <tr key={reason}>
                    <td>{reason}</td>
                    <td>{count}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="two-col">
        <DecisionLogTable
          decisions={decisions ?? []}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <DecisionDetail decision={detail ?? null} />
      </div>
    </div>
  )
}
