<script setup lang="ts">
// 单股跟踪运营面板：列表 + 规则批量评估 + 告警 + LLM 建议 + OrderIntent 确认/否决
// 后端入口：tracking.py / tracking_alert.py / tracking_evaluation.py / tracking_llm.py / tracking_intent.py
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listTrackingItems,
  listTrackingAlerts,
  evaluateTrackingRules,
  evaluateTrackingItem,
  getTrackingLLMAdvice,
  confirmTrackingIntent,
  rejectTrackingIntent,
  type TrackingItem,
  type TrackingAlertItem,
} from '@/api'

// —— 列表状态 ——
const items = ref<TrackingItem[]>([])
const loading = ref(false)
const statusFilter = ref<string>('all')
const codeFilter = ref<string>('')
const batchLoading = ref(false)

// —— 展开行（每个跟踪项独立缓存告警 / 建议） ——
interface RowState {
  alerts: TrackingAlertItem[]
  advice: Record<string, any> | null
  alertsLoading: boolean
  adviceLoading: boolean
  actionLoading: boolean
}
const rowStateMap = ref<Record<string, RowState>>({})

function ensureRowState(id: string): RowState {
  if (!rowStateMap.value[id]) {
    rowStateMap.value[id] = {
      alerts: [],
      advice: null,
      alertsLoading: false,
      adviceLoading: false,
      actionLoading: false,
    }
  }
  return rowStateMap.value[id]
}

// —— 拉取列表 ——
async function refreshItems() {
  loading.value = true
  try {
    const params: { status?: string; code?: string; limit?: number } = { limit: 200 }
    if (statusFilter.value && statusFilter.value !== 'all') params.status = statusFilter.value
    const trimmed = codeFilter.value.trim()
    if (trimmed) params.code = trimmed
    const resp = await listTrackingItems(params)
    items.value = resp.data?.data?.items ?? []
  } catch (e: any) {
    ElMessage.error(`加载跟踪列表失败：${e?.message || e}`)
  } finally {
    loading.value = false
  }
}

// —— 批量规则评估（P5） ——
async function runBatchEvaluate() {
  batchLoading.value = true
  try {
    const resp = await evaluateTrackingRules({})
    const summary = resp.data?.data ?? {}
    ElMessage.success(
      `评估完成：已评估 ${summary.evaluated ?? 0} 条；新增告警 ${summary.alerts_created ?? 0}（去重 ${summary.alerts_skipped_dup ?? 0}）`,
    )
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`批量评估失败：${e?.message || e}`)
  } finally {
    batchLoading.value = false
  }
}

// —— 单条评估 ——
async function evaluateOne(item: TrackingItem) {
  try {
    await evaluateTrackingItem(item.tracking_id)
    ElMessage.success(`已评估 ${item.code}`)
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`评估失败：${e?.message || e}`)
  }
}

// —— 展开时拉取告警 ——
async function handleExpand(row: TrackingItem, expandedRows: TrackingItem[]) {
  const isOpen = expandedRows.some((r) => r.tracking_id === row.tracking_id)
  if (!isOpen) return
  const state = ensureRowState(row.tracking_id)
  if (state.alerts.length > 0 || state.alertsLoading) return
  state.alertsLoading = true
  try {
    const resp = await listTrackingAlerts({ tracking_id: row.tracking_id, limit: 50 })
    state.alerts = resp.data?.data?.items ?? []
  } catch (e: any) {
    ElMessage.error(`加载告警失败：${e?.message || e}`)
  } finally {
    state.alertsLoading = false
  }
}

// —— LLM 建议 ——
async function fetchAdvice(row: TrackingItem) {
  const state = ensureRowState(row.tracking_id)
  state.adviceLoading = true
  try {
    const resp = await getTrackingLLMAdvice(row.tracking_id)
    state.advice = resp.data?.data ?? null
    ElMessage.success('已获取操盘建议')
  } catch (e: any) {
    if (e?.response?.status === 404) {
      ElMessage.error('跟踪记录不存在')
    } else {
      ElMessage.error(`获取建议失败：${e?.message || e}`)
    }
  } finally {
    state.adviceLoading = false
  }
}

// —— 确认 OrderIntent ——
async function confirmIntent(row: TrackingItem) {
  const state = ensureRowState(row.tracking_id)
  // 优先使用建议里的 intent，其次使用 latest_intent
  const intent = state.advice?.intent ?? row.latest_intent ?? null
  state.actionLoading = true
  try {
    await confirmTrackingIntent(row.tracking_id, intent)
    ElMessage.success(`已确认操盘指令：${row.code}`)
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`确认失败：${e?.message || e}`)
  } finally {
    state.actionLoading = false
  }
}

// —— 否决 OrderIntent ——
async function rejectIntent(row: TrackingItem) {
  const state = ensureRowState(row.tracking_id)
  let reason = ''
  try {
    const result = await ElMessageBox.prompt('请输入否决原因（操盘手判断）', '否决建议', {
      confirmButtonText: '提交',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：假信号 / 大盘风险 / 已手动平仓',
    })
    reason = result.value || ''
  } catch {
    return
  }
  state.actionLoading = true
  try {
    await rejectTrackingIntent(row.tracking_id, reason)
    ElMessage.success(`已否决，next_action 已重置为 HOLD`)
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`否决失败：${e?.message || e}`)
  } finally {
    state.actionLoading = false
  }
}

// —— 状态展示辅助 ——
const STATUS_TAG: Record<string, string> = {
  watch_buy: 'warning',
  holding: 'success',
  partial_sold: 'info',
  closed: '',
}

function statusType(s?: string) {
  if (!s) return ''
  return STATUS_TAG[s] ?? ''
}

function returnPctText(v?: number | null) {
  if (v === null || v === undefined) return '-'
  return `${v >= 0 ? '+' : ''}${(v as number).toFixed(2)}%`
}

function priorityTagType(p?: number) {
  if (p === undefined || p === null) return 'info'
  if (p < 30) return 'danger'
  if (p < 60) return 'warning'
  return 'info'
}

const hasItems = computed(() => items.value.length > 0)

onMounted(refreshItems)
</script>

<template>
  <div class="tracking-view">
    <div class="toolbar">
      <el-select v-model="statusFilter" style="width: 160px" placeholder="状态">
        <el-option label="全部" value="all" />
        <el-option label="待买入 watch_buy" value="watch_buy" />
        <el-option label="持仓 holding" value="holding" />
        <el-option label="部分卖出 partial_sold" value="partial_sold" />
        <el-option label="已平仓 closed" value="closed" />
      </el-select>
      <el-input
        v-model="codeFilter"
        placeholder="按代码过滤（6 位）"
        style="width: 180px"
        clearable
      />
      <el-button type="primary" :loading="loading" @click="refreshItems">刷新</el-button>
      <el-button type="success" :loading="batchLoading" @click="runBatchEvaluate">
        批量规则评估
      </el-button>
      <span class="hint">共 {{ items.length }} 条</span>
    </div>

    <el-empty v-if="!loading && !hasItems" description="暂无跟踪记录" />

    <el-table
      v-else
      :data="items"
      v-loading="loading"
      style="width: 100%"
      row-key="tracking_id"
      @expand-change="handleExpand"
    >
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand-panel">
            <!-- 告警列表 -->
            <div class="panel-block">
              <h4>近期告警</h4>
              <el-table
                :data="rowStateMap[row.tracking_id]?.alerts ?? []"
                v-loading="rowStateMap[row.tracking_id]?.alertsLoading"
                size="small"
                empty-text="暂无告警"
              >
                <el-table-column prop="eval_date" label="评估日" width="110" />
                <el-table-column label="优先级" width="90">
                  <template #default="{ row: a }">
                    <el-tag :type="priorityTagType(a.priority)" size="small">
                      {{ a.priority ?? '-' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="rule_id" label="规则" width="160" show-overflow-tooltip />
                <el-table-column prop="ui_status" label="状态" width="100" />
                <el-table-column prop="message" label="说明" show-overflow-tooltip />
              </el-table>
            </div>

            <!-- LLM 建议 -->
            <div class="panel-block">
              <h4>LLM 操盘建议（mock，确定性）</h4>
              <el-button
                size="small"
                type="primary"
                :loading="rowStateMap[row.tracking_id]?.adviceLoading"
                @click="fetchAdvice(row)"
              >
                获取 / 刷新建议
              </el-button>
              <div v-if="rowStateMap[row.tracking_id]?.advice" class="advice">
                <pre>{{ JSON.stringify(rowStateMap[row.tracking_id]!.advice, null, 2) }}</pre>
              </div>
            </div>

            <!-- 操盘确认 / 否决 -->
            <div class="panel-block">
              <h4>操盘手动作</h4>
              <el-button
                type="success"
                size="small"
                :loading="rowStateMap[row.tracking_id]?.actionLoading"
                @click="confirmIntent(row)"
              >
                确认 OrderIntent
              </el-button>
              <el-button
                type="danger"
                size="small"
                :loading="rowStateMap[row.tracking_id]?.actionLoading"
                @click="rejectIntent(row)"
              >
                否决并重置 HOLD
              </el-button>
              <el-button size="small" @click="evaluateOne(row)">单条评估</el-button>
              <div v-if="row.latest_intent" class="advice">
                <span class="muted">latest_intent：</span>
                <pre>{{ JSON.stringify(row.latest_intent, null, 2) }}</pre>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="code" label="代码" width="100" />
      <el-table-column prop="name" label="名称" width="120" />
      <el-table-column prop="strategy_name" label="策略" width="140" show-overflow-tooltip />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status) as any" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="signal_date" label="信号日" width="110" />
      <el-table-column prop="last_eval_date" label="最近评估" width="110" />
      <el-table-column label="收益" width="100">
        <template #default="{ row }">
          <span :class="(row.latest_return_pct ?? 0) >= 0 ? 'pos' : 'neg'">
            {{ returnPctText(row.latest_return_pct) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="next_action" label="下一步" width="120" />
    </el-table>
  </div>
</template>

<style scoped>
.tracking-view {
  padding: 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.toolbar .hint {
  color: var(--text-secondary);
  font-size: 12px;
}
.expand-panel {
  padding: 12px 24px;
  background: var(--bg-tertiary);
}
.panel-block {
  margin-bottom: 14px;
}
.panel-block h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
  color: var(--text-primary);
}
.advice {
  margin-top: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 8px;
  max-height: 260px;
  overflow: auto;
}
.advice pre {
  margin: 0;
  font-size: 12px;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-all;
}
.muted {
  color: var(--text-secondary);
  font-size: 12px;
}
.pos {
  color: #f56c6c;
}
.neg {
  color: #67c23a;
}
</style>
