<script setup lang="ts">
import { ref, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import StockTable from '@/components/StockTable.vue'
import { getStrategyCacheStatus, getStrategyResults, getStockList } from '@/api'

const router = useRouter()

const activeStrategy = ref('b1')
const searchText = ref('')
const loading = ref(false)
const strategyLoading = ref(false)
const cacheStatusLoading = ref(false)
const tableData = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)

const strategySignals = ref<Map<string, any>>(new Map())
const cacheStatus = ref<any>(null)
const rebuildRunning = ref(false)
const rebuildProgress = ref(0)
const rebuildMessage = ref('')
const rebuildLogs = ref<string[]>([])
const liveSignals = ref<any[]>([])

let searchTimer: ReturnType<typeof setTimeout> | null = null
let rebuildController: AbortController | null = null

const tabs = [
  { key: 'all', label: '全部' },
  { key: 'b1', label: 'B1形态' },
  { key: 'b2', label: 'B2突破' },
  { key: 'bowl', label: '碗底反弹' },
]

onMounted(() => {
  loadData()
  void loadCacheStatus()
})

onBeforeUnmount(() => {
  rebuildController?.abort()
})

async function loadData() {
  loading.value = true
  try {
    const listRes = await getStockList({
      page: page.value,
      per_page: pageSize.value,
      search: searchText.value,
    })
    const rawList = listRes.data.data || []
    total.value = listRes.data.total || 0

    tableData.value = rawList.map((stock: any) => ({
      ...stock,
      strategy: '',
      trigger_date: '',
      j_value: '',
    }))

    // 首页股票列表和策略命中结果来自两个接口，前端再按 code 做一次合并。
    void loadStrategySignals()
  } catch (e) {
    console.error('加载数据失败', e)
  } finally {
    loading.value = false
  }
}

async function loadStrategySignals() {
  strategyLoading.value = true
  try {
    const response = await getStrategyResults({ strategy: activeStrategy.value })
    const signals = response.data.data?.results || []

    strategySignals.value.clear()
    for (const signal of signals) {
      strategySignals.value.set(signal.code, signal)
    }

    tableData.value = tableData.value.map((stock: any) => {
      const matched = strategySignals.value.get(stock.code)
      return {
        ...stock,
        strategy: matched?.strategy_name || '',
        trigger_date: matched?.date || '',
        j_value: matched?.j_value || '',
      }
    })
  } catch (e) {
    console.error('加载策略结果失败', e)
  } finally {
    strategyLoading.value = false
  }
}

async function loadCacheStatus() {
  cacheStatusLoading.value = true
  try {
    const response = await getStrategyCacheStatus({ strategy: activeStrategy.value })
    cacheStatus.value = response.data.data || null
  } catch (e) {
    console.error('加载策略缓存状态失败', e)
  } finally {
    cacheStatusLoading.value = false
  }
}

function getStatusTagType(status?: string) {
  if (status === 'ready') return 'success'
  if (status === 'partial' || status === 'stale') return 'warning'
  if (status === 'missing' || status === 'not_found' || status === 'error') return 'danger'
  return 'info'
}

function getStatusLabel(status?: string) {
  if (status === 'ready') return '缓存可用'
  if (status === 'partial') return '部分可用'
  if (status === 'stale') return '缓存过期'
  if (status === 'missing') return '缓存缺失'
  if (status === 'not_found') return '当前策略未生成'
  return '状态未知'
}

function appendLog(message?: string) {
  if (!message) return
  rebuildLogs.value.push(message)
  if (rebuildLogs.value.length > 120) {
    rebuildLogs.value.shift()
  }
}

function appendLiveSignals(items: any[] = []) {
  for (const item of items) {
    liveSignals.value.unshift(item)
  }
  if (liveSignals.value.length > 20) {
    liveSignals.value = liveSignals.value.slice(0, 20)
  }
}

function handleRebuildEvent(eventName: string, data: any) {
  if (typeof data?.progress === 'number') {
    rebuildProgress.value = data.progress
  }
  if (data?.message) {
    rebuildMessage.value = data.message
    appendLog(data.message)
  }
  if (eventName === 'signal') {
    appendLiveSignals(data.items || [])
  }
  if (data?.status === 'done') {
    ElMessage.success(data.message || '策略缓存重建完成')
  }
  if (data?.status === 'error' || data?.status === 'busy') {
    ElMessage.error(data.message || '策略缓存重建失败')
  }
}

async function startStrategyRebuild() {
  if (rebuildRunning.value) return

  rebuildRunning.value = true
  rebuildProgress.value = 0
  rebuildMessage.value = '准备重建策略缓存...'
  rebuildLogs.value = []
  liveSignals.value = []
  rebuildController = new AbortController()

  try {
    const params = new URLSearchParams({ strategy: activeStrategy.value })
    const response = await fetch(`/api/strategy/cache/rebuild?${params.toString()}`, {
      method: 'POST',
      signal: rebuildController.signal,
    })

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`)
    }
    if (!response.body) {
      throw new Error('浏览器不支持流式读取')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      // SSE 可能分块到达，这里先按事件分隔符拼包，再逐条解析 event/data。
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''

      for (const chunk of chunks) {
        const lines = chunk.split('\n')
        const eventName = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
        const dataText = lines
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('\n')

        if (!dataText) continue

        try {
          const parsed = JSON.parse(dataText)
          handleRebuildEvent(eventName, parsed)
        } catch {
          // 忽略无法解析的 SSE 片段
        }
      }
    }
  } catch (e: any) {
    if (e?.name !== 'AbortError') {
      ElMessage.error('策略缓存重建请求失败: ' + (e?.message || '未知错误'))
    }
  } finally {
    rebuildRunning.value = false
    rebuildController = null
    await loadCacheStatus()
    await loadStrategySignals()
  }
}

function onTabChange(key: string) {
  activeStrategy.value = key
  page.value = 1
  loadData()
  void loadCacheStatus()
}

function onSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    loadData()
  }, 300)
}

function onPageChange(p: number) {
  page.value = p
  loadData()
}

function onRowClick(code: string) {
  router.push(`/stocks/${code}`)
}

watch(searchText, onSearch)
</script>

<template>
  <div class="home-view">
    <div class="cache-panel" v-loading="cacheStatusLoading">
      <div class="cache-head">
        <div>
          <div class="cache-title">策略缓存控制台</div>
          <div class="cache-meta">
            <el-tag :type="getStatusTagType(cacheStatus?.status)">{{ getStatusLabel(cacheStatus?.status) }}</el-tag>
            <span>目标日期 {{ cacheStatus?.requested_date || '-' }}</span>
            <span>缓存日期 {{ cacheStatus?.trade_date || '-' }}</span>
            <span>生成时间 {{ cacheStatus?.generated_at || '-' }}</span>
          </div>
        </div>
        <div class="cache-actions">
          <el-button
            type="primary"
            :loading="rebuildRunning"
            :disabled="rebuildRunning"
            @click="startStrategyRebuild"
          >
            重建当前策略缓存
          </el-button>
          <el-button :disabled="rebuildRunning || cacheStatusLoading" @click="loadCacheStatus">
            刷新状态
          </el-button>
        </div>
      </div>

      <div class="cache-summary">
        <span>当前标签 {{ activeStrategy }}</span>
        <span>覆盖分组 {{ (cacheStatus?.available_groups || []).join(', ') || '-' }}</span>
        <span>命中数 {{ cacheStatus?.group_totals?.[activeStrategy] ?? cacheStatus?.total ?? 0 }}</span>
      </div>

      <div class="cache-message">
        {{ rebuildRunning ? rebuildMessage : cacheStatus?.message || '暂无缓存说明' }}
      </div>

      <div class="progress-area" v-if="rebuildRunning || rebuildProgress > 0">
        <el-progress :percentage="rebuildProgress" :stroke-width="18" :text-inside="true" />
      </div>

      <div class="stream-grid" v-if="liveSignals.length || rebuildLogs.length">
        <div class="stream-card">
          <div class="stream-title">实时命中</div>
          <div class="signal-list">
            <div
              v-for="(item, index) in liveSignals"
              :key="`${item.code}-${item.date || 'na'}-${index}`"
              class="signal-item"
            >
              <span class="signal-code">{{ item.code }}</span>
              <span class="signal-name">{{ item.name }}</span>
              <span class="signal-strategy">{{ item.strategy_name }}</span>
              <span class="signal-date">{{ item.date || '-' }}</span>
            </div>
          </div>
        </div>

        <div class="stream-card">
          <div class="stream-title">执行日志</div>
          <div class="log-area">
            <div v-for="(line, index) in rebuildLogs" :key="`${line}-${index}`" class="log-line">
              {{ line }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="strategy-tabs">
      <el-radio-group v-model="activeStrategy" @change="onTabChange" size="large">
        <el-radio-button v-for="tab in tabs" :key="tab.key" :value="tab.key">
          {{ tab.label }}
        </el-radio-button>
      </el-radio-group>
      <el-input
        v-model="searchText"
        placeholder="搜索股票代码或名称..."
        clearable
        class="search-input"
        prefix-icon="Search"
      />
    </div>

    <StockTable
      :data="tableData"
      :loading="loading || strategyLoading"
      :total="total"
      :page="page"
      :page-size="pageSize"
      @page-change="onPageChange"
      @row-click="onRowClick"
    />
  </div>
</template>

<style scoped>
.home-view {
  padding: 20px;
}
.cache-panel {
  margin-bottom: 18px;
  padding: 18px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(246, 248, 252, 0.96), rgba(255, 255, 255, 0.92));
}
.cache-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
.cache-title {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 8px;
}
.cache-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  color: var(--text-secondary);
  font-size: 13px;
}
.cache-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.cache-summary {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 14px;
  font-size: 13px;
  color: var(--text-secondary);
}
.cache-message {
  margin-top: 10px;
  font-size: 14px;
}
.progress-area {
  margin-top: 14px;
}
.stream-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
  margin-top: 14px;
}
.stream-card {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.9);
}
.stream-title {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 10px;
}
.signal-list,
.log-area {
  max-height: 220px;
  overflow-y: auto;
}
.signal-item,
.log-line {
  display: grid;
  grid-template-columns: 72px 1fr 120px 96px;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border-color);
  font-size: 12px;
}
.signal-code,
.signal-strategy,
.signal-date {
  color: var(--text-secondary);
}
.strategy-tabs {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.search-input {
  width: 280px;
}

@media (max-width: 768px) {
  .signal-item,
  .log-line {
    grid-template-columns: 1fr;
  }
}
</style>
