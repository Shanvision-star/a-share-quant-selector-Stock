import { describe, expect, it } from 'vitest'
import {
  trackingLoopStatusMeta,
  trackingLoopSummary,
} from '@/views/trackingLoopState'
import type { TrackingLoopRun } from '@/api'

function run(overrides: Partial<TrackingLoopRun> = {}): TrackingLoopRun {
  return {
    run_id: 'tlr_test',
    loop_type: 'post_close',
    status: 'done',
    slot: 'post_close',
    trigger: 'manual',
    sync_first: true,
    per_slot_limit: 8,
    started_at: '2026-07-14T15:31:00',
    completed_at: '2026-07-14T15:31:05',
    sync: { updated: ['000001'], skipped: ['600000'], errors: [] },
    evaluation: { evaluated: 2, alerts_created: 1, alerts_skipped_dup: 3 },
    dispatch: { dispatched: 1, deferred: 0, aggregated: 0 },
    error: null,
    ...overrides,
  }
}

describe('tracking loop state', () => {
  it('maps operational statuses without presenting partial or errors as success', () => {
    expect(trackingLoopStatusMeta('done')).toEqual({ label: '已完成', tagType: 'success' })
    expect(trackingLoopStatusMeta('partial')).toEqual({ label: '部分完成', tagType: 'warning' })
    expect(trackingLoopStatusMeta('error')).toEqual({ label: '失败', tagType: 'danger' })
    expect(trackingLoopStatusMeta('running')).toEqual({ label: '运行中', tagType: 'primary' })
    expect(trackingLoopStatusMeta('busy')).toEqual({ label: '已有任务运行', tagType: 'warning' })
  })

  it('summarizes sync, evaluation, deduplication and dispatch counts', () => {
    expect(trackingLoopSummary(run())).toBe(
      '行情更新 1 / 跳过 1 / 失败 0；评估 2 / 新告警 1 / 去重 3；分发 1 / 延后 0',
    )
  })

  it('surfaces the recorded failure stage and message', () => {
    expect(trackingLoopSummary(run({
      status: 'error',
      sync: null,
      evaluation: null,
      dispatch: null,
      error: { stage: 'sync', message: 'fetch failed' },
    }))).toBe('sync：fetch failed')
  })
})
