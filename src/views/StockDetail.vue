<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import KlineChart from '@/components/KlineChart.vue'
import StockInfoPanel from '@/components/StockInfoPanel.vue'
import { getStockPrice, getStrategyResultsHistory, getStockInfo } from '@/api'
import { useStrategyListStore } from '@/stores/strategyList'

const props = defineProps<{ code: string }>()
const router = useRouter()
const strategyListStore = useStrategyListStore()
const KLINE_LIMIT_10Y = 2600

const period = ref('daily')
const adjust = ref<'qfq' | 'hfq' | 'nfq'>('qfq')
const priceInfo = ref<any>(null)
const stockInfo = ref<any>(null)
const signals = ref<any[]>([])
const strategyCard = ref<any>(null)
const loading = ref(false)
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
const strategyListDate = computed(() => strategyListStore.tradeDate)

function goToStockFromList(targetCode: string) {
  router.push(`/stocks/${targetCode}`)
}

onMounted(() => {
  loadAll(props.code)
  // 从非策略结果页面直接进入时，自动加载最新策略列表填充右侧面板
  if (!strategyListStore.items.length) {
    loadDefaultStrategyList()
  }
})

watch(() => props.code, (newCode) => {
  loadAll(newCode)
})

// 个股扩展信息客户端缓存（行业/地区/经营范围/概念标签，同一股票只请求一次）
const _stockInfoCache = new Map<string, any>()

async function loadAll(code: string) {
  loading.value = true
  stockInfo.value = null
  try {
    const [pRes] = await Promise.all([
      getStockPrice(code),
      loadSignals(code),
    ])
    priceInfo.value = pRes.data.data
  } catch (e) {
    console.error('加载失败', e)
  } finally {
    loading.value = false
  }
  // 懒加载扩展信息（行业/地区/经营范围/概念标签）——有客户端缓存，同一股票只请求一次
  if (_stockInfoCache.has(code)) {
    stockInfo.value = _stockInfoCache.get(code)
  } else {
    getStockInfo(code).then(res => {
      const data = res.data.data
      _stockInfoCache.set(code, data)
      stockInfo.value = data
    }).catch((err) => {
      console.warn('扩展信息加载失败', err)
      const fallback = { industry: '', region: '', main_business: '', concept_tags: [] }
      _stockInfoCache.set(code, fallback)
      stockInfo.value = fallback
    })
  }
}

/** 当 store 为空时（例如从首页或直接导航），自动拉取最新策略结果填右侧列表 */
async function loadDefaultStrategyList() {
  try {
    const res = await getStrategyResultsHistory({
      strategy: 'all',
      per_page: 100,
      sort_by: 'run_started_at',
      sort_order: 'desc',
    })
    const items: any[] = res.data.data?.items || []
    if (items.length) {
      const uniqueList = Array.from(
        new Map(items.map((i: any) => [i.code, i])).values(),
      ) as any[]
      strategyListStore.setList(uniqueList, 'all', items[0]?.trade_date || '')
    }
  } catch (e) {
    console.error('自动加载策略列表失败', e)
  }
}

async function loadSignals(code: string) {
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
    console.error('加载策略信号失败', e)
    strategyCard.value = null
    signals.value = []
  }
}

function onPeriodChange(nextPeriod: string) {
  period.value = nextPeriod
}
</script>

<template>
  <div class="stock-detail" v-loading="loading">
    <!-- ══ 左侧：个股信息面板 ═══════════════════════════════════════════ -->
    <div
      class="panel-aside panel-left"
      :class="{ 'panel-collapsed': leftCollapsed }"
      :style="leftCollapsed ? {} : { width: leftWidth + 'px' }"
    >
      <StockInfoPanel :price-info="priceInfo" :stock-info="stockInfo" side="left" />
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
        <h2>{{ priceInfo?.name }} {{ code }}</h2>
        <div class="detail-actions">
          <el-checkbox v-model="showShortTermTrend">短期趋势线</el-checkbox>
          <el-checkbox v-model="showBullBearLine">知行多空线</el-checkbox>
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
        v-if="strategyCard"
        class="card-resize-handle"
        title="拖拽调整策略详情区高度"
        @mousedown.prevent="startCardResize"
      ></div>

      <div class="strategy-card" v-if="strategyCard" :style="{ height: strategyCardHeight + 'px' }">
        <el-card shadow="never">
          <template #header>策略匹配详情</template>
          <p><strong>策略:</strong> {{ strategyCard.strategy_name }}</p>
          <p><strong>分类:</strong> {{ strategyCard.category }}</p>
          <p><strong>匹配日期:</strong> {{ strategyCard.signal_date || strategyCard.trade_date }}</p>
          <p v-if="strategyCard.reason"><strong>原因:</strong> {{ strategyCard.reason }}</p>
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
        <span class="slp-meta" v-if="strategyListDate">{{ strategyListDate }}</span>
        <span class="slp-count">{{ strategyListItems.length }} 只</span>
      </div>
      <div class="slp-scroll" v-if="strategyListItems.length">
        <div
          v-for="item in strategyListItems"
          :key="item.code"
          class="slp-item"
          :class="{ active: item.code === code }"
          @click="goToStockFromList(item.code)"
        >
          <span class="slp-code">{{ item.code }}</span>
          <span class="slp-name">{{ item.name }}</span>
          <span class="slp-date">{{ item.signal_date || item.trade_date }}</span>
        </div>
      </div>
      <div class="slp-empty" v-else>
        <span>加载策略选股中...</span>
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
  padding: 10px 12px 8px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: #f5f7fa;
}
.slp-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
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
.slp-item {
  padding: 7px 10px;
  cursor: pointer;
  border-bottom: 1px solid #f0f0f0;
  transition: background 0.15s;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
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
.slp-name {
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.slp-date {
  font-size: 11px;
  color: #909399;
  grid-column: 1 / -1;
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
