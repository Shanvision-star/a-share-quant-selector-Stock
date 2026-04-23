import { describe, expect, it } from 'vitest'
import { buildMainKlineRequestKey } from '@/components/klineRequest'

describe('buildMainKlineRequestKey', () => {
  it('returns a stable key across different chart params', () => {
    expect(buildMainKlineRequestKey('000001', 'daily', 'qfq')).toBe('kline:render')
    expect(buildMainKlineRequestKey('600000', 'weekly', 'hfq')).toBe('kline:render')
  })
})
