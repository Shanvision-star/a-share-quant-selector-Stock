import { describe, expect, it } from 'vitest'
import {
  buildVolumeAxisScaleForZoom,
  calculateVolumeAxisScale,
  pickVisibleVolumeValues,
} from '@/utils/klineVolumeScale'

describe('klineVolumeScale', () => {
  it('keeps a normal linear axis when volume values are in the same range', () => {
    const scale = calculateVolumeAxisScale([100, 120, 130, 150])

    expect(scale.capped).toBe(false)
    expect(scale.max).toBeGreaterThan(150)
  })

  it('caps isolated volume spikes so regular bars remain readable', () => {
    const regular = Array.from({ length: 30 }, (_, index) => 100 + index)
    const scale = calculateVolumeAxisScale([...regular, 12000])

    expect(scale.capped).toBe(true)
    expect(scale.max).toBeLessThan(12000)
    expect(scale.max).toBeGreaterThan(Math.max(...regular))
  })

  it('uses the current zoom window instead of distant off-screen spikes', () => {
    const values = [15000, 100, 110, 120, 130, 140]

    expect(pickVisibleVolumeValues(values, 6, 50, 100)).toEqual([120, 130, 140])
    expect(buildVolumeAxisScaleForZoom(values, 6, 50, 100).max).toBeLessThan(1000)
  })
})
