import { describe, expect, it } from 'vitest'
import { isBacktestTaskCancelable } from '@/views/backtestState'
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
})
