import { describe, it, expect } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSettingsDraftStore } from '@/stores/settingsDraft'

describe('settingsDraft', () => {
  it('marks draft as dirty when param changes', () => {
    setActivePinia(createPinia())
    const store = useSettingsDraftStore()
    store.loadFromServer({
      revision: 'r1',
      updated_at: '2026-04-23T00:00:00Z',
      configs: [{ strategy_name: 'B1CaseStrategy', params: { lookback_days: 60 }, param_meta: {} }],
    })
    store.updateParam('B1CaseStrategy', 'lookback_days', 80)
    expect(store.isDirty).toBe(true)
  })
})
