export type DirtyChecker = () => boolean

export function createBeforeUnloadHandler(isDirty: DirtyChecker) {
  return (event: BeforeUnloadEvent) => {
    if (!isDirty()) return
    event.preventDefault()
    event.returnValue = ''
  }
}

export function bindBeforeUnloadGuard(isDirty: DirtyChecker): () => void {
  const handler = createBeforeUnloadHandler(isDirty)
  window.addEventListener('beforeunload', handler)
  return () => {
    window.removeEventListener('beforeunload', handler)
  }
}
