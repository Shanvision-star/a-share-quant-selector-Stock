<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getStrategyCacheStatus, getStrategyResults, getStockList, getInitStatus } from '@/api'
import { ElMessage } from 'element-plus'
import { RefreshRight } from '@element-plus/icons-vue'
import StockTable from '@/components/StockTable.vue'
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
  return HOME_SORT_FIELDS.includes(prop as HomeSortField)
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
      :title="initState === 'empty' ? '🚀 欢迎使用 A股量化选股系统' : '⚠️ 数据需要更新'"
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

    <!-- 总览卡片 -->
    <div class="overview-cards">
      <el-card shadow="hover" class="overview-card cache-status-card" v-loading="cacheLoading">
        <div class="card-title-row">
          <span class="card-title">缓存状态</span>
          <el-button
            :icon="RefreshRight"
            circle
            size="small"
            text
            :loading="cacheLoading"
            title="刷新状态"
            @click.stop="refreshCacheStatus"
          />
        </div>
        <div class="card-body">
          <!-- 状态标签 -->
          <el-tag :type="getStatusType(cacheStatus?.status)" size="large" style="font-size:13px">
            {{ getStatusLabel(cacheStatus?.status) }}
          </el-tag>

          <!-- 重建进度条 -->
          <el-progress
            v-if="cacheStatus?.status === 'running'"
            :percentage="cacheStatus?.rebuild?.progress || 0"
            :stroke-width="8"
            style="margin-top:6px"
          />

          <!-- 状态说明 -->
          <el-tooltip
            v-if="cacheStatus?.message"
            :content="cacheStatus.message"
            placement="bottom"
            :show-after="200"
          >
            <div class="cache-message text-ellipsis">{{ cacheStatus.message }}</div>
          </el-tooltip>

          <!-- 数据摘要 -->
          <div class="card-detail" v-if="cacheStatus">
            <div>目标日期：<strong>{{ cacheStatus.requested_date || '-' }}</strong></div>
            <div>缓存日期：<strong>{{ cacheStatus.trade_date || '-' }}</strong></div>
            <div v-if="cacheStatus.unique_total">命中个股：<strong>{{ cacheStatus.unique_total }} 只</strong></div>
            <div v-if="cacheStatus.generated_at" style="font-size:11px;color:var(--el-text-color-placeholder)">
              生成于 {{ cacheStatus.generated_at?.slice(0, 16) || '-' }}
            </div>
          </div>

          <!-- 分组命中数 -->
          <div
            v-if="cacheStatus?.group_totals && Object.keys(cacheStatus.group_totals).length"
            class="group-totals"
          >
            <el-tag
              v-for="(cnt, grp) in cacheStatus.group_totals"
              :key="grp as string"
              size="small"
              type="info"
              style="margin:2px"
            >
              {{ grp }}: {{ cnt }}
            </el-tag>
          </div>

          <!-- 缺失分组提示 -->
          <div
            v-if="cacheStatus?.missing_groups?.length"
            style="font-size:12px;color:var(--el-color-warning)"
          >
            缺失: {{ cacheStatus.missing_groups.join(', ') }}
          </div>

          <!-- 操作按钮 -->
          <div class="cache-actions" v-if="cacheStatus">
            <el-button
              v-if="['stale','missing','not_found','partial'].includes(cacheStatus.status)"
              type="primary"
              size="small"
              @click="goToRebuild"
            >
              立即重建
            </el-button>
            <el-button
              v-if="cacheStatus.status === 'running'"
              type="info"
              size="small"
              @click="goToRebuild"
            >
              查看进度
            </el-button>
            <el-button
              v-if="cacheStatus.status === 'ready'"
              size="small"
              @click="goToResults"
            >
              查看结果
            </el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover" class="overview-card">
        <div class="card-title">今日命中</div>
        <div class="card-body">
          <div class="hit-count">{{ todayTotal }}</div>
          <div class="card-detail">
            <div v-for="(count, group) in (cacheStatus?.group_totals || {})" :key="group as string">
              {{ group }}: {{ count }} 条
            </div>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover" class="overview-card action-card" @click="goToResults">
        <div class="card-title">策略结果</div>
        <div class="card-body">
          <div class="action-icon">📊</div>
          <div class="action-label">查看正式结果 →</div>
        </div>
      </el-card>

      <el-card shadow="hover" class="overview-card action-card" @click="goToTxtLibrary">
        <div class="card-title">TXT文件库</div>
        <div class="card-body">
          <div class="action-icon">📄</div>
          <div class="action-label">按日期下载通达信TXT →</div>
        </div>
      </el-card>

      <el-card
        shadow="hover"
        class="overview-card action-card"
        :class="{ 'card-running': updateJobStore.isRunning }"
        @click="goToUpdate"
      >
        <div class="card-title">数据更新</div>
        <div class="card-body">
          <!-- 运行中：显示进度 -->
          <template v-if="updateJobStore.isRunning">
            <div class="action-icon">🔄</div>
            <el-progress
              :percentage="updateJobStore.progress"
              :stroke-width="8"
              style="margin-top:4px"
            />
            <div style="font-size:12px;color:var(--el-color-primary);margin-top:4px">
              {{ updateJobStore.progressMsg || '正在处理...' }}
            </div>
            <div v-if="updateJobStore.liveSignals.length" style="font-size:12px;color:var(--el-text-color-secondary);">
              实时命中 {{ updateJobStore.liveSignals.length }} 只 →
            </div>
          </template>
          <!-- 完成：显示结果 -->
          <template v-else-if="updateJobStore.jobCompleted">
            <div class="action-icon">✅</div>
            <div class="action-label" style="color:#67c23a">
              完成，命中 {{ updateJobStore.totalMatched }} 条
            </div>
            <div class="action-label" @click.stop="goToResults" style="cursor:pointer">
              查看结果 →
            </div>
          </template>
          <!-- 默认 -->
          <template v-else>
            <div class="action-icon">🔄</div>
            <div class="action-label">一键更新+重建 →</div>
          </template>
        </div>
      </el-card>
    </div>

    <!-- 今日命中摘要 -->
    <div class="today-highlights" v-if="todayResults.length">
      <div class="section-head">
        <h3>今日策略命中概览</h3>
        <el-button type="primary" text @click="goToResults">查看全部 →</el-button>
      </div>
      <el-table :data="todayResults" stripe size="small" @row-click="(row: any) => goToStock(row.code)">
        <el-table-column prop="code" label="代码" width="90">
          <template #default="{ row }">
            <el-link type="primary">{{ row.code }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="strategy_name" label="策略" width="140" />
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
          placeholder="搜索股票代码或名称..."
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
.home-view {
  padding: 20px;
}

.overview-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.overview-card {
  cursor: default;
}

.action-card {
  cursor: pointer;
  transition: transform 0.2s;
}
.action-card:hover {
  transform: translateY(-2px);
}
.card-running {
  border-color: var(--el-color-primary) !important;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.25) !important;
}

.card-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.cache-message {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}
.group-totals {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  margin-top: 2px;
}
.cache-actions {
  display: flex;
  gap: 8px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.card-detail {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.8;
}

.hit-count {
  font-size: 36px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.action-icon {
  font-size: 32px;
}

.action-label {
  font-size: 14px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-head h3 {
  font-size: 16px;
  margin: 0;
}

.today-highlights {
  margin-bottom: 24px;
}

.stock-list-section {
  margin-bottom: 24px;
}

.search-input {
  width: 280px;
}
</style>
