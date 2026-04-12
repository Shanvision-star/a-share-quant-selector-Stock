<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getDataStatus } from '@/api'
import { ElMessage } from 'element-plus'

interface BoardStatus {
  board: string
  count: number
  latest_date: string
  fresh: boolean
  stale_pct: number
}

const boards = ref<BoardStatus[]>([])
const updating = ref(false)
const progress = ref(0)
const progressMsg = ref('')
const logLines = ref<string[]>([])
const loading = ref(true)

onMounted(async () => {
  await loadStatus()
})

async function loadStatus() {
  loading.value = true
  try {
    const res = await getDataStatus()
    const payload = res.data.data || {}
    const boardEntries = Object.entries(payload.boards || {})
    boards.value = boardEntries.map(([board, info]: [string, any]) => ({
      board,
      count: info.total || 0,
      latest_date: info.latest_date || '-',
      fresh: (info.stale_ratio || 0) === 0,
      stale_pct: info.stale_ratio || 0,
    }))
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function startUpdate() {
  updating.value = true
  progress.value = 0
  progressMsg.value = '开始更新...'
  logLines.value = []

  try {
    const response = await fetch('/api/update', { method: 'POST' })
    if (!response.body) {
      ElMessage.error('浏览器不支持流式读取')
      updating.value = false
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const raw = JSON.parse(line.slice(6))
            const data = typeof raw === 'string' ? { message: raw } : raw
            if (data.progress !== undefined) progress.value = data.progress
            if (data.message) {
              progressMsg.value = data.message
              logLines.value.push(data.message)
              // 限制日志行数
              if (logLines.value.length > 200) logLines.value.shift()
            }
            if (data.status === 'done') {
              ElMessage.success('数据更新完成')
            }
            if (data.status === 'error') {
              ElMessage.error(data.message || '更新失败')
            }
          } catch {
            // 非JSON行忽略
          }
        }
      }
    }
  } catch (e: any) {
    ElMessage.error('更新请求失败: ' + e.message)
  } finally {
    updating.value = false
    await loadStatus()
  }
}
</script>

<template>
  <div class="update-view" v-loading="loading">
    <h2>数据管理</h2>

    <!-- 板块状态卡片 -->
    <div class="board-cards">
      <el-card v-for="b in boards" :key="b.board" shadow="hover" class="board-card">
        <div class="board-name">{{ b.board }} 板块</div>
        <div class="board-count">{{ b.count }} 只</div>
        <div class="board-date">{{ b.latest_date }}</div>
        <div class="board-fresh">
          <el-tag v-if="b.fresh" type="success" size="small">✅ 数据新鲜</el-tag>
          <el-tag v-else type="warning" size="small">⚠️ {{ b.stale_pct }}% 过期</el-tag>
        </div>
      </el-card>
    </div>

    <!-- 更新按钮 -->
    <div class="update-action">
      <el-button
        type="primary"
        size="large"
        :loading="updating"
        @click="startUpdate"
        :disabled="updating"
      >
        🔄 一键更新数据
      </el-button>
    </div>

    <!-- 进度条 -->
    <div class="progress-area" v-if="updating || progress > 0">
      <el-progress :percentage="progress" :stroke-width="18" :text-inside="true" />
      <div class="progress-msg">{{ progressMsg }}</div>
      <div class="log-area">
        <div v-for="(line, i) in logLines" :key="i" class="log-line">{{ line }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.update-view {
  padding: 20px;
  max-width: 900px;
}
h2 {
  margin-bottom: 20px;
}
.board-cards {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 24px;
}
.board-card {
  width: 180px;
  text-align: center;
}
.board-name {
  font-weight: bold;
  font-size: 16px;
  margin-bottom: 8px;
}
.board-count {
  font-size: 14px;
  color: var(--text-secondary);
}
.board-date {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 4px 0;
}
.board-fresh {
  margin-top: 8px;
}
.update-action {
  margin-bottom: 24px;
}
.progress-area {
  margin-top: 16px;
}
.progress-msg {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}
.log-area {
  margin-top: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 12px;
  max-height: 300px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
}
.log-line {
  padding: 1px 0;
  color: var(--text-secondary);
}
</style>
