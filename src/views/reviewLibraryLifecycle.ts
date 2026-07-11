import type { ReviewDocument, ReviewUpdatePayload } from '@/api/reviews'
import {
  createSavedReviewSnapshot,
  reviewIsDirty,
  stripLevelOneHeadings,
} from '@/views/reviewLibraryState'

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
      body: stripLevelOneHeadings(submitted.body),
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

  const saved = createSavedReviewSnapshot(serverReview)
  if (!reviewIsDirty(active, operation.submitted)) {
    return {
      applied: true,
      current: createSavedReviewSnapshot(serverReview),
      saved,
    }
  }

  return {
    applied: true,
    current: {
      ...serverReview,
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
