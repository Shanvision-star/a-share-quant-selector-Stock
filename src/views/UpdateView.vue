<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getDataStatus } from '@/api'
import { ElMessage } from 'element-plus'
import { useStrategyListStore } from '@/stores/strategyList'

const router = useRouter()
const strategyListStore = useStrategyListStore()

interface BoardStatus {
  board: string
  count: number
  latest_date: string
  fresh: boolean
  stale_pct: number
}

function createUpdateStageState() {
  return {
    status: 'pending',
    progress: 0,
    message: '',
    scanTotal: 0,
    checked: 0,
    toUpdate: 0,
    upToDate: 0,
    completed: 0,
    updated: 0,
    failed: 0,
    remaining: 0,
    verifyTotal: 0,
    verifyReached: 0,
    currentCode: '',
    cacheHit: false,
    cacheWritten: false,
  }
}

function createRebuildStageState() {
  return {
    status: 'pending',
    progress: 0,
    message: '',
    processed: 0,
    total: 0,
    matched: 0,
    currentStrategy: '',
  }
}

const boards = ref<BoardStatus[]>([])
const updating = ref(false)
const progress = ref(0)
const progressMsg = ref('')
const logLines = ref<string[]>([])
const loading = ref(true)
const currentStage = ref<string>('')
const runId = ref<string>('')
const liveSignals = ref<any[]>([])
const jobCompleted = ref(false)
const jobResult = ref<any>(null)
const selectedDate = ref<string>('')
const effectiveRunDateLabel = computed(() => selectedDate.value || '后端默认交易日')

// 详细阶段进展
const stageDetail = ref({
  update: createUpdateStageState(),
  rebuild: createRebuildStageState(),
})
const rebuildStrategies = ref<{ name: string; filter: string; status: string; total: number }[]>([])

const updateStageProgress = computed(() => stageDetail.value.update.progress)
const rebuildStageProgress = computed(() => stageDetail.value.rebuild.progress)

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

async function startUpdate(autoRebuild: boolean = true) {
  updating.value = true
  progress.value = 0
  progressMsg.value = '开始统一作业...'
  currentStage.value = 'update'
  logLines.value = []
  liveSignals.value = []
  jobCompleted.value = false
  jobResult.value = null
  rebuildStrategies.value = []
  stageDetail.value = {
    update: createUpdateStageState(),
    rebuild: createRebuildStageState(),
  }

  try {
    const params = new URLSearchParams({
      auto_rebuild: String(autoRebuild),
      pipeline: 'true',
    })
    if (selectedDate.value) {
      params.set('date', selectedDate.value)
    }
    const response = await fetch(`/api/update?${params}`, { method: 'POST' })
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
        } catch { /* ignore */ }
      }
    }
  } catch (e: any) {
    ElMessage.error('作业请求失败: ' + e.message)
  } finally {
    updating.value = false
    await loadStatus()
  }
}

function handleEvent(eventName: string, data: any) {
  if (data.run_id) runId.value = data.run_id
  if (data.stage) currentStage.value = data.stage
  if (typeof data.progress === 'number') progress.value = data.progress
  if (data.message) {
    progressMsg.value = data.message
    logLines.value.push(`[${eventName}] ${data.message}`)
    if (logLines.value.length > 200) logLines.value.shift()
  }

  // 阶段细节跟踪
  if (data.stage === 'update' || eventName === 'update_start' || eventName === 'update_progress' || eventName === 'update_complete') {
    const s = stageDetail.value.update
    if (eventName === 'update_start') { s.status = 'running'; s.progress = 0 }
    else if (eventName === 'update_complete') { s.status = 'done'; s.progress = 100 }
    else if (data.stage === 'update' && typeof data.progress === 'number') {
      s.status = 'running'
      // 数据更新进度映射: 总体 5%-40% → 阶段 0%-100%
      s.progress = Math.min(100, Math.round(((data.progress - 5) / 35) * 100))
    }
    if (data.message) s.message = data.message
    if (typeof data.scan_total === 'number') s.scanTotal = data.scan_total
    if (typeof data.checked === 'number') s.checked = data.checked
    if (typeof data.to_update === 'number') s.toUpdate = data.to_update
    if (typeof data.up_to_date === 'number') s.upToDate = data.up_to_date
    if (typeof data.completed === 'number') s.completed = data.completed
    if (typeof data.updated === 'number') s.updated = data.updated
    if (typeof data.failed === 'number') s.failed = data.failed
    if (typeof data.remaining === 'number') s.remaining = data.remaining
    if (typeof data.verify_total === 'number') s.verifyTotal = data.verify_total
    if (typeof data.verify_reached === 'number') s.verifyReached = data.verify_reached
    if (typeof data.current_code === 'string') s.currentCode = data.current_code
    if (typeof data.cache_hit === 'boolean') s.cacheHit = data.cache_hit
    if (typeof data.cache_written === 'boolean') s.cacheWritten = data.cache_written
  }

  if (data.stage === 'rebuild' || eventName === 'rebuild_start' || eventName === 'strategy_start' || eventName === 'strategy_complete') {
    const s = stageDetail.value.rebuild
    if (eventName === 'rebuild_start') { s.status = 'running'; s.progress = 0 }
    if (data.stage === 'rebuild' && typeof data.progress === 'number') {
      s.status = 'running'
      // 策略重建进度映射: 总体 42%-98% → 阶段 0%-100%
      s.progress = Math.min(100, Math.round(((data.progress - 42) / 56) * 100))
    }
    if (data.message) s.message = data.message
    if (typeof data.processed === 'number') s.processed = data.processed
    if (typeof data.total === 'number') s.total = data.total
    if (typeof data.matched === 'number') s.matched = data.matched
    if (data.strategy_name) s.currentStrategy = data.strategy_name
  }

  // 策略级进展
  if (eventName === 'strategy_start' && data.strategy_name) {
    const existing = rebuildStrategies.value.find(s => s.filter === data.strategy_filter)
    if (!existing) {
      rebuildStrategies.value.push({ name: data.strategy_name, filter: data.strategy_filter, status: 'running', total: 0 })
    } else {
      existing.status = 'running'
    }
  }
  if (eventName === 'strategy_complete' && data.strategy_name) {
    const existing = rebuildStrategies.value.find(s => s.filter === data.strategy_filter)
    if (existing) {
      existing.status = 'done'
      existing.total = data.group_total || 0
    }
  }

  // 实时命中信号
  if (eventName === 'signal' && data.items) {
    for (const item of data.items) {
      strategyListStore.pushItem(item)
      liveSignals.value.unshift(item)
    }
    if (liveSignals.value.length > 30) liveSignals.value = liveSignals.value.slice(0, 30)
  }

  if (data.status === 'done') {
    if (currentStage.value === 'rebuild' || stageDetail.value.rebuild.status === 'running') {
      stageDetail.value.rebuild.status = 'done'
      stageDetail.value.rebuild.progress = 100
    }
    jobCompleted.value = true
    jobResult.value = data
    ElMessage.success(data.message || '作业完成')
  }
  if (data.status === 'error') {
    ElMessage.error(data.message || '作业失败')
  }
}

function goToResults() {
  const targetDate = jobResult.value?.trade_date || selectedDate.value
  router.push({
    path: '/strategy-results',
    query: targetDate ? { date: targetDate } : undefined,
  })
}

function getStageLabel(stage: string) {
  if (stage === 'update') return '数据更新'
  if (stage === 'rebuild') return '策略重建'
  return stage
}
</script>

<template>
  <div class="update-view" v-loading="loading">
    <h2>统一作业 - 数据更新 + 策略重建</h2>

    <!-- 板块状态卡片 -->
    <div class="board-cards">
      <el-card v-for="b in boards" :key="b.board" shadow="hover" class="board-card">
        <div class="board-name">{{ b.board }} 板块</div>
        <div class="board-count">{{ b.count }} 只</div>
        <div class="board-date">{{ b.latest_date }}</div>
        <div class="board-fresh">
          <el-tag v-if="b.fresh" type="success" size="small">数据新鲜</el-tag>
          <el-tag v-else type="warning" size="small">{{ b.stale_pct }}% 过期</el-tag>
        </div>
      </el-card>
    </div>

    <!-- 操作按钮 -->
    <div class="date-action-card">
      <div class="date-action-header">
        <div>
          <div class="section-title">执行日期</div>
          <div class="section-desc">先选择交易日，再点击下方按钮启动对应策略流程。不选日期时，后端会使用默认交易日。</div>
        </div>
        <el-date-picker
          v-model="selectedDate"
          type="date"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          placeholder="请选择交易日"
          clearable
        />
      </div>

      <div class="selected-date-tip">
        当前执行日期：{{ effectiveRunDateLabel }}
      </div>
    </div>

    <div class="update-action">
      <el-button
        type="primary"
        size="large"
        :loading="updating"
        @click="startUpdate(true)"
        :disabled="updating"
      >
        执行该日期：更新数据 + 自动重建策略
      </el-button>
      <el-button
        size="large"
        :loading="updating"
        @click="startUpdate(false)"
        :disabled="updating"
      >
        执行该日期：仅更新数据
      </el-button>
    </div>

    <!-- 进度区域 -->
    <div class="progress-area" v-if="updating || progress > 0">
      <div class="stage-indicator" v-if="currentStage">
        <el-tag :type="currentStage === 'rebuild' ? 'success' : 'primary'" size="default">
          当前阶段: {{ getStageLabel(currentStage) }}
        </el-tag>
        <span v-if="runId" class="run-id">run_id: {{ runId }}</span>
      </div>

      <el-progress :percentage="progress" :stroke-width="18" :text-inside="true" />
      <div class="progress-msg">{{ progressMsg }}</div>

      <!-- 分阶段详细进展 -->
      <div class="stage-details">
        <div class="stage-row">
          <div class="stage-header">
            <el-icon v-if="stageDetail.update.status === 'done'" color="#67c23a"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a448 448 0 1 1 0 896 448 448 0 0 1 0-896zm-55.808 536.384-99.52-99.584a38.4 38.4 0 1 0-54.336 54.336l126.72 126.72a38.272 38.272 0 0 0 54.336 0l262.4-262.464a38.4 38.4 0 1 0-54.272-54.336L456.192 600.384z"/></svg></el-icon>
            <el-icon v-else-if="stageDetail.update.status === 'running'" class="is-loading" color="#409eff"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a32 32 0 0 1 32 32v192a32 32 0 0 1-64 0V96a32 32 0 0 1 32-32zm0 640a32 32 0 0 1 32 32v192a32 32 0 1 1-64 0V736a32 32 0 0 1 32-32zm448-192a32 32 0 0 1-32 32H736a32 32 0 1 1 0-64h192a32 32 0 0 1 32 32zM288 512a32 32 0 0 1-32 32H64a32 32 0 0 1 0-64h192a32 32 0 0 1 32 32z"/></svg></el-icon>
            <span v-else class="stage-pending-dot"></span>
            <span class="stage-label">阶段一：数据更新</span>
            <el-tag v-if="stageDetail.update.status === 'done'" type="success" size="small">完成</el-tag>
            <el-tag v-else-if="stageDetail.update.status === 'running'" type="primary" size="small">进行中</el-tag>
            <el-tag v-else type="info" size="small">等待</el-tag>
          </div>
          <el-progress
            v-if="stageDetail.update.status !== 'pending'"
            :percentage="updateStageProgress"
            :stroke-width="10"
            :text-inside="true"
            :status="stageDetail.update.status === 'done' ? 'success' : undefined"
            class="stage-progress"
          />
          <div class="stage-msg" v-if="stageDetail.update.message">{{ stageDetail.update.message }}</div>
          <div class="update-stats" v-if="stageDetail.update.status === 'running' || stageDetail.update.status === 'done'">
            <span>扫描: {{ stageDetail.update.scanTotal ? `${stageDetail.update.checked}/${stageDetail.update.scanTotal}` : '-' }}</span>
            <span>待更新: {{ stageDetail.update.toUpdate }}</span>
            <span>已最新: {{ stageDetail.update.upToDate }}</span>
            <span>已执行: {{ stageDetail.update.toUpdate ? `${stageDetail.update.completed}/${stageDetail.update.toUpdate}` : '-' }}</span>
            <span>成功: {{ stageDetail.update.updated }}</span>
            <span>失败: {{ stageDetail.update.failed }}</span>
            <span v-if="stageDetail.update.remaining > 0">剩余: {{ stageDetail.update.remaining }}</span>
            <span v-if="stageDetail.update.verifyTotal">验证: {{ stageDetail.update.verifyReached }}/{{ stageDetail.update.verifyTotal }}</span>
            <span v-if="stageDetail.update.currentCode">当前代码: {{ stageDetail.update.currentCode }}</span>
            <span v-if="stageDetail.update.cacheHit">缓存命中</span>
            <span v-else-if="stageDetail.update.cacheWritten">缓存已写入</span>
          </div>
        </div>

        <div class="stage-row">
          <div class="stage-header">
            <el-icon v-if="stageDetail.rebuild.status === 'done'" color="#67c23a"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a448 448 0 1 1 0 896 448 448 0 0 1 0-896zm-55.808 536.384-99.52-99.584a38.4 38.4 0 1 0-54.336 54.336l126.72 126.72a38.272 38.272 0 0 0 54.336 0l262.4-262.464a38.4 38.4 0 1 0-54.272-54.336L456.192 600.384z"/></svg></el-icon>
            <el-icon v-else-if="stageDetail.rebuild.status === 'running'" class="is-loading" color="#409eff"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a32 32 0 0 1 32 32v192a32 32 0 0 1-64 0V96a32 32 0 0 1 32-32zm0 640a32 32 0 0 1 32 32v192a32 32 0 1 1-64 0V736a32 32 0 0 1 32-32zm448-192a32 32 0 0 1-32 32H736a32 32 0 1 1 0-64h192a32 32 0 0 1 32 32zM288 512a32 32 0 0 1-32 32H64a32 32 0 0 1 0-64h192a32 32 0 0 1 32 32z"/></svg></el-icon>
            <span v-else class="stage-pending-dot"></span>
            <span class="stage-label">阶段二：策略重建</span>
            <el-tag v-if="stageDetail.rebuild.status === 'done'" type="success" size="small">完成</el-tag>
            <el-tag v-else-if="stageDetail.rebuild.status === 'running'" type="primary" size="small">进行中</el-tag>
            <el-tag v-else type="info" size="small">等待</el-tag>
          </div>
          <el-progress
            v-if="stageDetail.rebuild.status !== 'pending'"
            :percentage="rebuildStageProgress"
            :stroke-width="10"
            :text-inside="true"
            :status="stageDetail.rebuild.status === 'done' ? 'success' : undefined"
            class="stage-progress"
          />
          <div class="stage-msg" v-if="stageDetail.rebuild.message">{{ stageDetail.rebuild.message }}</div>
          <div class="rebuild-stats" v-if="stageDetail.rebuild.status === 'running' || stageDetail.rebuild.status === 'done'">
            <span>扫描: {{ stageDetail.rebuild.processed }}/{{ stageDetail.rebuild.total }}</span>
            <span>命中: {{ stageDetail.rebuild.matched }}</span>
            <span v-if="stageDetail.rebuild.currentStrategy">当前策略: {{ stageDetail.rebuild.currentStrategy }}</span>
          </div>
          <!-- 各策略进展 -->
          <div class="strategy-chips" v-if="rebuildStrategies.length">
            <el-tag
              v-for="s in rebuildStrategies" :key="s.filter"
              :type="s.status === 'done' ? 'success' : 'primary'"
              size="small"
              class="strategy-chip"
            >
              {{ s.name }} {{ s.status === 'done' ? `✓ ${s.total}条` : '扫描中...' }}
            </el-tag>
          </div>
        </div>
      </div>

      <!-- 实时命中（重建阶段） -->
      <div class="live-area" v-if="liveSignals.length">
        <h4>实时命中 ({{ liveSignals.length }})</h4>
        <div class="signal-grid">
          <div v-for="(item, i) in liveSignals" :key="i" class="signal-row">
            <span class="s-code">{{ item.code }}</span>
            <span class="s-name">{{ item.name }}</span>
            <span class="s-strategy">{{ item.strategy_name }}</span>
            <span class="s-date">{{ item.date || '-' }}</span>
          </div>
        </div>
      </div>

      <!-- 日志 -->
      <div class="log-area">
        <div v-for="(line, i) in logLines" :key="i" class="log-line">{{ line }}</div>
      </div>
    </div>

    <!-- 完成提示 -->
    <div class="complete-card" v-if="jobCompleted">
      <el-result
        icon="success"
        :title="jobResult?.message || '作业完成'"
        :sub-title="`共命中 ${jobResult?.total_results ?? 0} 条结果`"
      >
        <template #extra>
          <el-button type="primary" @click="goToResults">查看策略结果</el-button>
        </template>
      </el-result>
    </div>
  </div>
</template>

<style scoped>
.update-view {
  padding: 20px;
  max-width: 1000px;
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
  color: var(--el-text-color-secondary);
}
.board-date {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin: 4px 0;
}
.board-fresh {
  margin-top: 8px;
}
.date-action-card {
  margin-bottom: 18px;
  padding: 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  background: var(--el-fill-color-blank);
}
.date-action-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.section-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}
.section-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.selected-date-tip {
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-color-primary);
}
.update-action {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}
.progress-area {
  margin-top: 16px;
}
.stage-indicator {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.run-id {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: monospace;
}
.progress-msg {
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.live-area {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: rgba(245, 250, 255, 0.7);
}
.live-area h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.signal-grid {
  max-height: 200px;
  overflow-y: auto;
}
.signal-row {
  display: grid;
  grid-template-columns: 80px 100px 140px 100px;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
  font-size: 12px;
}
.s-code { color: var(--el-color-primary); }
.s-strategy, .s-date { color: var(--el-text-color-secondary); }
.log-area {
  margin-top: 12px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  padding: 12px;
  max-height: 300px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
}
.log-line {
  line-height: 1.6;
}
.complete-card {
  margin-top: 20px;
  padding: 20px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
}

/* 分阶段进展 */
.stage-details {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.stage-row {
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}
.stage-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 14px;
}
.stage-label {
  font-weight: 600;
}
.stage-pending-dot {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--el-border-color-light);
}
.stage-progress {
  margin-bottom: 4px;
}
.stage-msg {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.update-stats,
.rebuild-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 6px;
}
.update-stats span,
.rebuild-stats span {
  white-space: nowrap;
}
.strategy-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.strategy-chip {
  font-size: 12px;
}
</style>
