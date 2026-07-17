import { api } from '../api/client'
import { AccountPanel } from '../components/AccountPanel'
import { EquityChart } from '../components/EquityChart'
import { OpenTradesTable } from '../components/OpenTradesTable'
import { RiskGauge } from '../components/RiskGauge'
import { RunControls } from '../components/RunControls'
import { usePolling } from '../hooks/usePolling'

export function Dashboard() {
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

  function refreshAll() {
    void refetchRun()
    void refetchAccount()
    void refetchEquity()
    void refetchTrades()
  }

  return (
    <div className="grid" style={{ gap: 16 }}>
      <RunControls run={run ?? null} onChanged={refreshAll} />
      <div className="grid grid-2">
        <AccountPanel account={account} />
        <RiskGauge account={account} />
      </div>
      <div className="card">
        <h2>Equity curve</h2>
        <EquityChart points={equity ?? []} />
      </div>
      <OpenTradesTable trades={trades ?? []} />
    </div>
  )
}
