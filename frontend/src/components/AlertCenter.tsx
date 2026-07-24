import { useEffect, useRef, useState } from 'react'
import { useAlertCenter } from '../hooks/useAlertCenter'
import type { AlertOut } from '../api/types'

/**
 * Plan 13's alert UI: a bell with an unread badge in the header, and a fixed toast
 * stack for anything that arrives while you are looking.
 *
 * Written by hand rather than pulled from sonner/react-hot-toast (decision recorded in
 * docs/decisions.md): the whole surface is ~150 lines, it reuses the existing CSS
 * variables so light/dark keeps working for free, and it avoids adding a runtime
 * dependency to an app whose other three dependencies are react, router and axios.
 *
 * Severity is the only thing the visual language encodes: INFO fades out on its own,
 * WARN stays long enough to notice, ERROR/CRITICAL do not leave until dismissed.
 */

const LEVEL_ICON: Record<string, string> = {
  INFO: 'ℹ️',
  WARN: '⚠️',
  ERROR: '⛔',
  CRITICAL: '🛑',
}

function timeOf(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString()
}

/** The few body fields worth showing under the title, in a stable order. */
const BODY_KEYS = ['symbol', 'result', 'pnl_r', 'pnl_amount', 'equity', 'detail']

function bodyLine(alert: AlertOut): string {
  const parts = BODY_KEYS.filter((k) => alert.body[k] !== undefined && alert.body[k] !== null).map(
    (k) => `${k}=${String(alert.body[k])}`,
  )
  return parts.join('  ')
}

function Toast({ alert, onClose }: { alert: AlertOut; onClose: () => void }) {
  return (
    <div className={`toast toast-${alert.level.toLowerCase()}`} role="alert">
      <span className="toast-icon">{LEVEL_ICON[alert.level] ?? '•'}</span>
      <div className="toast-text">
        <div className="toast-title">{alert.title}</div>
        <div className="toast-meta">
          {alert.code} · {timeOf(alert.ts_utc)}
          {bodyLine(alert) ? ` · ${bodyLine(alert)}` : ''}
        </div>
      </div>
      <button className="toast-close" onClick={onClose} aria-label="đóng">
        ×
      </button>
    </div>
  )
}

export function AlertCenter() {
  const { toasts, history, unread, dismiss, markRead, refreshHistory } = useAlertCenter()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    void refreshHistory()
    const onClickAway = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickAway)
    return () => document.removeEventListener('mousedown', onClickAway)
  }, [open, refreshHistory])

  const unreadIds = history.filter((a) => !a.read).map((a) => a.id)

  return (
    <div className="alert-center" ref={rootRef}>
      <button
        className="alert-bell"
        onClick={() => setOpen((v) => !v)}
        title="Cảnh báo"
        aria-label={`Cảnh báo (${unread} chưa đọc)`}
      >
        🔔
        {unread > 0 && <span className="alert-badge">{unread > 99 ? '99+' : unread}</span>}
      </button>

      {open && (
        <div className="alert-dropdown">
          <div className="alert-dropdown-head">
            <strong>Cảnh báo</strong>
            <button
              className="alert-mark-read"
              disabled={unreadIds.length === 0}
              onClick={() => void markRead(unreadIds)}
            >
              Đánh dấu đã đọc ({unreadIds.length})
            </button>
          </div>
          {history.length === 0 && <div className="alert-empty muted">Chưa có cảnh báo nào.</div>}
          <ul className="alert-list">
            {history.map((a) => (
              <li
                key={a.id}
                className={`alert-item alert-${a.level.toLowerCase()}${a.read ? ' alert-read' : ''}`}
              >
                <span className="alert-item-icon">{LEVEL_ICON[a.level] ?? '•'}</span>
                <div>
                  <div className="alert-item-title">{a.title}</div>
                  <div className="alert-item-meta muted">
                    {a.code} · {timeOf(a.ts_utc)}
                    {a.source ? ` · ${a.source}${a.run_id != null ? `#${a.run_id}` : ''}` : ''}
                    {a.sent_telegram ? ' · ✈️' : ''}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/*
       * Toasts are hidden while the dropdown is open: both live in the top-right
       * corner, and a CRITICAL toast (which never auto-dismisses) would otherwise sit
       * on top of the very list the user opened to read. Nothing is lost — the
       * dropdown shows the same alerts — and an undismissed toast comes back when the
       * dropdown closes.
       */}
      {!open && (
        <div className="toast-stack">
          {toasts.map((a) => (
            <Toast key={a.id} alert={a} onClose={() => dismiss(a.id)} />
          ))}
        </div>
      )}
    </div>
  )
}
