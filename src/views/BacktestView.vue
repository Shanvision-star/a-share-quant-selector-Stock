<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getManualSelections,
  getStrategyResultsHistory,
  runBacktest,
  type BacktestRequestPayload,
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
  loading.value = true
  try {
    const res = await runBacktest(payload)
    result.value = res.data.data
    ElMessage.success(`回测完成：${result.value?.summary?.trade_count || 0} 笔交易`)
  } catch (error: any) {
    console.error('回测失败', error)
    ElMessage.error(error?.response?.data?.detail || '回测失败，请确认后端已重启到最新代码')
  } finally {
    loading.value = false
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
})

watch(() => params.source, (next) => {
  candidateRows.value = []
  selectedCandidateKeys.value = new Set()
  if (next === 'manual') {
    manualSelectionMode.value = 'none'
    loadManualSelections()
  }
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
        <el-button type="primary" :loading="loading" @click="handleRunBacktest">开始回测</el-button>
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

      <main class="result-panel" v-loading="loading">
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

        <div v-if="summary" class="metric-grid">
          <div v-for="metric in metricItems" :key="metric.label" class="metric-cell">
            <span>{{ metric.label }}</span>
            <strong :class="metricClass(metric.value)">{{ metric.value }}{{ metric.suffix }}</strong>
          </div>
        </div>

        <el-empty v-else description="加载候选或输入个股后点击开始回测" />

        <div v-if="summary" class="result-section">
          <div class="section-title">交易明细</div>
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
.candidate-panel { margin-bottom: 12px; }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.metric-grid { display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); gap: 8px; margin-bottom: 14px; }
.metric-cell { padding: 10px 12px; border: 1px solid #ebeef5; border-radius: 6px; background: #fafafa; }
.metric-cell span { display: block; color: #909399; font-size: 12px; margin-bottom: 6px; }
.metric-cell strong { color: #303133; font-size: 18px; }
.positive { color: #f56c6c !important; }
.negative { color: #67c23a !important; }
.result-section { margin-top: 12px; }
.section-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
@media (max-width: 1180px) { .backtest-layout { grid-template-columns: 1fr; overflow: auto; } .metric-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); } }
</style>
