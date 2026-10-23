<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { useStockStore } from '@/stores/stock'
import { strategyLabel } from '@/utils/strategyLabels'
import { useRouter } from 'vue-router'
import { getStrategyCacheStatus, getStrategyResults, getStockList, getInitStatus } from '@/api'
import { ElMessage } from 'element-plus'
import { RefreshRight, Search } from '@element-plus/icons-vue'
import StockTable from '@/components/StockTable.vue'
import KlineChart from '@/components/KlineChart.vue'
import { useUpdateJobStore } from '@/stores/updateJob'
import { useQueryStateStore } from '@/stores/queryState'
import { createRequestManager, isAbortError } from '@/api/requestManager'

const updateJobStore = useUpdateJobStore()
const queryStateStore = useQueryStateStore()
const requestManager = createRequestManager()

const router = useRouter()

const loading = ref(false)
const cacheStatus = ref<any>(null)
const cacheLoading = ref(false)
const todayResults = ref<any[]>([])
const todayTotal = ref(0)
const stockContext = useStockStore()
const focusCode = ref(stockContext.currentCode)
const focusPeriod = ref('daily')
const showShortTermTrend = ref(true)
const showBullBearLine = ref(true)
const focusSearchResults = ref<any[]>([])
const focusSearchLoading = ref(false)
const focusQuery = ref('')
const selectedFocusStock = ref<any>(null)
const focusOptions = computed(() => Array.from(new Map([
  ...(focusQuery.value ? focusSearchResults.value : [...todayResults.value, ...focusSearchResults.value,
    ...(selectedFocusStock.value ? [selectedFocusStock.value] : [])]),
].map(item => [item.code, item])).values()))
const focusIndex = computed(() => focusOptions.value.findIndex(item => item.code === focusCode.value))
const focusedStock = computed(() => todayResults.value.find(item => item.code === focusCode.value)
  || focusOptions.value.find(item => item.code === focusCode.value)
  || (selectedFocusStock.value?.code === focusCode.value ? selectedFocusStock.value : undefined)
  || (focusCode.value ? { code: focusCode.value, name: '' } : undefined))

watch(focusCode, code => {
  if (!code) return
  selectedFocusStock.value = focusOptions.value.find(item => item.code === code) || { code, name: '' }
  stockContext.currentCode = code
}, { immediate: true })

async function searchFocusStocks(query: string) {
  focusQuery.value = query.trim()
  const controller = requestManager.start('home:focus-search')
  focusSearchLoading.value = true
  try {
    const response = await getStockList({ page: 1, per_page: 30, search: focusQuery.value, sort_by: 'code', sort_order: 'asc' }, { signal: controller.signal })
    if (!requestManager.isCurrent('home:focus-search', controller)) return
    focusSearchResults.value = response.data.data || []
    const selected = focusSearchResults.value.find(item => item.code === focusCode.value)
    if (selected) selectedFocusStock.value = selected
  } catch (error) {
    if (!isAbortError(error)) ElMessage.error('股票搜索失败，请重试')
  } finally {
    if (requestManager.isCurrent('home:focus-search', controller)) focusSearchLoading.value = false
    requestManager.clear('home:focus-search', controller)
  }
}

function stepFocusStock(direction: number) {
  const next = focusOptions.value[focusIndex.value + direction]
  if (next) focusCode.value = next.code
}

// 股票列表
const tableData = ref<any[]>([])
const total = ref(0)
const page = computed({
  get: () => queryStateStore.home.page,
  set: (value: number) => queryStateStore.setHomePage(value),
})
const pageSize = computed(() => queryStateStore.home.perPage)
const searchText = computed({
  get: () => queryStateStore.home.search,
  set: (value: string) => queryStateStore.setHomeSearch(value),
})
const sortBy = computed(() => queryStateStore.home.sortBy)
const sortOrder = computed(() => queryStateStore.home.sortOrder)
let searchTimer: ReturnType<typeof setTimeout> | null = null
const HOME_SORT_FIELDS = ['code', 'name', 'latest_price', 'change_pct', 'market_cap', 'latest_date', 'k_value', 'd_value', 'j_value'] as const

type HomeSortField = (typeof HOME_SORT_FIELDS)[number]

function isHomeSortField(prop: string): prop is HomeSortField {
  return (HOME_SORT_FIELDS as readonly string[]).includes(prop)
}

// ─── 首次运行检测 ───
const showInitDialog = ref(false)
const initState = ref<string>('')
const initMessage = ref<string>('')
const initTotalStocks = ref(0)
const initRunning = ref(false)
const initProgress = ref(0)
const initProgressMsg = ref('')
const initLogLines = ref<string[]>([])

onMounted(async () => {
  // 作业进行中时跳过首次运行检测（避免弹出初始化对话框），但正常加载已有缓存数据
  if (!updateJobStore.isRunning) {
    await checkFirstRun()
  }
  loadCacheStatus()
  loadTodayHighlights()
  loadStockList()
  if (focusCode.value) void searchFocusStocks(focusCode.value)
})

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
  requestManager.cancelAll()
})

// 作业完成后自动刷新首页数据
watch(
  () => updateJobStore.jobCompleted,
  (done) => {
    if (done) {
      loadCacheStatus()
      loadTodayHighlights()
      loadStockList()
    }
  },
)

async function checkFirstRun() {
  try {
    const res = await getInitStatus()
    const data = res.data.data || {}
    initState.value = data.state || 'ready'
    initMessage.value = data.message || ''
    initTotalStocks.value = data.total_stocks || 0
    if (data.state === 'empty') {
      showInitDialog.value = true
    } else if (data.state === 'stale' && (data.max_lag_days || 0) > 30) {
      showInitDialog.value = true
    }
  } catch (e) {
    console.error('首次运行检测失败', e)
  }
}

function goToInitUpdate() {
  showInitDialog.value = false
  if (initState.value === 'empty') {
    // 跳转到更新页并传递 init 标识
    router.push({ path: '/update', query: { init: '1' } })
  } else {
    router.push('/update')
  }
}

async function startInitInline() {
  initRunning.value = true
  initProgress.value = 0
  initProgressMsg.value = '正在连接服务器...'
  initLogLines.value = []

  try {
    const response = await fetch('/api/data/init', { method: 'POST' })
    if (!response.body) {
      ElMessage.error('浏览器不支持流式读取')
      initRunning.value = false
      return
    }
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
        const dataText = lines.filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()).join('\n')
        if (!dataText) continue
        try {
          const data = JSON.parse(dataText)
          if (typeof data.progress === 'number') initProgress.value = data.progress
          if (data.message) {
            initProgressMsg.value = data.message
            initLogLines.value.push(data.message)
            if (initLogLines.value.length > 100) initLogLines.value.shift()
          }
          if (data.status === 'done') {
            ElMessage.success(data.message || '初始化完成')
            showInitDialog.value = false
            loadStockList()
          }
          if (data.status === 'error') {
            ElMessage.error(data.message || '初始化失败')
          }
        } catch (error) {
          console.warn('[HomeView] 初始化流事件解析失败', { error, dataText })
        }
      }
    }
  } catch (e: any) {
    ElMessage.error('初始化请求失败: ' + e.message)
  } finally {
    initRunning.value = false
  }
}

async function loadCacheStatus() {
  const controller = requestManager.start('home:cache')
  cacheLoading.value = true
  try {
    const res = await getStrategyCacheStatus({ strategy: 'all' }, { signal: controller.signal })
    if (!requestManager.isCurrent('home:cache', controller)) return
    cacheStatus.value = res.data.data || null
  } catch (e) {
    if (!isAbortError(e)) console.error(e)
  } finally {
    if (requestManager.isCurrent('home:cache', controller)) {
      cacheLoading.value = false
    }
    requestManager.clear('home:cache', controller)
  }
}

async function loadTodayHighlights() {
  const controller = requestManager.start('home:today-highlights')
  try {
    const res = await getStrategyResults({ strategy: 'all' }, { signal: controller.signal })
    if (!requestManager.isCurrent('home:today-highlights', controller)) return
    const data = res.data.data || {}
    todayResults.value = (data.results || []).slice(0, 10)
    todayTotal.value = data.total || 0
    if (!focusCode.value && todayResults.value[0]) focusCode.value = todayResults.value[0].code
  } catch (e) {
    if (!isAbortError(e)) console.error(e)
  } finally {
    requestManager.clear('home:today-highlights', controller)
  }
}

async function loadStockList() {
  const controller = requestManager.start('home:stock-list')
  loading.value = true
  try {
    const res = await getStockList({
      page: page.value,
      per_page: pageSize.value,
      search: searchText.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    }, { signal: controller.signal })
    if (!requestManager.isCurrent('home:stock-list', controller)) return
    tableData.value = res.data.data || []
    total.value = res.data.total || 0
    if (!focusCode.value && tableData.value[0]) {
      selectedFocusStock.value = tableData.value[0]
      focusCode.value = tableData.value[0].code
    }
  } catch (e) {
    if (!isAbortError(e)) console.error(e)
  } finally {
    if (requestManager.isCurrent('home:stock-list', controller)) {
      loading.value = false
    }
    requestManager.clear('home:stock-list', controller)
  }
}

function onPageChange(p: number) {
  queryStateStore.setHomePage(p)
  loadStockList()
}

function onSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    queryStateStore.setHomePage(1)
    loadStockList()
  }, 300)
}

function onSortChange(prop: string, order: string | null) {
  if (!prop) {
    queryStateStore.setHomeSort('code', 'asc')
  } else {
    const safeProp = isHomeSortField(prop) ? prop : 'code'
    if (!isHomeSortField(prop)) {
      console.warn('[HomeView] 收到不支持的排序字段，已回退到 code', { prop })
    }
    queryStateStore.setHomeSort(
      safeProp,
      order === 'ascending' ? 'asc' : 'desc',
    )
  }
  loadStockList()
}

function goToResults() { router.push('/strategy-results') }
function goToTxtLibrary() { router.push({ path: '/strategy-results', query: { focus: 'txt' } }) }
function goToUpdate() { router.push('/update') }
function goToSystemStatus() { router.push('/status') }
function goToStock(code: string) { router.push(`/stocks/${code}`) }

function getStatusType(s?: string) {
  if (s === 'ready') return 'success'
  if (s === 'partial' || s === 'stale') return 'warning'
  if (s === 'missing' || s === 'not_found') return 'danger'
  if (s === 'running') return 'primary'
  return 'info'
}
function getStatusLabel(s?: string) {
  const map: Record<string, string> = {
    ready: '✅ 缓存可用',
    partial: '⚠️ 部分可用',
    stale: '⏰ 缓存过期',
    missing: '❌ 缓存缺失',
    not_found: '❌ 策略未找到',
    running: '🔄 正在重建',
  }
  return map[s || ''] || (s ? `未知(${s})` : '加载中...')
}

async function refreshCacheStatus() {
  await loadCacheStatus()
  ElMessage.success('缓存状态已刷新')
}

function goToRebuild() {
  router.push('/update')
}
</script>

<template>
  <div class="home-view">
    <!-- 首次运行 / 数据过期提示对话框 -->
    <el-dialog
      v-model="showInitDialog"
      :title="initState === 'empty' ? '初始化数据' : '数据需要更新'"
      width="560px"
      :close-on-click-modal="false"
    >
      <div v-if="!initRunning">
        <el-alert
          :type="initState === 'empty' ? 'warning' : 'info'"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
        >
          <template #title>
            <span v-if="initState === 'empty'">检测到这是首次运行，本地仅有 {{ initTotalStocks }} 只股票数据</span>
            <span v-else>{{ initMessage }}</span>
          </template>
        </el-alert>
        <p v-if="initState === 'empty'" style="line-height: 1.8">
          系统需要下载全部 A 股（约5000+只）的6年历史数据才能正常运行策略选股。<br>
          <strong>预计耗时</strong>：30-60 分钟（取决于网络速度）<br>
          <strong>磁盘空间</strong>：约 2-3 GB
        </p>
        <p v-else style="line-height: 1.8">
          建议前往数据更新页面执行一键更新。
        </p>
      </div>
      <div v-else>
        <el-progress :percentage="initProgress" :stroke-width="20" style="margin-bottom: 12px" />
        <div style="font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 8px">
          {{ initProgressMsg }}
        </div>
        <div
          style="max-height: 200px; overflow-y: auto; background: var(--el-fill-color-lighter); padding: 8px; border-radius: 4px; font-size: 12px; font-family: monospace; line-height: 1.6"
        >
          <div v-for="(line, i) in initLogLines" :key="i">{{ line }}</div>
        </div>
      </div>
      <template #footer>
        <div v-if="!initRunning">
          <el-button @click="showInitDialog = false">稍后再说</el-button>
          <el-button v-if="initState === 'empty'" type="primary" @click="startInitInline">
            立即初始化数据
          </el-button>
          <el-button v-if="initState === 'empty'" @click="goToInitUpdate">
            前往更新页面
          </el-button>
          <el-button v-if="initState === 'stale'" type="primary" @click="goToInitUpdate">
            前往更新数据
          </el-button>
        </div>
        <div v-else>
          <el-tag type="info">正在初始化中，请勿关闭页面...</el-tag>
        </div>
      </template>
    </el-dialog>

    <!-- 作业进行中时的页面级提示 -->
    <el-alert
      v-if="updateJobStore.isRunning"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:16px"
    >
      <template #title>
        <span>
          后台正在执行数据更新 + 策略重建（当前：{{ updateJobStore.progressMsg || '处理中...' }}），下方显示的是<b>上次的缓存数据</b>，完成后自动刷新。
          <el-button type="primary" text size="small" @click="goToUpdate" style="padding:0 4px">
            查看实时进度 →
          </el-button>
        </span>
      </template>
    </el-alert>

    <section class="cache-strip" aria-label="缓存状态" v-loading="cacheLoading">
      <el-tag :type="getStatusType(cacheStatus?.status)">{{ getStatusLabel(cacheStatus?.status) }}</el-tag>
      <span>目标 {{ cacheStatus?.requested_date || '—' }} · 缓存 {{ cacheStatus?.trade_date || '—' }}</span>
      <span>策略命中 <strong>{{ todayTotal }}</strong></span>
      <span v-if="cacheStatus?.missing_groups?.length" class="cache-warning">缺失：{{ cacheStatus.missing_groups.map(strategyLabel).join('、') }}</span>
      <el-button v-if="cacheStatus?.status === 'running'" text size="small" @click="goToRebuild">重建 {{ cacheStatus?.rebuild?.progress || 0 }}% · 查看进度</el-button>
      <el-button text :icon="RefreshRight" aria-label="刷新缓存状态" @click="refreshCacheStatus" />
      <el-button v-if="['stale','missing','not_found','partial'].includes(cacheStatus?.status)" size="small" @click="goToRebuild">更新 / 重建</el-button>
      <el-button text size="small" @click="goToResults">策略结果 ↗</el-button>
      <el-button text size="small" @click="goToTxtLibrary">下载 TXT ↗</el-button>
      <el-button text size="small" @click="goToSystemStatus">系统状态 ↗</el-button>
    </section>

    <!-- 今日命中摘要 -->
    <section class="focus-stock">
      <div class="section-head">
        <div class="focus-picker">
          <el-select v-model="focusCode" filterable remote :remote-method="searchFocusStocks" :loading="focusSearchLoading" default-first-option :reserve-keyword="false" placeholder="搜索名称 / 代码" aria-label="搜索并切换图表股票" class="focus-select">
            <template #prefix><el-icon aria-hidden="true"><Search /></el-icon></template>
            <el-option v-for="item in focusOptions" :key="item.code" :label="`${item.name} ${item.code}`" :value="item.code" />
          </el-select>
          <el-button-group>
            <el-button :disabled="focusIndex <= 0" aria-label="上一只股票" @click="stepFocusStock(-1)">上一只</el-button>
            <el-button :disabled="focusIndex < 0 || focusIndex >= focusOptions.length - 1" aria-label="下一只股票" @click="stepFocusStock(1)">下一只</el-button>
          </el-button-group>
        </div>
        <div class="focus-tools"><el-checkbox v-model="showShortTermTrend">短期趋势线</el-checkbox><el-checkbox v-model="showBullBearLine">知行多空线</el-checkbox><el-segmented v-model="focusPeriod" :options="[{label:'日 K',value:'daily'},{label:'周 K',value:'weekly'}]" aria-label="K 线周期" /><el-button v-if="focusedStock" text @click="goToStock(focusedStock.code)">详情 ↗</el-button></div>
      </div>
      <div v-if="focusedStock" class="focus-identity"><strong>{{ focusedStock.name }}</strong><span>{{ focusedStock.code }}</span><el-tag v-if="focusedStock.strategy_name" size="small">{{ strategyLabel(focusedStock.strategy_name) }}</el-tag><span v-if="focusedStock.date">信号 {{ focusedStock.date }}</span></div>
      <div v-if="focusedStock" class="focus-chart"><KlineChart :code="focusedStock.code" :period="focusPeriod" compact :show-adj-volume="false" :show-short-term-trend="showShortTermTrend" :show-bull-bear-line="showBullBearLine" /></div>
    </section>
    <div class="today-highlights" v-if="todayResults.length">
      <div class="section-head">
        <h3>策略候选 <span class="candidate-count">{{ todayTotal }}</span></h3>
        <el-button type="primary" text @click="goToResults">查看全部 →</el-button>
      </div>
      <el-table :data="todayResults" stripe size="small" max-height="300" @row-click="(row: any) => focusCode = row.code">
        <el-table-column prop="code" label="代码" width="90">
          <template #default="{ row }">
            <el-link type="primary">{{ row.code }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="strategy_name" label="策略" width="140"><template #default="{ row }">{{ strategyLabel(row.strategy_name) }}</template></el-table-column>
        <el-table-column prop="category" label="分类" width="100" />
        <el-table-column prop="date" label="信号日期" width="110" />
        <el-table-column prop="j_value" label="J值" width="70">
          <template #default="{ row }">
            <span :style="{ color: row.j_value != null && Number(row.j_value) < 20 ? '#67c23a' : row.j_value != null && Number(row.j_value) > 80 ? '#f56c6c' : undefined }">
              {{ row.j_value != null ? Number(row.j_value).toFixed(1) : '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip />
      </el-table>
    </div>

    <!-- 股票列表 -->
    <div class="stock-list-section">
      <div class="section-head">
        <h3>股票列表</h3>
        <el-input
          v-model="searchText"
          placeholder="代码或名称"
          aria-label="搜索股票代码或名称"
          clearable
          class="search-input"
          @input="onSearch"
        />
      </div>

      <StockTable
        :data="tableData"
        :loading="loading"
        :total="total"
        :page="page"
        :page-size="pageSize"
        @page-change="onPageChange"
        @sort-change="onSortChange"
        @row-click="goToStock"
      />
    </div>
  </div>
</template>

<style scoped>
.home-view { padding: 26px 30px; }
.cache-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 12px 16px;
  margin-bottom: 20px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}
.cache-strip .el-button { margin: 0; }
.cache-warning { color: #9b641a; }
.focus-stock, .today-highlights, .stock-list-section {
  padding: 20px;
  margin-bottom: 24px;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  background: white;
}
.focus-chart { height: 500px; min-width: 0; }
.focus-picker { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.focus-select { width: 260px; max-width: 100%; }
.focus-tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.focus-identity { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 18px 0 10px; font-size: 12px; color: var(--text-secondary); }
.focus-identity strong { font-size: 20px; letter-spacing: -.5px; color: var(--text-primary); }
.candidate-count { font-size: 12px; background: #edf3fb; padding: 3px 8px; border-radius: 6px; color: #687b99; }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 12px; flex-wrap: wrap; }
.section-head h3 { font-size: 16px; margin: 0; }
.search-input { width: 280px; max-width: 60%; }
@media(max-width:1100px) { .home-view { padding: 20px; } }
@media(max-width:600px) {
  .home-view { padding: 14px; }
  .focus-stock, .today-highlights, .stock-list-section { padding: 12px; }
  .section-head h3 { font-size: 14px; }
  .section-head { flex-wrap: wrap; }
  .focus-select { max-width: 100%; }
}
</style>
