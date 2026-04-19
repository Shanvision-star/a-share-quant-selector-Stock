import { defineStore } from 'pinia'
import { ref } from 'vue'

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
  category?: string
  signal_date?: string
  trade_date?: string
  trigger_price?: number
  j_value?: number
  reason?: string
}

export const useStrategyListStore = defineStore('strategyList', () => {
  const initial = loadFromSession()

  /** 当前策略结果列表（来自 StrategyResultsView 或最近一次查询） */
  const items = ref<StrategyResultItem[]>(initial.items)
  const strategy = ref(initial.strategy)
  const tradeDate = ref(initial.tradeDate)

  function setList(newItems: StrategyResultItem[], strat: string, date: string) {
    items.value = newItems
    strategy.value = strat
    tradeDate.value = date
    saveToSession({ items: items.value, strategy: strategy.value, tradeDate: tradeDate.value })
  }

  function clear() {
    items.value = []
    strategy.value = 'all'
    tradeDate.value = ''
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

  return { items, strategy, tradeDate, setList, clear, pushItem }
})
