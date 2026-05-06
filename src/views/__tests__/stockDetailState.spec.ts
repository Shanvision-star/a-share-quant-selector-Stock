import { describe, expect, it } from 'vitest'
import {
  createStockDetailLoadGuard,
  getDisplayStockName,
  normalizeStockCode,
} from '@/views/stockDetailState'

describe('stockDetailState', () => {
  it('treats older stock detail loads as stale after a newer code starts loading', () => {
    const guard = createStockDetailLoadGuard()
    const first = guard.start('000767')
    const second = guard.start('000889')

    expect(guard.isCurrent(first, '000889')).toBe(false)
    expect(guard.isCurrent(second, '000889')).toBe(true)
  })

  it('does not show a stale price name for the current route code', () => {
    expect(getDisplayStockName(
      { code: '000767', name: '晋控电力' },
      '000889',
      '中嘉博创',
    )).toBe('中嘉博创')
  })

  it('uses the price name when it belongs to the current route code', () => {
    expect(getDisplayStockName(
      { code: '000889', name: '中嘉博创' },
      '000889',
      '列表名称',
    )).toBe('中嘉博创')
  })

  it('normalizes common stock code formats before comparing names', () => {
    expect(normalizeStockCode('000889.SZ')).toBe('000889')
    expect(normalizeStockCode('SH600000')).toBe('600000')
    expect(normalizeStockCode(null)).toBe('')
  })
})
