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

  it('keeps draft after route-like reset and clears after save success', async () => {
    setActivePinia(createPinia())
    const store = useSettingsDraftStore()
    store.loadFromServer({
      revision: 'r1',
      updated_at: '2026-04-23T00:00:00Z',
      configs: [{ strategy_name: 'B2Strategy', params: { b2_breakout_pct: 4 }, param_meta: {} }],
    })
    store.updateParam('B2Strategy', 'b2_breakout_pct', 5)
    expect(store.isDirty).toBe(true)
    store.markSaved('r2')
    expect(store.isDirty).toBe(false)
    expect(store.revision).toBe('r2')
  })

  it('keeps other unsaved strategy changes dirty after saving one strategy', () => {
    setActivePinia(createPinia())
    const store = useSettingsDraftStore()
    store.loadFromServer({
      revision: 'r1',
      updated_at: '2026-04-23T00:00:00Z',
      configs: [
        { strategy_name: 'B1Strategy', params: { lookback_days: 60 }, param_meta: {} },
        { strategy_name: 'B2Strategy', params: { b2_breakout_pct: 4 }, param_meta: {} },
      ],
    })

    store.updateParam('B1Strategy', 'lookback_days', 80)
    store.updateParam('B2Strategy', 'b2_breakout_pct', 5)
    store.markSaved('r2', 'B1Strategy')

    expect(store.revision).toBe('r2')
    expect(store.isDirty).toBe(true)
  })
})
