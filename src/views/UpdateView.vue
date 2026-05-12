<script setup lang="ts">
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getDataStatus, getInitStatus, getMarketCap } from '@/api'
import { ElMessage } from 'element-plus'
import { useStrategyListStore } from '@/stores/strategyList'
import { useUpdateJobStore } from '@/stores/updateJob'

const router = useRouter()
const route = useRoute()
const strategyListStore = useStrategyListStore()
const updateJobStore = useUpdateJobStore()

interface BoardStatus {
  board: string
  count: number
  latest_date: string
  fresh: boolean
  stale_pct: number
}

const boards = ref<BoardStatus[]>([])
const loading = ref(true)
const selectedDate = ref<string>('')
const allowIntradayFast = ref(false)
const selectedStrategies = ref<string[]>(['b1', 'b2', 'bowl', 'brick'])
const strategyOptions = [
  { value: 'b1', label: 'B1（涨幅）' },
  { value: 'b2', label: 'B2（B1+1日内回踩）' },
  { value: 'bowl', label: '碗形' },
  { value: 'brick', label: '砖型图' },
]
const effectiveRunDateLabel = computed(() => selectedDate.value || '后端默认交易日')
const jobResult = ref<any>(null)
const logLines = ref<string[]>([])
const logAreaRef = ref<HTMLElement | null>(null)

const slowPathReasonText: Record<string, string> = {
  time_gate: '快路径门禁（目标日不是最近已完成交易日）',
  missing_local_data: '本地无历史数据',
  gap_gt1: '缺口大于1个交易日',
  missing_spot: '目标日快照缺失',
  suspended: '停牌或无成交',
  other: '其他原因',
}

const slowPathReasonEntries = computed(() => {
  const reasonMap = (updateJobStore.updateStats as any)?.slowPathReasons || {}
  return Object.entries(reasonMap)
    .map(([key, value]) => ({
      key,
      label: slowPathReasonText[key] || key,
      count: Number(value) || 0,
    }))
    .filter((item) => item.count > 0)
    .sort((a, b) => b.count - a.count)
})

const updateStageProgress = computed(() => updateJobStore.updateStage.progress)
const rebuildStageProgress = computed(() => updateJobStore.rebuildStage.progress)
const showMarketCapStatus = computed(() => updateJobStore.marketCapStatus !== 'idle')
const marketCapTagType = computed(() => {
  if (updateJobStore.marketCapStatus === 'done') return 'success'
  if (updateJobStore.marketCapStatus === 'cached') return 'info'
  if (updateJobStore.marketCapStatus === 'refreshing') return 'warning'
  return 'danger'
})
const marketCapTagText = computed(() => {
  if (updateJobStore.marketCapStatus === 'done') {
    return `市值已刷新 ${updateJobStore.marketCapCount} 只`
  }
  if (updateJobStore.marketCapStatus === 'cached') {
    const ageText = updateJobStore.marketCapCacheAgeDays == null ? '' : `（${updateJobStore.marketCapCacheAgeDays} 天前）`
    return `市值使用缓存基准${ageText}，本次不阻塞更新`
  }
  if (updateJobStore.marketCapStatus === 'refreshing') {
    if (updateJobStore.marketCapCachedCount > 0) {
      return `市值后台维护中，先使用缓存 ${updateJobStore.marketCapCachedCount} 只，不阻塞更新`
    }
    return '市值缓存初始化中，K线更新会继续推进'
  }
  return '市值刷新失败，继续使用缓存'
})

// 从 store 映射（供模板读取全局状态）
const updating = computed(() => updateJobStore.isRunning)
const liveSignals = computed(() => updateJobStore.liveSignals)

watch(
  () => logLines.value.length,
  async () => {
    await nextTick()
    const element = logAreaRef.value
    if (element) element.scrollTop = element.scrollHeight
  }
)

onMounted(async () => {
  if (route.query.init === '1') {
    ElMessage.info('检测到首次使用，更新任务会先执行全量初始化，再进入日更分流。')
  }
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
  try {
    const initRes = await getInitStatus()
    const initState = initRes?.data?.data?.state
    if (initState === 'empty') {
      ElMessage.info('本地暂无CSV数据，本次将自动先执行全量初始化（慢路径）再继续更新。')
    } else if (initState === 'stale') {
      ElMessage.warning('检测到数据明显过期，本次会优先快路径并自动对缺口执行慢路径补齐。')
    }
  } catch (e) {
    console.error('更新前状态检查失败，将继续执行更新', e)
  }

  // 初始化 store（全局共享状态）
  updateJobStore.startJob()
  logLines.value = []
  jobResult.value = null

  try {
    const params = new URLSearchParams({
      auto_rebuild: String(autoRebuild),
      pipeline: 'true',
      allow_intraday_fast: String(allowIntradayFast.value),
      init_if_empty: 'true',
    })
    if (selectedStrategies.value.length && selectedStrategies.value.length < strategyOptions.length) {
      params.set('strategies', selectedStrategies.value.join(','))
    }
    if (selectedDate.value) {
      params.set('date', selectedDate.value)
    }
    const response = await fetch(`/api/update?${params}`, { method: 'POST' })
    if (!response.body) {
      ElMessage.error('浏览器不支持流式读取')
      updateJobStore.reset()
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const consumeSseBlock = (block: string) => {
      const lines = block.split(/\r?\n/)
      const eventName = lines.find(l => l.startsWith('event:'))?.slice(6).trim() || 'message'
      const dataText = lines
        .filter(l => l.startsWith('data:'))
        .map(l => l.slice(5).trim())
        .join('\n')
      if (!dataText) return

      try {
        const data = JSON.parse(dataText)
        handleEvent(eventName, data)
      } catch {
        // 忽略非 JSON 数据行，避免中断后续事件消费
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        if (buffer.trim()) {
          consumeSseBlock(buffer)
        }
        break
      }

      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split(/\r?\n\r?\n/)
      buffer = chunks.pop() || ''

      for (const chunk of chunks) {
        consumeSseBlock(chunk)
      }
    }

    if (updateJobStore.isRunning) {
      ElMessage.warning('作业连接已结束，已停止本地运行状态，请刷新状态确认结果。')
      updateJobStore.reset()
    }
  } catch (e: any) {
    ElMessage.error('作业请求失败: ' + e.message)
    updateJobStore.reset()
  } finally {
    await loadStatus()
  }
}

function handleEvent(eventName: string, data: any) {
  // 同步到全局 store（用于跨页面进度显示）
  updateJobStore.handleEvent(eventName, data)

  // 本页面本地状态（日志、策略列表、市值等）
  if (data.message) {
    const stockSuffix = data.current_code
      ? ` [${data.current_code}${data.current_name ? ` ${data.current_name}` : ''}]`
      : ''
    logLines.value.push(`[${eventName}] ${data.message}${stockSuffix}`)
    if (logLines.value.length > 200) logLines.value.shift()
  }

  // 实时命中信号 — 同步到 strategyListStore（store 已在 updateJobStore.handleEvent 里维护 liveSignals）
  if (eventName === 'signal' && data.items) {
    for (const item of data.items) {
      strategyListStore.pushItem(item)
    }
  }

  // 市值后台刷新完成
  if (data.phase === 'market_cap_complete' && data.market_cap_count) {
    ElMessage({
      message: `市值已后台刷新：${data.market_cap_count} 只最新市值已写入缓存`,
      type: 'info',
      duration: 4000,
    })
    refreshLiveSignalMarketCap()
  }

  if (data.status === 'done') {
    jobResult.value = data
    ElMessage.success(data.message || '作业完成')
    loadStatus()
  }
  if (data.status === 'error') {
    ElMessage.error(data.message || '作业失败')
    loadStatus()
  }
}

function goToResults() {
  const targetDate = jobResult.value?.trade_date || selectedDate.value
  router.push({
    path: '/strategy-results',
    query: targetDate ? { date: targetDate } : undefined,
  })
}

async function refreshLiveSignalMarketCap() {
  const signals = updateJobStore.liveSignals
  if (!signals.length) return
  try {
    const codes = [...new Set(signals.map((s: any) => s.code))]
    const res = await getMarketCap(codes)
    const capMap: Record<string, number> = res.data?.data || {}
    // 直接通过 store 的 liveSignals 更新市值
    for (const s of updateJobStore.liveSignals) {
      if (capMap[s.code] !== undefined) {
        ;(s as any).market_cap = capMap[s.code]
      }
    }
  } catch { /* 刷新失败不影响主流程 */ }
}

function getStageLabel(stage: string) {
  if (stage === 'update') return '数据更新'
  if (stage === 'rebuild') return '策略重建'
  return stage
}

function getUpdatePhaseLabel(phase: string) {
  if (phase === 'precheck') return '更新前预检查'
  if (phase === 'init_full') return '首次全量初始化'
  if (phase === 'scan') return '状态检查'
  if (phase === 'scan_complete') return '检查完成'
  if (phase === 'market_cap_cached') return '市值缓存复用'
  if (phase === 'market_cap_refresh') return '市值后台维护'
  if (phase === 'fast_update') return '快路径更新'
  if (phase === 'update') return '慢路径更新'
  if (phase === 'verify') return '抽样验证'
  if (phase === 'market_cap_wait') return '兼容等待市值刷新'
  if (phase === 'market_cap_complete') return '市值刷新完成'
  if (phase === 'complete') return '更新完成'
  return phase
}
</script>

<template>
  <div class="update-view" v-loading="loading && !updateJobStore.isRunning">
    <h2>统一作业 - 数据更新 + 策略重建</h2>

    <!-- 作业进行中时的简洁提示条（替代空转圈） -->
    <el-alert
      v-if="updateJobStore.isRunning && !boards.length"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom:16px"
    >
      <template #title>
        作业正在后台运行中，板块状态将在完成后更新。进度见下方实时面板。
      </template>
    </el-alert>

    <!-- 板块状态卡片 -->
    <div class="board-cards" v-if="boards.length">
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

      <div class="intraday-fast-box">
        <el-checkbox v-model="allowIntradayFast" :disabled="updating">
          盘中也允许极速快路径
        </el-checkbox>
        <div class="intraday-fast-tip">
          15:00 后会自动用全市场快照补当天日线；盘中勾选才会把未收盘快照写入当日数据，历史缺口仍自动进入慢路径补齐。
        </div>
      </div>

      <div class="strategy-filter-box">
        <div class="strategy-filter-label">策略筛选（统一作业仅重建已勾选策略）</div>
        <el-checkbox-group v-model="selectedStrategies" :disabled="updating">
          <el-checkbox
            v-for="opt in strategyOptions"
            :key="opt.value"
            :label="opt.value"
          >{{ opt.label }}</el-checkbox>
        </el-checkbox-group>
        <div class="intraday-fast-tip">
          全选 = 跑全部（等价 all）；单选/多选 = 仅重建对应策略缓存，其余沿用已有结果。
        </div>
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
    <div class="progress-area" v-if="updateJobStore.isRunning || updateJobStore.progress > 0">
      <div class="stage-indicator" v-if="updateJobStore.currentStage">
        <el-tag :type="updateJobStore.currentStage === 'rebuild' ? 'success' : 'primary'" size="default">
          当前阶段: {{ getStageLabel(updateJobStore.currentStage) }}
        </el-tag>
        <span v-if="updateJobStore.runId" class="run-id">run_id: {{ updateJobStore.runId }}</span>
      </div>

      <el-progress :percentage="updateJobStore.progress" :stroke-width="18" :text-inside="true" />
      <div class="progress-msg">{{ updateJobStore.progressMsg }}</div>

      <!-- 分阶段详细进展 -->
      <div class="stage-details">

        <!-- ── 阶段一：数据更新 ── -->
        <div class="stage-row">
          <div class="stage-header">
            <el-icon v-if="updateJobStore.updateStage.status === 'done'" color="#67c23a"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a448 448 0 1 1 0 896 448 448 0 0 1 0-896zm-55.808 536.384-99.52-99.584a38.4 38.4 0 1 0-54.336 54.336l126.72 126.72a38.272 38.272 0 0 0 54.336 0l262.4-262.464a38.4 38.4 0 1 0-54.272-54.336L456.192 600.384z"/></svg></el-icon>
            <el-icon v-else-if="updateJobStore.updateStage.status === 'running'" class="is-loading" color="#409eff"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a32 32 0 0 1 32 32v192a32 32 0 0 1-64 0V96a32 32 0 0 1 32-32zm0 640a32 32 0 0 1 32 32v192a32 32 0 1 1-64 0V736a32 32 0 0 1 32-32zm448-192a32 32 0 0 1-32 32H736a32 32 0 1 1 0-64h192a32 32 0 0 1 32 32zM288 512a32 32 0 0 1-32 32H64a32 32 0 0 1 0-64h192a32 32 0 0 1 32 32z"/></svg></el-icon>
            <el-icon v-else-if="updateJobStore.isRunning && updateJobStore.rebuildStage.status === 'pending'" class="is-loading" color="#409eff"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a32 32 0 0 1 32 32v192a32 32 0 0 1-64 0V96a32 32 0 0 1 32-32zm0 640a32 32 0 0 1 32 32v192a32 32 0 1 1-64 0V736a32 32 0 0 1 32-32zm448-192a32 32 0 0 1-32 32H736a32 32 0 1 1 0-64h192a32 32 0 0 1 32 32zM288 512a32 32 0 0 1-32 32H64a32 32 0 0 1 0-64h192a32 32 0 0 1 32 32z"/></svg></el-icon>
            <span v-else class="stage-pending-dot"></span>
            <span class="stage-label">阶段一：数据更新</span>
            <el-tag v-if="updateJobStore.updateStage.status === 'done'" type="success" size="small">完成</el-tag>
            <el-tag v-else-if="updateJobStore.updateStage.status === 'running'" type="primary" size="small">进行中</el-tag>
            <el-tag v-else-if="updateJobStore.isRunning && updateJobStore.rebuildStage.status === 'pending'" type="primary" size="small">进行中</el-tag>
            <el-tag v-else type="info" size="small">等待</el-tag>
            <el-tag v-if="updateJobStore.updatePhase" type="info" size="small">
              {{ getUpdatePhaseLabel(updateJobStore.updatePhase) }}
            </el-tag>
          </div>

          <!-- 进度条：作业进行中就显示 -->
          <el-progress
            :percentage="updateStageProgress"
            :stroke-width="10"
            :text-inside="true"
            :status="updateJobStore.updateStage.status === 'done' ? 'success' : undefined"
            class="stage-progress"
          />

          <!-- 实时股票代码滚动 -->
          <div class="current-ticker" v-if="updateJobStore.updateStats?.currentCode">
            <span class="ticker-label">正在更新：</span>
            <span class="ticker-code">{{ updateJobStore.updateStats?.currentCode }}</span>
          </div>

          <!-- 统计数据：作业进行中就显示 -->
          <div class="update-stats">
            <span v-if="updateJobStore.updateStats?.scanTotal">
              检查：<b>{{ updateJobStore.updateStats?.checked }}/{{ updateJobStore.updateStats?.scanTotal }}</b>
            </span>
            <span v-else class="stat-muted">等待数据...</span>
            <template v-if="updateJobStore.updateStats?.scanTotal">
              <span>需更新：<b>{{ updateJobStore.updateStats?.toUpdate ?? 0 }}</b> 只</span>
              <span>已最新：<b>{{ updateJobStore.updateStats?.upToDate ?? 0 }}</b> 只</span>
              <span v-if="updateJobStore.updateStats?.toUpdate">
                执行：<b>{{ updateJobStore.updateStats?.completed }}/{{ updateJobStore.updateStats?.toUpdate }}</b>
              </span>
              <span>成功：<b class="stat-success">{{ updateJobStore.updateStats?.updated ?? 0 }}</b></span>
              <span v-if="(updateJobStore.updateStats?.failed ?? 0) > 0">失败：<b class="stat-fail">{{ updateJobStore.updateStats?.failed }}</b></span>
              <span v-if="(updateJobStore.updateStats?.remaining ?? 0) > 0">剩余：{{ updateJobStore.updateStats?.remaining }}</span>
              <span v-if="updateJobStore.updateStats?.cacheHit" class="stat-cache">✓ 缓存命中跳过</span>
              <span v-if="updateJobStore.updateStats?.initTotal > 0">
                初始化：<b>{{ updateJobStore.updateStats?.initSuccess }}/{{ updateJobStore.updateStats?.initTotal }}</b>
              </span>
              <span v-if="updateJobStore.updateStats?.fastPathTotal > 0">
                快路径：<b class="stat-success">{{ updateJobStore.updateStats?.fastPathSuccess }}/{{ updateJobStore.updateStats?.fastPathTotal }}</b>
              </span>
              <span v-if="updateJobStore.updateStats?.slowPathTotal > 0">
                慢路径：<b>{{ updateJobStore.updateStats?.slowPathTotal }}</b>
              </span>
            </template>
          </div>

          <div v-if="slowPathReasonEntries.length" class="slow-reason-list">
            <span class="reason-title">慢路径原因：</span>
            <el-tag
              v-for="reason in slowPathReasonEntries"
              :key="reason.key"
              type="warning"
              size="small"
              class="reason-tag"
            >
              {{ reason.label }} {{ reason.count }}
            </el-tag>
          </div>

          <div class="stage-msg" v-if="updateJobStore.updateStage.message">{{ updateJobStore.updateStage.message }}</div>

          <div v-if="showMarketCapStatus" class="market-cap-status">
            <el-tag :type="marketCapTagType" size="small" class="market-cap-tag">{{ marketCapTagText }}</el-tag>
          </div>
        </div>

        <!-- ── 阶段二：策略重建 ── -->
        <div class="stage-row">
          <div class="stage-header">
            <el-icon v-if="updateJobStore.rebuildStage.status === 'done'" color="#67c23a"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a448 448 0 1 1 0 896 448 448 0 0 1 0-896zm-55.808 536.384-99.52-99.584a38.4 38.4 0 1 0-54.336 54.336l126.72 126.72a38.272 38.272 0 0 0 54.336 0l262.4-262.464a38.4 38.4 0 1 0-54.272-54.336L456.192 600.384z"/></svg></el-icon>
            <el-icon v-else-if="updateJobStore.rebuildStage.status === 'running'" class="is-loading" color="#409eff"><svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64a32 32 0 0 1 32 32v192a32 32 0 0 1-64 0V96a32 32 0 0 1 32-32zm0 640a32 32 0 0 1 32 32v192a32 32 0 1 1-64 0V736a32 32 0 0 1 32-32zm448-192a32 32 0 0 1-32 32H736a32 32 0 1 1 0-64h192a32 32 0 0 1 32 32zM288 512a32 32 0 0 1-32 32H64a32 32 0 0 1 0-64h192a32 32 0 0 1 32 32z"/></svg></el-icon>
            <span v-else class="stage-pending-dot"></span>
            <span class="stage-label">阶段二：策略重建</span>
            <el-tag v-if="updateJobStore.rebuildStage.status === 'done'" type="success" size="small">完成</el-tag>
            <el-tag v-else-if="updateJobStore.rebuildStage.status === 'running'" type="primary" size="small">进行中</el-tag>
            <el-tag v-else type="info" size="small">等待</el-tag>
          </div>

          <!-- 进度条：作业进行中就显示 -->
          <el-progress
            :percentage="rebuildStageProgress"
            :stroke-width="10"
            :text-inside="true"
            :status="updateJobStore.rebuildStage.status === 'done' ? 'success' : undefined"
            class="stage-progress"
          />

          <!-- 实时股票代码滚动 -->
          <div class="current-ticker" v-if="updateJobStore.rebuildStats?.currentCode">
            <span class="ticker-label">最新扫描：</span>
            <span class="ticker-code">{{ updateJobStore.rebuildStats?.currentCode }}</span>
            <span class="ticker-name" v-if="updateJobStore.rebuildStats?.currentName">{{ updateJobStore.rebuildStats?.currentName }}</span>
          </div>

          <!-- 统计数据：作业进行中就显示 -->
          <div class="rebuild-stats">
            <span v-if="updateJobStore.rebuildStats?.total">
              扫描：<b>{{ updateJobStore.rebuildStats?.processed ?? 0 }}/{{ updateJobStore.rebuildStats?.total }}</b>
            </span>
            <span v-else class="stat-muted">等待阶段一完成...</span>
            <span v-if="updateJobStore.rebuildStats?.total">
              命中：<b class="stat-success">{{ updateJobStore.rebuildStats?.matched ?? 0 }}</b> 条
            </span>
          </div>

          <div class="stage-msg" v-if="updateJobStore.rebuildStage.message">{{ updateJobStore.rebuildStage.message }}</div>

          <div class="strategy-chips" v-if="updateJobStore.rebuildStrategyList?.length">
            <el-tag
              v-for="s in updateJobStore.rebuildStrategyList" :key="s.filter"
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
      <div ref="logAreaRef" class="log-area">
        <div v-for="(line, i) in logLines" :key="i" class="log-line">{{ line }}</div>
      </div>
    </div>

    <!-- 完成提示 -->
    <div class="complete-card" v-if="updateJobStore.jobCompleted">
      <el-result
        icon="success"
        :title="jobResult?.message || '作业完成'"
        :sub-title="`共命中 ${jobResult?.total_results ?? updateJobStore.totalMatched} 条结果`"
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
.intraday-fast-box {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}
.intraday-fast-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
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
.market-cap-status {
  margin-top: 8px;
}
.market-cap-tag {
  white-space: normal;
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
.slow-reason-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  align-items: center;
}
.reason-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.reason-tag {
  margin: 0;
}
.stat-success { color: var(--el-color-success); }
.stat-fail    { color: var(--el-color-danger); }
.stat-cache   { color: var(--el-color-warning); }
.stat-muted   { color: var(--el-text-color-placeholder); font-style: italic; }
/* 实时股票代码显示器 */
.current-ticker {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0 4px;
  padding: 6px 12px;
  background: var(--el-fill-color-light);
  border-left: 3px solid var(--el-color-primary);
  border-radius: 0 6px 6px 0;
  font-size: 14px;
}
.ticker-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}
.ticker-code {
  font-family: monospace;
  font-weight: 700;
  font-size: 15px;
  color: var(--el-color-primary);
  letter-spacing: 1px;
}
.ticker-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
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
