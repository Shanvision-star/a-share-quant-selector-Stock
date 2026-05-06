import { describe, expect, it } from 'vitest'

import { buildBrickSegments, buildBrickStackedBars } from '@/utils/klineIndicators'

describe('buildBrickSegments', () => {
  it('builds brick rectangles from previous value to current value', () => {
    expect(buildBrickSegments([null, 5, 8, 6, 0])).toEqual([
      null,
      null,
      { value: [2, 5, 8], itemStyle: { color: '#ff2d2d' } },
      { value: [3, 8, 6], itemStyle: { color: '#15ff00' } },
      { value: [4, 6, 0], itemStyle: { color: '#15ff00' } },
    ])
  })

  it('skips bars with missing endpoints', () => {
    expect(buildBrickSegments([3, null, 4])).toEqual([null, null, null])
  })

  it('builds stacked bar data for native ECharts rendering', () => {
    expect(buildBrickStackedBars([null, 5, 8, 6, 0])).toEqual({
      base: [null, null, 5, 6, 0],
      body: [
        null,
        null,
        { value: 3, itemStyle: { color: '#ff2d2d' } },
        { value: 2, itemStyle: { color: '#15ff00' } },
        { value: 6, itemStyle: { color: '#15ff00' } },
      ],
    })
  })
})
