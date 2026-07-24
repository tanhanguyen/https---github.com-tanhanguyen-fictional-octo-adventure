/** A tiny pub/sub for surfacing fetch failures as toasts (plan 09 §3).
 *
 * `usePolling` publishes here whenever a fetch throws and clears the entry when the next
 * fetch succeeds. A single <GlobalErrorToasts/> subscribes and renders one toast per
 * failing source, each with a Retry button wired to that source's refetch. Keyed by a
 * stable id per hook instance so a poller that keeps failing updates its toast in place
 * instead of stacking a new one every interval.
 */

export interface FetchError {
  key: string
  message: string
  retry: () => void
}

type Listener = (errors: FetchError[]) => void

const errors = new Map<string, FetchError>()
const listeners = new Set<Listener>()

function emit(): void {
  const snapshot = [...errors.values()]
  for (const l of listeners) l(snapshot)
}

export function publishFetchError(key: string, message: string, retry: () => void): void {
  errors.set(key, { key, message, retry })
  emit()
}

export function clearFetchError(key: string): void {
  if (errors.delete(key)) emit()
}

export function subscribeFetchErrors(listener: Listener): () => void {
  listeners.add(listener)
  listener([...errors.values()])
  return () => {
    listeners.delete(listener)
  }
}
