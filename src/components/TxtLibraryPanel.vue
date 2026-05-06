<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getTxtDates,
  getTxtFiles,
  getTxtInfo,
  getTxtSummary,
  generateTxtFile,
  generateTxtFilesBatch,
  getTxtDownloadUrl,
} from '@/api'

type TxtStrategy = 'all' | 'b1' | 'b2' | 'bowl'

const props = defineProps<{
  strategy?: string
  date?: string
}>()

function normalizeStrategy(value?: string): TxtStrategy {
  return value === 'b1' || value === 'b2' || value === 'bowl' ? value : 'all'
}

const txtFiles = ref<any[]>([])
const txtDates = ref<string[]>([])
const txtFilterDate = ref<string>('')
const txtStrategy = ref<TxtStrategy>(normalizeStrategy(props.strategy))
const txtGenerating = ref(false)
const txtBatchGenerating = ref(false)
const txtLoading = ref(false)
const txtInfo = ref<{ storage_dir: string; relative_dir: string; filename_pattern: string } | null>(null)
const txtSummary = ref<any>(null)

const storageDirLabel = computed(() => txtInfo.value?.relative_dir || 'data/txt/web_export')
const summaryDate = computed(() => txtFilterDate.value || props.date || txtSummary.value?.date || '')
const hasSummary = computed(() => !!txtSummary.value && Number(txtSummary.value.signal_total || 0) > 0)

onMounted(() => {
  loadTxtInfo()
  loadTxtDates()
  loadTxtFiles()
  loadTxtSummary()
})

watch(
  () => props.strategy,
  (value) => {
    txtStrategy.value = normalizeStrategy(value)
  },
  { immediate: true },
)

watch(
  () => props.date,
  (value) => {
    if (value && !txtFilterDate.value) {
      txtFilterDate.value = value
      loadTxtSummary()
    }
  },
  { immediate: true },
)

async function loadTxtInfo() {
  try {
    const res = await getTxtInfo()
    txtInfo.value = res.data.data || null
  } catch (e) {
    console.error('加载TXT目录信息失败', e)
  }
}

async function loadTxtDates() {
  try {
    const res = await getTxtDates()
    txtDates.value = res.data.data || []
  } catch (e) {
    console.error('加载TXT日期失败', e)
  }
}

async function loadTxtFiles() {
  txtLoading.value = true
  try {
    const params: any = {}
    if (txtFilterDate.value) params.date = txtFilterDate.value
    const res = await getTxtFiles(params)
    txtFiles.value = res.data.data || []
  } catch (e) {
    console.error('加载TXT文件列表失败', e)
  } finally {
    txtLoading.value = false
  }
}

async function loadTxtSummary() {
  try {
    const params: { date?: string } = {}
    const targetDate = txtFilterDate.value || props.date || ''
    if (targetDate) params.date = targetDate
    const res = await getTxtSummary(params)
    txtSummary.value = res.data.data || null
  } catch (e) {
    console.error('加载TXT统计失败', e)
    txtSummary.value = null
  }
}

async function onGenerateTxt() {
  txtGenerating.value = true
  try {
    const targetDate = txtFilterDate.value || props.date || ''
    const params: { strategy: string; date?: string } = { strategy: txtStrategy.value }
    if (targetDate) params.date = targetDate

    const res = await generateTxtFile(params)
    if (!res.data.success) {
      ElMessage.error(res.data.error || '生成失败')
      return
    }

    const payload = res.data.data
    const overlap = Number(payload.overlap_signal_count || 0)
    const signalTotal = Number(payload.signal_total || payload.count || 0)
    if (overlap > 0) {
      ElMessage.success(`已生成：${payload.filename}（${payload.count} 只，原始命中 ${signalTotal} 条，重合 ${overlap} 条）`)
    } else {
      ElMessage.success(`已生成：${payload.filename}（共 ${payload.count} 只股票）`)
    }
    await loadTxtFiles()
    await loadTxtDates()
    await loadTxtSummary()
  } catch (e: any) {
    ElMessage.error('生成失败：' + (e?.message || '未知错误'))
  } finally {
    txtGenerating.value = false
  }
}

async function onGenerateBatchTxt() {
  txtBatchGenerating.value = true
  try {
    const params: { date?: string } = {}
    const targetDate = txtFilterDate.value || props.date || ''
    if (targetDate) params.date = targetDate
    const res = await generateTxtFilesBatch(params)
    if (!res.data.success) {
      ElMessage.error(res.data.error || '生成失败')
      return
    }

    const payload = res.data.data
    const fileCount = Array.isArray(payload.files) ? payload.files.length : 0
    const summary = payload.summary || {}
    ElMessage.success(
      `已生成 ${fileCount} 个分类TXT；最终 ${summary.unique_code_total || 0} 只股票，跨策略重合 ${summary.cross_strategy_overlap_count || 0} 只`,
    )
    await loadTxtFiles()
    await loadTxtDates()
    await loadTxtSummary()
  } catch (e: any) {
    ElMessage.error('批量生成失败：' + (e?.message || '未知错误'))
  } finally {
    txtBatchGenerating.value = false
  }
}

function onDownloadTxt(filename: string) {
  window.open(getTxtDownloadUrl(filename), '_blank')
}

function onTxtDateChange() {
  loadTxtFiles()
  loadTxtSummary()
}
</script>

<template>
  <div class="txt-section">
    <div class="txt-section-head">
      <h3>通达信 TXT 文件库</h3>
      <div class="txt-controls">
        <el-select v-model="txtStrategy" size="default" style="width:130px">
          <el-option value="all" label="全部策略" />
          <el-option value="b1" label="B1形态" />
          <el-option value="b2" label="B2突破" />
          <el-option value="bowl" label="碗底反弹" />
        </el-select>
        <el-select
          v-model="txtFilterDate"
          placeholder="按日期筛选"
          clearable
          size="default"
          style="width:150px"
          @change="onTxtDateChange"
        >
          <el-option v-for="d in txtDates" :key="d" :label="d" :value="d" />
        </el-select>
        <el-button type="primary" :loading="txtGenerating" @click="onGenerateTxt">
          生成TXT
        </el-button>
        <el-button type="success" :loading="txtBatchGenerating" @click="onGenerateBatchTxt">
          分类生成
        </el-button>
        <el-button :loading="txtLoading" @click="loadTxtFiles">刷新列表</el-button>
      </div>
    </div>

    <div v-if="hasSummary" class="txt-summary">
      <div class="txt-summary-head">
        <span>{{ summaryDate || txtSummary.date }} 导出统计</span>
        <strong>{{ txtSummary.signal_total }} 条信号 / {{ txtSummary.unique_code_total }} 只股票</strong>
        <em>跨策略重合 {{ txtSummary.cross_strategy_overlap_count }} 只</em>
      </div>
      <div class="txt-summary-grid">
        <div v-for="item in txtSummary.strategies" :key="item.strategy" class="txt-summary-item">
          <span>{{ item.strategy_label }}</span>
          <strong>{{ item.unique_code_total }} 只</strong>
          <em>{{ item.signal_total }} 条，重合 {{ item.overlap_signal_count }} 条</em>
        </div>
      </div>
    </div>

    <el-alert type="info" :closable="false" class="txt-hint">
      <template #title>
        服务器保存目录：{{ storageDirLabel }}；下载后文件会进入浏览器默认下载目录，可直接在通达信中导入。
      </template>
    </el-alert>

    <div v-loading="txtLoading" class="txt-file-list">
      <el-empty v-if="!txtFiles.length" description="暂无TXT文件，点击「生成TXT」创建" />
      <el-table v-else :data="txtFiles" size="small" stripe>
        <el-table-column prop="date" label="日期" width="120" sortable />
        <el-table-column prop="strategy_label" label="策略" width="100" />
        <el-table-column prop="count" label="股票数" width="80" />
        <el-table-column prop="created_at" label="生成时间" width="160" />
        <el-table-column prop="filename" label="文件名" show-overflow-tooltip />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" type="primary" text @click="onDownloadTxt(row.filename)">
              下载
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.txt-section {
  margin-bottom: 24px;
  padding: 16px;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  background: #fff;
}

.txt-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.txt-section-head h3 {
  font-size: 15px;
  margin: 0;
  color: #303133;
}

.txt-controls {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.txt-hint {
  margin-bottom: 12px;
}

.txt-summary {
  margin-bottom: 12px;
  border: 1px solid #d9ecff;
  border-radius: 8px;
  background: #f4faff;
  overflow: hidden;
}

.txt-summary-head {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  padding: 10px 12px;
  border-bottom: 1px solid #d9ecff;
  font-size: 13px;
}

.txt-summary-head span {
  font-weight: 600;
  color: #303133;
}

.txt-summary-head strong {
  color: #409eff;
}

.txt-summary-head em {
  color: #909399;
  font-style: normal;
}

.txt-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
}

.txt-summary-item {
  padding: 10px 12px;
  display: grid;
  gap: 3px;
  border-right: 1px solid #e8f4ff;
}

.txt-summary-item span {
  font-size: 12px;
  color: #606266;
}

.txt-summary-item strong {
  font-size: 15px;
  color: #303133;
}

.txt-summary-item em {
  font-size: 12px;
  color: #909399;
  font-style: normal;
}

.txt-file-list {
  min-height: 60px;
}
</style>
