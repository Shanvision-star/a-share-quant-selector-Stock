import { afterEach, describe, expect, it, vi } from 'vitest'
import api from '@/api'
import {
  addStockToReview,
  createReview,
  deleteReviewAttachment,
  generateReviewTitle,
  getReview,
  listReviews,
  updateReview,
  uploadReviewAttachment,
  type ReviewDocument,
} from '@/api/reviews'

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

describe('review API', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('lists reviews with server filter parameters', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { success: true, data: { items: [] } } } as any)

    await listReviews({ query: '突破', status: 'draft', limit: 20 })

    expect(get).toHaveBeenCalledWith('/reviews', {
      params: { query: '突破', status: 'draft', limit: 20 },
    })
  })

  it('encodes review dates for document operations', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { success: true, data: review } } as any)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: review } } as any)
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: { success: true, data: review } } as any)
    const reviewDate = '2026-07-11 test'

    await createReview(reviewDate)
    await getReview(reviewDate)
    await updateReview(reviewDate, review)
    await addStockToReview(reviewDate, { code: '600000', name: '浦发银行' })

    expect(post).toHaveBeenNthCalledWith(1, '/reviews/2026-07-11%20test')
    expect(get).toHaveBeenCalledWith('/reviews/2026-07-11%20test')
    expect(put).toHaveBeenCalledWith('/reviews/2026-07-11%20test', review)
    expect(post).toHaveBeenNthCalledWith(2, '/reviews/2026-07-11%20test/stocks', {
      code: '600000',
      name: '浦发银行',
    })
  })

  it('posts the current unsaved draft when generating a title', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: {} } } as any)

    await generateReviewTitle('2026-07-11', {
      title: review.title,
      body: review.body,
      tags: review.tags,
      stocks: review.stocks,
    })

    expect(post).toHaveBeenCalledWith('/reviews/2026-07-11/generate-title', {
      title: review.title,
      body: review.body,
      tags: review.tags,
      stocks: review.stocks,
    })
  })

  it('uploads an attachment as multipart form data', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: {} } } as any)

    await uploadReviewAttachment('2026-07-11', new File(['png'], 'shot.png', { type: 'image/png' }))

    expect(post).toHaveBeenCalledWith('/reviews/2026-07-11/attachments', expect.any(FormData), {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const formData = post.mock.calls[0][1] as FormData
    expect(formData.get('file')).toBeInstanceOf(File)
  })

  it('encodes attachment names and sends explicit force confirmation', async () => {
    const deleteRequest = vi.spyOn(api, 'delete').mockResolvedValue({ data: { success: true, data: {} } } as any)

    await deleteReviewAttachment('2026-07-11', 'chart 1.png', true)

    expect(deleteRequest).toHaveBeenCalledWith('/reviews/2026-07-11/attachments/chart%201.png', {
      params: { force: true },
    })
  })
})
