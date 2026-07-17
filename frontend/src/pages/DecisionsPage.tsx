import { useState } from 'react'
import { api } from '../api/client'
import { DecisionDetail } from '../components/DecisionDetail'
import { DecisionLogTable } from '../components/DecisionLogTable'
import { usePolling } from '../hooks/usePolling'

export function DecisionsPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: decisions } = usePolling(() => api.listDecisions({ limit: 100 }), 2000, true)
  const { data: stats } = usePolling(() => api.getDecisionStats(), 2000, true)
  const { data: detail } = usePolling(
    () => (selectedId ? api.getDecision(selectedId) : Promise.resolve(null)),
    2000,
    selectedId !== null,
    [selectedId],
  )

  return (
    <div className="grid" style={{ gap: 16 }}>
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
