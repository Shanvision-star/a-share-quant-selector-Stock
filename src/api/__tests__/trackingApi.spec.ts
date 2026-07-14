import { afterEach, describe, expect, it, vi } from 'vitest'
import api, {
  acknowledgeTrackingAlert,
  batchCreateTrackingFromSelection,
  createTrackingItem,
  evaluateTrackingItem,
  getLatestTrackingLoopRun,
  getTrackingLLMAdvice,
  ignoreTrackingAlert,
  listTrackingItems,
  runTrackingPostClose,
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

  it('marks tracking alerts acknowledged and ignored', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: {} } } as any)

    await acknowledgeTrackingAlert(12)
    await ignoreTrackingAlert(13)

    expect(postSpy).toHaveBeenCalledWith('/tracking/alerts/12/ack')
    expect(postSpy).toHaveBeenCalledWith('/tracking/alerts/13/ignore')
  })

  it('requests zettaranc profile advice', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: {} } } as any)

    await getTrackingLLMAdvice('trk_test', 'zettaranc_style')

    expect(postSpy).toHaveBeenCalledWith(
      '/tracking/trk_test/llm-advice',
      { profile: 'zettaranc_style' },
    )
  })

  it('batch creates tracking items from a manual selection date', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        success: true,
        data: { created: 1, skipped: 0, skipped_codes: [], failed: [] },
      },
    } as any)
    const intakePayload = {
      selection_date: '2026-05-06',
      codes: ['000559', '600000'],
    }

    await batchCreateTrackingFromSelection(intakePayload)

    expect(postSpy).toHaveBeenCalledWith('/tracking/batch-from-selection', intakePayload)
  })

  it('loads and runs the post-close tracking loop', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: { success: true, data: null },
    } as any)
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: { success: true, data: { status: 'done' } },
    } as any)

    await getLatestTrackingLoopRun()
    await runTrackingPostClose({ trigger: 'manual', sync_first: true, per_slot_limit: 8 })

    expect(getSpy).toHaveBeenCalledWith('/tracking/loops/runs/latest')
    expect(postSpy).toHaveBeenCalledWith('/tracking/loops/post-close/run', {
      trigger: 'manual',
      sync_first: true,
      per_slot_limit: 8,
    })
  })
})
