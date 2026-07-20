import type { AccountOut } from '../api/types'

function fmt(n: number, digits = 2): string {
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function AccountPanel({ account }: { account: AccountOut | null }) {
  if (!account) return <p className="muted">Đang tải...</p>

  return (
    <div className="card">
      <h2>Tài khoản</h2>
      <div className="stat-row">
        <span className="label">Equity</span>
        <span className="value">{fmt(account.equity)}</span>
      </div>
      <div className="stat-row">
        <span className="label">Balance</span>
        <span className="value">{fmt(account.balance)}</span>
      </div>
      <div className="stat-row">
        <span className="label">Drawdown</span>
        <span className="value">{fmt(account.drawdown_pct)}%</span>
      </div>
      <div className="stat-row">
        <span className="label">Lệnh đang mở</span>
        <span className="value">{account.open_trades}</span>
      </div>
      {Object.keys(account.open_trades_by_symbol).length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Lệnh mở</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(account.open_trades_by_symbol).map(([sym, n]) => (
                <tr key={sym}>
                  <td>{sym}</td>
                  <td>{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {account.max_total_open_risk_pct != null && (
        <div className="stat-row">
          <span className="label">Tổng risk đang mở</span>
          <span className="value">
            {account.open_risk_pct_total.toFixed(2)}% / {account.max_total_open_risk_pct.toFixed(2)}%
          </span>
        </div>
      )}
      <div className="stat-row">
        <span className="label">Thua liên tiếp</span>
        <span className="value">{account.consecutive_losses}</span>
      </div>
      <div className="stat-row">
        <span className="label">Thắng liên tiếp</span>
        <span className="value">{account.consecutive_wins}</span>
      </div>
      <div className="stat-row">
        <span className="label">Thua hôm nay</span>
        <span className="value">
          {account.daily_loss_count}
          {account.daily_losses_remaining >= 0
            ? ` (còn ${account.daily_losses_remaining})`
            : ' (không giới hạn)'}
        </span>
      </div>
      <div className="stat-row">
        <span className="label">Ngày giao dịch</span>
        <span className="value">{account.current_trading_day ?? '—'}</span>
      </div>
      <div className="stat-row">
        <span className="label">Bot</span>
        <span className="value">
          {account.bot_enabled ? 'ON' : `OFF (${account.blocked_reason ?? ''})`}
        </span>
      </div>
    </div>
  )
}
