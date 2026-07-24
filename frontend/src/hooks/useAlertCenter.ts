import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AlertOut } from '../api/types'

/** How often the alert log is polled. Plan 13 says ~10s; there is no push channel. */
const POLL_MS = 10_000

/** How many rows the bell dropdown keeps in memory. */
const HISTORY_LIMIT = 50

/**
 * Auto-dismiss per level. CRITICAL and ERROR are `null` on purpose: an alert that says
 * a position was closed naked, or that the bot reverted to paper, must still be on
 * screen when the user comes back to the desk — it goes away when they dismiss it.
 */
const TOAST_TTL_MS: Record<string, number | null> = {
  INFO: 6_000,
  WARN: 20_000,
  ERROR: null,
  CRITICAL: null,
}

/**
 * Plan 13's web-UI half: poll `since_id`, toast what is new, count what is unread.
 *
 * The first poll deliberately toasts NOTHING. It only learns the current cursor —
 * otherwise opening the dashboard after a week away would bury the screen under a
 * week of history, which trains people to dismiss alerts without reading them. History
 * is still there in the bell dropdown; the toast is for "since you were looking".
 */
export function useAlertCenter() {
  const [toasts, setToasts] = useState<AlertOut[]>([])
  const [history, setHistory] = useState<AlertOut[]>([])
  const [unread, setUnread] = useState(0)
  const cursorRef = useRef<number | null>(null)
  /** Live auto-dismiss timers, keyed by alert id (see the effect below). */
  const timersRef = useRef(new Map<number, number>())

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((a) => a.id !== id))
  }, [])

  const poll = useCallback(async () => {
    try {
      const since = cursorRef.current
      const data = await api.listAlerts({
        ...(since !== null ? { since_id: since } : {}),
        limit: HISTORY_LIMIT,
      })
      setUnread(data.unread)
      const firstPoll = since === null
      cursorRef.current = data.max_id
      if (firstPoll) {
        setHistory(data.alerts)
        return
      }
      if (data.alerts.length === 0) return
      // The API returns newest-first; toast oldest-first so the stack reads top-down.
      const fresh = [...data.alerts].reverse()
      setToasts((current) => [...current, ...fresh])
      setHistory((current) => [...data.alerts, ...current].slice(0, HISTORY_LIMIT))
    } catch {
      // A failed poll is not worth a toast of its own — the LIVE badge already shows
      // when the backend is unreachable, and retrying in 10s is the whole fix.
    }
  }, [])

  useEffect(() => {
    void poll()
    const id = window.setInterval(() => void poll(), POLL_MS)
    return () => window.clearInterval(id)
  }, [poll])

  // Auto-dismiss timers: exactly ONE per toast, armed when it first appears. Arming
  // them from the array wholesale would restart every countdown each time a new alert
  // arrives, so a busy minute would keep old INFO toasts on screen indefinitely.
  useEffect(() => {
    const timers = timersRef.current
    for (const alert of toasts) {
      const ttl = TOAST_TTL_MS[alert.level]
      if (ttl == null || timers.has(alert.id)) continue
      timers.set(
        alert.id,
        window.setTimeout(() => {
          timers.delete(alert.id)
          dismiss(alert.id)
        }, ttl),
      )
    }
  }, [toasts, dismiss])

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      timers.forEach((t) => window.clearTimeout(t))
      timers.clear()
    }
  }, [])

  const markRead = useCallback(async (ids: number[]) => {
    if (ids.length === 0) return
    try {
      const result = await api.markAlertsRead(ids)
      setUnread(result.unread)
      setHistory((current) =>
        current.map((a) => (ids.includes(a.id) ? { ...a, read: true } : a)),
      )
    } catch {
      // Leave the badge as-is; the next poll re-reads the authoritative count.
    }
  }, [])

  /** Reload the dropdown's history on open, so it shows more than this session. */
  const refreshHistory = useCallback(async () => {
    try {
      const data = await api.listAlerts({ limit: HISTORY_LIMIT })
      setHistory(data.alerts)
      setUnread(data.unread)
    } catch {
      /* keep whatever is on screen */
    }
  }, [])

  return { toasts, history, unread, dismiss, markRead, refreshHistory }
}
