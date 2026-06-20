import { afterEach, describe, expect, it, vi } from 'vitest'
import api, { getSystemStatus, type SystemStatusPayload } from '@/api'

describe('system status API', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('requests the system status endpoint', async () => {
    const payload: SystemStatusPayload = {
      checked_at: '2026-06-21T10:00:00+08:00',
      overall_status: 'ready',
      backend: { status: 'ready', message: 'ok', checked_at: 'now', next_action: '', details: {} },
      data: { status: 'ready', message: 'ok', checked_at: 'now', next_action: '', details: {} },
      strategy_cache: { status: 'ready', message: 'ok', checked_at: 'now', next_action: '', details: {} },
      update_pipeline: { status: 'missing', message: 'none', checked_at: 'now', next_action: '', details: {} },
      tracking: { status: 'ready', message: 'ok', checked_at: 'now', next_action: '', details: {} },
      integrations: { status: 'disabled', message: 'off', checked_at: 'now', next_action: '', details: {} },
      frontend_hints: [],
    }
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: { success: true, data: payload } } as any)

    await getSystemStatus()

    expect(getSpy).toHaveBeenCalledWith('/system/status')
  })
})
