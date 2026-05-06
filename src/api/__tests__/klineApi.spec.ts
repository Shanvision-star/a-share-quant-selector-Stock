import { afterEach, describe, expect, it, vi } from 'vitest'
import api, {
  clearKlineCache,
  getKline,
  getKlineCacheKey,
  prefetchKline,
} from '@/api'

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
})
