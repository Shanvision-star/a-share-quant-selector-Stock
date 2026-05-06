import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getAvailableDates, getStrategyResultsHistory } from '../api/index'
import { fetchAllStrategyResultItems } from '@/utils/strategyResults'

const STORAGE_KEY = 'strategy-list-cache-v1'

function loadFromSession(): { items: StrategyResultItem[]; strategy: string; tradeDate: string } {
  if (typeof window === 'undefined') {
    return { items: [], strategy: 'all', tradeDate: '' }
  }

  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { items: [], strategy: 'all', tradeDate: '' }
    const parsed = JSON.parse(raw)
    return {
      items: Array.isArray(parsed?.items) ? parsed.items : [],
      strategy: typeof parsed?.strategy === 'string' ? parsed.strategy : 'all',
      tradeDate: typeof parsed?.tradeDate === 'string' ? parsed.tradeDate : '',
    }
  } catch {
    return { items: [], strategy: 'all', tradeDate: '' }
  }
}

function saveToSession(payload: { items: StrategyResultItem[]; strategy: string; tradeDate: string }) {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  } catch {
    // 忽略持久化失败（例如隐私模式配额限制）
  }
}

export interface StrategyResultItem {
  code: string
  name: string
  strategy_name: string
  strategy_filter?: string
  category?: string
  signal_date?: string
  trade_date?: string
  trigger_price?: number
  j_value?: number
  similarity_score?: number | null
  reason?: string
}

export const useStrategyListStore = defineStore('strategyList', () => {
  const initial = loadFromSession()

  /** 当前策略结果列表（来自 StrategyResultsView 或最近一次查询） */
  const items = ref<StrategyResultItem[]>(initial.items)
  const strategy = ref(initial.strategy)
  const tradeDate = ref(initial.tradeDate)

  /** 右侧个股详情侧栏专用：当前选中日期 / 可用日期列表 / 加载态 */
  const selectedDate = ref<string>(initial.tradeDate)
  const availableDates = ref<string[]>([])
  const isLoadingDates = ref(false)
  const isLoadingList = ref(false)

  /** 获取可用交易日列表（供个股详情右侧日期下拉框使用） */
  async function fetchAvailableDates(limit = 30): Promise<void> {
    isLoadingDates.value = true
    try {
      const res = await getAvailableDates(limit)
      const dates: string[] = res?.data?.data ?? res?.data?.dates ?? []
      availableDates.value = Array.isArray(dates) ? dates : []
      // 若当前 selectedDate 为空，默认选最新交易日
      if (!selectedDate.value && availableDates.value.length > 0) {
        selectedDate.value = availableDates.value[0]
      }
    } catch (e) {
      // 忽略，保留旧列表
    } finally {
      isLoadingDates.value = false
    }
  }

  /** 按指定交易日重新加载侧栏策略列表 */
  async function fetchListByDate(date: string, strat = 'all'): Promise<void> {
    if (!date) return
    isLoadingList.value = true
    selectedDate.value = date
    try {
      const rawItems = await fetchAllStrategyResultItems(
        async (params) => {
          const res = await getStrategyResultsHistory(params as any)
          return res?.data?.data ?? res?.data ?? {}
        },
        {
          start_date: date,
          end_date: date,
          strategy: strat === 'all' ? undefined : strat,
          sort_by: 'run_started_at',
          sort_order: 'desc',
        },
        { pageSize: 200 },
      )
      const mapped: StrategyResultItem[] = rawItems.map((r: any) => ({
        code: r.code ?? '',
        name: r.name ?? r.stock_name ?? '',
        strategy_filter: r.strategy_filter,
        strategy_name: r.strategy_name ?? '',
        category: r.category,
        signal_date: r.signal_date ?? r.b2_date ?? r.trade_date,
        trade_date: r.trade_date,
        trigger_price: r.trigger_price ?? r.b2_close,
        j_value: r.j_value ?? r.j_at_b2,
        similarity_score: r.similarity_score,
        reason: r.reason,
      }))
      items.value = mapped
      strategy.value = strat
      tradeDate.value = date
      saveToSession({ items: items.value, strategy: strategy.value, tradeDate: tradeDate.value })
    } catch (e) {
      items.value = []
    } finally {
      isLoadingList.value = false
    }
  }

  function setList(newItems: StrategyResultItem[], strat: string, date: string) {
    items.value = newItems
    strategy.value = strat
    tradeDate.value = date
    selectedDate.value = date
    saveToSession({ items: items.value, strategy: strategy.value, tradeDate: tradeDate.value })
  }

  function clear() {
    items.value = []
    strategy.value = 'all'
    tradeDate.value = ''
    selectedDate.value = ''
    if (typeof window !== 'undefined') {
      window.sessionStorage.removeItem(STORAGE_KEY)
    }
  }

  /** 实时追加单条命中结果（pipeline 模式用）。按 code+strategy_name 去重，已存在则更新，否则前插。 */
  function pushItem(item: StrategyResultItem) {
    const idx = items.value.findIndex(
      i => i.code === item.code && i.strategy_name === item.strategy_name,
    )
    if (idx === -1) {
      items.value.unshift(item)
    } else {
      items.value.splice(idx, 1, item)
    }
    saveToSession({ items: items.value, strategy: strategy.value, tradeDate: tradeDate.value })
  }

  return {
    items, strategy, tradeDate,
    selectedDate, availableDates, isLoadingDates, isLoadingList,
    setList, clear, pushItem,
    fetchAvailableDates, fetchListByDate,
  }
})
