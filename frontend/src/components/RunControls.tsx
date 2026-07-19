import { useState } from 'react'
import { api } from '../api/client'
import type { RunOut } from '../api/types'
import { usePolling } from '../hooks/usePolling'

interface Props {
  run: RunOut | null
  onChanged: () => void
}

export function RunControls({ run, onChanged }: Props) {
  const [seed, setSeed] = useState(42)
  const [bars, setBars] = useState(2000)
  const [datasetId, setDatasetId] = useState('')
  const [busy, setBusy] = useState(false)
  const [lastReason, setLastReason] = useState<string | null>(null)
  const { data: datasets } = usePolling(() => api.listDatasets(), 1000, false)

  async function withBusy(fn: () => Promise<void>) {
    setBusy(true)
    try {
      await fn()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2>Điều khiển chạy bot</h2>
      <div className="toolbar">
        <label>
          Dataset{' '}
          <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
            <option value="">(synthetic seed/bars)</option>
            {(datasets ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.kind === 'csv' ? `${d.symbol} ${d.native_tf} (${d.id})` : `synthetic (${d.id})`}
              </option>
            ))}
          </select>
        </label>
        <label>
          Seed{' '}
          <input
            type="number"
            disabled={Boolean(datasetId)}
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
          />
        </label>
        <label>
          Bars{' '}
          <input
            type="number"
            value={bars}
            onChange={(e) => setBars(Number(e.target.value))}
          />
        </label>
        <button
          className="primary"
          disabled={busy}
          onClick={() =>
            withBusy(async () => {
              await api.createRun(seed, bars, datasetId || undefined)
              onChanged()
            })
          }
        >
          New Run
        </button>
      </div>
      <div className="toolbar">
        <button
          disabled={busy || !run}
          onClick={() =>
            withBusy(async () => {
              const summary = await api.step()
              setLastReason(`${summary.reason} / ${summary.stage}`)
              onChanged()
            })
          }
        >
          Step
        </button>
        <button
          disabled={busy || !run || run.is_playing}
          onClick={() =>
            withBusy(async () => {
              await api.play(150)
              onChanged()
            })
          }
        >
          Play
        </button>
        <button
          disabled={busy || !run || !run.is_playing}
          onClick={() =>
            withBusy(async () => {
              await api.pause()
              onChanged()
            })
          }
        >
          Pause
        </button>
        <button
          disabled={busy || !run}
          onClick={() =>
            withBusy(async () => {
              await api.reset()
              setLastReason(null)
              onChanged()
            })
          }
        >
          Reset
        </button>
      </div>
      <p className="muted">
        Run #{run?.id ?? '—'} · {run?.status ?? 'no active run'}
        {run?.is_playing ? ' · PLAYING' : ''}
      </p>
      {lastReason && <p className="muted">Last decision: {lastReason}</p>}
    </div>
  )
}
