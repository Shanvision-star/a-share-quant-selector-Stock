<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import KlineChart from '@/components/KlineChart.vue'
import StockInfoPanel from '@/components/StockInfoPanel.vue'
import { getStockPrice, getStrategyResultsHistory, getStockInfo, prefetchKline, prefetchKlineBatch } from '@/api'
import { buildStrategyDayPrefetchCodes, getNeighborCodes } from '@/components/klineRequest'
import { useStrategyListStore } from '@/stores/strategyList'
import { useManualSelectionStore } from '@/stores/manualSelection'
import {
  buildStrategyGroups,
  fetchAllStrategyResultItems,
  formatSimilarityPercent,
} from '@/utils/strategyResults'
import {
  createStockDetailLoadGuard,
  getDisplayStockName,
  getStockSequenceState,
  isStockDetailPayloadCurrent,
  normalizeStockCode,
  shouldShowInitialStockDetailLoading,
  type StockDetailLoadTicket,
} from '@/views/stockDetailState'

const props = defineProps<{ code: string }>()
const router = useRouter()
const route = useRoute()
const strategyListStore = useStrategyListStore()
const manualSelectionStore = useManualSelectionStore()
const loadGuard = createStockDetailLoadGuard()
const KLINE_LIMIT_10Y = 2600
const KLINE_PREFETCH_LIMIT = 500
const KLINE_PREFETCH_RADIUS = 5
const KLINE_PREFETCH_DAY_LIMIT = 240

const period = ref('daily')
const adjust = ref<'qfq' | 'hfq' | 'nfq'>('qfq')
const priceInfo = ref<any>(null)
const stockInfo = ref<any>(null)
const stockInfoCode = ref('')
const signals = ref<any[]>([])
const strategyCard = ref<any>(null)
const loading = ref(false)
const switchingCode = ref('')
const hasLoadedInitialDetail = ref(false)
const safePriceInfo = computed(() =>
  isStockDetailPayloadCurrent(priceInfo.value, props.code) ? priceInfo.value : null,
)
const safeStockInfo = computed(() =>
  normalizeStockCode(stockInfoCode.value) === normalizeStockCode(props.code) ? stockInfo.value : null,
)
const safeStrategyCard = computed(() =>
  isStockDetailPayloadCurrent(strategyCard.value, props.code) ? strategyCard.value : null,
)
const showInitialLoading = computed(() =>
  shouldShowInitialStockDetailLoading(loading.value, hasLoadedInitialDetail.value),
)
const isSwitchingStock = computed(() =>
  loading.value
  && hasLoadedInitialDetail.value
  && normalizeStockCode(switchingCode.value) === normalizeStockCode(props.code),
)
const showShortTermTrend = ref(true)
const showBullBearLine = ref(true)

// ─── 面板折叠与宽度 ────────────────────────────────────────────────────
const leftCollapsed = ref(false)
const rightCollapsed = ref(false)
const leftWidth = ref(220)
const rightWidth = ref(220)
const MIN_PANEL = 140
const MAX_PANEL = 520

// ─── 拖拽调整宽度 ──────────────────────────────────────────────────────
let _resizeTarget: 'left' | 'right' | null = null
let _resizeStartX = 0
let _resizeStartWidth = 0

function startResize(e: MouseEvent, side: 'left' | 'right') {
  e.preventDefault()
  _resizeTarget = side
  _resizeStartX = e.clientX
  _resizeStartWidth = side === 'left' ? leftWidth.value : rightWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)
}

function onResize(e: MouseEvent) {
  if (!_resizeTarget) return
  const delta = _resizeTarget === 'left' ? e.clientX - _resizeStartX : _resizeStartX - e.clientX
  const w = Math.min(MAX_PANEL, Math.max(MIN_PANEL, _resizeStartWidth + delta))
  if (_resizeTarget === 'left') leftWidth.value = w
  else rightWidth.value = w
}

function stopResize() {
  _resizeTarget = null
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleStockNavigationKeydown)
  stopResize()
  stopCardResize()
})

// ─── 策略详情卡可调整高度 ──────────────────────────────────────────────
const strategyCardHeight = ref(160)
const MIN_CARD_H = 60
const MAX_CARD_H = 480
let _cardResizeStartY = 0
let _cardResizeStartH = 0

function startCardResize(e: MouseEvent) {
  e.preventDefault()
  _cardResizeStartY = e.clientY
  _cardResizeStartH = strategyCardHeight.value
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onCardResize)
  document.addEventListener('mouseup', stopCardResize)
}
function onCardResize(e: MouseEvent) {
  const delta = _cardResizeStartY - e.clientY
  strategyCardHeight.value = Math.min(MAX_CARD_H, Math.max(MIN_CARD_H, _cardResizeStartH + delta))
}
function stopCardResize() {
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  document.removeEventListener('mousemove', onCardResize)
  document.removeEventListener('mouseup', stopCardResize)
}

// ─── 策略选股列表 ──────────────────────────────────────────────────────
const strategyListItems = computed(() => strategyListStore.items)
const currentStrategyItem = computed(() => strategyListItems.value.find(item => item.code === props.code))
const displayStockName = computed(() => getDisplayStockName(safePriceInfo.value, props.code, currentStrategyItem.value?.name || ''))
const strategyGroups = computed(() => buildStrategyGroups(strategyListItems.value))
const sidebarSignalCount = computed(() => strategyListItems.value.length)
const sidebarUniqueCount = computed(() => new Set(strategyListItems.value.map(item => item.code)).size)
const stockNavigation = computed(() => getStockSequenceState(strategyListItems.value, props.code))
const stockNavigationIndexText = computed(() => {
  if (stockNavigation.value.currentIndex < 0 || stockNavigation.value.total <= 0) return '0/0'
  return `${stockNavigation.value.currentIndex + 1}/${stockNavigation.value.total}`
})
// strategyListDate was superseded by sidebarSelectedDate (date picker)
const sidebarSelectedDate = computed({
  get: () => strategyListStore.selectedDate,
  set: (val: string) => { void selectSidebarDate(val) },
})
const sidebarAvailableDates = computed(() => strategyListStore.availableDates)
const sidebarLoadingList = computed(() => strategyListStore.isLoadingList)

function goToStockFromList(targetCode: string) {
  prefetchKlineCode(targetCode)
  prefetchAroundCode(targetCode)
  router.push(`/stocks/${targetCode}`)
}

function navigateStockSequence(direction: 'prev' | 'next') {
  const targetCode = direction === 'prev'
    ? stockNavigation.value.prevCode
    : stockNavigation.value.nextCode
  if (!targetCode) return
  goToStockFromList(targetCode)
}

function shouldIgnoreStockNavigationShortcut(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null
  const tag = target?.tagName?.toLowerCase()
  return !!(
    event.altKey
    || event.ctrlKey
    || event.metaKey
    || event.shiftKey
    || tag === 'input'
    || tag === 'textarea'
    || tag === 'select'
    || target?.isContentEditable
    || target?.closest('.el-select, .el-date-editor, .el-input, .el-textarea, .intraday-popup')
  )
}

function handleStockNavigationKeydown(event: KeyboardEvent) {
  if (shouldIgnoreStockNavigationShortcut(event)) return
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    navigateStockSequence('prev')
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    navigateStockSequence('next')
  }
}

function prefetchKlineCode(targetCode: string) {
  if (!targetCode) return
  void prefetchKline(targetCode, {
    period: period.value,
    limit: KLINE_PREFETCH_LIMIT,
    adjust: adjust.value,
  })
}

function scheduleKlinePrefetch(codes: string[], priority: 'normal' | 'high' = 'normal') {
  const targets = Array
    .from(new Set(codes.filter(code => code && code !== props.code)))
    .slice(0, priority === 'high' ? KLINE_PREFETCH_RADIUS * 2 : KLINE_PREFETCH_DAY_LIMIT)

  if (!targets.length) return

  const run = () => {
    prefetchKlineBatch(
      targets,
      {
        period: period.value,
        limit: KLINE_PREFETCH_LIMIT,
        adjust: adjust.value,
      },
      { priority },
    )
  }

  if (priority === 'high' || typeof window === 'undefined') {
    run()
    return
  }

  const requestIdleCallback = (window as any).requestIdleCallback
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(run, { timeout: 350 })
  } else {
    window.setTimeout(run, 50)
  }
}

function prefetchAroundCode(centerCode: string) {
  const codes = strategyListItems.value.map(item => item.code)
  scheduleKlinePrefetch(getNeighborCodes(codes, centerCode, KLINE_PREFETCH_RADIUS), 'high')
}

function prefetchStrategyDayKlines() {
  const codes = buildStrategyDayPrefetchCodes(
    strategyListItems.value.map(item => item.code),
    props.code,
    KLINE_PREFETCH_DAY_LIMIT,
  )
  scheduleKlinePrefetch(codes)
}

function prefetchStrategyItem(item: { code?: string }) {
  if (item?.code) {
    prefetchKlineCode(item.code)
    prefetchAroundCode(item.code)
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleStockNavigationKeydown)
  loadAll(props.code)
  void initStrategySidebar()
})

async function initStrategySidebar() {
  // 加载可用交易日列表（供右侧日期选择器使用）
  await strategyListStore.fetchAvailableDates(30)
  // 若 route 带有 date 参数，优先按该日期加载侧栏列表；否则加载最新有结果日期
  const routeDate = route.query.date as string | undefined
  if (routeDate) {
    await selectSidebarDate(routeDate)
  } else if (strategyListStore.selectedDate) {
    await selectSidebarDate(strategyListStore.selectedDate)
  } else if (!strategyListStore.items.length) {
    await loadDefaultStrategyList()
    if (strategyListStore.selectedDate) {
      await manualSelectionStore.fetchByDate(strategyListStore.selectedDate)
    }
  }
}

async function selectSidebarDate(date: string) {
  await strategyListStore.fetchListByDate(date)
  await manualSelectionStore.fetchByDate(date)
}

async function toggleManualSelection(item: any, checked: boolean) {
  const selectionDate = strategyListStore.selectedDate || item.trade_date || item.signal_date
  if (!selectionDate) {
    ElMessage.warning('请先选择日期')
    return
  }
  try {
    if (checked) {
      await manualSelectionStore.add({
        selection_date: selectionDate,
        code: item.code,
        name: item.name || '',
        strategy_name: item.strategy_name || '',
        source_trade_date: item.trade_date || selectionDate,
        source_signal_date: item.signal_date || item.trade_date || selectionDate,
        source_payload: item,
      })
      ElMessage.success(`${item.code} 已加入人工选股池`)
    } else {
      await manualSelectionStore.remove(selectionDate, item.code)
      ElMessage.success(`${item.code} 已移出人工选股池`)
    }
  } catch (error) {
    console.error('人工选股保存失败', error)
    ElMessage.error('人工选股保存失败')
  }
}

watch(() => props.code, (newCode) => {
  loadAll(newCode)
})

watch(
  () => [
    strategyListItems.value.map(item => item.code).join(','),
    props.code,
    period.value,
    adjust.value,
  ],
  () => {
    prefetchStrategyDayKlines()
    prefetchAroundCode(props.code)
  },
  { flush: 'post' },
)

// 个股扩展信息客户端缓存（行业/地区/经营范围/概念标签，同一股票只请求一次）
const _stockInfoCache = new Map<string, any>()

async function loadAll(code: string) {
  const ticket = loadGuard.start(code)
  loading.value = true
  switchingCode.value = code
  if (!hasLoadedInitialDetail.value) {
    priceInfo.value = null
    stockInfo.value = null
    stockInfoCode.value = ''
    strategyCard.value = null
  }
  signals.value = []
  try {
    const [pRes] = await Promise.all([
      getStockPrice(code),
      loadSignals(code, ticket),
    ])
    if (!loadGuard.isCurrent(ticket, props.code)) return
    priceInfo.value = pRes.data.data
    hasLoadedInitialDetail.value = true
  } catch (e) {
    if (loadGuard.isCurrent(ticket, props.code)) {
      console.error('加载失败', e)
    }
  } finally {
    if (loadGuard.isCurrent(ticket, props.code)) {
      loading.value = false
      switchingCode.value = ''
    }
  }
  // 懒加载扩展信息（行业/地区/经营范围/概念标签）——有客户端缓存，同一股票只请求一次
  if (_stockInfoCache.has(code)) {
    if (!loadGuard.isCurrent(ticket, props.code)) return
    stockInfoCode.value = code
    stockInfo.value = _stockInfoCache.get(code)
  } else {
    getStockInfo(code).then(res => {
      if (!loadGuard.isCurrent(ticket, props.code)) return
      const data = res.data.data
      _stockInfoCache.set(code, data)
      stockInfoCode.value = code
      stockInfo.value = data
    }).catch((err) => {
      if (!loadGuard.isCurrent(ticket, props.code)) return
      console.warn('扩展信息加载失败', err)
      const fallback = { industry: '', region: '', main_business: '', concept_tags: [] }
      _stockInfoCache.set(code, fallback)
      stockInfoCode.value = code
      stockInfo.value = fallback
    })
  }
}

/** 当 store 为空时（例如从首页或直接导航），自动拉取最新策略结果填右侧列表 */
async function loadDefaultStrategyList() {
  try {
    const items = await fetchAllStrategyResultItems(
      async (params) => {
        const res = await getStrategyResultsHistory(params as any)
        return res.data.data || {}
      },
      {
        strategy: 'all',
        sort_by: 'run_started_at',
        sort_order: 'desc',
      },
      { pageSize: 200 },
    )
    if (items.length) {
      strategyListStore.setList(items as any[], 'all', items[0]?.signal_date || items[0]?.trade_date || '')
    }
  } catch (e) {
    console.error('自动加载策略列表失败', e)
  }
}

async function loadSignals(code: string, ticket?: StockDetailLoadTicket) {
  try {
    const response = await getStrategyResultsHistory({
      strategy: 'all',
      code,
      per_page: 200,
      sort_by: 'signal_date',
      sort_order: 'desc',
    })
    const allResults = response.data.data?.items || []

    const matched = allResults.filter((row: any) => row.code === code)
    if (ticket && !loadGuard.isCurrent(ticket, props.code)) return
    strategyCard.value = matched[0] || null
    signals.value = matched.map((item: any) => ({
      date: item.signal_date || item.trade_date,
      close: item.trigger_price || item.close,
      category: item.category || item.strategy_name,
      label:
        item.strategy_name === 'B1CaseStrategy'
          ? 'B1'
          : item.strategy_name === 'BowlReboundStrategy'
            ? '碗'
            : 'B2',
    }))
  } catch (e) {
    if (!ticket || loadGuard.isCurrent(ticket, props.code)) {
      console.error('加载策略信号失败', e)
      strategyCard.value = null
      signals.value = []
    }
  }
}

function onPeriodChange(nextPeriod: string) {
  period.value = nextPeriod
}

function formatListSimilarity(score: unknown): string {
  return formatSimilarityPercent(score)
}
</script>

<template>
  <div class="stock-detail" v-loading="showInitialLoading">
    <!-- ══ 左侧：个股信息面板 ═══════════════════════════════════════════ -->
    <div
      class="panel-aside panel-left"
      :class="{ 'panel-collapsed': leftCollapsed }"
      :style="leftCollapsed ? {} : { width: leftWidth + 'px' }"
    >
      <StockInfoPanel :price-info="safePriceInfo" :stock-info="safeStockInfo" side="left" />
    </div>

    <!-- 左侧：分隔条（拖拽 + 折叠） -->
    <div class="panel-edge panel-edge-left">
      <div
        v-show="!leftCollapsed"
        class="resize-handle"
        title="拖拽调整宽度"
        @mousedown.prevent="startResize($event, 'left')"
      ></div>
      <button
        class="collapse-btn"
        :title="leftCollapsed ? '展开左侧面板' : '收起左侧面板'"
        @click="leftCollapsed = !leftCollapsed"
      >{{ leftCollapsed ? '▶' : '◀' }}</button>
    </div>

    <!-- ══ 中间：K线 + 策略详情 ════════════════════════════════════════ -->
    <div class="detail-main">
      <div class="detail-header">
        <h2>{{ displayStockName || '加载中' }} {{ code }}</h2>
        <div class="detail-actions">
          <span v-if="isSwitchingStock" class="switching-hint">切换中 {{ code }}</span>
          <el-checkbox v-model="showShortTermTrend">短期趋势线</el-checkbox>
          <el-checkbox v-model="showBullBearLine">知行多空线</el-checkbox>
          <div v-if="stockNavigation.total > 1" class="stock-nav-control" title="可用键盘 ↑ / ↓ 顺序切换">
            <el-button-group>
              <el-button
                size="small"
                :icon="ArrowUp"
                :disabled="!stockNavigation.prevCode"
                title="上一只（↑）"
                @click="navigateStockSequence('prev')"
              />
              <el-button
                size="small"
                :icon="ArrowDown"
                :disabled="!stockNavigation.nextCode"
                title="下一只（↓）"
                @click="navigateStockSequence('next')"
              />
            </el-button-group>
            <span class="stock-nav-index">{{ stockNavigationIndexText }}</span>
          </div>
          <el-radio-group v-model="period" size="small" @change="onPeriodChange">
            <el-radio-button value="daily">日K</el-radio-button>
            <el-radio-button value="weekly">周K</el-radio-button>
          </el-radio-group>
          <el-radio-group v-model="adjust" size="small">
            <el-radio-button value="qfq">前复权</el-radio-button>
            <el-radio-button value="hfq">后复权</el-radio-button>
            <el-radio-button value="nfq">不复权</el-radio-button>
          </el-radio-group>
          <span v-if="adjust !== 'qfq'" style="font-size:11px;color:#909399">策略信号仅在前复权图上显示</span>
        </div>
      </div>

      <div class="chart-area">
        <KlineChart
          :code="code"
          :period="period"
          :limit="KLINE_LIMIT_10Y"
          :adjust="adjust"
          :signals="adjust === 'qfq' ? signals : []"
          :show-short-term-trend="showShortTermTrend"
          :show-bull-bear-line="showBullBearLine"
        />
      </div>

      <!-- 策略匹配详情拖拽调整把手 -->
      <div
        v-if="safeStrategyCard"
        class="card-resize-handle"
        title="拖拽调整策略详情区高度"
        @mousedown.prevent="startCardResize"
      ></div>

      <div class="strategy-card" v-if="safeStrategyCard" :style="{ height: strategyCardHeight + 'px' }">
        <el-card shadow="never">
          <template #header>策略匹配详情</template>
          <p><strong>策略:</strong> {{ safeStrategyCard.strategy_name }}</p>
          <p><strong>分类:</strong> {{ safeStrategyCard.category }}</p>
          <p><strong>匹配日期:</strong> {{ safeStrategyCard.signal_date || safeStrategyCard.trade_date }}</p>
          <p v-if="safeStrategyCard.reason"><strong>原因:</strong> {{ safeStrategyCard.reason }}</p>
        </el-card>
      </div>
    </div>

    <!-- 右侧：分隔条（折叠 + 拖拽） -->
    <div class="panel-edge panel-edge-right">
      <button
        class="collapse-btn"
        :title="rightCollapsed ? '展开右侧面板' : '收起右侧面板'"
        @click="rightCollapsed = !rightCollapsed"
      >{{ rightCollapsed ? '◀' : '▶' }}</button>
      <div
        v-show="!rightCollapsed"
        class="resize-handle"
        title="拖拽调整宽度"
        @mousedown.prevent="startResize($event, 'right')"
      ></div>
    </div>

    <!-- ══ 右侧：策略选股列表 ══════════════════════════════════════════ -->
    <div
      class="panel-aside panel-right"
      :class="{ 'panel-collapsed': rightCollapsed }"
      :style="rightCollapsed ? {} : { width: rightWidth + 'px' }"
    >
      <div class="slp-header">
        <span class="slp-title">策略选股列表</span>
        <el-select
          v-model="sidebarSelectedDate"
          placeholder="选择日期"
          size="small"
          class="slp-date-select"
          :loading="strategyListStore.isLoadingDates"
        >
          <el-option
            v-for="d in sidebarAvailableDates"
            :key="d"
            :label="d"
            :value="d"
          />
        </el-select>
        <span class="slp-count" v-if="!sidebarLoadingList">
          {{ sidebarUniqueCount }} 只 / {{ sidebarSignalCount }} 条
        </span>
      </div>
      <div class="slp-scroll" v-if="!sidebarLoadingList && strategyGroups.length">
        <div v-for="group in strategyGroups" :key="group.key" class="slp-group">
          <div class="slp-group-head">
            <span>{{ group.label }}</span>
            <em>{{ group.uniqueCount }} 只 / {{ group.signalCount }} 条</em>
          </div>
          <div
            v-for="item in group.items"
            :key="`${group.key}-${item.code}`"
            class="slp-item"
            :class="{ active: item.code === code }"
            @mouseenter="prefetchStrategyItem(item)"
            @click="goToStockFromList(item.code)"
          >
            <el-checkbox
              class="slp-check"
              :model-value="manualSelectionStore.isSelected(item.code)"
              :disabled="manualSelectionStore.savingCodes.has(item.code)"
              title="加入人工选股池"
              @click.stop
              @change="(checked: any) => toggleManualSelection(item, Boolean(checked))"
            />
            <span class="slp-code">{{ item.code }}</span>
            <span class="slp-name">{{ item.name }}</span>
            <span class="slp-sim">{{ formatListSimilarity(item.similarity_score) }}</span>
            <span class="slp-date">{{ item.signal_date || item.trade_date }}</span>
          </div>
        </div>
      </div>
      <div class="slp-empty" v-else-if="sidebarLoadingList">
        <span>加载中...</span>
      </div>
      <div class="slp-empty" v-else>
        <span>该日期无策略结果</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ─── 整体布局 ─────────────────────────────────────────────────────── */
.stock-detail {
  display: flex;
  height: 100%;
  overflow: hidden;
  background-color: #ffffff;
}

/* ─── 侧边面板通用 ─────────────────────────────────────────────────── */
.panel-aside {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.18s ease;
}
.panel-aside.panel-collapsed {
  width: 0 !important;
  transition: width 0.18s ease;
}
.panel-left {
  background-color: var(--bg-secondary, #f5f7fa);
  border-right: 1px solid var(--border-color, #ebeef5);
}
/* 允许 StockInfoPanel 内部宽度撑满容器 */
.panel-left :deep(.stock-info-panel) {
  width: 100%;
  height: 100%;
}
.panel-right {
  background-color: #fafafa;
  border-left: 1px solid #ebeef5;
}

/* ─── 侧边控制条（拖拽柄 + 折叠按钮） ─────────────────────────────── */
.panel-edge {
  flex-shrink: 0;
  width: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #f0f2f5;
  z-index: 20;
}
.panel-edge-left {
  border-right: 1px solid #dcdfe6;
}
.panel-edge-right {
  border-left: 1px solid #dcdfe6;
}
.resize-handle {
  flex: 1;
  width: 100%;
  cursor: col-resize;
  transition: background 0.15s;
}
.resize-handle:hover {
  background: rgba(64, 158, 255, 0.25);
}
.collapse-btn {
  flex-shrink: 0;
  width: 14px;
  height: 36px;
  border: none;
  background: #dde1e8;
  cursor: pointer;
  font-size: 9px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #606266;
  transition: background 0.15s, color 0.15s;
}
.panel-edge-left .collapse-btn {
  border-radius: 0 4px 4px 0;
}
.panel-edge-right .collapse-btn {
  border-radius: 4px 0 0 4px;
}
.collapse-btn:hover {
  background: #409eff;
  color: #fff;
}

/* ─── 中间主区 ─────────────────────────────────────────────────────── */
.detail-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-color: #ffffff;
}
.detail-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 16px 8px;
  border-bottom: 1px solid #ebeef5;
}
.detail-header h2 {
  margin: 0;
  font-size: 18px;
  color: #303133;
}
.detail-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.switching-hint {
  font-size: 12px;
  color: #409eff;
  white-space: nowrap;
}
.stock-nav-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 6px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #f8fbff;
}
.stock-nav-index {
  min-width: 42px;
  font-size: 12px;
  line-height: 1;
  color: #606266;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
:deep(.stock-nav-control .el-button) {
  width: 28px;
  padding-left: 0;
  padding-right: 0;
}

/* ─── K 线图区：填满可用高度 ─────────────────────────────────────── */
.chart-area {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ── 策略详情拖拽把手 ─────────────────────────────────── */
.card-resize-handle {
  flex-shrink: 0;
  height: 6px;
  cursor: row-resize;
  background: #ebeef5;
  border-top: 1px solid #dcdfe6;
  border-bottom: 1px solid #dcdfe6;
  transition: background 0.15s;
}
.card-resize-handle:hover {
  background: rgba(64, 158, 255, 0.3);
}

/* ── 策略匹配详情卡 ───────────────────────────────────── */
.strategy-card {
  flex-shrink: 0;
  overflow-y: auto;
  border-top: none;
}
.strategy-card p {
  margin: 4px 0;
  font-size: 13px;
}

/* ─── 右侧股票列表 ────────────────────────────────────────────────── */
.slp-header {
  flex-shrink: 0;
  padding: 8px 10px 6px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  background: #f5f7fa;
}
.slp-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-right: auto;
}
.slp-date-select {
  width: 110px;
}
:deep(.slp-date-select .el-input__wrapper) {
  padding: 0 6px;
}
.slp-meta {
  font-size: 11px;
  color: #909399;
}
.slp-count {
  font-size: 11px;
  color: #909399;
}
.slp-scroll {
  flex: 1;
  overflow-y: auto;
}
.slp-group {
  border-bottom: 1px solid #ebeef5;
}
.slp-group-head {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  background: #eef5ff;
  border-bottom: 1px solid #d9ecff;
}
.slp-group-head span {
  font-size: 12px;
  font-weight: 600;
  color: #303133;
}
.slp-group-head em {
  font-size: 11px;
  color: #909399;
  font-style: normal;
  white-space: nowrap;
}
.slp-item {
  padding: 7px 10px;
  cursor: pointer;
  border-bottom: 1px solid #f0f0f0;
  transition: background 0.15s;
  display: grid;
  grid-template-columns: 22px minmax(62px, 1fr) minmax(64px, 1fr);
  gap: 2px 4px;
  align-items: center;
}
.slp-item:hover {
  background-color: #e6f4ff;
}
.slp-item.active {
  background-color: #d6eaff;
  border-left: 3px solid #409eff;
}
.slp-code {
  font-size: 12px;
  font-weight: 600;
  color: #409eff;
}
.slp-check {
  grid-row: 1 / span 2;
  align-self: center;
  justify-self: center;
  height: 16px;
}
:deep(.slp-check .el-checkbox__label) {
  display: none;
}
.slp-name {
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.slp-sim {
  font-size: 11px;
  color: #909399;
  text-align: right;
}
.slp-date {
  font-size: 11px;
  color: #909399;
  grid-column: 2 / -1;
}
.slp-empty {
  padding: 24px 12px;
  text-align: center;
  font-size: 12px;
  color: #c0c4cc;
}

/* ─── 响应式（小屏隐藏侧边栏控制条） ─────────────────────────────── */
@media (max-width: 1100px) {
  .panel-edge {
    display: none;
  }
  .panel-aside {
    display: none !important;
  }
  .stock-detail {
    overflow: auto;
  }
  .detail-main {
    overflow: auto;
  }
  .chart-area {
    min-height: 380px;
  }
}
</style>
