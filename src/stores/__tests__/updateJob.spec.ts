import { describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUpdateJobStore } from '@/stores/updateJob'

describe('updateJob', () => {
  it('stops running state when backend rejects an overlapping update job', () => {
    setActivePinia(createPinia())
    const store = useUpdateJobStore()

    store.startJob()
    store.handleEvent('error', {
      status: 'busy',
      message: '已有数据更新任务正在运行',
      active_run_id: 'run-active',
    })

    expect(store.isRunning).toBe(false)
    expect(store.jobError).toBe('已有数据更新任务正在运行')
  })

  it('treats bare sse error event as terminal update failure', () => {
    setActivePinia(createPinia())
    const store = useUpdateJobStore()

    store.startJob()
    store.handleEvent('update_progress', {
      stage: 'update',
      progress: 92,
      message: '并发更新中',
      completed: 972,
      to_update: 3877,
    })
    store.handleEvent('error', {
      message: '2026-05-25 数据更新未全量完成：已执行 972/3877，成功 948 只，失败 24 只，验证 0/0',
    })

    expect(store.isRunning).toBe(false)
    expect(store.jobError).toContain('未全量完成')
    expect(store.updateStage.status).toBe('error')
    expect(store.updateStage.progress).toBe(100)
    expect(store.rebuildStage.status).toBe('pending')
  })
})
