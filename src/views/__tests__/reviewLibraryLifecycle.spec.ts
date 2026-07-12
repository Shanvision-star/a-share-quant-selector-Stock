import { describe, expect, it, vi } from 'vitest'
import type { ReviewDocument, ReviewTitleSuggestion } from '@/api/reviews'
import {
  applyReviewCreateResponse,
  applyReviewSaveResponse,
  applyReviewTitleResponse,
  createReviewCreateOperation,
  createReviewLoadController,
  createReviewSaveOperation,
  createReviewTitleOperation,
  reviewSelectionIsActive,
} from '@/views/reviewLibraryLifecycle'

function review(reviewDate: string, overrides: Partial<ReviewDocument> = {}): ReviewDocument {
  return {
    review_date: reviewDate,
    title: '原始标题',
    status: 'draft',
    title_source: 'manual',
    tags: ['原始'],
    stocks: [{ code: '600000', name: '浦发银行' }],
    body: '原始正文',
    created_at: `${reviewDate}T09:00:00+08:00`,
    updated_at: `${reviewDate}T09:00:00+08:00`,
    version: 'v1',
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('review library lifecycle', () => {
  it('keeps a user-authored leading H1 in the save payload', () => {
    const operation = createReviewSaveOperation(review('2026-07-11', {
      body: '# 市场总览\n正文',
    }), 'document-1')

    expect(operation.payload.body).toBe('# 市场总览\n正文')
  })

  it('treats selecting the active review document as a no-op', () => {
    expect(reviewSelectionIsActive(review('2026-07-11'), '2026-07-11')).toBe(true)
    expect(reviewSelectionIsActive(review('2026-07-11'), '2026-07-12')).toBe(false)
    expect(reviewSelectionIsActive(null, '2026-07-11')).toBe(false)
  })

  it('applies server metadata without replacing edits made after save started', () => {
    const submitted = review('2026-07-11')
    const operation = createReviewSaveOperation(submitted, 'document-1')
    const edited = review('2026-07-11', {
      title: '请求期间的新标题',
      status: 'follow_up',
      tags: ['新标签'],
      body: '请求期间的新正文',
    })
    const server = review('2026-07-11', {
      title: '原始标题',
      body: '原始正文',
      updated_at: '2026-07-11T10:00:00+08:00',
      version: 'v2',
    })

    const result = applyReviewSaveResponse(edited, submitted, 'document-1', operation, server)

    expect(result.applied).toBe(true)
    expect(result.current).toMatchObject({
      title: '请求期间的新标题',
      status: 'follow_up',
      tags: ['新标签'],
      body: '请求期间的新正文',
      version: 'v2',
      updated_at: '2026-07-11T10:00:00+08:00',
    })
    expect(result.saved).toEqual(server)
  })

  it('ignores a save response after the active review date changes', () => {
    const submitted = review('2026-07-11')
    const operation = createReviewSaveOperation(submitted, 'document-1')
    const active = review('2026-07-12')
    const activeSaved = review('2026-07-12')

    const result = applyReviewSaveResponse(
      active,
      activeSaved,
      'document-2',
      operation,
      review('2026-07-11', { version: 'v2' }),
    )

    expect(result).toEqual({ applied: false, current: active, saved: activeSaved })
  })

  it('ignores a save response after the same date is reloaded as a new document identity', () => {
    const submitted = review('2026-07-11')
    const operation = createReviewSaveOperation(submitted, 'document-1')
    const reloaded = review('2026-07-11', { body: '重新加载后的正文' })

    const result = applyReviewSaveResponse(
      reloaded,
      reloaded,
      'document-2',
      operation,
      review('2026-07-11', { version: 'v2' }),
    )

    expect(result).toEqual({ applied: false, current: reloaded, saved: reloaded })
  })

  it('marks an older deferred load stale when a newer date resolves first', async () => {
    const first = deferred<ReviewDocument>()
    const second = deferred<ReviewDocument>()
    const loader = vi.fn((reviewDate: string) => (
      reviewDate === '2026-07-11' ? first.promise : second.promise
    ))
    const controller = createReviewLoadController(loader)

    const firstLoad = controller.load('2026-07-11')
    const secondLoad = controller.load('2026-07-12')
    second.resolve(review('2026-07-12'))
    expect(await secondLoad).toMatchObject({ stale: false, reviewDate: '2026-07-12' })

    first.resolve(review('2026-07-11'))
    expect(await firstLoad).toEqual({ stale: true, reviewDate: '2026-07-11' })
  })

  it('ignores a deferred title candidate after switching dates', async () => {
    const candidate = deferred<ReviewTitleSuggestion>()
    const operation = createReviewTitleOperation(review('2026-07-11'), 'document-1', 1)
    let active = review('2026-07-11')
    let activeIdentity = 'document-1'
    let latestToken = 1
    const completion = candidate.promise.then(suggestion => applyReviewTitleResponse(
      active,
      activeIdentity,
      latestToken,
      operation,
      suggestion,
    ))

    active = review('2026-07-12', { title: 'B 文档标题' })
    activeIdentity = 'document-2'
    latestToken = 2
    candidate.resolve({
      title: 'A 文档候选标题',
      source: 'deepseek',
      provider_fallback: false,
      provider_error: null,
      provider_error_code: null,
    })

    expect(await completion).toEqual({ applied: false, current: active })
    expect(active).toMatchObject({ title: 'B 文档标题', title_source: 'manual' })
  })

  it('ignores a deferred title candidate after a manual title edit', async () => {
    const candidate = deferred<ReviewTitleSuggestion>()
    const operation = createReviewTitleOperation(review('2026-07-11'), 'document-1', 1)
    const active = review('2026-07-11', { title: '请求期间手改标题', title_source: 'manual' })
    const completion = candidate.promise.then(suggestion => applyReviewTitleResponse(
      active,
      'document-1',
      1,
      operation,
      suggestion,
    ))

    candidate.resolve({
      title: '过期候选标题',
      source: 'deepseek',
      provider_fallback: false,
      provider_error: null,
      provider_error_code: null,
    })

    expect(await completion).toEqual({ applied: false, current: active })
    expect(active).toMatchObject({ title: '请求期间手改标题', title_source: 'manual' })
  })

  it('ignores a deferred create response after the selected date changes', async () => {
    const created = deferred<ReviewDocument>()
    const operation = createReviewCreateOperation('2026-07-11', 1)
    let selectedDate = '2026-07-11'
    let latestToken = 1
    const completion = created.promise.then(document => applyReviewCreateResponse(
      selectedDate,
      latestToken,
      operation,
      document,
    ))

    selectedDate = '2026-07-12'
    latestToken = 2
    created.resolve(review('2026-07-11'))

    expect(await completion).toEqual({ applied: false, document: null })
  })
})
