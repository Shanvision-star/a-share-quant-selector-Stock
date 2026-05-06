export interface StrategyResultListItem {
  code: string
  name?: string
  strategy_filter?: string
  strategy_name?: string
  category?: string
  signal_date?: string
  trade_date?: string
  trigger_price?: number
  j_value?: number
  similarity_score?: number | null
  reason?: string
}

export interface StrategyResultsPagePayload<T = StrategyResultListItem> {
  items?: T[]
  total?: number
  page?: number
  per_page?: number
}

export interface FetchAllStrategyOptions {
  pageSize?: number
  maxPages?: number
}

export type StrategyGroupKey = 'b1' | 'b2' | 'bowl' | 'brick'

export interface StrategyGroup<T = StrategyResultListItem> {
  key: StrategyGroupKey
  label: string
  signalCount: number
  uniqueCount: number
  overlapCount: number
  items: T[]
}

export const STRATEGY_GROUP_META: Array<{ key: StrategyGroupKey; label: string }> = [
  { key: 'b1', label: 'B1形态' },
  { key: 'b2', label: 'B2突破' },
  { key: 'bowl', label: '碗底反弹' },
  { key: 'brick', label: '砖型图' },
]

export async function fetchAllStrategyResultItems<T = StrategyResultListItem>(
  fetchPage: (params: Record<string, unknown>) => Promise<StrategyResultsPagePayload<T>>,
  baseParams: Record<string, unknown>,
  options: FetchAllStrategyOptions = {},
): Promise<T[]> {
  const pageSize = options.pageSize ?? 200
  const maxPages = options.maxPages ?? 50
  const allItems: T[] = []
  let total = 0

  for (let page = 1; page <= maxPages; page += 1) {
    const payload = await fetchPage({ ...baseParams, page, per_page: pageSize })
    const pageItems = Array.isArray(payload.items) ? payload.items : []
    if (page === 1) {
      total = typeof payload.total === 'number' && payload.total > 0 ? payload.total : pageItems.length
    }
    allItems.push(...pageItems)

    if (!pageItems.length || pageItems.length < pageSize || allItems.length >= total) {
      break
    }
  }

  return allItems
}

export function buildUniqueStrategyList<T extends StrategyResultListItem>(items: T[]): T[] {
  const seen = new Set<string>()
  const unique: T[] = []

  for (const item of items) {
    const code = String(item.code || '')
    if (!code || seen.has(code)) continue
    seen.add(code)
    unique.push(item)
  }

  return unique
}

export function getStrategyGroupKey(item: StrategyResultListItem): StrategyGroupKey {
  const strategyFilter = String(item.strategy_filter || '').toLowerCase()
  if (strategyFilter === 'b1' || strategyFilter === 'b2' || strategyFilter === 'bowl' || strategyFilter === 'brick') {
    return strategyFilter
  }

  const name = String(item.strategy_name || '').toLowerCase()
  const category = String(item.category || '').toLowerCase()
  if (
    strategyFilter.includes('brick')
    || name.includes('brick')
    || category.includes('brick')
    || category.includes('砖')
  ) {
    return 'brick'
  }
  if (strategyFilter.includes('bowl') || name.includes('bowl') || category.includes('bowl')) {
    return 'bowl'
  }
  if (strategyFilter.includes('b2') || name.includes('b2') || category.includes('b2')) {
    return 'b2'
  }
  return 'b1'
}

export function buildStrategyGroups<T extends StrategyResultListItem>(items: T[]): StrategyGroup<T>[] {
  return STRATEGY_GROUP_META
    .map((meta) => {
      const groupRows = items.filter(item => getStrategyGroupKey(item) === meta.key)
      const uniqueItems = buildUniqueStrategyList(groupRows)
      return {
        key: meta.key,
        label: meta.label,
        signalCount: groupRows.length,
        uniqueCount: uniqueItems.length,
        overlapCount: Math.max(0, groupRows.length - uniqueItems.length),
        items: uniqueItems,
      }
    })
    .filter(group => group.signalCount > 0)
}

export function formatSimilarityPercent(score: unknown): string {
  if (typeof score !== 'number' || !Number.isFinite(score)) return '-'
  const normalized = score > 1 ? score : score * 100
  return `${normalized.toFixed(0)}%`
}
