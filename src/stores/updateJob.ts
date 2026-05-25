import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface StageState {
  status: 'pending' | 'running' | 'done' | 'error'
  progress: number
  message: string
}

export interface LiveSignal {
  code: string
  name: string
  strategy_name: string
  date?: string
  category?: string
}

type MarketCapStatus = 'idle' | 'cached' | 'refreshing' | 'done' | 'error'

export const useUpdateJobStore = defineStore('updateJob', () => {
  // ─── 整体作业状态 ───
  const isRunning = ref(false)
  const jobCompleted = ref(false)
  const jobError = ref<string | null>(null)
  const progress = ref(0)
  const progressMsg = ref('')
  const currentStage = ref<'update' | 'rebuild' | ''>('')
  const updatePhase = ref('')
  const runId = ref('')
  const tradeDate = ref('')
  const marketCapStatus = ref<MarketCapStatus>('idle')
  const marketCapCount = ref(0)
  const marketCapCachedCount = ref(0)
  const marketCapCacheAgeDays = ref<number | null>(null)
  const marketCapRefreshNeeded = ref(false)

  // ─── 阶段详情 ───
  const updateStage = ref<StageState>({ status: 'pending', progress: 0, message: '' })
  const rebuildStage = ref<StageState>({ status: 'pending', progress: 0, message: '' })

  // ─── 数据更新详细统计 ───
  const updateStats = ref({
    scanTotal: 0,
    checked: 0,
    toUpdate: 0,
    upToDate: 0,
    completed: 0,
    updated: 0,
    failed: 0,
    remaining: 0,
    currentCode: '',
    verifyTotal: 0,
    verifyReached: 0,
    cacheHit: false,
    cacheWritten: false,
    allowIntradayFast: false,
    precheckState: '',
    initTotal: 0,
    initSuccess: 0,
    initFailed: 0,
    fastPathTotal: 0,
    fastPathSuccess: 0,
    fastPathFailed: 0,
    shortPathTotal: 0,
    shortPathSuccess: 0,
    shortPathFailed: 0,
    slowPathTotal: 0,
    slowPathReasons: {
      time_gate: 0,
      missing_local_data: 0,
      gap_gt1: 0,
      short_gap_fallback: 0,
      missing_spot: 0,
      suspended: 0,
      other: 0,
    } as Record<string, number>,
  })

  // ─── 策略重建详细统计 ───
  const rebuildStats = ref({
    processed: 0,
    total: 0,
    matched: 0,
    currentCode: '',
    currentName: '',
  })
  const rebuildStrategyList = ref<{ name: string; filter: string; status: string; total: number }[]>([])

  // ─── 实时命中 ───
  const liveSignals = ref<LiveSignal[]>([])
  const totalMatched = ref(0)

  // ─── Banner 折叠状态（持久化） ───
  const bannerCollapsed = ref(localStorage.getItem('bannerCollapsed') === '1')
  function toggleBannerCollapse() {
    bannerCollapsed.value = !bannerCollapsed.value
    localStorage.setItem('bannerCollapsed', bannerCollapsed.value ? '1' : '0')
  }

  // ─── 派生状态 ───
  const statusLabel = computed(() => {
    if (!isRunning.value && !jobCompleted.value) return ''
    if (jobError.value) return `❌ ${jobError.value}`
    if (jobCompleted.value) return `✅ 完成，命中 ${totalMatched.value} 条`
    if (currentStage.value === 'rebuild') return `🔍 选股扫描中 ${rebuildStage.value.progress}%`
    if (currentStage.value === 'update') return `⬇️ 数据更新中 ${updateStage.value.progress}%`
    return `🔄 ${progressMsg.value || '处理中...'}`
  })

  // ─── 动作 ───
  function startJob() {
    isRunning.value = true
    jobCompleted.value = false
    jobError.value = null
    progress.value = 0
    progressMsg.value = ''
    currentStage.value = ''
    updatePhase.value = ''
    runId.value = ''
    tradeDate.value = ''
    marketCapStatus.value = 'idle'
    marketCapCount.value = 0
    marketCapCachedCount.value = 0
    marketCapCacheAgeDays.value = null
    marketCapRefreshNeeded.value = false
    liveSignals.value = []
    totalMatched.value = 0
    updateStage.value = { status: 'pending', progress: 0, message: '' }
    rebuildStage.value = { status: 'pending', progress: 0, message: '' }
    updateStats.value = {
      scanTotal: 0,
      checked: 0,
      toUpdate: 0,
      upToDate: 0,
      completed: 0,
      updated: 0,
      failed: 0,
      remaining: 0,
      currentCode: '',
      verifyTotal: 0,
      verifyReached: 0,
      cacheHit: false,
      cacheWritten: false,
      allowIntradayFast: false,
      precheckState: '',
      initTotal: 0,
      initSuccess: 0,
      initFailed: 0,
      fastPathTotal: 0,
      fastPathSuccess: 0,
      fastPathFailed: 0,
      shortPathTotal: 0,
      shortPathSuccess: 0,
      shortPathFailed: 0,
      slowPathTotal: 0,
      slowPathReasons: {
        time_gate: 0,
        missing_local_data: 0,
        gap_gt1: 0,
        short_gap_fallback: 0,
        missing_spot: 0,
        suspended: 0,
        other: 0,
      },
    }
    rebuildStats.value = { processed: 0, total: 0, matched: 0, currentCode: '', currentName: '' }
    rebuildStrategyList.value = []
  }

  function handleEvent(eventName: string, data: any) {
    if (data.run_id) runId.value = data.run_id
    if (data.stage) currentStage.value = data.stage
    if (data.stage === 'update' && typeof data.phase === 'string') updatePhase.value = data.phase
    if (typeof data.progress === 'number') progress.value = data.progress
    if (data.message) progressMsg.value = data.message

    // 数据更新阶段
    if (eventName === 'update_start') {
      updateStage.value.status = 'running'
      updateStage.value.progress = 0
    } else if (eventName === 'update_complete') {
      updateStage.value.status = 'done'
      updateStage.value.progress = 100
    } else if (data.stage === 'update' && typeof data.progress === 'number') {
      updateStage.value.status = 'running'
      updateStage.value.progress = Math.max(0, Math.min(100, Math.round(((data.progress - 5) / 35) * 100)))
    }
    if (data.stage === 'update' && data.message) updateStage.value.message = data.message

    // 数据更新详细统计
    if (data.stage === 'update' || eventName === 'update_start' || eventName === 'update_progress' || eventName === 'update_complete') {
      if (typeof data.scan_total === 'number') updateStats.value.scanTotal = data.scan_total
      if (typeof data.checked === 'number') updateStats.value.checked = data.checked
      if (typeof data.to_update === 'number') updateStats.value.toUpdate = data.to_update
      if (typeof data.up_to_date === 'number') updateStats.value.upToDate = data.up_to_date
      if (typeof data.completed === 'number') updateStats.value.completed = data.completed
      if (typeof data.updated === 'number') updateStats.value.updated = data.updated
      if (typeof data.failed === 'number') updateStats.value.failed = data.failed
      if (typeof data.remaining === 'number') updateStats.value.remaining = data.remaining
      if (typeof data.current_code === 'string') updateStats.value.currentCode = data.current_code
      if (typeof data.verify_total === 'number') updateStats.value.verifyTotal = data.verify_total
      if (typeof data.verify_reached === 'number') updateStats.value.verifyReached = data.verify_reached
      if (typeof data.cache_hit === 'boolean') updateStats.value.cacheHit = data.cache_hit
      if (typeof data.cache_written === 'boolean') updateStats.value.cacheWritten = data.cache_written
      if (typeof data.allow_intraday_fast === 'boolean') updateStats.value.allowIntradayFast = data.allow_intraday_fast
      if (typeof data.precheck_state === 'string') updateStats.value.precheckState = data.precheck_state
      if (typeof data.init_total === 'number') updateStats.value.initTotal = data.init_total
      if (typeof data.init_success === 'number') updateStats.value.initSuccess = data.init_success
      if (typeof data.init_failed === 'number') updateStats.value.initFailed = data.init_failed
      if (typeof data.fast_path_total === 'number') updateStats.value.fastPathTotal = data.fast_path_total
      if (typeof data.fast_path_success === 'number') updateStats.value.fastPathSuccess = data.fast_path_success
      if (typeof data.fast_path_failed === 'number') updateStats.value.fastPathFailed = data.fast_path_failed
      if (typeof data.short_path_total === 'number') updateStats.value.shortPathTotal = data.short_path_total
      if (typeof data.short_path_success === 'number') updateStats.value.shortPathSuccess = data.short_path_success
      if (typeof data.short_path_failed === 'number') updateStats.value.shortPathFailed = data.short_path_failed
      if (typeof data.slow_path_total === 'number') updateStats.value.slowPathTotal = data.slow_path_total
      if (data.slow_path_reasons && typeof data.slow_path_reasons === 'object') {
        updateStats.value.slowPathReasons = {
          ...updateStats.value.slowPathReasons,
          ...data.slow_path_reasons,
        }
      }
      if (typeof data.market_cap_refresh_needed === 'boolean') marketCapRefreshNeeded.value = data.market_cap_refresh_needed
      if (typeof data.market_cap_count === 'number') marketCapCount.value = data.market_cap_count
      if (typeof data.market_cap_cached_count === 'number') marketCapCachedCount.value = data.market_cap_cached_count
      if (typeof data.market_cap_cache_age_days === 'number') marketCapCacheAgeDays.value = data.market_cap_cache_age_days

      if (data.phase === 'market_cap_cached') {
        marketCapStatus.value = 'cached'
      } else if (data.phase === 'market_cap_refresh' || data.phase === 'market_cap_wait') {
        marketCapStatus.value = 'refreshing'
      } else if (data.phase === 'market_cap_complete') {
        marketCapStatus.value = 'done'
      }
    }

    // 策略重建阶段
    if (eventName === 'rebuild_start') {
      rebuildStage.value.status = 'running'
      rebuildStage.value.progress = 0
    } else if (data.stage === 'rebuild' && typeof data.progress === 'number') {
      rebuildStage.value.status = 'running'
      rebuildStage.value.progress = Math.min(100, Math.round(((data.progress - 42) / 56) * 100))
    }
    if (data.stage === 'rebuild' && data.message) rebuildStage.value.message = data.message

    // 策略重建详细统计
    if (data.stage === 'rebuild' || eventName === 'rebuild_start' || eventName === 'strategy_start' || eventName === 'strategy_complete') {
      if (typeof data.processed === 'number') rebuildStats.value.processed = data.processed
      if (typeof data.total === 'number') rebuildStats.value.total = data.total
      if (typeof data.matched === 'number') rebuildStats.value.matched = data.matched
      if (typeof data.current_code === 'string' && data.current_code) rebuildStats.value.currentCode = data.current_code
      if (typeof data.current_name === 'string' && data.current_name) rebuildStats.value.currentName = data.current_name
    }

    // 策略列表跟踪
    if (eventName === 'strategy_start' && data.strategy_name) {
      const existing = rebuildStrategyList.value.find((s: any) => s.filter === data.strategy_filter)
      if (!existing) {
        rebuildStrategyList.value.push({ name: data.strategy_name, filter: data.strategy_filter, status: 'running', total: 0 })
      } else {
        existing.status = 'running'
      }
    }
    if (eventName === 'strategy_complete' && data.strategy_name) {
      const existing = rebuildStrategyList.value.find((s: any) => s.filter === data.strategy_filter)
      if (existing) {
        existing.status = 'done'
        existing.total = data.group_total || 0
      }
    }

    // 实时命中信号
    if (eventName === 'signal' && data.items) {
      for (const item of data.items) {
        const idx = liveSignals.value.findIndex(
          s => s.code === item.code && s.strategy_name === item.strategy_name
        )
        if (idx === -1) liveSignals.value.unshift(item)
        else liveSignals.value.splice(idx, 1, item)
      }
      if (liveSignals.value.length > 50) liveSignals.value = liveSignals.value.slice(0, 50)
    }

    if (data.status === 'done') {
      if (rebuildStage.value.status === 'running') {
        rebuildStage.value.status = 'done'
        rebuildStage.value.progress = 100
      }
      totalMatched.value = data.total_results ?? liveSignals.value.length
      tradeDate.value = data.trade_date || ''
      isRunning.value = false
      jobCompleted.value = true
    }
    const isTerminalError = eventName === 'error' || data.status === 'error' || data.status === 'busy' || data.status === 'partial'
    if (isTerminalError) {
      jobError.value = data.message || '作业失败'
      isRunning.value = false
      if (currentStage.value === 'rebuild' || rebuildStage.value.status === 'running') {
        rebuildStage.value.status = 'error'
        rebuildStage.value.progress = Math.max(rebuildStage.value.progress, 100)
        rebuildStage.value.message = data.message || rebuildStage.value.message
      } else if (currentStage.value === 'update' || updateStage.value.status === 'running') {
        updateStage.value.status = 'error'
        updateStage.value.progress = Math.max(updateStage.value.progress, 100)
        updateStage.value.message = data.message || updateStage.value.message
      }
    }
  }

  function reset() {
    isRunning.value = false
    jobCompleted.value = false
    jobError.value = null
    progress.value = 0
    progressMsg.value = ''
    currentStage.value = ''
    updatePhase.value = ''
    marketCapStatus.value = 'idle'
    marketCapCount.value = 0
    marketCapCachedCount.value = 0
    marketCapCacheAgeDays.value = null
    marketCapRefreshNeeded.value = false
    liveSignals.value = []
    totalMatched.value = 0
    updateStage.value = { status: 'pending', progress: 0, message: '' }
    rebuildStage.value = { status: 'pending', progress: 0, message: '' }
    updateStats.value = {
      scanTotal: 0,
      checked: 0,
      toUpdate: 0,
      upToDate: 0,
      completed: 0,
      updated: 0,
      failed: 0,
      remaining: 0,
      currentCode: '',
      verifyTotal: 0,
      verifyReached: 0,
      cacheHit: false,
      cacheWritten: false,
      allowIntradayFast: false,
      precheckState: '',
      initTotal: 0,
      initSuccess: 0,
      initFailed: 0,
      fastPathTotal: 0,
      fastPathSuccess: 0,
      fastPathFailed: 0,
      shortPathTotal: 0,
      shortPathSuccess: 0,
      shortPathFailed: 0,
      slowPathTotal: 0,
      slowPathReasons: {
        time_gate: 0,
        missing_local_data: 0,
        gap_gt1: 0,
        short_gap_fallback: 0,
        missing_spot: 0,
        suspended: 0,
        other: 0,
      },
    }
    rebuildStats.value = { processed: 0, total: 0, matched: 0, currentCode: '', currentName: '' }
    rebuildStrategyList.value = []
  }

  return {
    isRunning, jobCompleted, jobError,
    progress, progressMsg, currentStage, updatePhase, runId, tradeDate,
    updateStage, rebuildStage,
    updateStats, rebuildStats, rebuildStrategyList,
    marketCapStatus, marketCapCount, marketCapCachedCount, marketCapCacheAgeDays, marketCapRefreshNeeded,
    liveSignals, totalMatched,
    bannerCollapsed, toggleBannerCollapse,
    statusLabel,
    startJob, handleEvent, reset,
  }
})
