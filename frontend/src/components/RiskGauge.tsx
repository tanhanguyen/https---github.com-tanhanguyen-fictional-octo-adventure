import type { AccountOut } from '../api/types'

export function RiskGauge({ account }: { account: AccountOut | null }) {
  if (!account) return <p className="muted">Đang tải...</p>

  const riskPct = Math.min(100, (account.current_risk_pct / 3) * 100)
  const drawdownPct = Math.min(100, account.drawdown_pct)

  return (
    <div className="card">
      <h2>Rủi ro</h2>
      <p className="muted">Risk per trade: {account.current_risk_pct.toFixed(2)}%</p>
      <div className="gauge-track">
        <div className="gauge-fill" style={{ width: `${riskPct}%` }} />
      </div>
      <p className="muted" style={{ marginTop: 12 }}>
        Drawdown: {account.drawdown_pct.toFixed(2)}%
      </p>
      <div className="gauge-track">
        <div
          className="gauge-fill"
          style={{ width: `${drawdownPct}%`, background: '#dc2626' }}
        />
      </div>
      <p className="muted" style={{ marginTop: 12 }}>
        Risk multiplier (equity curve): {account.risk_multiplier.toFixed(2)}x
      </p>
    </div>
  )
}
