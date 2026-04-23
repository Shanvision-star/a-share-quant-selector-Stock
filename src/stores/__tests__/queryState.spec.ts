import { beforeEach, describe, it, expect } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useQueryStateStore } from '@/stores/queryState'

describe('queryState', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('persists results filters in store', () => {
    setActivePinia(createPinia())
    const s = useQueryStateStore()
    s.setResultsKeyword('军工')
    expect(s.results.keyword).toBe('军工')
  })

  it('normalizes invalid persisted snapshot values', () => {
    window.sessionStorage.setItem('query-state-cache-v1', JSON.stringify({
      home: {
        page: 0,
        perPage: -10,
        search: 12,
        sortBy: 'bad-field',
        sortOrder: 'upward',
      },
      results: {
        page: -3,
        perPage: 0,
        runsPage: 'x',
        strategy: 9,
        keyword: false,
        dateRange: ['2026-04-01', 2],
        jRange: [1, '9'],
        similarityRange: [null, 0.8],
        sortBy: 'bad-field',
        sortOrder: 'downward',
      },
    }))

    setActivePinia(createPinia())
    const s = useQueryStateStore()

    expect(s.home).toEqual({
      page: 1,
      perPage: 50,
      search: '',
      sortBy: 'code',
      sortOrder: 'asc',
    })
    expect(s.results).toEqual({
      page: 1,
      perPage: 50,
      runsPage: 1,
      strategy: 'all',
      keyword: '',
      dateRange: null,
      jRange: null,
      similarityRange: null,
      sortBy: 'trade_date',
      sortOrder: 'descending',
    })
  })

  it('keeps valid persisted snapshot values', () => {
    window.sessionStorage.setItem('query-state-cache-v1', JSON.stringify({
      home: {
        page: 3,
        perPage: 100,
        search: '银行',
        sortBy: 'market_cap',
        sortOrder: 'desc',
      },
      results: {
        page: 2,
        perPage: 20,
        runsPage: 4,
        strategy: 'macd_zeroaxis',
        keyword: '平安',
        dateRange: ['2026-04-01', '2026-04-15'],
        jRange: [10, 90],
        similarityRange: [0.2, 0.95],
        sortBy: 'signal_date',
        sortOrder: 'ascending',
      },
    }))

    setActivePinia(createPinia())
    const s = useQueryStateStore()

    expect(s.home).toEqual({
      page: 3,
      perPage: 100,
      search: '银行',
      sortBy: 'market_cap',
      sortOrder: 'desc',
    })
    expect(s.results).toEqual({
      page: 2,
      perPage: 20,
      runsPage: 4,
      strategy: 'macd_zeroaxis',
      keyword: '平安',
      dateRange: ['2026-04-01', '2026-04-15'],
      jRange: [10, 90],
      similarityRange: [0.2, 0.95],
      sortBy: 'signal_date',
      sortOrder: 'ascending',
    })
  })
})
