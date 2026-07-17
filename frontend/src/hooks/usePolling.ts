import { useCallback, useEffect, useRef, useState } from 'react'

/** Polls `fetcher` every `intervalMs` while `enabled`; always fetches once on mount/change. */
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

  const refetch = useCallback(async () => {
    try {
      const result = await fetcherRef.current()
      setData(result)
      setError(null)
    } catch (err) {
      setError(err)
    }
  }, [])

  useEffect(() => {
    void refetch()
    if (!enabled) return
    const id = window.setInterval(() => {
      void refetch()
    }, intervalMs)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, refetch, ...deps])

  return { data, error, refetch }
}
