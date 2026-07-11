import type { ReviewDocument, ReviewTitleSuggestion } from '@/api/reviews'

type EditableReview = Pick<
  ReviewDocument,
  'title' | 'status' | 'title_source' | 'tags' | 'stocks' | 'body'
>

function editableReviewSnapshot(review: ReviewDocument): EditableReview {
  return {
    title: review.title,
    status: review.status,
    title_source: review.title_source,
    tags: review.tags,
    stocks: review.stocks,
    body: review.body,
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * Only local Markdown image paths with the current review date and a safe file
 * name are converted to the API route. Other Markdown URLs stay untouched.
 */
export function rewriteReviewImageUrls(markdown: string, reviewDate: string): string {
  const escapedDate = escapeRegExp(reviewDate)
  const safeFilename = '[A-Za-z0-9][A-Za-z0-9._-]*'
  const imagePath = new RegExp(`(!\\[[^\\]]*\\])\\(\\./${escapedDate}\\.assets/(${safeFilename})\\)`, 'g')
  const encodedDate = encodeURIComponent(reviewDate)

  return markdown.replace(imagePath, (_match, image, filename: string) => (
    `${image}(/reviews/${encodedDate}/attachments/${encodeURIComponent(filename)})`
  ))
}

export function reviewIsDirty(
  current: ReviewDocument | null | undefined,
  saved: ReviewDocument | null | undefined,
): boolean {
  if (!current || !saved) return current !== saved
  return JSON.stringify(editableReviewSnapshot(current)) !== JSON.stringify(editableReviewSnapshot(saved))
}

export function mergeTitleSuggestion(
  review: ReviewDocument,
  suggestion: ReviewTitleSuggestion,
): ReviewDocument {
  return {
    ...review,
    title: suggestion.title,
    title_source: suggestion.source,
  }
}
