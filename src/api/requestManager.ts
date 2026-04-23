export interface RequestManager {
  start: (key: string) => AbortController
  clear: (key: string, controller?: AbortController) => void
  isCurrent: (key: string, controller: AbortController) => boolean
  cancelAll: () => void
}

export function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const maybe = error as { name?: string; code?: string }
  return maybe.name === 'AbortError' || maybe.code === 'ERR_CANCELED'
}

export function createRequestManager(): RequestManager {
  const controllers = new Map<string, AbortController>()

  function start(key: string) {
    controllers.get(key)?.abort()
    const controller = new AbortController()
    controllers.set(key, controller)
    return controller
  }

  function clear(key: string, controller?: AbortController) {
    if (!controller || controllers.get(key) === controller) {
      controllers.delete(key)
    }
  }

  function isCurrent(key: string, controller: AbortController) {
    return controllers.get(key) === controller
  }

  function cancelAll() {
    for (const controller of controllers.values()) {
      controller.abort()
    }
    controllers.clear()
  }

  return { start, clear, isCurrent, cancelAll }
}
