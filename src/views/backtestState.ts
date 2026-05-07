import type { BacktestCapabilities, BacktestTask } from '@/api'

export function isBacktestTaskCancelable(
  task: BacktestTask | null | undefined,
  capabilities: BacktestCapabilities | null | undefined,
): task is BacktestTask {
  if (capabilities?.asyncTasks === false) return false
  return task?.status === 'queued' || task?.status === 'running'
}

export function formatTrackingAction(action: unknown): string {
  const mapping: Record<string, string> = {
    WAIT_BUY: '等待买入',
    BUY: '买入意图',
    HOLD: '继续持有',
    HOLD_RUNNER: '放飞持有',
    HOLD_CORE: '底仓持有',
    SELL: '卖出',
    SELL_PARTIAL: '部分卖出',
    NO_DATA: '无行情',
  }
  const key = action == null ? '' : String(action)
  return mapping[key] || key || '-'
}

export function formatTrackingIntentSummary(intent: Record<string, any> | null | undefined): string {
  if (!intent) return '暂无下单意图'
  const side = intent.side === 'BUY' ? '买入' : intent.side === 'SELL' ? '卖出' : String(intent.side || '意图')
  const quantity = Number.isFinite(Number(intent.quantity)) ? `${Number(intent.quantity)} 股` : '数量未定'
  const priceType = intent.price_type || 'market'
  const price = intent.target_price == null ? '' : ` ${Number(intent.target_price)}`
  return `${side} ${quantity}，${priceType}${price}`
}
