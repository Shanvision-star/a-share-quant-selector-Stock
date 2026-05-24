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
})
