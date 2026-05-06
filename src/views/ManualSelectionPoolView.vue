<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Download, DataAnalysis } from '@element-plus/icons-vue'
import { useManualSelectionStore } from '@/stores/manualSelection'

const router = useRouter()
const store = useManualSelectionStore()

const selectedDate = ref('')
const filterText = ref('')

function shiftDays(days: number): Date {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date
}
function formatDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

const rangeDefault: [string, string] = [formatDate(shiftDays(-90)), formatDate(new Date())]
const dateRange = ref<[string, string]>([...rangeDefault])

const filteredItems = computed(() => {
  const keyword = filterText.value.trim()
  if (!keyword) return store.items
  return store.items.filter(item =>
    item.code.includes(keyword) ||
    (item.name || '').includes(keyword) ||
    (item.strategy_name || '').includes(keyword)
  )
})

async function refresh() {
  if (selectedDate.value) {
    await store.fetchByDate(selectedDate.value)
  } else {
    await store.fetchByRange(dateRange.value[0], dateRange.value[1])
  }
  await store.fetchDates(120)
}

async function selectDate(date: string) {
  selectedDate.value = date
  await store.fetchByDate(date)
}

async function clearDateFilter() {
  selectedDate.value = ''
  await store.fetchByRange(dateRange.value[0], dateRange.value[1])
}

async function removeItem(item: any) {
  try {
    await ElMessageBox.confirm(`确认从池子移出 ${item.code} ${item.name || ''}？`, '移出确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await store.remove(item.selection_date, item.code)
    ElMessage.success('已移出')
  } catch (error) {
    console.error(error)
    ElMessage.error('移出失败')
  }
}

function gotoDetail(code: string) {
  router.push(`/stocks/${code}`)
}

function sendToBacktest() {
  if (!filteredItems.value.length) {
    ElMessage.warning('当前列表为空')
    return
  }
  const start = selectedDate.value || dateRange.value[0]
  const end = selectedDate.value || dateRange.value[1]
  router.push({
    path: '/backtest',
    query: { source: 'manual', start, end },
  })
}

function exportCsv() {
  if (!filteredItems.value.length) {
    ElMessage.warning('当前列表为空')
    return
  }
  const header = ['selection_date', 'code', 'name', 'strategy_name', 'source_signal_date', 'source_trade_date', 'note']
  const rows = filteredItems.value.map(item => header.map(key => {
    const value = (item as any)[key] ?? ''
    const text = String(value).replace(/"/g, '""')
    return /[",\n]/.test(text) ? `"${text}"` : text
  }).join(','))
  const csv = '\ufeff' + [header.join(','), ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `manual_pool_${selectedDate.value || dateRange.value[0] + '_' + dateRange.value[1]}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  await store.fetchDates(120)
  if (store.dates.length) {
    await selectDate(store.dates[0])
  } else {
    await store.fetchByRange(dateRange.value[0], dateRange.value[1])
  }
})
</script>

<template>
  <div class="pool-view">
    <div class="pool-toolbar">
      <div>
        <h2>人工选股池</h2>
        <p>每日勾选保存的人工目标股票，作为后续量化跟踪和回测的数据源。</p>
      </div>
      <div class="toolbar-actions">
        <el-input v-model="filterText" placeholder="代码/名称/策略筛选" size="small" style="width: 200px" clearable />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          size="small"
          :disabled="!!selectedDate"
          style="width: 240px"
        />
        <el-button :icon="Refresh" size="small" @click="refresh">刷新</el-button>
        <el-button :icon="Download" size="small" @click="exportCsv">导出 CSV</el-button>
        <el-button type="primary" :icon="DataAnalysis" size="small" @click="sendToBacktest">发送到回测</el-button>
      </div>
    </div>

    <div class="pool-layout">
      <aside class="date-panel">
        <div class="panel-title">日期</div>
        <div
          class="date-item"
          :class="{ active: !selectedDate }"
          @click="clearDateFilter"
        >
          <span>全部区间</span>
        </div>
        <div
          v-for="date in store.dates"
          :key="date"
          class="date-item"
          :class="{ active: selectedDate === date }"
          @click="selectDate(date)"
        >
          <span>{{ date }}</span>
        </div>
        <div v-if="!store.dates.length" class="date-empty">暂无人工选股记录</div>
      </aside>

      <main class="result-panel" v-loading="store.loading">
        <div class="result-header">
          <strong>{{ selectedDate || `${dateRange[0]} ~ ${dateRange[1]}` }}</strong>
          <span class="hint">共 {{ filteredItems.length }} 只</span>
        </div>
        <el-table :data="filteredItems" size="small" border height="100%" empty-text="还没有人工选股，请到策略结果页或个股详情页勾选加入">
          <el-table-column prop="selection_date" label="选股日期" width="110" />
          <el-table-column prop="code" label="代码" width="90">
            <template #default="{ row }">
              <el-link type="primary" @click="gotoDetail(row.code)">{{ row.code }}</el-link>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="100" />
          <el-table-column prop="strategy_name" label="来源策略" min-width="120" />
          <el-table-column prop="source_signal_date" label="信号日" width="110" />
          <el-table-column prop="source_trade_date" label="原策略交易日" width="120" />
          <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
          <el-table-column prop="updated_at" label="更新时间" width="160" />
          <el-table-column label="操作" width="120" align="center">
            <template #default="{ row }">
              <el-button size="small" @click="gotoDetail(row.code)">详情</el-button>
              <el-button size="small" type="danger" link @click="removeItem(row)">移出</el-button>
            </template>
          </el-table-column>
        </el-table>
      </main>
    </div>
  </div>
</template>

<style scoped>
.pool-view { display: flex; flex-direction: column; height: 100%; background: #f5f7fa; overflow: hidden; }
.pool-toolbar { flex-shrink: 0; display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 14px 18px; background: #fff; border-bottom: 1px solid #e4e7ed; }
.pool-toolbar h2 { margin: 0; font-size: 18px; color: #303133; }
.pool-toolbar p { margin: 4px 0 0; font-size: 12px; color: #909399; }
.toolbar-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.pool-layout { flex: 1; min-height: 0; display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 12px; padding: 12px; overflow: hidden; }
.date-panel, .result-panel { background: #fff; border: 1px solid #e4e7ed; border-radius: 6px; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
.date-panel { overflow-y: auto; padding: 8px; }
.panel-title { font-size: 12px; color: #909399; padding: 4px 8px 8px; border-bottom: 1px solid #ebeef5; }
.date-item { padding: 8px 10px; cursor: pointer; font-size: 13px; color: #303133; border-radius: 4px; }
.date-item:hover { background: #f0f2f5; }
.date-item.active { background: #ecf5ff; color: #409eff; font-weight: 600; }
.date-empty { padding: 16px; font-size: 12px; color: #909399; text-align: center; }
.result-panel { padding: 12px; }
.result-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.hint { font-size: 12px; color: #909399; }
</style>
