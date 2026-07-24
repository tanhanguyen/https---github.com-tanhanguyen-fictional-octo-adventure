import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePolling } from './usePolling'

describe('usePolling', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('does not keep polling after unmount (no interval leak)', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { unmount } = renderHook(() => usePolling(fetcher, 1000, true))

    // Initial fetch on mount.
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))

    // A couple of interval ticks while mounted.
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(fetcher).toHaveBeenCalledTimes(3)

    unmount()
    const callsAtUnmount = fetcher.mock.calls.length

    // Advancing well past several intervals must NOT trigger further fetches.
    await act(() => vi.advanceTimersByTimeAsync(5000))
    expect(fetcher).toHaveBeenCalledTimes(callsAtUnmount)
  })

  it('does not set up an interval when disabled (fetches once only)', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    renderHook(() => usePolling(fetcher, 1000, false))

    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    await act(() => vi.advanceTimersByTimeAsync(5000))
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})

// A plain (non-fake-timer) block for the error-bus integration.
describe('usePolling error surfacing', () => {
  it('reports a fetch error and recovers on the next success', async () => {
    const { clearFetchError } = await import('../api/errorBus')
    clearFetchError('any') // ensure module loaded

    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValue('ok')

    const { result } = renderHook(() => usePolling(fetcher, 1000, false))

    await waitFor(() => expect(result.current.error).not.toBeNull())

    await act(() => result.current.refetch())
    await waitFor(() => expect(result.current.error).toBeNull())
  })
})
