import { useEffect, useState } from 'react'
import { type FetchError, subscribeFetchErrors } from '../api/errorBus'

/** Renders one toast per failing data source (plan 09 §3): a message plus a Retry button
 * wired to that source's refetch. Mounted once at the app root; the toasts clear
 * themselves when the underlying fetch next succeeds or the page unmounts. */
export function GlobalErrorToasts() {
  const [errors, setErrors] = useState<FetchError[]>([])

  useEffect(() => subscribeFetchErrors(setErrors), [])

  if (errors.length === 0) return null

  return (
    <div className="toast-stack toast-stack-errors">
      {errors.map((e) => (
        <div key={e.key} className="toast toast-error" role="alert">
          <span className="toast-icon">⚠️</span>
          <div className="toast-text">
            <div className="toast-title">Lỗi tải dữ liệu</div>
            <div className="toast-meta">{e.message}</div>
          </div>
          <button className="toast-retry" onClick={e.retry}>
            Thử lại
          </button>
        </div>
      ))}
    </div>
  )
}
