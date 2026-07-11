import { describe, expect, it } from 'vitest'
import type { ReviewDocument, ReviewTitleSuggestion } from '@/api/reviews'
import {
  mergeTitleSuggestion,
  reviewIsDirty,
  rewriteReviewImageUrls,
} from '@/views/reviewLibraryState'

const review: ReviewDocument = {
  review_date: '2026-07-11',
  title: '盘中复盘',
  status: 'draft',
  title_source: 'manual',
  tags: ['突破'],
  stocks: [{ code: '600000', name: '浦发银行' }],
  body: '# 盘中复盘\n',
  created_at: '2026-07-11T09:00:00+08:00',
  updated_at: '2026-07-11T09:00:00+08:00',
  version: 'version-1',
}

describe('review library state', () => {
  it('rewrites only safe local review image paths', () => {
    expect(rewriteReviewImageUrls('![图](./2026-07-11.assets/a.png)', '2026-07-11'))
      .toContain('/reviews/2026-07-11/attachments/a.png')
    expect(rewriteReviewImageUrls('![图](javascript:alert(1))', '2026-07-11'))
      .toContain('javascript:alert(1)')
    expect(rewriteReviewImageUrls('![图](./2026-07-10.assets/a.png)', '2026-07-11'))
      .toContain('./2026-07-10.assets/a.png')
    expect(rewriteReviewImageUrls('![图](./2026-07-11.assets/../private.png)', '2026-07-11'))
      .toContain('./2026-07-11.assets/../private.png')
  })

  it('detects editable document changes without considering server timestamps', () => {
    expect(reviewIsDirty({ ...review, updated_at: '2026-07-11T10:00:00+08:00' }, review)).toBe(false)
    expect(reviewIsDirty({ ...review, body: '# 已修改\n' }, review)).toBe(true)
  })

  it('merges a title suggestion without mutating the active document', () => {
    const suggestion: ReviewTitleSuggestion = {
      title: '浦发银行放量突破',
      source: 'deepseek',
      provider_fallback: false,
      provider_error: null,
      provider_error_code: null,
    }

    const merged = mergeTitleSuggestion(review, suggestion)

    expect(merged).toMatchObject({ title: '浦发银行放量突破', title_source: 'deepseek' })
    expect(merged).not.toBe(review)
    expect(review.title).toBe('盘中复盘')
  })
})
