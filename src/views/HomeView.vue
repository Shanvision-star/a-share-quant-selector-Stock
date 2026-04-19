<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getStrategyCacheStatus, getStrategyResults, getStockList } from '@/api'
import StockTable from '@/components/StockTable.vue'

const router = useRouter()

const loading = ref(false)
const cacheStatus = ref<any>(null)
const cacheLoading = ref(false)
const todayResults = ref<any[]>([])
const todayTotal = ref(0)

// 股票列表
const tableData = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const searchText = ref('')
const sortBy = ref<'code' | 'name' | 'latest_price' | 'change_pct' | 'market_cap' | 'latest_date' | 'k_value' | 'd_value' | 'j_value'>('code')
const sortOrder = ref<'asc' | 'desc'>('asc')
let searchTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  loadCacheStatus()
  loadTodayHighlights()
  loadStockList()
})

async function loadCacheStatus() {
  cacheLoading.value = true
  try {
    const res = await getStrategyCacheStatus({ strategy: 'all' })
    cacheStatus.value = res.data.data || null
  } catch (e) {
    console.error(e)
  } finally {
    cacheLoading.value = false
  }
}

async function loadTodayHighlights() {
  try {
    const res = await getStrategyResults({ strategy: 'all' })
    const data = res.data.data || {}
    todayResults.value = (data.results || []).slice(0, 10)
    todayTotal.value = data.total || 0
  } catch (e) {
    console.error(e)
  }
}

async function loadStockList() {
  loading.value = true
  try {
    const res = await getStockList({
      page: page.value,
      per_page: pageSize.value,
      search: searchText.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    })
    tableData.value = res.data.data || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  loadStockList()
}

function onSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; loadStockList() }, 300)
}

function onSortChange(prop: string, order: string | null) {
  if (!prop) {
    sortBy.value = 'code'
    sortOrder.value = 'asc'
  } else {
    sortBy.value = prop as typeof sortBy.value
    sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  }
  page.value = 1
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
  return 'info'
}
function getStatusLabel(s?: string) {
  const map: Record<string, string> = {
    ready: '缓存可用', partial: '部分可用', stale: '缓存过期', missing: '缓存缺失',
  }
  return map[s || ''] || '未知'
}
</script>

<template>
  <div class="home-view">
    <!-- 总览卡片 -->
    <div class="overview-cards">
      <el-card shadow="hover" class="overview-card" v-loading="cacheLoading">
        <div class="card-title">缓存状态</div>
        <div class="card-body">
          <el-tag :type="getStatusType(cacheStatus?.status)" size="large">
            {{ getStatusLabel(cacheStatus?.status) }}
          </el-tag>
          <div class="card-detail">
            <div>目标日期: {{ cacheStatus?.requested_date || '-' }}</div>
            <div>缓存日期: {{ cacheStatus?.trade_date || '-' }}</div>
            <div>生成时间: {{ cacheStatus?.generated_at || '-' }}</div>
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

      <el-card shadow="hover" class="overview-card action-card" @click="goToUpdate">
        <div class="card-title">数据更新</div>
        <div class="card-body">
          <div class="action-icon">🔄</div>
          <div class="action-label">一键更新+重建 →</div>
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

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-bottom: 12px;
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
