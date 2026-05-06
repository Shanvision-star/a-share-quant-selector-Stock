import { describe, expect, it, vi } from 'vitest'
import {
  buildStrategyGroups,
  buildUniqueStrategyList,
  fetchAllStrategyResultItems,
  formatSimilarityPercent,
} from '@/utils/strategyResults'

describe('strategyResults utils', () => {
  it('fetches all paginated strategy results before building list', async () => {
    const fetchPage = vi.fn(async (params: Record<string, unknown>) => {
      const page = Number(params.page || 1)
      if (page === 1) {
        return {
          items: Array.from({ length: 50 }, (_, i) => ({ code: `000${i}`, name: `A${i}` })),
          total: 130,
          page: 1,
          per_page: 50,
        }
      }
      if (page === 2) {
        return {
          items: Array.from({ length: 50 }, (_, i) => ({ code: `100${i}`, name: `B${i}` })),
          total: 130,
          page: 2,
          per_page: 50,
        }
      }
      return {
        items: Array.from({ length: 30 }, (_, i) => ({ code: `200${i}`, name: `C${i}` })),
        total: 130,
        page: 3,
        per_page: 50,
      }
    })

    const items = await fetchAllStrategyResultItems(fetchPage, { strategy: 'all' }, { pageSize: 50 })
    expect(items).toHaveLength(130)
    expect(fetchPage).toHaveBeenCalledTimes(3)
  })

  it('deduplicates by code and preserves first item similarity', () => {
    const unique = buildUniqueStrategyList([
      { code: '000001', name: 'A', similarity_score: 0.85 },
      { code: '000001', name: 'A2', similarity_score: 0.2 },
      { code: '000002', name: 'B', similarity_score: 0 },
    ])

    expect(unique).toHaveLength(2)
    expect(unique[0].code).toBe('000001')
    expect(unique[0].similarity_score).toBe(0.85)
    expect(unique[1].code).toBe('000002')
  })

  it('formats similarity with normalized percentage output', () => {
    expect(formatSimilarityPercent(null)).toBe('-')
    expect(formatSimilarityPercent(undefined)).toBe('-')
    expect(formatSimilarityPercent(0)).toBe('0%')
    expect(formatSimilarityPercent(0.73)).toBe('73%')
    expect(formatSimilarityPercent(73)).toBe('73%')
  })

  it('groups strategy rows with per-strategy de-duplicated stocks', () => {
    const groups = buildStrategyGroups([
      { code: '000001', name: 'A', strategy_filter: 'b1', strategy_name: 'B1CaseAnalyzer' },
      { code: '000001', name: 'A', strategy_filter: 'b1', strategy_name: 'B1CaseAnalyzer', category: 'stage_b1_setup' },
      { code: '000001', name: 'A', strategy_filter: 'b2', strategy_name: 'B2Strategy' },
      { code: '000002', name: 'B', strategy_filter: 'bowl', strategy_name: 'BowlReboundStrategy' },
      { code: '000003', name: 'C', strategy_filter: 'brick', strategy_name: 'BrickPatternStrategy', category: 'brick_trend_reversal' },
    ])

    expect(groups.map(group => group.key)).toEqual(['b1', 'b2', 'bowl', 'brick'])
    expect(groups[0].signalCount).toBe(2)
    expect(groups[0].uniqueCount).toBe(1)
    expect(groups[0].overlapCount).toBe(1)
    expect(groups[1].items.map(item => item.code)).toEqual(['000001'])
    expect(groups[2].label).toBe('碗底反弹')
    expect(groups[3].label).toBe('砖型图')
    expect(groups[3].items.map(item => item.code)).toEqual(['000003'])
  })
})
