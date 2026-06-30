// zettaranc 前端 API 封装
//
// 后端统一 envelope: { success, data, message }
// 这里只解开 data 层，调用方拿到的就是业务对象，
// 与 api/index.ts 中 strategy-docs 的处理风格一致。

import axios from 'axios'

const api = axios.create({ baseURL: '/api/zettaranc', timeout: 120000 })

// -------- 回测 --------
export interface BacktestSummary {
  config: Record<string, any>
  total_signals: number
  total_trades: number
  win_count: number
  loss_count: number
  win_rate: number
  avg_win_pct: number
  avg_loss_pct: number
  profit_loss_ratio: number
  avg_holding_days: number
  max_drawdown_pct: number
  exit_reason_counts: Record<string, number>
  category_counts: Record<string, number>
  monthly_pnl: Record<string, number>
  skipped_codes: number
  trades?: any[]
}

export const fetchBacktestLatest = async (): Promise<BacktestSummary> => {
  const res = await api.get<{ success: boolean; data: BacktestSummary }>('/backtest/latest')
  return res.data.data
}

export interface BacktestRunPayload {
  start?: string
  end?: string
  limit?: number
  take_profit?: number
  hold_days?: number
  j_buy?: number
  vol_ratio?: number
}

export const runBacktest = async (payload: BacktestRunPayload): Promise<BacktestSummary> => {
  const res = await api.post<{ success: boolean; data: BacktestSummary }>('/backtest/run', payload)
  return res.data.data
}

// -------- 持仓 --------
export interface Holding {
  code: string
  name: string
  entry_date: string
  entry_price: number
  qty: number
  stop_loss: number
  take_profit_pct?: number
  hold_days_limit?: number
  max_position_pct?: number
  total_capital?: number
  notes?: string
  created_at?: string
}

export interface HoldingAlert {
  code: string
  name: string
  rule: string
  severity: 'critical' | 'warn' | 'info'
  message: string
  extra: Record<string, any>
}

export const listHoldings = async (): Promise<Holding[]> => {
  const res = await api.get<{ success: boolean; data: Holding[] }>('/holdings')
  return res.data.data
}

export const addHolding = async (h: Holding): Promise<Holding> => {
  const res = await api.post<{ success: boolean; data: Holding }>('/holdings', h)
  return res.data.data
}

export const updateHolding = async (code: string, patch: Partial<Holding>): Promise<Holding> => {
  const res = await api.patch<{ success: boolean; data: Holding }>(`/holdings/${code}`, patch)
  return res.data.data
}

export const deleteHolding = async (code: string): Promise<void> => {
  await api.delete(`/holdings/${code}`)
}

export interface HoldingAlertsResponse {
  alerts: HoldingAlert[]
  summary: { total: number; critical: number; warn: number }
}

export const fetchHoldingAlerts = async (today?: string): Promise<HoldingAlertsResponse> => {
  const res = await api.get<{ success: boolean; data: HoldingAlertsResponse }>(
    '/holdings/alerts',
    { params: today ? { today } : {} },
  )
  return res.data.data
}

// -------- 攻击日扫描 --------
export interface AttackCandidate {
  code: string
  name: string
  signal_date: string
  close: number
  stop_loss: number
  J: number
  bbi: number
  vol_ratio: number
  category: string
  extra: Record<string, any>
}

export interface AttackScanResponse {
  count: number
  candidates: AttackCandidate[]
}

export const fetchAttackCandidates = async (limit = 50): Promise<AttackScanResponse> => {
  const res = await api.get<{ success: boolean; data: AttackScanResponse }>(
    '/attack-scan',
    { params: { limit } },
  )
  return res.data.data
}
