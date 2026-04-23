import { afterEach, describe, expect, it, vi } from 'vitest'
import api, { getKline } from '@/api'

describe('getKline', () => {
  afterEach(() => {
    vi.restoreAllMocks()
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
})
