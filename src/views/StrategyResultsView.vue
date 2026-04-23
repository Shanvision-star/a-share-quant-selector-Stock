<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getStrategyCacheStatus,
  getStrategyResultsHistory,
  getStrategyRuns,
  getStrategyRunEvents,
} from '@/api'
import { useStrategyListStore } from '@/stores/strategyList'
import { useUpdateJobStore } from '@/stores/updateJob'
import { useQueryStateStore } from '@/stores/queryState'
import TxtLibraryPanel from '@/components/TxtLibraryPanel.vue'
import { createRequestManager, isAbortError } from '@/api/requestManager'

const route = useRoute()
const router = useRouter()
const strategyListStore = useStrategyListStore()
const updateJobStore = useUpdateJobStore()
const queryStateStore = useQueryStateStore()
const requestManager = createRequestManager()

// ─── 缓存状态 ───
const cacheStatus = ref<any>(null)
const cacheLoading = ref(false)

// ─── 正式结果表 ───
const results = ref<any[]>([])
const resultsTotal = ref(0)
const resultsUniqueTotal = ref(0)
const resultsPage = computed({
  get: () => queryStateStore.results.page,
  set: (value: number) => queryStateStore.setResultsPage(value),
})
const resultsPageSize = computed(() => queryStateStore.results.perPage)
const resultsLoading = ref(false)
const sortBy = computed(() => queryStateStore.results.sortBy)
const sortOrder = computed(() => queryStateStore.results.sortOrder)

// ─── 筛选条件 ───
const activeStrategy = computed({
  get: () => queryStateStore.results.strategy,
  set: (value: string) => queryStateStore.setResultsStrategy(value),
})
const filterKeyword = computed({
  get: () => queryStateStore.results.keyword,
  set: (value: string) => queryStateStore.setResultsKeyword(value),
})
const filterDateRange = computed({
  get: () => queryStateStore.results.dateRange,
  set: (value: [string, string] | null) => queryStateStore.setResultsDateRange(value),
})
const filterJRange = computed({
  get: () => queryStateStore.results.jRange,
  set: (value: [number, number] | null) => queryStateStore.setResultsJRange(value),
})
const filterSimilarityRange = computed({
  get: () => queryStateStore.results.similarityRange,
  set: (value: [number, number] | null) => queryStateStore.setResultsSimilarityRange(value),
})

// ─── 实时命中 ───
const liveSignals = ref<any[]>([])
const rebuildRunning = ref(false)
const rebuildProgress = ref(0)
const rebuildMessage = ref('')

// ─── 运行记录 ───
const runs = ref<any[]>([])
const runsTotal = ref(0)
const runsPage = computed({
  get: () => queryStateStore.results.runsPage,
  set: (value: number) => queryStateStore.setResultsRunsPage(value),
})
const runsLoading = ref(false)

// ─── 作业详情抽屉 ───
const drawerVisible = ref(false)
const drawerRunId = ref('')
const drawerEvents = ref<any[]>([])
const drawerLoading = ref(false)
const txtSectionRef = ref<HTMLElement | null>(null)

let rebuildController: AbortController | null = null

const tabs = [
  { key: 'all', label: '全部' },
  { key: 'b1', label: 'B1形态' },
  { key: 'b2', label: 'B2突破' },
  { key: 'bowl', label: '碗底反弹' },
]

const strategyLabel = computed(() => tabs.find(t => t.key === activeStrategy.value)?.label || activeStrategy.value)
const requestedTradeDate = computed(() => {
  const date = route.query.date
  return typeof date === 'string' ? date : ''
})

onMounted(() => {
  // 正常加载已有缓存数据（作业进行中时读取的是上次结果，完成后会自动刷新）
  loadCacheStatus()
  loadResults()
  loadRuns()
})

// 作业完成后自动刷新
watch(
  () => updateJobStore.jobCompleted,
  (done) => {
    if (done) {
      loadCacheStatus()
      loadResults()
      loadRuns()
    }
  },
)

watch(
  () => route.query.focus,
  (focus) => {
    if (focus === 'txt') {
      nextTick(() => {
        txtSectionRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      })
    }
  },
  { immediate: true },
)

watch(
  () => route.query.date,
  () => {
    queryStateStore.setResultsPage(1)
    queryStateStore.setResultsRunsPage(1)
    loadCacheStatus()
    loadResults()
    loadRuns()
  },
)

onBeforeUnmount(() => {
  rebuildController?.abort()
  requestManager.cancelAll()
})

// ─── 加载缓存状态 ───
async function loadCacheStatus() {
  const controller = requestManager.start('results:cache-status')
  cacheLoading.value = true
  try {
    const params: { strategy: string; date?: string } = { strategy: activeStrategy.value }
    if (requestedTradeDate.value) {
      params.date = requestedTradeDate.value
    }
    const res = await getStrategyCacheStatus(params, { signal: controller.signal })
    if (!requestManager.isCurrent('results:cache-status', controller)) return
    cacheStatus.value = res.data.data || null
    const rebuild = cacheStatus.value?.rebuild
    if (rebuild?.is_running) {
      rebuildRunning.value = true
      rebuildProgress.value = typeof rebuild.progress === 'number' ? rebuild.progress : rebuildProgress.value
      rebuildMessage.value = rebuild.message || '策略缓存正在重建...'
    } else if (!rebuildController) {
      rebuildRunning.value = false
      rebuildProgress.value = 0
      rebuildMessage.value = ''
    }
  } catch (e) {
    if (!isAbortError(e)) {
      console.error('加载缓存状态失败', e)
    }
  } finally {
    if (requestManager.isCurrent('results:cache-status', controller)) {
      cacheLoading.value = false
    }
    requestManager.clear('results:cache-status', controller)
  }
}

// ─── 加载正式结果 ───
async function loadResults() {
  const controller = requestManager.start('results:list')
  resultsLoading.value = true
  try {
    const params: any = {
      strategy: activeStrategy.value,
      page: resultsPage.value,
      per_page: resultsPageSize.value,
    }
    if (filterKeyword.value) params.keyword = filterKeyword.value
    const effectiveDateRange = filterDateRange.value || (requestedTradeDate.value
      ? [requestedTradeDate.value, requestedTradeDate.value]
      : null)
    if (effectiveDateRange) {
      params.start_date = effectiveDateRange[0]
      params.end_date = effectiveDateRange[1]
    }
    if (filterJRange.value) {
      params.min_j_value = filterJRange.value[0]
      params.max_j_value = filterJRange.value[1]
    }
    if (filterSimilarityRange.value) {
      params.min_similarity = filterSimilarityRange.value[0]
      params.max_similarity = filterSimilarityRange.value[1]
    }
    params.sort_by = sortBy.value
    params.sort_order = sortOrder.value === 'ascending' ? 'asc' : 'desc'

    const res = await getStrategyResultsHistory(params, { signal: controller.signal })
    if (!requestManager.isCurrent('results:list', controller)) return
    const data = res.data.data || {}
    results.value = data.items || []
    resultsTotal.value = data.total || 0
    resultsUniqueTotal.value = data.unique_code_total || 0
  } catch (e) {
    if (!isAbortError(e)) {
      console.error('加载策略结果失败', e)
    }
  } finally {
    if (requestManager.isCurrent('results:list', controller)) {
      resultsLoading.value = false
    }
    requestManager.clear('results:list', controller)
  }
}

// ─── 加载运行记录 ───
async function loadRuns() {
  const controller = requestManager.start('results:runs')
  runsLoading.value = true
  try {
    const params: any = {
      strategy: activeStrategy.value,
      page: runsPage.value,
      per_page: 10,
    }
    if (requestedTradeDate.value) {
      params.date = requestedTradeDate.value
    }
    const res = await getStrategyRuns(params, { signal: controller.signal })
    if (!requestManager.isCurrent('results:runs', controller)) return
    const data = res.data.data || {}
    runs.value = data.items || []
    runsTotal.value = data.total || 0
  } catch (e) {
    if (!isAbortError(e)) {
      console.error('加载运行记录失败', e)
    }
  } finally {
    if (requestManager.isCurrent('results:runs', controller)) {
      runsLoading.value = false
    }
    requestManager.clear('results:runs', controller)
  }
}

// ─── 查看运行详情 ───
async function openRunDetail(runId: string) {
  const controller = requestManager.start('results:run-events')
  drawerRunId.value = runId
  drawerVisible.value = true
  drawerLoading.value = true
  try {
    const res = await getStrategyRunEvents(runId, 500, { signal: controller.signal })
    if (!requestManager.isCurrent('results:run-events', controller)) return
    drawerEvents.value = res.data.data || []
  } catch (e) {
    if (!isAbortError(e)) {
      console.error(e)
    }
  } finally {
    if (requestManager.isCurrent('results:run-events', controller)) {
      drawerLoading.value = false
    }
    requestManager.clear('results:run-events', controller)
  }
}

// ─── 重建策略缓存 ───
async function startRebuild() {
  if (rebuildRunning.value) return

  try {
    await ElMessageBox.confirm(
      `确认重建 "${strategyLabel.value}" 策略缓存？`,
      '重建确认',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    console.error('[StrategyResultsView] 重建确认失败', error)
    ElMessage.error('重建确认失败，请稍后重试')
    return
  }

  rebuildRunning.value = true
  rebuildProgress.value = 0
  rebuildMessage.value = '准备重建...'
  liveSignals.value = []
  rebuildController = new AbortController()

  try {
    const params = new URLSearchParams({ strategy: activeStrategy.value })
    if (requestedTradeDate.value) {
      params.set('date', requestedTradeDate.value)
    }
    const response = await fetch(`/api/strategy/cache/rebuild?${params}`, {
      method: 'POST',
      signal: rebuildController.signal,
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    if (!response.body) throw new Error('浏览器不支持流式读取')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''

      for (const chunk of chunks) {
        const lines = chunk.split('\n')
        const eventName = lines.find(l => l.startsWith('event:'))?.slice(6).trim() || 'message'
        const dataText = lines.filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()).join('\n')
        if (!dataText) continue
        try {
          const data = JSON.parse(dataText)
          handleEvent(eventName, data)
        } catch (error) {
          console.warn('[StrategyResultsView] 重建流事件解析失败', { error, dataText, eventName })
        }
      }
    }
  } catch (e: any) {
    if (e?.name !== 'AbortError') {
      ElMessage.error('策略重建失败: ' + (e?.message || '未知错误'))
    }
  } finally {
    rebuildRunning.value = false
    rebuildController = null
    loadCacheStatus()
    loadResults()
    loadRuns()
  }
}

// ─── 实时并表辅助函数 ───
function normalizeRealtimeResultItem(item: any) {
  return {
    ...item,
    signal_date: item.signal_date || item.date || '',
    trade_date: item.trade_date || cacheStatus.value?.trade_date || cacheStatus.value?.requested_date || '',
    run_started_at: item.run_started_at || null,
    run_completed_at: item.run_completed_at || null,
  }
}

function makeResultKey(row: any) {
  return [
    row.trade_date || '',
    row.code || '',
    row.strategy_name || '',
    row.signal_date || row.date || '',
    row.category || '',
  ].join('|')
}

function sortResults(a: any, b: any) {
  const tradeDateA = a.trade_date || ''
  const tradeDateB = b.trade_date || ''
  if (tradeDateA !== tradeDateB) return tradeDateB.localeCompare(tradeDateA)
  const runStartedA = a.run_started_at || ''
  const runStartedB = b.run_started_at || ''
  if (runStartedA !== runStartedB) return runStartedB.localeCompare(runStartedA)
  const dateA = a.signal_date || a.date || ''
  const dateB = b.signal_date || b.date || ''
  if (dateA !== dateB) return dateB.localeCompare(dateA)
  const codeA = String(a.code || '')
  const codeB = String(b.code || '')
  if (codeA !== codeB) return codeA.localeCompare(codeB)
  return String(a.strategy_name || '').localeCompare(String(b.strategy_name || ''))
}

function mergeRealtimeItemsIntoResults(items: any[]) {
  const normalized = items.map(normalizeRealtimeResultItem)
  const map = new Map(results.value.map((row: any) => [makeResultKey(row), row]))
  for (const row of normalized) {
    map.set(makeResultKey(row), { ...map.get(makeResultKey(row)), ...row })
  }
  results.value = Array.from(map.values()).sort(sortResults)
  resultsTotal.value = results.value.length
  resultsUniqueTotal.value = new Set(results.value.map((row: any) => row.code)).size
}

function handleEvent(eventName: string, data: any) {
  if (typeof data?.progress === 'number') rebuildProgress.value = data.progress
  if (data?.message) rebuildMessage.value = data.message
  if (eventName === 'signal' && data.items) {
    const normalizedItems = data.items.map(normalizeRealtimeResultItem)
    for (const item of normalizedItems) {
      liveSignals.value.unshift(item)
    }
    const liveMap = new Map(liveSignals.value.map((row: any) => [makeResultKey(row), row]))
    liveSignals.value = Array.from(liveMap.values()).sort(sortResults).slice(0, 50)
    mergeRealtimeItemsIntoResults(normalizedItems)
  }
  if (data?.status === 'done') ElMessage.success(data.message || '重建完成')
  if (data?.status === 'error' || data?.status === 'busy') ElMessage.error(data.message || '重建失败')
}

function onStrategyChange(key: string) {
  queryStateStore.setResultsStrategy(key)
  loadResults()
  loadCacheStatus()
  loadRuns()
}

function onResultsPageChange(p: number) {
  queryStateStore.setResultsPage(p)
  loadResults()
}

function onRunsPageChange(p: number) {
  queryStateStore.setResultsRunsPage(p)
  loadRuns()
}

function onSearch() {
  queryStateStore.setResultsPage(1)
  loadResults()
}

function onSortChange({ prop, order }: { prop: string; order: string | null }) {
  // prop from el-table matches our backend column names
  queryStateStore.setResultsSort(
    prop || 'trade_date',
    order === 'ascending' ? 'ascending' : 'descending',
  )
  loadResults()
}

function goToStock(code: string) {
  // 保存当前结果列表到 store，供 K 线详情页右侧展示
  const uniqueList = Array.from(new Map(results.value.map((item: any) => [item.code, item])).values())
  strategyListStore.setList(uniqueList, activeStrategy.value, requestedTradeDate.value || (filterDateRange.value?.[0] ?? ''))
  router.push(`/stocks/${code}`)
}

function getStatusType(s: string) {
  if (s === 'done' || s === 'ready') return 'success'
  if (s === 'running' || s === 'partial' || s === 'stale') return 'warning'
  if (s === 'error' || s === 'missing') return 'danger'
  return 'info'
}

function getStatusLabel(s?: string) {
  const map: Record<string, string> = {
    ready: '缓存可用', partial: '部分可用', stale: '缓存过期',
    missing: '缓存缺失', done: '已完成', running: '运行中',
    error: '失败', queued: '排队中', cancelled: '已取消',
  }
  return map[s || ''] || s || '未知'
}

function formatDuration(start: string, end?: string) {
  if (!start) return '-'
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  const diff = Math.round((e - s) / 1000)
  if (diff < 60) return `${diff}s`
  return `${Math.floor(diff / 60)}m ${diff % 60}s`
}
</script>

<template>
  <div class="strategy-results-view">
    <!-- 作业进行中提示 -->
    <el-alert
      v-if="updateJobStore.isRunning"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:16px"
    >
      <template #title>
        后台正在执行数据更新 + 策略重建，下方显示的是<b>上次生成的策略结果</b>，完成后自动刷新。
      </template>
    </el-alert>

    <!-- 区块 A：缓存状态卡 -->
    <div class="status-card" v-loading="cacheLoading">
      <div class="status-card-head">
        <div>
          <h2>策略结果工作台</h2>
          <div class="status-meta">
            <el-tag :type="getStatusType(cacheStatus?.status)" size="small">
              {{ getStatusLabel(cacheStatus?.status) }}
            </el-tag>
            <span>目标日期: {{ cacheStatus?.requested_date || '-' }}</span>
            <span>缓存日期: {{ cacheStatus?.trade_date || '-' }}</span>
            <span>生成时间: {{ cacheStatus?.generated_at || '-' }}</span>
            <span>总命中: {{ cacheStatus?.total ?? 0 }} 条 / {{ cacheStatus?.unique_total ?? 0 }} 只</span>
          </div>
        </div>
        <!-- 区块 B：重建控制区 -->
        <div class="status-actions">
          <el-button
            type="primary"
            :loading="rebuildRunning"
            :disabled="rebuildRunning"
            @click="startRebuild"
          >
            重建当前策略
          </el-button>
          <el-button :disabled="rebuildRunning || cacheLoading" @click="loadCacheStatus">
            刷新状态
          </el-button>
        </div>
      </div>

      <!-- 重建进度 -->
      <div class="rebuild-area" v-if="rebuildRunning || rebuildProgress > 0">
        <el-progress :percentage="rebuildProgress" :stroke-width="14" :text-inside="true" />
        <div class="rebuild-msg">{{ rebuildMessage }}</div>
      </div>
    </div>

    <!-- 区块 C：实时命中表 -->
    <div class="live-signals" v-if="liveSignals.length">
      <h3>实时命中 ({{ liveSignals.length }})</h3>
      <el-table :data="liveSignals" size="small" max-height="260" stripe>
        <el-table-column prop="code" label="代码" width="90">
          <template #default="{ row }">
            <el-link type="primary" @click="goToStock(row.code)">{{ row.code }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="strategy_name" label="策略" width="140" />
        <el-table-column prop="category" label="分类" width="100" />
        <el-table-column prop="signal_date" label="信号日期" width="110" />
        <el-table-column prop="trigger_price" label="触发价" width="90">
          <template #default="{ row }">{{ row.trigger_price?.toFixed(2) ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="j_value" label="J值" width="70">
          <template #default="{ row }">{{ row.j_value?.toFixed(1) ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" show-overflow-tooltip />
      </el-table>
    </div>

    <!-- 策略切换 + 筛选 -->
    <div class="filter-bar">
      <el-radio-group v-model="activeStrategy" @change="onStrategyChange" size="default">
        <el-radio-button v-for="tab in tabs" :key="tab.key" :value="tab.key">{{ tab.label }}</el-radio-button>
      </el-radio-group>

      <el-input
        v-model="filterKeyword"
        placeholder="代码或名称..."
        clearable
        class="filter-input"
        @change="onSearch"
      />

      <el-date-picker
        v-model="filterDateRange"
        type="daterange"
        range-separator="-"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
        size="default"
        @change="onSearch"
      />

      <el-button @click="onSearch" type="primary" size="default">查询</el-button>
    </div>

    <!-- 区块 D：正式结果表 -->
    <div class="results-section" v-loading="resultsLoading">
      <h3>正式结果 (共 {{ resultsTotal }} 条信号，{{ resultsUniqueTotal }} 只股票)</h3>
      <div class="results-note" v-if="requestedTradeDate && !filterDateRange">
        当前默认展示 {{ requestedTradeDate }} 的最新执行结果；如需反查其他日期，可直接使用上方日期筛选或下方运行记录。
      </div>
      <el-table
        :data="results"
        stripe
        style="width: 100%"
        :default-sort="{ prop: sortBy, order: sortOrder }"
        @sort-change="onSortChange"
        @row-click="(row: any) => goToStock(row.code)"
      >
        <el-table-column prop="code" label="代码" width="90" sortable="custom">
          <template #default="{ row }">
            <el-link type="primary">{{ row.code }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="strategy_name" label="策略" width="140" sortable="custom" />
        <el-table-column prop="category" label="分类" width="100" />
        <el-table-column prop="signal_date" label="信号日期" width="110" sortable="custom" />
        <el-table-column prop="trigger_price" label="触发价" width="90" sortable="custom">
          <template #default="{ row }">{{ row.trigger_price?.toFixed(2) ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="close" label="收盘价" width="90">
          <template #default="{ row }">{{ row.close?.toFixed(2) ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="j_value" label="J值" width="70" sortable="custom">
          <template #default="{ row }">{{ row.j_value?.toFixed(1) ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="similarity_score" label="相似度" width="80" sortable="custom">
          <template #default="{ row }">
            {{ row.similarity_score ? (row.similarity_score * 100).toFixed(0) + '%' : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" show-overflow-tooltip />
        <el-table-column prop="run_started_at" label="最近执行" width="165" sortable="custom">
          <template #default="{ row }">
            <el-link v-if="row.run_id" type="primary" @click.stop="openRunDetail(row.run_id)">
              {{ row.run_started_at || '-' }}
            </el-link>
            <span v-else>{{ row.run_started_at || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="trade_date" label="交易日" width="110" sortable="custom" />
      </el-table>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="resultsPage"
          :page-size="resultsPageSize"
          :total="resultsTotal"
          layout="prev, pager, next, total"
          @current-change="onResultsPageChange"
        />
      </div>
    </div>

    <!-- 区块 F：运行记录列表 -->
    <div class="runs-section" v-loading="runsLoading">
      <h3>运行记录</h3>
      <el-table :data="runs" stripe size="small">
        <el-table-column prop="started_at" label="开始时间" width="160" />
        <el-table-column prop="completed_at" label="结束时间" width="160">
          <template #default="{ row }">{{ row.completed_at || '进行中...' }}</template>
        </el-table-column>
        <el-table-column prop="run_type" label="类型" width="140">
          <template #default="{ row }">
            <el-tag size="small" :type="row.run_type === 'update_and_rebuild' ? 'success' : 'info'">
              {{ row.run_type === 'update_and_rebuild' ? '更新+重建' : row.run_type === 'rebuild_only' ? '仅重建' : row.run_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="strategy_filter" label="策略范围" width="100" />
        <el-table-column prop="total_count" label="扫描数" width="80" />
        <el-table-column prop="matched_count" label="命中数" width="80" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="80">
          <template #default="{ row }">{{ formatDuration(row.started_at, row.completed_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openRunDetail(row.run_id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row" v-if="runsTotal > 10">
        <el-pagination
          v-model:current-page="runsPage"
          :page-size="10"
          :total="runsTotal"
          layout="prev, pager, next"
          @current-change="onRunsPageChange"
        />
      </div>
    </div>

    <!-- 区块 E：通达信 TXT 文件库 -->
    <div id="txt-library" ref="txtSectionRef">
      <TxtLibraryPanel />
    </div>

    <!-- 作业详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="`作业详情: ${drawerRunId}`" size="600px">
      <div v-loading="drawerLoading">
        <el-timeline v-if="drawerEvents.length">
          <el-timeline-item
            v-for="evt in drawerEvents"
            :key="evt.event_id"
            :timestamp="evt.created_at"
            :type="evt.event_type === 'error' ? 'danger' : evt.event_type === 'signal' ? 'success' : 'primary'"
          >
            <div class="event-label">{{ evt.event_type }}</div>
            <div class="event-msg">{{ evt.message }}</div>
            <div class="event-meta" v-if="evt.strategy_name">{{ evt.strategy_name }}</div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无事件记录" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.strategy-results-view {
  padding: 20px;
  max-width: 1400px;
  background-color: #ffffff;
  min-height: 100%;
  color: #333;
}

/* 覆盖暗色主题表格 */
.strategy-results-view :deep(.el-table) {
  --el-table-bg-color: #ffffff;
  --el-table-tr-bg-color: #ffffff;
  --el-table-header-bg-color: #f5f7fa;
  --el-table-row-hover-bg-color: #f0f7ff;
  --el-table-text-color: #303133;
  --el-table-header-text-color: #606266;
  --el-table-border-color: #ebeef5;
  --el-table-stripe-color: #fafafa;
}

/* 覆盖暗色主题分页 */
.strategy-results-view :deep(.el-pagination) {
  --el-pagination-text-color: #606266;
  --el-pagination-bg-color: #ffffff;
  --el-pagination-button-bg-color: #ffffff;
  --el-pagination-button-color: #606266;
  --el-pagination-hover-color: #409eff;
}

/* 覆盖暗色主题标签 */
.strategy-results-view :deep(.el-tag) {
  color: inherit;
}

.status-card {
  padding: 18px;
  border: 1px solid #e4e7ed;
  border-radius: 12px;
  background: linear-gradient(135deg, #f6f8fc, #ffffff);
  margin-bottom: 18px;
}

.status-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.status-card h2 {
  font-size: 18px;
  font-weight: 700;
  margin: 0 0 8px;
  color: #303133;
}

.status-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  color: #909399;
  font-size: 13px;
  align-items: center;
}

.status-actions {
  display: flex;
  gap: 10px;
}

.rebuild-area {
  margin-top: 14px;
}

.rebuild-msg {
  margin-top: 6px;
  font-size: 13px;
  color: #909399;
}

.live-signals {
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  background: #f0f9ff;
}

.live-signals h3 {
  font-size: 15px;
  margin: 0 0 10px;
  color: #303133;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.filter-input {
  width: 200px;
}

.results-section {
  margin-bottom: 24px;
}

.results-section h3 {
  font-size: 15px;
  margin: 0 0 12px;
  color: #303133;
}

.results-note {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #d9ecff;
  border-radius: 8px;
  background: #f4faff;
  color: #606266;
  font-size: 13px;
}

.pagination-row {
  display: flex;
  justify-content: center;
  margin-top: 14px;
}

.runs-section {
  margin-bottom: 24px;
}

.runs-section h3 {
  font-size: 15px;
  margin: 0 0 12px;
  color: #303133;
}

.event-label {
  font-weight: 600;
  font-size: 13px;
}

.event-msg {
  font-size: 13px;
  color: #606266;
}

.event-meta {
  font-size: 12px;
  color: #909399;
}
</style>
