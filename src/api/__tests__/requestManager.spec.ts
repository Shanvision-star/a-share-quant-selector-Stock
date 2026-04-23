import { describe, it, expect } from 'vitest'
import { createRequestManager } from '@/api/requestManager'

describe('requestManager', () => {
  it('cancels older request with same key', () => {
    const manager = createRequestManager()
    const first = manager.start('results:list')
    const second = manager.start('results:list')
    expect(first.signal.aborted).toBe(true)
    expect(second.signal.aborted).toBe(false)
  })
})
