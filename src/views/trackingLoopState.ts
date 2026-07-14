import type { TrackingLoopRun } from '@/api'

export type TrackingLoopTagType = 'success' | 'warning' | 'danger' | 'primary' | 'info'

export function trackingLoopStatusMeta(status?: string | null): {
  label: string
  tagType: TrackingLoopTagType
} {
  switch (status) {
    case 'done':
      return { label: '已完成', tagType: 'success' }
    case 'partial':
      return { label: '部分完成', tagType: 'warning' }
    case 'error':
      return { label: '失败', tagType: 'danger' }
    case 'running':
      return { label: '运行中', tagType: 'primary' }
    case 'busy':
      return { label: '已有任务运行', tagType: 'warning' }
    default:
      return { label: '尚未运行', tagType: 'info' }
  }
}

function count(value: unknown): number {
  return Array.isArray(value) ? value.length : Number(value ?? 0) || 0
}

export function trackingLoopSummary(run?: TrackingLoopRun | null): string {
  if (!run) return '尚未执行过收盘循环'
  if (run.status === 'error' && run.error) {
    const stage = String(run.error.stage || 'runner')
    const message = String(run.error.message || '未知错误')
    return `${stage}：${message}`
  }

  const sync = run.sync ?? {}
  const evaluation = run.evaluation ?? {}
  const dispatch = run.dispatch ?? {}
  return [
    `行情更新 ${count(sync.updated)} / 跳过 ${count(sync.skipped)} / 失败 ${count(sync.errors)}`,
    `评估 ${count(evaluation.evaluated)} / 新告警 ${count(evaluation.alerts_created)} / 去重 ${count(evaluation.alerts_skipped_dup)}`,
    `分发 ${count(dispatch.dispatched)} / 延后 ${count(dispatch.deferred)}`,
  ].join('；')
}
