import { describe, expect, it } from 'vitest'
import {
  buildMainKlineRequestKey,
  getNeighborCodes,
  selectFastKlineLimit,
  shouldShowBlockingKlineLoading,
} from '@/components/klineRequest'

describe('buildMainKlineRequestKey', () => {
  it('returns a stable key across different chart params', () => {
    expect(buildMainKlineRequestKey('000001', 'daily', 'qfq')).toBe('kline:render')
    expect(buildMainKlineRequestKey('600000', 'weekly', 'hfq')).toBe('kline:render')
  })

  it('only blocks the chart area while the first kline render is loading', () => {
    expect(shouldShowBlockingKlineLoading(true, false)).toBe(true)
    expect(shouldShowBlockingKlineLoading(true, true)).toBe(false)
    expect(shouldShowBlockingKlineLoading(false, false)).toBe(false)
  })

  it('uses a smaller first kline request when the full chart is not cached', () => {
    expect(selectFastKlineLimit(2600, false)).toBe(500)
    expect(selectFastKlineLimit(2600, true)).toBe(2600)
    expect(selectFastKlineLimit(300, false)).toBe(300)
  })

  it('chooses nearby unique stock codes for prefetching', () => {
    expect(getNeighborCodes(['000001', '000002', '000003', '000004'], '000003', 1)).toEqual(['000002', '000004'])
    expect(getNeighborCodes(['000001', '000002', '000001'], '000001', 2)).toEqual(['000002'])
  })
})
