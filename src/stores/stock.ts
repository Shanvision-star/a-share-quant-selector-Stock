import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getStockList, getKline, getStockPrice, getStrategyResults } from '@/api'

export const useStockStore = defineStore('stock', () => {
  const currentCode = ref('')
  const stockList = ref<any[]>([])
  const stockTotal = ref(0)
  const klineData = ref<any>(null)
  const priceInfo = ref<any>(null)
  const strategyResults = ref<any>({})
  const loading = ref(false)

  async function fetchStockList(params: { page?: number; per_page?: number; search?: string } = {}) {
    loading.value = true
    try {
      const res = await getStockList(params)
      stockList.value = res.data.data
      stockTotal.value = res.data.total
    } finally {
      loading.value = false
    }
  }

  async function fetchKline(code: string, params?: { period?: string; limit?: number }) {
    currentCode.value = code
    const res = await getKline(code, params)
    klineData.value = res.data.data
  }

  async function fetchPriceInfo(code: string) {
    const res = await getStockPrice(code)
    priceInfo.value = res.data.data
  }

  async function fetchStrategyResults(params?: { strategy?: string; date?: string }) {
    loading.value = true
    try {
      const res = await getStrategyResults(params)
      strategyResults.value = res.data.data
    } finally {
      loading.value = false
    }
  }

  return {
    currentCode, stockList, stockTotal, klineData, priceInfo,
    strategyResults, loading,
    fetchStockList, fetchKline, fetchPriceInfo, fetchStrategyResults,
  }
})
