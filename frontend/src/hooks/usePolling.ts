import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { errorDetail } from '../api/client'
import { clearFetchError, publishFetchError } from '../api/errorBus'

/** Polls `fetcher` every `intervalMs` while `enabled`; always fetches once on mount/change.
 * A failed fetch is surfaced as a global error toast with a Retry button; a subsequent
 * success clears it. The toast entry is cleared on unmount so a leaving page never leaves
 * a stale error behind. */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  enabled: boolean,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const errorKey = useId()

  const refetch = useCallback(async () => {
    try {
      const result = await fetcherRef.current()
      setData(result)
      setError(null)
      clearFetchError(errorKey)
    } catch (err) {
      setError(err)
      publishFetchError(errorKey, errorDetail(err), () => void refetch())
    }
  }, [errorKey])

  useEffect(() => {
    void refetch()
    if (!enabled) return
    const id = window.setInterval(() => {
      void refetch()
    }, intervalMs)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, refetch, ...deps])

  // Drop this source's toast when the component using it unmounts.
  useEffect(() => () => clearFetchError(errorKey), [errorKey])

  return { data, error, refetch }
}
