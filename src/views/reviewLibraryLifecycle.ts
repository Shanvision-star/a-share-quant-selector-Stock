import type {
  ReviewDocument,
  ReviewTitlePayload,
  ReviewTitleSuggestion,
  ReviewUpdatePayload,
} from '@/api/reviews'
import {
  createEditableReviewSnapshot,
  createSavedReviewSnapshot,
  mergeTitleSuggestion,
  reviewIsDirty,
} from '@/views/reviewLibraryState'

export function reviewSelectionIsActive(
  active: ReviewDocument | null | undefined,
  requestedDate: string,
): boolean {
  return active?.review_date === requestedDate
}

export interface ReviewSaveOperation {
  reviewDate: string
  documentIdentity: string
  submitted: ReviewDocument
  payload: ReviewUpdatePayload
}

export interface ReviewSaveResolution {
  applied: boolean
  current: ReviewDocument | null
  saved: ReviewDocument | null
}

export function createReviewSaveOperation(
  review: ReviewDocument,
  documentIdentity: string,
): ReviewSaveOperation {
  const submitted = createSavedReviewSnapshot(review)
  return {
    reviewDate: review.review_date,
    documentIdentity,
    submitted,
    payload: {
      title: submitted.title.trim(),
      status: submitted.status,
      title_source: submitted.title_source,
      tags: [...submitted.tags],
      stocks: submitted.stocks.map(stock => ({ ...stock })),
      body: submitted.body,
      version: submitted.version,
    },
  }
}

export function applyReviewSaveResponse(
  active: ReviewDocument | null,
  activeSaved: ReviewDocument | null,
  activeDocumentIdentity: string,
  operation: ReviewSaveOperation,
  serverReview: ReviewDocument,
): ReviewSaveResolution {
  if (
    !active
    || active.review_date !== operation.reviewDate
    || activeDocumentIdentity !== operation.documentIdentity
  ) {
    return { applied: false, current: active, saved: activeSaved }
  }

  const editableServerReview = createEditableReviewSnapshot(serverReview)
  const saved = createSavedReviewSnapshot(editableServerReview)
  if (!reviewIsDirty(active, operation.submitted)) {
    return {
      applied: true,
      current: createSavedReviewSnapshot(editableServerReview),
      saved,
    }
  }

  return {
    applied: true,
    current: {
      ...editableServerReview,
      title: active.title,
      status: active.status,
      title_source: active.title_source,
      tags: [...active.tags],
      stocks: active.stocks.map(stock => ({ ...stock })),
      body: active.body,
    },
    saved,
  }
}

export type ReviewLoadResult =
  | { stale: true; reviewDate: string }
  | { stale: false; reviewDate: string; document: ReviewDocument }

export function createReviewLoadController(
  loader: (reviewDate: string) => Promise<ReviewDocument>,
) {
  let latestRequest = 0

  return {
    async load(reviewDate: string): Promise<ReviewLoadResult> {
      const request = ++latestRequest
      try {
        const document = await loader(reviewDate)
        if (request !== latestRequest) return { stale: true, reviewDate }
        return { stale: false, reviewDate, document }
      } catch (error) {
        if (request !== latestRequest) return { stale: true, reviewDate }
        throw error
      }
    },
    invalidate() {
      latestRequest += 1
    },
  }
}

export interface ReviewTitleOperation {
  reviewDate: string
  documentIdentity: string
  requestToken: number
  titleSnapshot: string
  payload: ReviewTitlePayload
}

export interface ReviewTitleResolution {
  applied: boolean
  current: ReviewDocument | null
}

export function createReviewTitleOperation(
  review: ReviewDocument,
  documentIdentity: string,
  requestToken: number,
): ReviewTitleOperation {
  return {
    reviewDate: review.review_date,
    documentIdentity,
    requestToken,
    titleSnapshot: review.title,
    payload: {
      title: review.title,
      body: review.body,
      tags: [...review.tags],
      stocks: review.stocks.map(stock => ({ ...stock })),
    },
  }
}

export function reviewTitleOperationIsCurrent(
  active: ReviewDocument | null | undefined,
  activeDocumentIdentity: string,
  latestRequestToken: number,
  operation: ReviewTitleOperation,
): boolean {
  return Boolean(
    active
    && active.review_date === operation.reviewDate
    && activeDocumentIdentity === operation.documentIdentity
    && latestRequestToken === operation.requestToken
    && active.title === operation.titleSnapshot,
  )
}

export function applyReviewTitleResponse(
  active: ReviewDocument | null,
  activeDocumentIdentity: string,
  latestRequestToken: number,
  operation: ReviewTitleOperation,
  suggestion: ReviewTitleSuggestion,
): ReviewTitleResolution {
  if (!reviewTitleOperationIsCurrent(
    active,
    activeDocumentIdentity,
    latestRequestToken,
    operation,
  )) {
    return { applied: false, current: active }
  }
  return { applied: true, current: mergeTitleSuggestion(active!, suggestion) }
}

export interface ReviewCreateOperation {
  reviewDate: string
  requestToken: number
}

export interface ReviewCreateResolution {
  applied: boolean
  document: ReviewDocument | null
}

export function createReviewCreateOperation(
  reviewDate: string,
  requestToken: number,
): ReviewCreateOperation {
  return { reviewDate, requestToken }
}

export function reviewCreateOperationIsCurrent(
  selectedDate: string,
  latestRequestToken: number,
  operation: ReviewCreateOperation,
): boolean {
  return selectedDate === operation.reviewDate && latestRequestToken === operation.requestToken
}

export function applyReviewCreateResponse(
  selectedDate: string,
  latestRequestToken: number,
  operation: ReviewCreateOperation,
  document: ReviewDocument,
): ReviewCreateResolution {
  if (
    !reviewCreateOperationIsCurrent(selectedDate, latestRequestToken, operation)
    || document.review_date !== operation.reviewDate
  ) {
    return { applied: false, document: null }
  }
  return { applied: true, document }
}
