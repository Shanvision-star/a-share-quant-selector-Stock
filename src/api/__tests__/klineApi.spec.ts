import { afterEach, describe, expect, it, vi } from 'vitest'
import api, {
  clearKlineCache,
  getKline,
  getKlineCacheKey,
  getKlinePrefetchQueueState,
  prefetchKline,
  prefetchKlineBatch,
} from '@/api'

async function flushAsyncQueue() {
  await Promise.resolve()
  await Promise.resolve()
  await new Promise(resolve => setTimeout(resolve, 0))
}

describe('getKline', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    clearKlineCache()
  })

  it('forwards AbortSignal to api.get config', async () => {
    const controller = new AbortController()
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: {} } as any)

    await getKline(
      '000001',
      { period: 'daily', limit: 120, adjust: 'qfq' },
      { signal: controller.signal },
    )

    expect(getSpy).toHaveBeenCalledWith('/kline/000001', {
      params: { period: 'daily', limit: 120, adjust: 'qfq' },
      signal: controller.signal,
    })
  })

  it('serves repeated kline requests from the in-memory cache', async () => {
    const response = { data: { data: { bars: [{ date: '2026-04-30' }] } } } as any
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue(response)

    const first = await getKline('000001', { period: 'daily', limit: 500, adjust: 'qfq' })
    const second = await getKline('000001', { period: 'daily', limit: 500, adjust: 'qfq' })

    expect(first).toBe(response)
    expect(second).toBe(response)
    expect(getSpy).toHaveBeenCalledTimes(1)
  })

  it('prefetches kline data into the same cache used by getKline', async () => {
    const response = { data: { data: { bars: [{ date: '2026-04-30' }] } } } as any
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue(response)

    await prefetchKline('000001', { period: 'daily', limit: 500, adjust: 'qfq' })
    const cached = await getKline('000001', { period: 'daily', limit: 500, adjust: 'qfq' })

    expect(cached).toBe(response)
    expect(getKlineCacheKey('000001', { period: 'daily', limit: 500, adjust: 'qfq' })).toBe('000001|daily|qfq|500')
    expect(getSpy).toHaveBeenCalledTimes(1)
  })

  it('evicts the oldest kline cache entries when the cache grows past its limit', async () => {
    const getSpy = vi.spyOn(api, 'get').mockImplementation((url: string) => Promise.resolve({
      data: { data: { bars: [{ date: '2026-04-30', url }] } },
    } as any))

    await getKline('000001', { period: 'daily', limit: 500, adjust: 'qfq' })
    for (let i = 2; i <= 190; i += 1) {
      await getKline(String(i).padStart(6, '0'), { period: 'daily', limit: 500, adjust: 'qfq' })
    }
    await getKline('000001', { period: 'daily', limit: 500, adjust: 'qfq' })

    expect(getSpy.mock.calls.filter(call => call[0] === '/kline/000001')).toHaveLength(2)
  })

  it('queues strategy-day kline prefetches with bounded concurrency and deduped codes', async () => {
    const pending: Array<() => void> = []
    const getSpy = vi.spyOn(api, 'get').mockImplementation(() => new Promise((resolve) => {
      pending.push(() => resolve({ data: { data: { bars: [] } } }))
    }))

    prefetchKlineBatch(
      ['000001', '000002', '000001', '000003'],
      { period: 'daily', limit: 500, adjust: 'qfq' },
      { maxConcurrent: 2 },
    )

    expect(getSpy).toHaveBeenCalledTimes(2)
    expect(getKlinePrefetchQueueState()).toMatchObject({ active: 2, queued: 1 })

    pending.shift()?.()
    await flushAsyncQueue()

    expect(getSpy).toHaveBeenCalledTimes(3)
    expect(getSpy.mock.calls.map(call => call[0])).toEqual([
      '/kline/000001',
      '/kline/000002',
      '/kline/000003',
    ])

    pending.shift()?.()
    pending.shift()?.()
    await flushAsyncQueue()
  })

  it('lets high-priority prefetch jobs jump ahead of the strategy-day queue', async () => {
    const pending: Array<() => void> = []
    const getSpy = vi.spyOn(api, 'get').mockImplementation(() => new Promise((resolve) => {
      pending.push(() => resolve({ data: { data: { bars: [] } } }))
    }))

    prefetchKlineBatch(
      ['000001', '000002'],
      { period: 'daily', limit: 500, adjust: 'qfq' },
      { maxConcurrent: 1 },
    )
    prefetchKlineBatch(
      ['000003'],
      { period: 'daily', limit: 500, adjust: 'qfq' },
      { priority: 'high', maxConcurrent: 1 },
    )

    expect(getSpy.mock.calls.map(call => call[0])).toEqual(['/kline/000001'])

    pending.shift()?.()
    await flushAsyncQueue()

    expect(getSpy.mock.calls.map(call => call[0])).toEqual(['/kline/000001', '/kline/000003'])

    pending.shift()?.()
    pending.shift()?.()
    await flushAsyncQueue()
  })
})
