import type { BacktestCapabilities, BacktestTask } from '@/api'

export function isBacktestTaskCancelable(
  task: BacktestTask | null | undefined,
  capabilities: BacktestCapabilities | null | undefined,
): task is BacktestTask {
  if (capabilities?.asyncTasks === false) return false
  return task?.status === 'queued' || task?.status === 'running'
}
