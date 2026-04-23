import { describe, it, expect } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useQueryStateStore } from '@/stores/queryState'

describe('queryState', () => {
  it('persists results filters in store', () => {
    setActivePinia(createPinia())
    const s = useQueryStateStore()
    s.setResultsKeyword('军工')
    expect(s.results.keyword).toBe('军工')
  })
})
