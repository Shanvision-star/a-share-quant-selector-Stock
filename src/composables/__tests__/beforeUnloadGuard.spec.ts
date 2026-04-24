import { describe, expect, it, vi } from 'vitest'
import { bindBeforeUnloadGuard, createBeforeUnloadHandler } from '@/composables/beforeUnloadGuard'

describe('beforeUnloadGuard', () => {
  it('prevents unload when draft is dirty', () => {
    const handler = createBeforeUnloadHandler(() => true)
    const event = {
      preventDefault: vi.fn(),
      returnValue: undefined as unknown,
    } as unknown as BeforeUnloadEvent

    handler(event)

    expect(event.preventDefault).toHaveBeenCalledTimes(1)
    expect(event.returnValue).toBe('')
  })

  it('does not block unload when draft is clean', () => {
    const handler = createBeforeUnloadHandler(() => false)
    const event = {
      preventDefault: vi.fn(),
      returnValue: undefined as unknown,
    } as unknown as BeforeUnloadEvent

    handler(event)

    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(event.returnValue).toBeUndefined()
  })

  it('binds and unbinds beforeunload listener', () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')

    const cleanup = bindBeforeUnloadGuard(() => true)
    cleanup()

    expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
  })
})
