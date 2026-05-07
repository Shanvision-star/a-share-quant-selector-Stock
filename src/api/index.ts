import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

interface RequestOptions {
  signal?: AbortSignal
}

export type KlineAdjust = 'qfq' | 'hfq' | 'nfq'

export interface KlineRequestParams {
  period?: string
  limit?: number
  adjust?: KlineAdjust
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
const DEFAULT_KLINE_PERIOD = 'daily'
const DEFAULT_KLINE_LIMIT = 2600
const DEFAULT_KLINE_ADJUST: KlineAdjust = 'qfq'
const klineResponseCache = new Map<string, any>()
const klinePendingRequests = new Map<string, Promise<any>>()
const DEFAULT_KLINE_PREFETCH_CONCURRENCY = 4
type KlinePrefetchPriority = 'normal' | 'high'

interface KlinePrefetchJob {
  code: string
  params: Required<KlineRequestParams>
  cacheKey: string
  priority: KlinePrefetchPriority
}

interface KlinePrefetchOptions {
  priority?: KlinePrefetchPriority
  maxConcurrent?: number
}

const klinePrefetchQueue: KlinePrefetchJob[] = []
const klinePrefetchQueuedKeys = new Set<string>()
let klinePrefetchActive = 0
let klinePrefetchMaxConcurrent = DEFAULT_KLINE_PREFETCH_CONCURRENCY

function normalizeKlineParams(params?: KlineRequestParams): Required<KlineRequestParams> {
  const limit = typeof params?.limit === 'number' && Number.isFinite(params.limit) && params.limit > 0
    ? Math.floor(params.limit)
    : DEFAULT_KLINE_LIMIT

  return {
    period: params?.period || DEFAULT_KLINE_PERIOD,
    limit,
    adjust: params?.adjust || DEFAULT_KLINE_ADJUST,
  }
}

export function getKlineCacheKey(code: string, params?: KlineRequestParams): string {
  const normalized = normalizeKlineParams(params)
  return `${code}|${normalized.period}|${normalized.adjust}|${normalized.limit}`
}

export function clearKlineCache() {
  klineResponseCache.clear()
  klinePendingRequests.clear()
  klinePrefetchQueue.splice(0, klinePrefetchQueue.length)
  klinePrefetchQueuedKeys.clear()
  klinePrefetchActive = 0
  klinePrefetchMaxConcurrent = DEFAULT_KLINE_PREFETCH_CONCURRENCY
}

export function getCachedKlineResponse(code: string, params?: KlineRequestParams) {
  return klineResponseCache.get(getKlineCacheKey(code, params))
}

export const getKline = (
  code: string,
  params?: KlineRequestParams,
  options: RequestOptions = {},
) => {
  const normalizedParams = normalizeKlineParams(params)
  const cacheKey = getKlineCacheKey(code, normalizedParams)
  const cached = klineResponseCache.get(cacheKey)
  if (cached) return Promise.resolve(cached)

  const pending = klinePendingRequests.get(cacheKey)
  if (pending) return pending

  const request = api
    .get(`/kline/${code}`, { params: normalizedParams, signal: options.signal })
    .then((response) => {
      klineResponseCache.set(cacheKey, response)
      return response
    })
    .finally(() => {
      if (klinePendingRequests.get(cacheKey) === request) {
        klinePendingRequests.delete(cacheKey)
      }
    })

  klinePendingRequests.set(cacheKey, request)

  return request
}

export const prefetchKline = (
  code: string,
  params?: KlineRequestParams,
) => getKline(code, params).catch(() => null)

function normalizePrefetchConcurrency(maxConcurrent?: number): number {
  if (typeof maxConcurrent !== 'number' || !Number.isFinite(maxConcurrent)) {
    return DEFAULT_KLINE_PREFETCH_CONCURRENCY
  }
  return Math.max(1, Math.floor(maxConcurrent))
}

function runKlinePrefetchQueue() {
  while (klinePrefetchActive < klinePrefetchMaxConcurrent && klinePrefetchQueue.length) {
    const job = klinePrefetchQueue.shift()
    if (!job) return
    klinePrefetchQueuedKeys.delete(job.cacheKey)

    if (klineResponseCache.has(job.cacheKey) || klinePendingRequests.has(job.cacheKey)) {
      continue
    }

    klinePrefetchActive += 1
    void getKline(job.code, job.params)
      .catch(() => null)
      .finally(() => {
        klinePrefetchActive = Math.max(0, klinePrefetchActive - 1)
        runKlinePrefetchQueue()
      })
  }
}

export function prefetchKlineBatch(
  codes: string[],
  params?: KlineRequestParams,
  options: KlinePrefetchOptions = {},
) {
  const uniqueCodes = Array.from(new Set(codes.filter(Boolean)))
  if (!uniqueCodes.length) return

  const priority = options.priority || 'normal'
  klinePrefetchMaxConcurrent = normalizePrefetchConcurrency(options.maxConcurrent)
  const jobs = uniqueCodes
    .map((code) => {
      const normalizedParams = normalizeKlineParams(params)
      const cacheKey = getKlineCacheKey(code, normalizedParams)
      return { code, params: normalizedParams, cacheKey, priority }
    })
    .filter(job =>
      !klineResponseCache.has(job.cacheKey)
      && !klinePendingRequests.has(job.cacheKey)
      && !klinePrefetchQueuedKeys.has(job.cacheKey),
    )

  if (!jobs.length) return

  for (const job of jobs) {
    klinePrefetchQueuedKeys.add(job.cacheKey)
  }

  if (priority === 'high') {
    klinePrefetchQueue.unshift(...jobs)
  } else {
    klinePrefetchQueue.push(...jobs)
  }

  runKlinePrefetchQueue()
}

export function getKlinePrefetchQueueState() {
  return {
    active: klinePrefetchActive,
    queued: klinePrefetchQueue.length,
    keys: klinePrefetchQueue.map(job => job.cacheKey),
  }
}

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

// 有结果的日期（按信号日期优先）
export const getAvailableDates = (limit?: number, strategy?: string) =>
  api.get('/strategy/results/dates', { params: { limit, strategy } })

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

export const updateConfig = (
  data: {
    strategy_name: string
    params: Record<string, any>
    expected_revision: string
  },
) =>
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

/** 获取 TXT 导出统计摘要 */
export const getTxtSummary = (params?: { date?: string }) =>
  api.get('/txt/summary', { params })

/** 从策略结果数据库生成通达信 TXT 文件 */
export const generateTxtFile = (params: { strategy: string; date?: string }) =>
  api.post('/txt/generate', null, { params })

/** 按策略分类批量生成通达信 TXT 文件 */
export const generateTxtFilesBatch = (params?: { date?: string }) =>
  api.post('/txt/generate-batch', null, { params })

/** 返回下载链接（直接浏览器跳转） */
export const getTxtDownloadUrl = (filename: string) =>
  `/api/txt/download/${encodeURIComponent(filename)}`

// 从内存缓存获取最新市值（后台刷新完成后调用）
export const getMarketCap = (codes?: string[]) =>
  api.get('/market-cap', { params: codes?.length ? { codes: codes.join(',') } : undefined })

// ─── 人工选股池 ───
export interface ManualSelectionPayload {
  selection_date: string
  code: string
  name?: string
  strategy_name?: string
  source_trade_date?: string
  source_signal_date?: string
  source_payload?: Record<string, any>
  note?: string
}

export const getManualSelections = (params?: {
  date?: string
  start_date?: string
  end_date?: string
}) => api.get('/manual-selections', { params })

export const getManualSelectionDates = (limit?: number) =>
  api.get('/manual-selections/dates', { params: { limit } })

export const saveManualSelection = (payload: ManualSelectionPayload) =>
  api.post('/manual-selections', payload)

export const deleteManualSelection = (date: string, code: string) =>
  api.delete('/manual-selections', { params: { date, code } })

// ─── 回测 ───
export interface BacktestRequestPayload {
  start_date: string
  end_date: string
  simulation_end_date?: string
  source: 'manual' | 'strategy' | 'codes'
  strategy: 'all' | 'b1' | 'b2' | 'bowl' | 'brick'
  selected_codes?: string[]
  selected_candidates?: Array<{
    code: string
    name?: string
    strategy_name?: string
    trade_date?: string
    signal_date?: string
  }>
  input_codes?: string[]
  holding_days: number
  buy_offset_days: number
  buy_price: 'open' | 'close'
  sell_price: 'open' | 'close'
  fee_rate: number
  slippage_rate: number
  take_profit_pct?: number
  stop_loss_pct?: number
  max_positions_per_day: number
  max_candidates?: number
  max_signals_per_code?: number
  max_runtime_seconds?: number
  codes_fallback_to_start_date?: boolean
  profit_run_enabled?: boolean
  profit_trigger_pct?: number
  profit_step_pct?: number
  profit_sell_pct?: number
  profit_keep_pct?: number
  hold_above_short_trend_after_trigger?: boolean
  enable_no_gain_exit?: boolean
  no_gain_days?: number
  exit_on_bull_bear_break?: boolean
  exit_on_short_trend_break?: boolean
  short_trend_break_days?: number
  exit_on_short_trend_drawdown?: boolean
  short_trend_drawdown_pct?: number
  intent_quantity?: number
  lot_size?: number
  allow_st_buy?: boolean
}

export type BacktestTaskStatus = 'queued' | 'running' | 'cancel_requested' | 'canceled' | 'done' | 'failed'

export interface BacktestTask {
  task_id: string
  status: BacktestTaskStatus
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
  updated_at?: string
  error?: string
  result?: any
  params?: Record<string, any>
  total_count?: number
  processed_count?: number
  current_code?: string
  progress_pct?: number
  message?: string
}

export interface BacktestTaskEvent {
  event_id: number
  task_id: string
  event_type: string
  progress_pct?: number | null
  message?: string
  payload?: Record<string, any>
  created_at?: string
}

export type BacktestLaunchMode = 'async' | 'sync_fallback'

export interface BacktestLaunchResult {
  mode: BacktestLaunchMode
  task: BacktestTask
}

export const runBacktest = (payload: BacktestRequestPayload) =>
  api.post('/backtest', payload)

export const startBacktestTask = (payload: BacktestRequestPayload) =>
  api.post('/backtest/tasks', payload)

function isMethodNotAllowed(error: any): boolean {
  return Number(error?.response?.status) === 405
}

function createSyncFallbackTask(payload: BacktestRequestPayload, result: any): BacktestTask {
  const now = new Date().toISOString()
  return {
    task_id: `sync_${Date.now()}`,
    status: 'done',
    created_at: now,
    started_at: now,
    finished_at: now,
    updated_at: now,
    error: '',
    result,
    params: { ...payload },
    total_count: result?.summary?.candidate_count ?? payload.selected_codes?.length ?? payload.input_codes?.length ?? 0,
    processed_count: result?.summary?.candidate_count ?? payload.selected_codes?.length ?? payload.input_codes?.length ?? 0,
    current_code: '',
    progress_pct: 100,
    message: '兼容同步回测完成',
  }
}

export async function startBacktestTaskCompatible(payload: BacktestRequestPayload): Promise<BacktestLaunchResult> {
  try {
    const response = await startBacktestTask(payload)
    return { mode: 'async', task: response.data.data as BacktestTask }
  } catch (error) {
    if (!isMethodNotAllowed(error)) throw error
    const response = await runBacktest(payload)
    return { mode: 'sync_fallback', task: createSyncFallbackTask(payload, response.data.data) }
  }
}

export const getBacktestTask = (taskId: string) =>
  api.get(`/backtest/tasks/${encodeURIComponent(taskId)}`)

export const cancelBacktestTask = (taskId: string) =>
  api.post(`/backtest/tasks/${encodeURIComponent(taskId)}/cancel`)

export const listBacktestTasks = (limit = 20) =>
  api.get('/backtest/tasks', { params: { limit } })

export const getBacktestTaskEvents = (taskId: string, limit = 500) =>
  api.get(`/backtest/tasks/${encodeURIComponent(taskId)}/events`, { params: { limit } })

export default api
