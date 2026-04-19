<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getAvailableDates,
  getTxtDates,
  getTxtFiles,
  getTxtInfo,
  generateTxtFile,
  getTxtDownloadUrl,
} from '@/api'

const txtFiles = ref<any[]>([])
const txtDates = ref<string[]>([])
const txtFilterDate = ref<string>('')
const txtStrategy = ref<'all' | 'b1' | 'b2' | 'bowl'>('all')
const txtGenerating = ref(false)
const txtLoading = ref(false)
const txtInfo = ref<{ storage_dir: string; relative_dir: string; filename_pattern: string } | null>(null)

const storageDirLabel = computed(() => txtInfo.value?.relative_dir || 'data/txt/web_export')

onMounted(() => {
  loadTxtInfo()
  loadTxtDates()
  loadTxtFiles()
})

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

async function onGenerateTxt() {
  txtGenerating.value = true
  try {
    const dates = await getAvailableDates(1)
    const latestDate = (dates.data.data || [])[0]
    const targetDate = txtFilterDate.value || latestDate

    if (!targetDate) {
      ElMessage.warning('暂无可用策略结果，请先执行选股')
      return
    }

    const res = await generateTxtFile({ strategy: txtStrategy.value, date: targetDate })
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
  } catch (e: any) {
    ElMessage.error('生成失败：' + (e?.message || '未知错误'))
  } finally {
    txtGenerating.value = false
  }
}

function onDownloadTxt(filename: string) {
  window.open(getTxtDownloadUrl(filename), '_blank')
}

function onTxtDateChange() {
  loadTxtFiles()
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
        <el-button :loading="txtLoading" @click="loadTxtFiles">刷新列表</el-button>
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

.txt-file-list {
  min-height: 60px;
}
</style>
