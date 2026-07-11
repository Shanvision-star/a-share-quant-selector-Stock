import type { AxiosResponse } from 'axios'
import api from './index'

export type ReviewStatus = 'draft' | 'completed' | 'follow_up'
export type ReviewTitleSource = 'manual' | 'deepseek' | 'local_fallback'

export interface ReviewStock {
  code: string
  name: string
}

export interface ReviewDocument {
  review_date: string
  title: string
  status: ReviewStatus
  title_source: ReviewTitleSource
  tags: string[]
  stocks: ReviewStock[]
  body: string
  created_at: string
  updated_at: string
  version: string
}

export interface ReviewListItem {
  review_date: string
  title: string
  status: ReviewStatus
  tags: string[]
  stocks: ReviewStock[]
  updated_at: string
  body_summary: string
  first_attachment_url: string | null
  version: string
}

export interface ReviewTitleSuggestion {
  title: string
  source: Exclude<ReviewTitleSource, 'manual'>
  provider_fallback: boolean
  provider_error: string | null
  provider_error_code: string | null
}

export interface ReviewAttachment {
  filename: string
  content_type: string
  size: number
  markdown?: string
}

export interface ReviewListParams {
  query?: string
  status?: ReviewStatus
  stock?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

export interface ReviewListResponse {
  items: ReviewListItem[]
  total: number
  limit: number
  offset: number
}

export interface ReviewTitlePayload {
  title: string
  body: string
  tags: string[]
  stocks: ReviewStock[]
}

export type ReviewUpdatePayload = Pick<
  ReviewDocument,
  'title' | 'status' | 'title_source' | 'tags' | 'stocks' | 'body' | 'version'
>

interface ApiEnvelope<T> {
  success: boolean
  data: T
}

type ReviewCreateResult = ReviewDocument & { created: boolean }
type ReviewStockResult = ReviewDocument & { already_exists: boolean }
type ReviewAttachmentDeleteResult = { filename: string; deleted: boolean }

function reviewPath(reviewDate: string): string {
  return `/reviews/${encodeURIComponent(reviewDate)}`
}

export const listReviews = (params: ReviewListParams = {}) =>
  api.get<ApiEnvelope<ReviewListResponse>>('/reviews', { params })

export const createReview = (reviewDate: string) =>
  api.post<ApiEnvelope<ReviewCreateResult>>(reviewPath(reviewDate))

export const getReview = (reviewDate: string) =>
  api.get<ApiEnvelope<ReviewDocument>>(reviewPath(reviewDate))

export const updateReview = (reviewDate: string, payload: ReviewUpdatePayload) =>
  api.put<ApiEnvelope<ReviewDocument>>(reviewPath(reviewDate), payload)

export const addStockToReview = (reviewDate: string, stock: ReviewStock) =>
  api.post<ApiEnvelope<ReviewStockResult>>(`${reviewPath(reviewDate)}/stocks`, stock)

export const generateReviewTitle = (reviewDate: string, payload: ReviewTitlePayload) =>
  api.post<ApiEnvelope<ReviewTitleSuggestion>>(`${reviewPath(reviewDate)}/generate-title`, payload)

export const uploadReviewAttachment = (reviewDate: string, file: File): Promise<AxiosResponse<ApiEnvelope<ReviewAttachment>>> => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`${reviewPath(reviewDate)}/attachments`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const deleteReviewAttachment = (reviewDate: string, filename: string, force = false) =>
  api.delete<ApiEnvelope<ReviewAttachmentDeleteResult>>(
    `${reviewPath(reviewDate)}/attachments/${encodeURIComponent(filename)}`,
    { params: { force } },
  )
