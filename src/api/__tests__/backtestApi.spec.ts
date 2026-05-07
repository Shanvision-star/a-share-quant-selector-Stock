import { afterEach, describe, expect, it, vi } from 'vitest'
import api, {
  startBacktestTaskCompatible,
  type BacktestRequestPayload,
} from '@/api'

const payload: BacktestRequestPayload = {
  start_date: '2026-05-01',
  end_date: '2026-05-01',
  source: 'manual',
  strategy: 'all',
  selected_codes: ['000559'],
  holding_days: 20,
  buy_offset_days: 1,
  buy_price: 'open',
  sell_price: 'close',
  fee_rate: 0.0003,
  slippage_rate: 0.0005,
  max_positions_per_day: 20,
}

describe('backtest API compatibility', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('falls back to synchronous backtest when async task endpoint returns 405', async () => {
    const postSpy = vi.spyOn(api, 'post')
      .mockRejectedValueOnce({ response: { status: 405, data: { detail: 'Method Not Allowed' } } })
      .mockResolvedValueOnce({ data: { success: true, data: { summary: { trade_count: 1 } } } } as any)

    const result = await startBacktestTaskCompatible(payload)

    expect(result.mode).toBe('sync_fallback')
    expect(result.task.status).toBe('done')
    expect(result.task.result.summary.trade_count).toBe(1)
    expect(postSpy.mock.calls.map(call => call[0])).toEqual(['/backtest/tasks', '/backtest'])
  })

  it('keeps using async task mode when the endpoint exists', async () => {
    const asyncTask = {
      task_id: 'bt_test',
      status: 'queued',
      result: null,
      params: payload,
    }
    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ data: { success: true, data: asyncTask } } as any)

    const result = await startBacktestTaskCompatible(payload)

    expect(result.mode).toBe('async')
    expect(result.task).toEqual(asyncTask)
    expect(postSpy).toHaveBeenCalledTimes(1)
  })
})
