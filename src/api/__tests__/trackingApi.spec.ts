import { afterEach, describe, expect, it, vi } from 'vitest'
import api, {
  createTrackingItem,
  evaluateTrackingItem,
  listTrackingItems,
  type TrackingCreatePayload,
} from '@/api'

const payload: TrackingCreatePayload = {
  code: '000559',
  name: '万向钱潮',
  strategy_name: 'BowlReboundStrategy',
  source: 'manual',
  source_date: '2026-05-01',
  signal_date: '2026-04-30',
  params: { buy_offset_days: 1 },
}

describe('tracking API', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('creates a tracking item', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: { tracking_id: 'trk_test' } } } as any)

    await createTrackingItem(payload)

    expect(postSpy).toHaveBeenCalledWith('/tracking', payload)
  })

  it('lists and evaluates tracking items', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: { success: true, data: { items: [] } } } as any)
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: { next_action: 'BUY' } } } as any)

    await listTrackingItems({ status: 'all', limit: 20 })
    await evaluateTrackingItem('trk_test', '2026-05-06')

    expect(getSpy).toHaveBeenCalledWith('/tracking', { params: { status: 'all', limit: 20 } })
    expect(postSpy).toHaveBeenCalledWith('/tracking/trk_test/evaluate', null, { params: { date: '2026-05-06' } })
  })
})
