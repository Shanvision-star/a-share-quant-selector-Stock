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

function loadSnapshot(): QueryStateSnapshot {
  if (typeof window === 'undefined') {
    return { home: { ...DEFAULT_HOME_QUERY }, results: { ...DEFAULT_RESULTS_QUERY } }
  }

  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { home: { ...DEFAULT_HOME_QUERY }, results: { ...DEFAULT_RESULTS_QUERY } }
    const parsed = JSON.parse(raw) as Partial<QueryStateSnapshot>
    return {
      home: { ...DEFAULT_HOME_QUERY, ...(parsed.home || {}) },
      results: { ...DEFAULT_RESULTS_QUERY, ...(parsed.results || {}) },
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
