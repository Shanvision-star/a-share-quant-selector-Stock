import { describe, expect, it } from 'vitest'
import {
  createStockDetailLoadGuard,
  getDisplayStockName,
  getStockSequenceState,
  isStockDetailPayloadCurrent,
  normalizeStockCode,
  shouldShowInitialStockDetailLoading,
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

  it('detects stale stock detail payloads during fast route switches', () => {
    expect(isStockDetailPayloadCurrent({ code: '000767', name: '晋控电力' }, '000889')).toBe(false)
    expect(isStockDetailPayloadCurrent({ ts_code: '000889.SZ', name: '中嘉博创' }, '000889')).toBe(true)
    expect(isStockDetailPayloadCurrent(null, '000889')).toBe(false)
  })

  it('only shows the blocking detail loader before the first successful detail render', () => {
    expect(shouldShowInitialStockDetailLoading(true, false)).toBe(true)
    expect(shouldShowInitialStockDetailLoading(true, true)).toBe(false)
    expect(shouldShowInitialStockDetailLoading(false, false)).toBe(false)
  })

  it('builds previous and next stock navigation from the deduped strategy order', () => {
    const state = getStockSequenceState([
      { code: '000070', name: '特发信息' },
      { code: '000070', name: '特发信息', strategy_name: 'B2' },
      { code: '000559', name: '万向钱潮' },
      { code: '600595.SH', name: '中孚实业' },
    ], '000559')

    expect(state.total).toBe(3)
    expect(state.currentIndex).toBe(1)
    expect(state.prevCode).toBe('000070')
    expect(state.nextCode).toBe('600595')
  })
})
