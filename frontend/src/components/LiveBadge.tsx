import { usePolling } from '../hooks/usePolling'
import { api } from '../api/client'

/**
 * Plan 07 §4: the LIVE badge. It answers three questions at a glance — is a live run
 * up, is its feed healthy, and how stale is the last bar it acted on.
 *
 * Lag is the honest health signal: a live process that is alive but 40 minutes behind
 * on 15m bars is broken even though nothing errored, so lag gets its own colour rather
 * than being buried in a tooltip. The thresholds are relative to nothing in particular
 * — anything past a few minutes means at least one bar was missed on the fastest
 * timeframe the bot runs.
 */
function lagClass(lagSeconds: number | null): string {
  if (lagSeconds === null) return 'live-badge-idle'
  if (lagSeconds > 15 * 60) return 'live-badge-bad'
  if (lagSeconds > 5 * 60) return 'live-badge-warn'
  return 'live-badge-ok'
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  const h = Math.floor(s / 3600)
  const d = Math.floor(h / 24)
  return d > 0 ? `${d}d ${h % 24}h` : `${h}h ${Math.floor((s % 3600) / 60)}m`
}

export function LiveBadge() {
  const { data } = usePolling(() => api.getLiveStatus(), 5000, true)

  if (!data || !data.running) {
    return <span className="live-badge live-badge-idle">no live run</span>
  }

  const degraded = data.feed_state === 'degraded'
  const className = degraded ? 'live-badge-bad' : lagClass(data.lag_seconds)
  const title = [
    `run #${data.run_id} — ${data.symbols.join(', ')}`,
    `feed: ${data.feed_state}${data.detail ? ` (${data.detail})` : ''}`,
    `last bar: ${data.last_bar_ts_utc ?? 'none yet'}`,
    `uptime: ${formatDuration(data.uptime_seconds)}`,
    data.stop_requested ? 'stop requested' : '',
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <span className={`live-badge ${className}`} title={title}>
      ● LIVE
      <span className="live-badge-lag">lag {formatDuration(data.lag_seconds)}</span>
      {degraded && <span className="live-badge-lag">feed degraded</span>}
      {data.stop_requested && <span className="live-badge-lag">stopping…</span>}
    </span>
  )
}
