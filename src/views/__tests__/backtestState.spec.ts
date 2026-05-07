import { describe, expect, it } from 'vitest'
import { formatTrackingAction, formatTrackingIntentSummary, isBacktestTaskCancelable } from '@/views/backtestState'
import type { BacktestCapabilities, BacktestTask } from '@/api'

const runningTask: BacktestTask = {
  task_id: 'bt_test',
  status: 'running',
}

describe('backtestState', () => {
  it('allows cancel buttons only when async task capability exists', () => {
    expect(isBacktestTaskCancelable(runningTask, { asyncTasks: true, mode: 'async_tasks', reason: 'test' })).toBe(true)
    expect(isBacktestTaskCancelable(runningTask, { asyncTasks: false, mode: 'sync_compat', reason: 'test' })).toBe(false)
  })

  it('does not allow cancel buttons for terminal tasks', () => {
    const capabilities: BacktestCapabilities = { asyncTasks: true, mode: 'async_tasks', reason: 'test' }

    expect(isBacktestTaskCancelable({ ...runningTask, status: 'done' }, capabilities)).toBe(false)
    expect(isBacktestTaskCancelable({ ...runningTask, status: 'failed' }, capabilities)).toBe(false)
  })

  it('formats tracking actions and latest order intent for drawer display', () => {
    expect(formatTrackingAction('SELL_PARTIAL')).toBe('部分卖出')
    expect(formatTrackingAction('HOLD_RUNNER')).toBe('放飞持有')
    expect(formatTrackingIntentSummary({
      side: 'SELL',
      quantity: 200,
      price_type: 'close',
      target_price: 11.6,
    })).toBe('卖出 200 股，close 11.6')
    expect(formatTrackingIntentSummary(null)).toBe('暂无下单意图')
  })
})
