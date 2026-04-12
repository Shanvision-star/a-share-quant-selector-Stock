import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

// 股票列表
export const getStockList = (params: { page?: number; per_page?: number; search?: string }) =>
  api.get('/stock/list', { params })

// K 线数据
export const getKline = (code: string, params?: { period?: string; limit?: number }) =>
  api.get(`/kline/${code}`, { params })

// 股票价格面板
export const getStockPrice = (code: string) =>
  api.get(`/stock/price/${code}`)

// 迷你 K 线
export const getMiniKline = (code: string, days?: number) =>
  api.get(`/stock/mini-kline/${code}`, { params: { days } })

// 策略选股结果
export const getStrategyResults = (params?: { strategy?: string; date?: string }) =>
  api.get('/strategy/results', { params })

// 策略缓存状态
export const getStrategyCacheStatus = (params?: { strategy?: string; date?: string }) =>
  api.get('/strategy/cache/status', { params })

// 数据状态
export const getDataStatus = () =>
  api.get('/data/status')

// 配置
export const getConfig = () =>
  api.get('/config')

export const updateConfig = (data: { strategy_name: string; params: Record<string, any> }) =>
  api.post('/config', data)

// 健康检查
export const healthCheck = () =>
  api.get('/health')

export default api
