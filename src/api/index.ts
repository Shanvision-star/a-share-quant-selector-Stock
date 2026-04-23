import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

interface RequestOptions {
  signal?: AbortSignal
}

// 股票列表
export const getStockList = (params: {
  page?: number
  per_page?: number
  search?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}, options: RequestOptions = {}) =>
  api.get('/stock/list', { params, signal: options.signal })

// K 线数据
export const getKline = (code: string, params?: {
  period?: string
  limit?: number
  adjust?: 'qfq' | 'hfq' | 'nfq'
}) =>
  api.get(`/kline/${code}`, { params })

// 股票价格面板
export const getStockPrice = (code: string) =>
  api.get(`/stock/price/${code}`)

// 迷你 K 线
export const getMiniKline = (code: string, days?: number) =>
  api.get(`/stock/mini-kline/${code}`, { params: { days } })

// 分时K线（弹窗用，仅对日K有效）
export const getIntradayKline = (code: string, date: string, period = '1') =>
  api.get(`/kline/${code}/intraday`, { params: { date, period } })

// 股票扩展信息（概念标签等，懒加载）
export const getStockInfo = (code: string) =>
  api.get(`/stock/info/${code}`)

// 策略选股结果
export const getStrategyResults = (
  params?: { strategy?: string; date?: string },
  options: RequestOptions = {},
) =>
  api.get('/strategy/results', { params, signal: options.signal })

// 策略历史结果查询
export const getStrategyResultsHistory = (params?: {
  strategy?: string; start_date?: string; end_date?: string;
  code?: string; keyword?: string;
  min_j_value?: number; max_j_value?: number;
  min_similarity?: number; max_similarity?: number;
  page?: number; per_page?: number;
  sort_by?: string; sort_order?: string;
}, options: RequestOptions = {}) => api.get('/strategy/results/history', { params, signal: options.signal })

// 有结果的交易日期
export const getAvailableDates = (limit?: number) =>
  api.get('/strategy/results/dates', { params: { limit } })

// 策略缓存状态
export const getStrategyCacheStatus = (
  params?: { strategy?: string; date?: string },
  options: RequestOptions = {},
) =>
  api.get('/strategy/cache/status', { params, signal: options.signal })

// 运行记录列表
export const getStrategyRuns = (params?: {
  run_type?: string; status?: string; strategy?: string; date?: string;
  page?: number; per_page?: number;
}, options: RequestOptions = {}) => api.get('/strategy/runs', { params, signal: options.signal })

// 单次运行详情
export const getStrategyRunDetail = (runId: string) =>
  api.get(`/strategy/runs/${runId}`)

// 单次运行事件
export const getStrategyRunEvents = (
  runId: string,
  limit?: number,
  options: RequestOptions = {},
) =>
  api.get(`/strategy/runs/${runId}/events`, { params: { limit }, signal: options.signal })

// 数据状态
export const getDataStatus = () =>
  api.get('/data/status')

// 数据初始化状态检测（首次克隆检测）
export const getInitStatus = () =>
  api.get('/data/init-status')

// 配置
export const getConfig = () =>
  api.get('/config')

export const updateConfig = (data: { strategy_name: string; params: Record<string, any> }) =>
  api.post('/config', data)

// 健康检查
export const healthCheck = () =>
  api.get('/health')

// ─── TXT 文件库 ───

/** 列出已生成的 TXT 文件（可按日期过滤） */
export const getTxtFiles = (params?: { date?: string }) =>
  api.get('/txt/files', { params })

/** 获取 TXT 文件库中已有的日期列表 */
export const getTxtDates = () =>
  api.get('/txt/dates')

/** 获取 TXT 导出目录等基础信息 */
export const getTxtInfo = () =>
  api.get('/txt/info')

/** 从策略结果数据库生成通达信 TXT 文件 */
export const generateTxtFile = (params: { strategy: string; date?: string }) =>
  api.post('/txt/generate', null, { params })

/** 返回下载链接（直接浏览器跳转） */
export const getTxtDownloadUrl = (filename: string) =>
  `/api/txt/download/${encodeURIComponent(filename)}`

// 从内存缓存获取最新市值（后台刷新完成后调用）
export const getMarketCap = (codes?: string[]) =>
  api.get('/market-cap', { params: codes?.length ? { codes: codes.join(',') } : undefined })

export default api
