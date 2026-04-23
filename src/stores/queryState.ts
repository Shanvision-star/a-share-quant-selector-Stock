import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const STORAGE_KEY = 'query-state-cache-v1'

type HomeSortBy = 'code' | 'name' | 'latest_price' | 'change_pct' | 'market_cap' | 'latest_date' | 'k_value' | 'd_value' | 'j_value'
type HomeSortOrder = 'asc' | 'desc'
type ResultsSortOrder = 'ascending' | 'descending'

export interface HomeQueryState {
  page: number
  perPage: number
  search: string
  sortBy: HomeSortBy
  sortOrder: HomeSortOrder
}

export interface ResultsQueryState {
  page: number
  perPage: number
  runsPage: number
  strategy: string
  keyword: string
  dateRange: [string, string] | null
  jRange: [number, number] | null
  similarityRange: [number, number] | null
  sortBy: string
  sortOrder: ResultsSortOrder
}

const DEFAULT_HOME_QUERY: HomeQueryState = {
  page: 1,
  perPage: 50,
  search: '',
  sortBy: 'code',
  sortOrder: 'asc',
}

const DEFAULT_RESULTS_QUERY: ResultsQueryState = {
  page: 1,
  perPage: 50,
  runsPage: 1,
  strategy: 'all',
  keyword: '',
  dateRange: null,
  jRange: null,
  similarityRange: null,
  sortBy: 'trade_date',
  sortOrder: 'descending',
}

interface QueryStateSnapshot {
  home: HomeQueryState
  results: ResultsQueryState
}

const HOME_SORT_BY_VALUES: ReadonlySet<HomeSortBy> = new Set([
  'code',
  'name',
  'latest_price',
  'change_pct',
  'market_cap',
  'latest_date',
  'k_value',
  'd_value',
  'j_value',
])

const RESULTS_SORT_BY_VALUES: ReadonlySet<string> = new Set([
  'code',
  'strategy_name',
  'signal_date',
  'trigger_price',
  'j_value',
  'similarity_score',
  'run_started_at',
  'trade_date',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function normalizePositiveInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : fallback
}

function normalizeHomeSortBy(value: unknown): HomeSortBy {
  return typeof value === 'string' && HOME_SORT_BY_VALUES.has(value as HomeSortBy)
    ? value as HomeSortBy
    : DEFAULT_HOME_QUERY.sortBy
}

function normalizeHomeSortOrder(value: unknown): HomeSortOrder {
  return value === 'asc' || value === 'desc' ? value : DEFAULT_HOME_QUERY.sortOrder
}

function normalizeResultsSortOrder(value: unknown): ResultsSortOrder {
  return value === 'ascending' || value === 'descending' ? value : DEFAULT_RESULTS_QUERY.sortOrder
}

function normalizeResultsSortBy(value: unknown): string {
  return typeof value === 'string' && RESULTS_SORT_BY_VALUES.has(value)
    ? value
    : DEFAULT_RESULTS_QUERY.sortBy
}

function isIsoDateString(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value
}

function normalizeDateRange(value: unknown): [string, string] | null {
  if (!Array.isArray(value) || value.length !== 2) return null
  const [start, end] = value
  if (!isIsoDateString(start) || !isIsoDateString(end)) return null
  return start <= end ? [start, end] : [end, start]
}

function normalizeNumberRange(value: unknown): [number, number] | null {
  if (!Array.isArray(value) || value.length !== 2) return null
  const [min, max] = value
  return typeof min === 'number' && Number.isFinite(min) && typeof max === 'number' && Number.isFinite(max)
    ? [min, max]
    : null
}

function normalizeHomeSnapshot(value: unknown): HomeQueryState {
  if (!isRecord(value)) return { ...DEFAULT_HOME_QUERY }
  return {
    page: normalizePositiveInteger(value.page, DEFAULT_HOME_QUERY.page),
    perPage: normalizePositiveInteger(value.perPage, DEFAULT_HOME_QUERY.perPage),
    search: typeof value.search === 'string' ? value.search : DEFAULT_HOME_QUERY.search,
    sortBy: normalizeHomeSortBy(value.sortBy),
    sortOrder: normalizeHomeSortOrder(value.sortOrder),
  }
}

function normalizeResultsSnapshot(value: unknown): ResultsQueryState {
  if (!isRecord(value)) return { ...DEFAULT_RESULTS_QUERY }
  return {
    page: normalizePositiveInteger(value.page, DEFAULT_RESULTS_QUERY.page),
    perPage: normalizePositiveInteger(value.perPage, DEFAULT_RESULTS_QUERY.perPage),
    runsPage: normalizePositiveInteger(value.runsPage, DEFAULT_RESULTS_QUERY.runsPage),
    strategy: typeof value.strategy === 'string' && value.strategy.trim().length > 0
      ? value.strategy
      : DEFAULT_RESULTS_QUERY.strategy,
    keyword: typeof value.keyword === 'string' ? value.keyword : DEFAULT_RESULTS_QUERY.keyword,
    dateRange: normalizeDateRange(value.dateRange),
    jRange: normalizeNumberRange(value.jRange),
    similarityRange: normalizeNumberRange(value.similarityRange),
    sortBy: normalizeResultsSortBy(value.sortBy),
    sortOrder: normalizeResultsSortOrder(value.sortOrder),
  }
}

function loadSnapshot(): QueryStateSnapshot {
  if (typeof window === 'undefined') {
    return { home: { ...DEFAULT_HOME_QUERY }, results: { ...DEFAULT_RESULTS_QUERY } }
  }

  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { home: { ...DEFAULT_HOME_QUERY }, results: { ...DEFAULT_RESULTS_QUERY } }
    const parsed = JSON.parse(raw) as unknown
    const snapshot = isRecord(parsed) ? parsed : {}
    return {
      home: normalizeHomeSnapshot(snapshot.home),
      results: normalizeResultsSnapshot(snapshot.results),
    }
  } catch {
    return { home: { ...DEFAULT_HOME_QUERY }, results: { ...DEFAULT_RESULTS_QUERY } }
  }
}

function saveSnapshot(snapshot: QueryStateSnapshot) {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
  } catch {
    // ignore storage errors
  }
}

export const useQueryStateStore = defineStore('queryState', () => {
  const initial = loadSnapshot()
  const home = ref<HomeQueryState>(initial.home)
  const results = ref<ResultsQueryState>(initial.results)

  watch([home, results], () => {
    saveSnapshot({ home: home.value, results: results.value })
  }, { deep: true })

  function setHomePage(page: number) {
    home.value.page = page
  }

  function setHomeSearch(search: string) {
    home.value.search = search
  }

  function setHomeSort(sortBy: HomeSortBy, sortOrder: HomeSortOrder) {
    home.value.sortBy = sortBy
    home.value.sortOrder = sortOrder
    home.value.page = 1
  }

  function setResultsPage(page: number) {
    results.value.page = page
  }

  function setResultsRunsPage(page: number) {
    results.value.runsPage = page
  }

  function setResultsStrategy(strategy: string) {
    results.value.strategy = strategy
    results.value.page = 1
    results.value.runsPage = 1
  }

  function setResultsKeyword(keyword: string) {
    results.value.keyword = keyword
    results.value.page = 1
  }

  function setResultsDateRange(dateRange: [string, string] | null) {
    results.value.dateRange = dateRange
    results.value.page = 1
  }

  function setResultsJRange(jRange: [number, number] | null) {
    results.value.jRange = jRange
    results.value.page = 1
  }

  function setResultsSimilarityRange(similarityRange: [number, number] | null) {
    results.value.similarityRange = similarityRange
    results.value.page = 1
  }

  function setResultsSort(sortBy: string, sortOrder: ResultsSortOrder) {
    results.value.sortBy = sortBy || 'trade_date'
    results.value.sortOrder = sortOrder
    results.value.page = 1
  }

  return {
    home,
    results,
    setHomePage,
    setHomeSearch,
    setHomeSort,
    setResultsPage,
    setResultsRunsPage,
    setResultsStrategy,
    setResultsKeyword,
    setResultsDateRange,
    setResultsJRange,
    setResultsSimilarityRange,
    setResultsSort,
  }
})
