import type {
  ReviewDocument,
  ReviewListParams,
  ReviewStatus,
  ReviewTitleSuggestion,
} from '@/api/reviews'
import MarkdownIt from 'markdown-it'

const bodyMarkdownParser = new MarkdownIt({ html: false })

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
    `${image}(/api/reviews/${encodedDate}/attachments/${encodeURIComponent(filename)})`
  ))
}

export function reviewIsDirty(
  current: ReviewDocument | null | undefined,
  saved: ReviewDocument | null | undefined,
): boolean {
  if (!current || !saved) return current !== saved
  return JSON.stringify(editableReviewSnapshot(current)) !== JSON.stringify(editableReviewSnapshot(saved))
}

export function createSavedReviewSnapshot(review: ReviewDocument): ReviewDocument {
  return {
    ...review,
    tags: [...review.tags],
    stocks: review.stocks.map(stock => ({ ...stock })),
  }
}

export function createEditableReviewSnapshot(review: ReviewDocument): ReviewDocument {
  const editable = createSavedReviewSnapshot(review)
  editable.body = stripLevelOneHeadings(editable.body, editable.title)
  return editable
}

export function markReviewTitleManual(review: ReviewDocument, title: string): ReviewDocument {
  return {
    ...review,
    title,
    title_source: 'manual',
  }
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

export interface MarkdownInsertion {
  value: string
  cursor: number
}

export function insertMarkdownAtSelection(
  value: string,
  markdown: string,
  selectionStart: number,
  selectionEnd: number,
): MarkdownInsertion {
  const start = Math.max(0, Math.min(selectionStart, value.length))
  const end = Math.max(start, Math.min(selectionEnd, value.length))
  return {
    value: `${value.slice(0, start)}${markdown}${value.slice(end)}`,
    cursor: start + markdown.length,
  }
}

export interface ReviewLibraryFilters {
  query?: string
  status?: ReviewStatus | ''
  dateRange?: [string, string] | null
}

export function buildReviewListParams(
  filters: ReviewLibraryFilters,
  offset = 0,
): ReviewListParams {
  const params: ReviewListParams = { limit: 100, offset }
  const query = filters.query?.trim()
  if (query) params.query = query
  if (filters.status) params.status = filters.status
  if (filters.dateRange?.[0]) params.date_from = filters.dateRange[0]
  if (filters.dateRange?.[1]) params.date_to = filters.dateRange[1]
  return params
}

export function stripLevelOneHeadings(markdown: string, canonicalTitle: string): string {
  const source = markdown.replace(/^\uFEFF/, '')
  const tokens = bodyMarkdownParser.parse(source, {})
  const firstBlockIndex = tokens.findIndex(token => token.map)
  const firstBlock = tokens[firstBlockIndex]
  if (
    firstBlock?.type !== 'heading_open'
    || firstBlock.tag !== 'h1'
    || !firstBlock.map
  ) return source.trim()
  const inline = tokens[firstBlockIndex + 1]
  if (inline?.type !== 'inline' || inline.content.trim() !== canonicalTitle.trim()) {
    return source.trim()
  }

  return source.split(/\r?\n/).slice(firstBlock.map[1]).join('\n').trim()
}
