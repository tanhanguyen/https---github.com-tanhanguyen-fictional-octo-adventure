import { useState } from 'react'
import { api, errorDetail } from '../api/client'
import { AccountPanel } from '../components/AccountPanel'
import { CandleChart } from '../components/CandleChart'
import { EquityChart } from '../components/EquityChart'
import { OpenTradesTable } from '../components/OpenTradesTable'
import { RiskGauge } from '../components/RiskGauge'
import { RunControls } from '../components/RunControls'
import { usePolling } from '../hooks/usePolling'

const CHART_TIMEFRAMES = ['15m', '1H', '4H', '1D']

export function Dashboard() {
  const [chartTf, setChartTf] = useState('1H')
  const { data: run, refetch: refetchRun } = usePolling(() => api.getRun(), 1000, true)
  const { data: account, refetch: refetchAccount } = usePolling(
    () => api.getAccount(),
    1000,
    Boolean(run?.is_playing),
    [run?.id],
  )
  const { data: equity, refetch: refetchEquity } = usePolling(
    () => api.getEquity(300),
    1000,
    Boolean(run?.is_playing),
    [run?.id],
  )
  const { data: trades, refetch: refetchTrades } = usePolling(
    () => api.listTrades(),
    1000,
    Boolean(run?.is_playing),
    [run?.id],
  )
  const { data: bars, error: barsError, refetch: refetchBars } = usePolling(
    () => (run ? api.getRunBars(run.id, chartTf) : Promise.resolve([])),
    1000,
    Boolean(run?.is_playing),
    [run?.id, chartTf],
  )

  function refreshAll() {
    void refetchRun()
    void refetchAccount()
    void refetchEquity()
    void refetchTrades()
    void refetchBars()
  }

  return (
    <div className="grid" style={{ gap: 16 }}>
      <RunControls run={run ?? null} onChanged={refreshAll} />
      <div className="grid grid-2">
        <AccountPanel account={account} />
        <RiskGauge account={account} />
      </div>
      <div className="card">
        <div className="toolbar">
          <h2 style={{ margin: 0 }}>Chart nến + trade markers</h2>
          <select value={chartTf} onChange={(e) => setChartTf(e.target.value)}>
            {CHART_TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </div>
        {!run ? (
          <p className="muted">Chưa có run — tạo run để xem chart.</p>
        ) : barsError ? (
          <p className="pill loss">{errorDetail(barsError)}</p>
        ) : (
          <CandleChart bars={bars ?? []} trades={trades ?? []} />
        )}
      </div>
      <div className="card">
        <h2>Equity curve</h2>
        <EquityChart points={equity ?? []} />
      </div>
      <OpenTradesTable trades={trades ?? []} />
    </div>
  )
}
