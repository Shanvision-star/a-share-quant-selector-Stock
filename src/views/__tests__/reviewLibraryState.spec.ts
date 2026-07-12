import { describe, expect, it } from 'vitest'
import type { ReviewDocument, ReviewTitleSuggestion } from '@/api/reviews'
import {
  buildReviewListParams,
  createEditableReviewSnapshot,
  createSavedReviewSnapshot,
  insertMarkdownAtSelection,
  markReviewTitleManual,
  mergeTitleSuggestion,
  reviewIsDirty,
  rewriteReviewImageUrls,
  stripLevelOneHeadings,
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
      .toContain('/api/reviews/2026-07-11/attachments/a.png')
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

  it('marks a manually edited title as manual without mutating the document', () => {
    const generatedReview: ReviewDocument = { ...review, title_source: 'deepseek' }

    const edited = markReviewTitleManual(generatedReview, '手工修订标题')

    expect(edited).toMatchObject({ title: '手工修订标题', title_source: 'manual' })
    expect(generatedReview).toMatchObject({ title: '盘中复盘', title_source: 'deepseek' })
  })

  it('keeps a saved snapshot stable while the active draft is edited', () => {
    const active = createSavedReviewSnapshot(review)
    const saved = createSavedReviewSnapshot(active)

    active.tags.push('跟进')
    active.stocks[0].name = '浦发银行（更新）'

    expect(saved.tags).toEqual(['突破'])
    expect(saved.stocks[0].name).toBe('浦发银行')
    expect(reviewIsDirty(active, saved)).toBe(true)
  })

  it('inserts image markdown at the current selection and returns the next cursor', () => {
    expect(insertMarkdownAtSelection('盘前\n盘后', '![截图](./2026-07-11.assets/a.png)', 3, 3)).toEqual({
      value: '盘前\n![截图](./2026-07-11.assets/a.png)盘后',
      cursor: 35,
    })
    expect(insertMarkdownAtSelection('旧内容', '![新图](image.png)', 0, 3)).toEqual({
      value: '![新图](image.png)',
      cursor: 16,
    })
  })

  it('builds trimmed status and date filter parameters for the requested page', () => {
    expect(buildReviewListParams({
      query: '  浦发  ',
      status: 'follow_up',
      dateRange: ['2026-07-01', '2026-07-11'],
    }, 100)).toEqual({
      query: '浦发',
      status: 'follow_up',
      date_from: '2026-07-01',
      date_to: '2026-07-11',
      limit: 100,
      offset: 100,
    })
    expect(buildReviewListParams({ query: ' ', status: '', dateRange: null })).toEqual({
      limit: 100,
      offset: 0,
    })
  })

  it('removes only a leading ATX level-one document title', () => {
    expect(stripLevelOneHeadings('\uFEFF  \n\n# 独立标题\n正文\n# 正文一级标题', '独立标题'))
      .toBe('正文\n# 正文一级标题')
  })

  it('removes only a leading Setext level-one document title', () => {
    expect(stripLevelOneHeadings('\n独立标题\n====\n正文\n后续一级标题\n====', '独立标题'))
      .toBe('正文\n后续一级标题\n====')
  })

  it('preserves later ATX and Setext level-one headings', () => {
    expect(stripLevelOneHeadings('正文开场\n\n# 后续 ATX\n\n后续 Setext\n====', '独立标题'))
      .toBe('正文开场\n\n# 后续 ATX\n\n后续 Setext\n====')
  })

  it('preserves level-one heading syntax inside fenced code', () => {
    expect(stripLevelOneHeadings('```md\n# 代码标题\n代码 Setext\n====\n```\n正文', '独立标题'))
      .toBe('```md\n# 代码标题\n代码 Setext\n====\n```\n正文')
  })

  it('preserves a leading H1 that does not match the canonical title', () => {
    expect(stripLevelOneHeadings('# 市场总览\n正文', '原始标题')).toBe('# 市场总览\n正文')
  })

  it('converts a server document into one editable body source', () => {
    const editable = createEditableReviewSnapshot({
      ...review,
      title: '盘中复盘',
      body: '# 盘中复盘\n\n正文\n\n# 用户章节',
    })

    expect(editable.body).toBe('正文\n\n# 用户章节')
    expect(editable.title).toBe('盘中复盘')
  })
})
