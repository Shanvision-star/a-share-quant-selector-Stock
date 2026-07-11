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

export function createSavedReviewSnapshot(review: ReviewDocument): ReviewDocument {
  return {
    ...review,
    tags: [...review.tags],
    stocks: review.stocks.map(stock => ({ ...stock })),
  }
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

export function buildReviewListParams(filters: ReviewLibraryFilters): ReviewListParams {
  const params: ReviewListParams = { limit: 100, offset: 0 }
  const query = filters.query?.trim()
  if (query) params.query = query
  if (filters.status) params.status = filters.status
  if (filters.dateRange?.[0]) params.date_from = filters.dateRange[0]
  if (filters.dateRange?.[1]) params.date_to = filters.dateRange[1]
  return params
}

export function stripLevelOneHeadings(markdown: string): string {
  const removedLines = new Set<number>()
  for (const token of bodyMarkdownParser.parse(markdown, {})) {
    if (token.type !== 'heading_open' || token.tag !== 'h1' || !token.map) continue
    for (let line = token.map[0]; line < token.map[1]; line += 1) removedLines.add(line)
  }

  return markdown
    .split(/\r?\n/)
    .filter((_line, index) => !removedLines.has(index))
    .join('\n')
    .trim()
}
