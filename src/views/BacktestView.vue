<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cancelBacktestTask,
  getManualSelections,
  getBacktestTaskEvents,
  getStrategyResultsHistory,
  getBacktestTask,
  listBacktestTasks,
  startBacktestTaskCompatible,
  type BacktestRequestPayload,
  type BacktestTask,
  type BacktestTaskEvent,
  type BacktestTaskStatus,
} from '@/api'
import { fetchAllStrategyResultItems, formatSimilarityPercent } from '@/utils/strategyResults'

interface StrategyCandidate {
  code: string
  name?: string
  strategy_name?: string
  trade_date?: string
  signal_date?: string
  similarity_score?: number | null
}

function formatDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function shiftDays(days: number): Date {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date
}

function parseCodes(value: string): string[] {
  const seen = new Set<string>()
  return value
    .split(/[\s,，;；]+/)
    .map(item => item.trim())
    .filter(item => /^\d{6}$/.test(item))
    .filter((code) => {
      if (seen.has(code)) return false
      seen.add(code)
      return true
    })
}

function candidateKey(item: StrategyCandidate): string {
  return `${item.code}|${item.strategy_name || ''}|${item.signal_date || item.trade_date || ''}`
}

const dateRange = ref<[string, string]>([formatDate(shiftDays(-90)), formatDate(new Date())])
const codeInput = ref('')
const candidateRows = ref<StrategyCandidate[]>([])
const selectedCandidateKeys = ref<Set<string>>(new Set())
const candidateLoading = ref(false)
const loading = ref(false)
const result = ref<any>(null)
const route = useRoute()
const manualSelectionMode = ref<'none' | 'single' | 'batch'>('none')
const activeTaskId = ref('')
const taskStatus = ref<BacktestTaskStatus | ''>('')
const taskMessage = ref('')
const currentTask = ref<BacktestTask | null>(null)
const taskHistory = ref<BacktestTask[]>([])
const taskEvents = ref<BacktestTaskEvent[]>([])
const taskDrawerVisible = ref(false)
const taskActionLoading = ref(false)
let backtestPollTimer: number | null = null

const params = reactive<BacktestRequestPayload>({
  start_date: dateRange.value[0],
  end_date: dateRange.value[1],
  source: 'strategy',
  strategy: 'all',
  selected_codes: [],
  selected_candidates: [],
  input_codes: [],
  holding_days: 20,
  buy_offset_days: 1,
  buy_price: 'open',
  sell_price: 'close',
  fee_rate: 0.0003,
  slippage_rate: 0.0005,
  take_profit_pct: 0,
  stop_loss_pct: 0,
  max_positions_per_day: 20,
  max_candidates: 800,
  max_signals_per_code: 80,
  max_runtime_seconds: 20,
  codes_fallback_to_start_date: false,
  profit_run_enabled: true,
  profit_trigger_pct: 5,
  profit_step_pct: 10,
  profit_sell_pct: 25,
  profit_keep_pct: 25,
  hold_above_short_trend_after_trigger: true,
  enable_no_gain_exit: true,
  no_gain_days: 3,
  exit_on_bull_bear_break: true,
  exit_on_short_trend_break: true,
  short_trend_break_days: 2,
  exit_on_short_trend_drawdown: true,
  short_trend_drawdown_pct: 5,
  intent_quantity: 0,
  lot_size: 100,
  allow_st_buy: false,
})

const parsedInputCodes = computed(() => parseCodes(codeInput.value))
const summary = computed(() => result.value?.summary || null)
const trades = computed(() => result.value?.trades || [])
const equityCurve = computed(() => result.value?.equity_curve || [])
const runtime = computed(() => result.value?.runtime || {})
const runtimeWarnings = computed(() => runtime.value?.warnings || [])
const taskProgress = computed(() => Math.max(0, Math.min(100, Number(currentTask.value?.progress_pct || 0))))
const drawerSummaryItems = computed(() => {
  const data = currentTask.value?.result?.summary || {}
  return [
    { label: '候选', value: data.candidate_count ?? 0, suffix: '只' },
    { label: '交易', value: data.trade_count ?? 0, suffix: '笔' },
    { label: '胜率', value: data.win_rate_pct ?? 0, suffix: '%' },
    { label: '收益', value: data.cumulative_return_pct ?? 0, suffix: '%' },
  ]
})
const selectedCandidateCodes = computed(() => {
  const selected = new Set<string>()
  for (const row of candidateRows.value) {
    if (selectedCandidateKeys.value.has(candidateKey(row))) selected.add(row.code)
  }
  return Array.from(selected)
})
const selectedCandidates = computed(() => (
  candidateRows.value
    .filter(row => selectedCandidateKeys.value.has(candidateKey(row)))
    .map(row => ({
      code: row.code,
      name: row.name || '',
      strategy_name: row.strategy_name || '',
      trade_date: row.trade_date || row.signal_date || '',
      signal_date: row.signal_date || row.trade_date || '',
    }))
))
const isAllCandidatesSelected = computed(() => (
  candidateRows.value.length > 0 && selectedCandidateKeys.value.size === candidateRows.value.length
))

const metricItems = computed(() => {
  const data = summary.value || {}
  return [
    { label: '候选', value: data.candidate_count ?? 0, suffix: '只' },
    { label: '交易', value: data.trade_count ?? 0, suffix: '笔' },
    { label: '胜率', value: data.win_rate_pct ?? 0, suffix: '%' },
    { label: '平均收益', value: data.avg_return_pct ?? 0, suffix: '%' },
    { label: '累计收益', value: data.cumulative_return_pct ?? 0, suffix: '%' },
    { label: '最大回撤', value: data.max_drawdown_pct ?? 0, suffix: '%' },
  ]
})

function syncDateRange() {
  params.start_date = dateRange.value?.[0] || ''
  params.end_date = dateRange.value?.[1] || ''
}

async function loadStrategyCandidates() {
  syncDateRange()
  if (!params.start_date || !params.end_date) {
    ElMessage.warning('请先选择信号日期范围')
    return
  }
  candidateLoading.value = true
  try {
    const inputCodes = parsedInputCodes.value
    let items: StrategyCandidate[] = []
    const noHit: string[] = []
    if (inputCodes.length) {
      // 逐 code 拉取策略命中，保留多次信号
      for (const code of inputCodes) {
        const codeItems = await fetchAllStrategyResultItems<StrategyCandidate>(
          async (query) => {
            const res = await getStrategyResultsHistory(query as any)
            return res.data.data || {}
          },
          {
            strategy: params.strategy,
            start_date: params.start_date,
            end_date: params.end_date,
            code,
            sort_by: 'signal_date',
            sort_order: 'asc',
          },
          { pageSize: 200, maxPages: 10 },
        )
        if (codeItems.length) items.push(...codeItems)
        else noHit.push(code)
      }
    } else {
      items = await fetchAllStrategyResultItems<StrategyCandidate>(
        async (query) => {
          const res = await getStrategyResultsHistory(query as any)
          return res.data.data || {}
        },
        {
          strategy: params.strategy,
          start_date: params.start_date,
          end_date: params.end_date,
          sort_by: 'signal_date',
          sort_order: 'asc',
        },
        { pageSize: 200, maxPages: 30 },
      )
    }
    candidateRows.value = items
    selectedCandidateKeys.value = new Set(candidateRows.value.map(candidateKey))
    if (inputCodes.length && !items.length) {
      try {
        await ElMessageBox.confirm(
          `输入的 ${inputCodes.length} 个代码在区间内均无策略命中。是否退化为“按 ${params.start_date} 直买入”模式？`,
          '无策略信号',
          { type: 'warning', confirmButtonText: '退化直买', cancelButtonText: '取消' },
        )
        params.source = 'codes'
        params.codes_fallback_to_start_date = true
        ElMessage.info('已切换到输入个股模式，点击开始回测即可')
      } catch {
        // 取消
      }
    } else if (noHit.length) {
      ElMessage.warning(`已加载 ${items.length} 条；${noHit.length} 个代码区间内无策略命中`)
    } else {
      ElMessage.success(`已加载 ${candidateRows.value.length} 条策略候选`)
    }
  } catch (error) {
    console.error('加载策略候选失败', error)
    ElMessage.error('加载策略候选失败')
  } finally {
    candidateLoading.value = false
  }
}

async function loadManualSelections() {
  syncDateRange()
  if (!params.start_date || !params.end_date) {
    ElMessage.warning('请先选择信号日期范围')
    return
  }
  candidateLoading.value = true
  try {
    const res = await getManualSelections({ start_date: params.start_date, end_date: params.end_date })
    const list = (res?.data?.data ?? []) as any[]
    candidateRows.value = list.map(item => ({
      code: item.code,
      name: item.name || '',
      strategy_name: item.strategy_name || 'manual',
      trade_date: item.selection_date,
      signal_date: item.source_signal_date || item.source_trade_date || item.selection_date,
      similarity_score: null,
    }))
    const inputCodeSet = new Set(parsedInputCodes.value)
    if (inputCodeSet.size) {
      selectedCandidateKeys.value = new Set(
        candidateRows.value
          .filter(row => inputCodeSet.has(row.code))
          .map(candidateKey),
      )
    } else if (manualSelectionMode.value === 'batch') {
      selectedCandidateKeys.value = new Set(candidateRows.value.map(candidateKey))
    } else {
      selectedCandidateKeys.value = new Set()
    }
    ElMessage.success(`已加载 ${candidateRows.value.length} 条人工选股，已选 ${selectedCandidateKeys.value.size} 条`)
  } catch (error) {
    console.error('加载人工选股失败', error)
    ElMessage.error('加载人工选股失败')
  } finally {
    candidateLoading.value = false
  }
}

async function handleLoadCandidates() {
  if (params.source === 'manual') {
    await loadManualSelections()
  } else {
    await loadStrategyCandidates()
  }
}

function toggleCandidate(row: StrategyCandidate, checked: boolean) {
  const next = new Set(selectedCandidateKeys.value)
  const key = candidateKey(row)
  if (checked) next.add(key)
  else next.delete(key)
  selectedCandidateKeys.value = next
}

function toggleAllCandidates() {
  selectedCandidateKeys.value = isAllCandidatesSelected.value
    ? new Set()
    : new Set(candidateRows.value.map(candidateKey))
}

function clearCandidates() {
  candidateRows.value = []
  selectedCandidateKeys.value = new Set()
}

function buildPayload(): BacktestRequestPayload {
  syncDateRange()
  const inputCodes = parsedInputCodes.value
  const selectedCodes = selectedCandidateCodes.value
  const candidatePayload = selectedCandidates.value
  return {
    ...params,
    input_codes: params.source === 'codes' ? inputCodes : (params.source === 'strategy' ? inputCodes : []),
    selected_candidates: params.source === 'strategy' ? candidatePayload : [],
    selected_codes: params.source === 'strategy'
      ? (candidatePayload.length ? selectedCodes : inputCodes)
      : params.source === 'manual'
        ? (selectedCodes.length ? selectedCodes : inputCodes)
        : [],
  }
}

async function handleRunBacktest() {
  const payload = buildPayload()
  if (!payload.start_date || !payload.end_date) {
    ElMessage.warning('请选择信号日期范围')
    return
  }
  if (payload.source === 'codes' && !payload.input_codes?.length) {
    ElMessage.warning('请输入至少一个6位股票代码')
    return
  }
  if (payload.source === 'manual' && !payload.selected_codes?.length) {
    ElMessage.warning('请先勾选人工选股，或从人工选股池点击单只回测')
    return
  }
  clearBacktestPoll()
  result.value = null
  loading.value = true
  activeTaskId.value = ''
  taskStatus.value = ''
  taskMessage.value = ''
  currentTask.value = null
  taskEvents.value = []
  try {
    const launched = await startBacktestTaskCompatible(payload)
    const task = launched.task
    applyBacktestTask(task)
    if (launched.mode === 'sync_fallback') {
      result.value = task.result
      taskEvents.value = []
      loading.value = false
      taskMessage.value = '当前后端未提供异步任务接口，已使用兼容同步回测完成'
      await loadBacktestTasks()
      ElMessage.warning('后端异步任务接口不可用，已自动切换到同步回测')
      return
    }
    taskMessage.value = `任务已提交：${task.task_id}`
    await loadBacktestTasks()
    scheduleBacktestPoll(task.task_id, 300)
  } catch (error: any) {
    console.error('回测失败', error)
    ElMessage.error(error?.response?.data?.detail || '回测失败，请确认后端已重启到最新代码')
    loading.value = false
  } finally {
    // 异步任务会在轮询结束时关闭 loading。
  }
}

function clearBacktestPoll() {
  if (backtestPollTimer !== null) {
    window.clearTimeout(backtestPollTimer)
    backtestPollTimer = null
  }
}

function scheduleBacktestPoll(taskId: string, delay = 1000) {
  clearBacktestPoll()
  backtestPollTimer = window.setTimeout(() => {
    void pollBacktestTask(taskId)
  }, delay)
}

async function pollBacktestTask(taskId: string) {
  try {
    const res = await getBacktestTask(taskId)
    const task = res.data.data as BacktestTask
    applyBacktestTask(task)
    await loadBacktestTaskEvents(taskId)

    if (task.status === 'done') {
      result.value = task.result
      loading.value = false
      clearBacktestPoll()
      await loadBacktestTasks()
      ElMessage.success(`回测完成：${result.value?.summary?.trade_count || 0} 笔交易`)
      return
    }

    if (task.status === 'canceled') {
      loading.value = false
      clearBacktestPoll()
      await loadBacktestTasks()
      ElMessage.warning('回测任务已取消')
      return
    }

    if (task.status === 'failed') {
      loading.value = false
      clearBacktestPoll()
      await loadBacktestTasks()
      ElMessage.error(task.error || '回测任务失败')
      return
    }

    scheduleBacktestPoll(taskId)
  } catch (error: any) {
    console.error('查询回测任务失败', error)
    loading.value = false
    clearBacktestPoll()
    ElMessage.error(error?.response?.data?.detail || '查询回测任务失败')
  }
}

function applyBacktestTask(task: BacktestTask) {
  currentTask.value = task
  activeTaskId.value = task.task_id
  taskStatus.value = task.status
  taskMessage.value = task.finished_at
    ? `任务 ${task.task_id} 已结束：${task.finished_at}`
    : task.message || `任务 ${task.task_id} ${formatTaskStatus(task.status)}`
}

async function loadBacktestTasks() {
  try {
    const res = await listBacktestTasks(12)
    taskHistory.value = (res.data.data?.items || []) as BacktestTask[]
  } catch (error) {
    console.warn('加载回测任务历史失败', error)
  }
}

async function loadBacktestTaskEvents(taskId: string) {
  try {
    const res = await getBacktestTaskEvents(taskId, 80)
    taskEvents.value = (res.data.data?.items || []) as BacktestTaskEvent[]
  } catch (error) {
    console.warn('加载回测任务事件失败', error)
  }
}

async function openBacktestTask(task: BacktestTask) {
  clearBacktestPoll()
  taskDrawerVisible.value = true
  try {
    const res = await getBacktestTask(task.task_id)
    const latestTask = res.data.data as BacktestTask
    applyBacktestTask(latestTask)
    await loadBacktestTaskEvents(latestTask.task_id)
    result.value = latestTask.result || null
    loading.value = isTaskActive(latestTask.status)
    if (loading.value) scheduleBacktestPoll(latestTask.task_id, 500)
  } catch (error: any) {
    applyBacktestTask(task)
    await loadBacktestTaskEvents(task.task_id)
    result.value = task.result || null
    loading.value = isTaskActive(task.status)
    ElMessage.error(error?.response?.data?.detail || '加载任务详情失败')
  }
}

async function cancelTask(task: BacktestTask | null) {
  if (!isTaskCancelable(task)) return
  try {
    await ElMessageBox.confirm(
      `确认取消回测任务 ${task.task_id}？`,
      '取消任务',
      { type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '继续等待' },
    )
  } catch {
    return
  }
  taskActionLoading.value = true
  try {
    const res = await cancelBacktestTask(task.task_id)
    const updatedTask = res.data.data as BacktestTask
    applyBacktestTask(updatedTask)
    await loadBacktestTaskEvents(updatedTask.task_id)
    await loadBacktestTasks()
    loading.value = isTaskActive(updatedTask.status)
    if (updatedTask.status === 'cancel_requested') {
      scheduleBacktestPoll(updatedTask.task_id, 500)
      ElMessage.warning('已发送取消请求，等待任务在进度边界停止')
    } else {
      clearBacktestPoll()
      ElMessage.warning('回测任务已取消')
    }
  } catch (error: any) {
    console.error('取消回测任务失败', error)
    ElMessage.error(error?.response?.data?.detail || '取消回测任务失败')
  } finally {
    taskActionLoading.value = false
  }
}

function isTaskActive(status: BacktestTaskStatus | ''): boolean {
  return status === 'queued' || status === 'running' || status === 'cancel_requested'
}

function isTaskCancelable(task: BacktestTask | null | undefined): task is BacktestTask {
  return task?.status === 'queued' || task?.status === 'running'
}

function formatTaskStatus(status: BacktestTaskStatus | ''): string {
  if (status === 'queued') return '排队中'
  if (status === 'running') return '运行中'
  if (status === 'cancel_requested') return '取消中'
  if (status === 'canceled') return '已取消'
  if (status === 'done') return '已完成'
  if (status === 'failed') return '失败'
  return ''
}

function taskAlertType(status: BacktestTaskStatus | '') {
  if (status === 'failed') return 'error'
  if (status === 'done') return 'success'
  if (status === 'cancel_requested' || status === 'canceled') return 'warning'
  return 'info'
}

function taskProgressStatus(status: BacktestTaskStatus | '') {
  if (status === 'failed') return 'exception'
  if (status === 'done') return 'success'
  if (status === 'cancel_requested' || status === 'canceled') return 'warning'
  return undefined
}

function taskTagType(status: BacktestTaskStatus | '') {
  if (status === 'failed') return 'danger'
  if (status === 'done') return 'success'
  if (status === 'cancel_requested' || status === 'canceled') return 'warning'
  if (status === 'running') return 'primary'
  return 'info'
}

function formatJson(value: unknown): string {
  if (value === undefined || value === null) return '{}'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function metricClass(value: unknown) {
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue) || numberValue === 0) return ''
  return numberValue > 0 ? 'positive' : 'negative'
}

function formatProfitActions(actions?: Array<Record<string, any>>): string {
  if (!actions?.length) return '-'
  return actions.map((action) => {
    if (action.action === 'enter_runner') {
      return `进入放飞 ${action.profit_pct ?? 0}%`
    }
    if (action.action === 'sell_partial') {
      return `放飞卖${action.sell_pct ?? 0}%，余${action.remaining_pct ?? 0}%`
    }
    if (action.action === 'hold_core') {
      return `保留底仓${action.keep_pct ?? action.remaining_pct ?? 0}%继续持有`
    }
    return String(action.action || '-')
  }).join(' / ')
}

onMounted(() => {
  const query = route.query || {}
  const source = String(query.source || '')
  const start = String(query.start || query.start_date || '')
  const end = String(query.end || query.end_date || '')
  if (source === 'manual' || source === 'strategy' || source === 'codes') {
    params.source = source as any
  }
  if (start && end) {
    dateRange.value = [start, end]
    syncDateRange()
  }
  const queryCodes = String(query.code || query.codes || '')
  if (queryCodes) {
    codeInput.value = queryCodes
    manualSelectionMode.value = 'single'
  } else if (String(query.batch || '') === '1') {
    manualSelectionMode.value = 'batch'
  }
  loadBacktestTasks()
})

watch(() => params.source, (next) => {
  candidateRows.value = []
  selectedCandidateKeys.value = new Set()
  if (next === 'manual') {
    manualSelectionMode.value = 'none'
    loadManualSelections()
  }
})

onBeforeUnmount(() => {
  clearBacktestPoll()
})
</script>

<template>
  <div class="backtest-view">
    <div class="backtest-toolbar">
      <div>
        <h2>回测工作台</h2>
        <p>策略候选可批量回测；人工选股默认单只或勾选后回测，避免误把整个池子一次性导入。</p>
      </div>
      <div class="toolbar-actions">
        <el-button :loading="candidateLoading" @click="handleLoadCandidates">{{ params.source === 'manual' ? '加载人工选股' : '加载策略候选' }}</el-button>
        <el-button type="primary" :loading="loading" :disabled="loading" @click="handleRunBacktest">{{ loading ? '回测运行中' : '开始回测' }}</el-button>
      </div>
    </div>

    <div class="backtest-layout">
      <section class="param-panel">
        <el-form label-position="top" size="small">
          <el-form-item label="信号日期范围">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              style="width: 100%"
              @change="syncDateRange"
            />
          </el-form-item>

          <el-form-item label="数据源">
            <el-segmented
              v-model="params.source"
              :options="[
                { label: '策略结果', value: 'strategy' },
                { label: '人工选股', value: 'manual' },
                { label: '输入个股', value: 'codes' },
              ]"
            />
          </el-form-item>

          <el-form-item label="个股输入">
            <el-input
              v-model="codeInput"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="000065, 001216，可用逗号/空格/换行分隔；策略源下用于过滤或指定回测代码"
            />
            <div class="hint">已识别 {{ parsedInputCodes.length }} 只</div>
          </el-form-item>

          <el-form-item v-if="params.source === 'strategy'" label="策略">
            <el-select v-model="params.strategy" style="width: 100%">
              <el-option label="全部" value="all" />
              <el-option label="B1形态" value="b1" />
              <el-option label="B2突破" value="b2" />
              <el-option label="碗底反弹" value="bowl" />
              <el-option label="砖型图" value="brick" />
            </el-select>
          </el-form-item>

          <el-form-item v-if="params.source === 'codes'" label="无策略信号时">
            <el-switch
              v-model="params.codes_fallback_to_start_date"
              active-text="按起始日直买"
              inactive-text="跳过该代码"
            />
          </el-form-item>

          <div class="param-grid">
            <el-form-item label="买入延后(交易日)">
              <el-input-number v-model="params.buy_offset_days" :min="0" :max="20" controls-position="right" />
            </el-form-item>
            <el-form-item label="最大持有天数">
              <el-input-number v-model="params.holding_days" :min="1" :max="120" controls-position="right" />
            </el-form-item>
            <el-form-item label="每日最大持仓">
              <el-input-number v-model="params.max_positions_per_day" :min="0" :max="500" controls-position="right" />
            </el-form-item>
          </div>

          <el-divider content-position="left">运行保护</el-divider>
          <div class="param-grid">
            <el-form-item label="总候选上限">
              <el-input-number v-model="params.max_candidates" :min="0" :max="100000" :step="100" controls-position="right" />
              <div class="hint">0 表示不限制；默认限制可避免长区间一次性跑太久。</div>
            </el-form-item>
            <el-form-item label="单股信号上限">
              <el-input-number v-model="params.max_signals_per_code" :min="0" :max="10000" :step="20" controls-position="right" />
              <div class="hint">解决单只股票多次策略命中导致重复回测拖慢。</div>
            </el-form-item>
            <el-form-item label="运行预算(秒)">
              <el-input-number v-model="params.max_runtime_seconds" :min="0" :max="600" :step="5" controls-position="right" />
              <div class="hint">超过预算会停止处理剩余候选，并在结果中提示。</div>
            </el-form-item>
          </div>

          <div class="param-grid two">
            <el-form-item label="买入价">
              <el-select v-model="params.buy_price"><el-option label="开盘价" value="open" /><el-option label="收盘价" value="close" /></el-select>
            </el-form-item>
            <el-form-item label="最终卖出价">
              <el-select v-model="params.sell_price"><el-option label="收盘价" value="close" /><el-option label="开盘价" value="open" /></el-select>
            </el-form-item>
          </div>

          <el-divider content-position="left">止盈窗口</el-divider>
          <el-form-item>
            <el-switch v-model="params.profit_run_enabled" active-text="达到阈值后放飞" />
          </el-form-item>
          <el-form-item :label="`出现 ${params.profit_trigger_pct}% 浮盈后进入放飞`">
            <el-slider v-model="params.profit_trigger_pct" :min="3" :max="30" :step="1" show-stops />
          </el-form-item>
          <el-form-item :label="`每继续上涨 ${params.profit_step_pct}% 分批卖出`">
            <el-slider v-model="params.profit_step_pct" :min="5" :max="30" :step="5" show-stops />
          </el-form-item>
          <el-form-item :label="`每档卖出 ${params.profit_sell_pct}% 仓位`">
            <el-slider v-model="params.profit_sell_pct" :min="10" :max="100" :step="5" show-stops />
          </el-form-item>
          <el-form-item :label="`放飞后至少保留 ${params.profit_keep_pct}% 底仓`">
            <el-slider v-model="params.profit_keep_pct" :min="0" :max="90" :step="5" show-stops />
          </el-form-item>
          <el-form-item>
            <el-switch v-model="params.hold_above_short_trend_after_trigger" active-text="放飞后不破白线不清仓" />
          </el-form-item>

          <el-divider content-position="left">止损窗口</el-divider>
          <el-form-item>
            <el-switch v-model="params.enable_no_gain_exit" active-text="买入后N天不涨清仓" />
            <el-input-number v-model="params.no_gain_days" :min="1" :max="10" size="small" class="inline-number" />
          </el-form-item>
          <el-form-item>
            <el-switch v-model="params.exit_on_bull_bear_break" active-text="跌破黄线清仓" />
          </el-form-item>
          <el-form-item>
            <el-switch v-model="params.exit_on_short_trend_break" active-text="连续跌破白线清仓" />
            <el-input-number v-model="params.short_trend_break_days" :min="1" :max="10" size="small" class="inline-number" />
          </el-form-item>
          <el-form-item :label="`跌破白线 ${params.short_trend_drawdown_pct}% 清仓`">
            <el-switch v-model="params.exit_on_short_trend_drawdown" />
            <el-slider v-model="params.short_trend_drawdown_pct" :min="1" :max="15" :step="1" show-stops class="inline-slider" />
          </el-form-item>

          <el-collapse>
            <el-collapse-item title="成本与固定止损" name="advanced">
              <div class="param-grid two">
                <el-form-item label="手续费率"><el-input-number v-model="params.fee_rate" :min="0" :max="0.02" :step="0.0001" :precision="4" controls-position="right" /></el-form-item>
                <el-form-item label="滑点率"><el-input-number v-model="params.slippage_rate" :min="0" :max="0.02" :step="0.0001" :precision="4" controls-position="right" /></el-form-item>
                <el-form-item label="固定止损%"><el-input-number v-model="params.stop_loss_pct" :min="0" :max="100" :step="1" controls-position="right" /></el-form-item>
                <el-form-item label="固定止盈%(关闭放飞时生效)"><el-input-number v-model="params.take_profit_pct" :min="0" :max="200" :step="1" controls-position="right" /></el-form-item>
                <el-form-item label="下单意图股数"><el-input-number v-model="params.intent_quantity" :min="0" :max="100000000" :step="100" controls-position="right" /></el-form-item>
                <el-form-item label="整数手股数"><el-input-number v-model="params.lot_size" :min="1" :max="10000" :step="100" controls-position="right" /></el-form-item>
              </div>
              <el-form-item>
                <el-switch v-model="params.allow_st_buy" active-text="允许 ST/退市风险股买入回测" />
              </el-form-item>
            </el-collapse-item>
          </el-collapse>
        </el-form>
      </section>

      <main class="result-panel">
        <section class="candidate-panel">
          <div class="section-head">
            <strong>策略候选列表</strong>
            <div>
              <span class="hint">{{ selectedCandidateKeys.size }}/{{ candidateRows.length }} 已选</span>
              <el-button size="small" @click="toggleAllCandidates">{{ isAllCandidatesSelected ? '取消全选' : '全选候选' }}</el-button>
              <el-button size="small" @click="clearCandidates">清空候选</el-button>
            </div>
          </div>
          <el-table :data="candidateRows" size="small" height="220" border empty-text="点击加载策略候选，或直接用输入个股回测">
            <el-table-column label="选" width="52" align="center">
              <template #default="{ row }">
                <el-checkbox :model-value="selectedCandidateKeys.has(candidateKey(row))" @change="(checked: any) => toggleCandidate(row, Boolean(checked))" />
              </template>
            </el-table-column>
            <el-table-column prop="trade_date" label="策略日期" width="100" />
            <el-table-column prop="signal_date" label="信号日" width="100" />
            <el-table-column prop="code" label="代码" width="90" />
            <el-table-column prop="name" label="名称" min-width="100" />
            <el-table-column prop="strategy_name" label="策略" min-width="130" />
            <el-table-column label="相似度" width="80"><template #default="{ row }">{{ formatSimilarityPercent(row.similarity_score) }}</template></el-table-column>
          </el-table>
        </section>

        <section class="task-panel">
          <div class="section-head">
            <strong>回测任务</strong>
            <div class="task-head-actions">
              <span class="hint">{{ activeTaskId ? `当前 ${activeTaskId}` : '暂无运行中任务' }}</span>
              <el-button v-if="activeTaskId" size="small" link type="primary" @click="taskDrawerVisible = true">详情</el-button>
              <el-button
                v-if="isTaskCancelable(currentTask)"
                size="small"
                link
                type="danger"
                :loading="taskActionLoading"
                @click="cancelTask(currentTask)"
              >
                取消任务
              </el-button>
            </div>
          </div>
          <el-alert
            v-if="activeTaskId"
            :title="taskMessage || `任务 ${activeTaskId} ${formatTaskStatus(taskStatus)}`"
            :type="taskAlertType(taskStatus)"
            show-icon
            :closable="false"
            class="task-alert"
          />
          <div v-if="activeTaskId" class="task-progress">
            <el-progress :percentage="taskProgress" :status="taskProgressStatus(taskStatus)" />
            <div class="runtime-meta">
              已处理 {{ currentTask?.processed_count || 0 }}/{{ currentTask?.total_count || 0 }}，
              当前代码 {{ currentTask?.current_code || '-' }}，
              状态 {{ formatTaskStatus(taskStatus) }}
            </div>
          </div>
          <el-table :data="taskHistory" size="small" height="150" border empty-text="暂无回测任务历史">
            <el-table-column prop="created_at" label="提交时间" width="150" />
            <el-table-column prop="status" label="状态" width="78">
              <template #default="{ row }">{{ formatTaskStatus(row.status) }}</template>
            </el-table-column>
            <el-table-column prop="progress_pct" label="进度" width="80">
              <template #default="{ row }">{{ row.progress_pct || 0 }}%</template>
            </el-table-column>
            <el-table-column prop="message" label="说明" min-width="150" show-overflow-tooltip />
            <el-table-column label="操作" width="126" align="center">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="openBacktestTask(row)">详情</el-button>
                <el-button
                  v-if="isTaskCancelable(row)"
                  size="small"
                  type="danger"
                  link
                  :loading="taskActionLoading"
                  @click.stop="cancelTask(row)"
                >
                  取消
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <div v-if="summary" class="metric-grid">
          <div v-for="metric in metricItems" :key="metric.label" class="metric-cell">
            <span>{{ metric.label }}</span>
            <strong :class="metricClass(metric.value)">{{ metric.value }}{{ metric.suffix }}</strong>
          </div>
        </div>

        <el-empty v-if="!summary && !loading" description="加载候选或输入个股后点击开始回测" />
        <el-empty v-else-if="!summary && loading" description="回测任务运行中，结果完成后自动刷新" />

        <div v-if="summary" class="result-section">
          <el-alert
            v-for="message in runtimeWarnings"
            :key="message"
            :title="message"
            type="warning"
            show-icon
            :closable="false"
            class="runtime-alert"
          />
          <div class="runtime-meta">
            原始候选 {{ summary.raw_candidate_count ?? summary.candidate_count }} 条，
            实际执行 {{ summary.candidate_count }} 条，
            已处理 {{ summary.runtime_processed_count ?? summary.candidate_count }} 条，
            用时 {{ summary.runtime_elapsed_seconds ?? 0 }} 秒
          </div>
          <div class="section-title">交易明细</div>
          <div v-if="taskEvents.length" class="runtime-meta">
            最近事件：{{ taskEvents.slice(-3).map(item => item.message || item.event_type).join(' / ') }}
          </div>
          <el-table :data="trades" size="small" height="360" border>
            <el-table-column prop="buy_date" label="买入日" width="100" />
            <el-table-column prop="sell_date" label="卖出日" width="100" />
            <el-table-column prop="code" label="代码" width="90" />
            <el-table-column prop="name" label="名称" min-width="100" />
            <el-table-column prop="strategy_name" label="策略" min-width="110" />
            <el-table-column prop="buy_price" label="买入" width="80" />
            <el-table-column prop="sell_price" label="末次卖出" width="90" />
            <el-table-column prop="return_pct" label="收益%" width="90"><template #default="{ row }"><span :class="metricClass(row.return_pct)">{{ row.return_pct }}%</span></template></el-table-column>
            <el-table-column prop="hold_days" label="持有" width="70" />
            <el-table-column prop="exit_reason" label="末次退出" width="150" />
            <el-table-column label="分批" width="70"><template #default="{ row }">{{ row.exits?.length || 0 }}</template></el-table-column>
            <el-table-column label="放飞动作" min-width="220" show-overflow-tooltip><template #default="{ row }">{{ formatProfitActions(row.profit_actions) }}</template></el-table-column>
          </el-table>
        </div>

        <div v-if="equityCurve.length" class="result-section">
          <div class="section-title">资金曲线数据</div>
          <el-table :data="equityCurve" size="small" height="180" border>
            <el-table-column prop="date" label="日期" width="120" />
            <el-table-column prop="daily_return_pct" label="日收益%" width="120" />
            <el-table-column prop="equity" label="权益倍数" width="120" />
            <el-table-column prop="drawdown_pct" label="回撤%" width="120" />
          </el-table>
        </div>
      </main>
    </div>

    <el-drawer
      v-model="taskDrawerVisible"
      title="回测任务详情"
      size="560px"
      destroy-on-close
    >
      <div v-if="currentTask" class="task-drawer">
        <div class="drawer-task-head">
          <el-tag :type="taskTagType(currentTask.status)">{{ formatTaskStatus(currentTask.status) }}</el-tag>
          <span class="drawer-task-id">{{ currentTask.task_id }}</span>
        </div>

        <el-progress :percentage="taskProgress" :status="taskProgressStatus(currentTask.status)" />
        <div class="detail-grid">
          <div>
            <span>提交时间</span>
            <strong>{{ currentTask.created_at || '-' }}</strong>
          </div>
          <div>
            <span>开始时间</span>
            <strong>{{ currentTask.started_at || '-' }}</strong>
          </div>
          <div>
            <span>结束时间</span>
            <strong>{{ currentTask.finished_at || '-' }}</strong>
          </div>
          <div>
            <span>当前代码</span>
            <strong>{{ currentTask.current_code || '-' }}</strong>
          </div>
        </div>

        <el-alert
          v-if="currentTask.error"
          :title="currentTask.error"
          type="error"
          show-icon
          :closable="false"
          class="runtime-alert"
        />

        <div class="drawer-actions">
          <el-button
            v-if="isTaskCancelable(currentTask)"
            type="danger"
            :loading="taskActionLoading"
            @click="cancelTask(currentTask)"
          >
            取消任务
          </el-button>
        </div>

        <el-divider content-position="left">结果摘要</el-divider>
        <div v-if="currentTask.result?.summary" class="drawer-summary">
          <div v-for="item in drawerSummaryItems" :key="item.label">
            <span>{{ item.label }}</span>
            <strong :class="metricClass(item.value)">{{ item.value }}{{ item.suffix }}</strong>
          </div>
        </div>
        <el-empty v-else description="任务尚未产生结果" />

        <el-divider content-position="left">任务参数</el-divider>
        <pre class="json-block">{{ formatJson(currentTask.params) }}</pre>

        <el-divider content-position="left">事件流</el-divider>
        <el-table :data="taskEvents" size="small" height="240" border empty-text="暂无事件">
          <el-table-column prop="created_at" label="时间" width="145" />
          <el-table-column prop="event_type" label="类型" width="120" />
          <el-table-column prop="progress_pct" label="进度" width="70">
            <template #default="{ row }">{{ row.progress_pct ?? '-' }}</template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip />
        </el-table>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.backtest-view { height: 100%; display: flex; flex-direction: column; background: #f5f7fa; overflow: hidden; }
.backtest-toolbar { flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 18px; background: #fff; border-bottom: 1px solid #e4e7ed; }
.backtest-toolbar h2 { margin: 0; font-size: 18px; color: #303133; }
.backtest-toolbar p { margin: 4px 0 0; font-size: 12px; color: #909399; }
.toolbar-actions { display: flex; gap: 8px; }
.backtest-layout { flex: 1; min-height: 0; display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 12px; padding: 12px; overflow: hidden; }
.param-panel, .result-panel { min-height: 0; overflow: auto; background: #fff; border: 1px solid #e4e7ed; border-radius: 6px; }
.param-panel { padding: 14px; }
.result-panel { padding: 14px; }
.param-grid { display: grid; grid-template-columns: 1fr; gap: 0 10px; }
.param-grid.two { grid-template-columns: 1fr 1fr; }
:deep(.param-grid .el-input-number) { width: 100%; }
.hint { font-size: 12px; color: #909399; margin-top: 4px; }
.inline-number { width: 92px; margin-left: 12px; }
.inline-slider { width: 210px; margin-left: 12px; }
.candidate-panel, .task-panel { margin-bottom: 12px; }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.task-head-actions { display: flex; align-items: center; gap: 8px; }
.metric-grid { display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); gap: 8px; margin-bottom: 14px; }
.metric-cell { padding: 10px 12px; border: 1px solid #ebeef5; border-radius: 6px; background: #fafafa; }
.metric-cell span { display: block; color: #909399; font-size: 12px; margin-bottom: 6px; }
.metric-cell strong { color: #303133; font-size: 18px; }
.positive { color: #f56c6c !important; }
.negative { color: #67c23a !important; }
.result-section { margin-top: 12px; }
.section-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.runtime-alert { margin-bottom: 8px; }
.runtime-meta { margin-bottom: 10px; font-size: 12px; color: #606266; }
.task-alert { margin-bottom: 12px; }
.task-progress { margin-bottom: 10px; }
.task-drawer { display: flex; flex-direction: column; gap: 12px; }
.drawer-task-head { display: flex; align-items: center; gap: 10px; min-width: 0; }
.drawer-task-id { color: #606266; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; overflow-wrap: anywhere; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.detail-grid div, .drawer-summary div { padding: 8px 10px; border: 1px solid #ebeef5; border-radius: 6px; background: #fafafa; }
.detail-grid span, .drawer-summary span { display: block; color: #909399; font-size: 12px; margin-bottom: 4px; }
.detail-grid strong, .drawer-summary strong { color: #303133; font-size: 13px; overflow-wrap: anywhere; }
.drawer-actions { display: flex; justify-content: flex-end; }
.drawer-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.json-block { max-height: 220px; overflow: auto; margin: 0; padding: 10px; border: 1px solid #ebeef5; border-radius: 6px; background: #f8fafc; color: #606266; font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
@media (max-width: 1180px) { .backtest-layout { grid-template-columns: 1fr; overflow: auto; } .metric-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); } }
</style>
