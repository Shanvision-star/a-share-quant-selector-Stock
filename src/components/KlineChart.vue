<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { getCachedKlineResponse, getKline, getIntradayKline } from '@/api'
import type { KlineAdjust } from '@/api'
import { createRequestManager, isAbortError } from '@/api/requestManager'
import { buildMainKlineRequestKey, scheduleKlineIdleWork, selectFastKlineLimit, shouldShowBlockingKlineLoading } from '@/components/klineRequest'
import { buildBrickStackedBars } from '@/utils/klineIndicators'
import { buildVolumeAxisScaleForZoom } from '@/utils/klineVolumeScale'

const props = withDefaults(defineProps<{
  code: string
  period?: string
  limit?: number
  signals?: Array<Record<string, any>>
  showShortTermTrend?: boolean
  showBullBearLine?: boolean
  adjust?: string
}>(), {
  period: 'daily',
  limit: 2600,
  signals: () => [],
  showShortTermTrend: true,
  showBullBearLine: true,
  adjust: 'qfq',
})

const wrapperRef = ref<HTMLDivElement>()
const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let chartRenderer: 'canvas' | 'svg' = 'canvas'
let resizeObserver: ResizeObserver | null = null
let pendingResizeFrame: number | null = null
let pendingGridFrame: number | null = null
let isApplyingOption = false
let cancelPendingFullKlineRender: (() => void) | null = null

/** 当前渲染的K线数组（供区间统计使用） */
const renderedBars = ref<any[]>([])

interface CursorLatestChange {
  fromDate: string
  toDate: string
  bars: number
  change: number
  changePct: number
}

const cursorLatestChange = ref<CursorLatestChange | null>(null)

// ── 时间跨度快速缩放预设 ─────────────────────────────────────────────────
// 日线预设（交易日近似：1月≈22根，1年≈252根）
// 周线预设（1年≈52根，3年≈156根）
const ZOOM_PRESETS_DAILY  = [
  { label: '1M',  bars: 22  },
  { label: '3M',  bars: 66  },
  { label: '6M',  bars: 132 },
  { label: '1Y',  bars: 252 },
  { label: '全部', bars: 0   },
]
const ZOOM_PRESETS_WEEKLY = [
  { label: '3M',  bars: 13  },
  { label: '6M',  bars: 26  },
  { label: '1Y',  bars: 52  },
  { label: '3Y',  bars: 156 },
  { label: '全部', bars: 0   },
]
const currentZoomBars = ref(0)   // 0 = 使用智能默认值
const totalAxisLength  = ref(0)  // renderChart 写入，供按钮点击时计算百分比
const zoomPresets = computed(() =>
  props.period === 'weekly' ? ZOOM_PRESETS_WEEKLY : ZOOM_PRESETS_DAILY
)
let renderSeq = 0
const loading = ref(false)
const hasRenderedChart = ref(false)
const showBlockingLoading = computed(() => shouldShowBlockingKlineLoading(loading.value, hasRenderedChart.value))
const containerHeight = ref(600)
const requestManager = createRequestManager()
const chartState = reactive({
  errorMessage: '',
  emptyMessage: '',
})

// ============ 可拖拽面板尺寸状态 ============
const PANEL_KEYS = ['main', 'volume', 'adjVolume', 'indicator'] as const
type PanelKey = typeof PANEL_KEYS[number]
const SUB_INDICATOR_OPTIONS = [
  { key: 'macd', label: 'MACD' },
  { key: 'kdj', label: 'KDJ' },
  { key: 'brick', label: '砖型图' },
] as const
type SubIndicatorKey = typeof SUB_INDICATOR_OPTIONS[number]['key']
const activeSubIndicator = ref<SubIndicatorKey>('macd')
const activeSubIndicatorLabel = computed(() =>
  SUB_INDICATOR_OPTIONS.find(item => item.key === activeSubIndicator.value)?.label || 'MACD',
)
const TOP_MARGIN = 40
const BOTTOM_MARGIN = 55   // 增大底部留白，避免横向时间轴与 dataZoom 滑块重叠
const PANEL_GAP = 10
const MIN_PANEL_PX = 40
const EXPANDED_MAIN_RATIO = 0.48

// 四个面板的高度比例（加起来 = 1.0）
// main=主图, volume=成交量, adjVolume=还原成交量, indicator=当前副图指标
const panelRatios = reactive<Record<PanelKey, number>>({
  main: 0.64,
  volume: 0.08,
  adjVolume: 0.08,
  indicator: 0.20,
})

function getEffectivePanelRatios(): Record<PanelKey, number> {
  if (!expandedSubPanel.value) {
    return { ...panelRatios }
  }

  const mainRatio = Math.min(panelRatios.main, EXPANDED_MAIN_RATIO)
  const subBudget = Math.max(0.05, 1 - mainRatio)
  return {
    main: mainRatio,
    volume: expandedSubPanel.value === 'volume' ? subBudget : 0,
    adjVolume: expandedSubPanel.value === 'adjVolume' ? subBudget : 0,
    indicator: expandedSubPanel.value === 'indicator' ? subBudget : 0,
  }
}

function getUsableHeight() {
  return containerHeight.value - TOP_MARGIN - BOTTOM_MARGIN - (PANEL_KEYS.length - 1) * PANEL_GAP
}

function computeGrids() {
  const usable = getUsableHeight()
  const effectiveRatios = getEffectivePanelRatios()
  let top = TOP_MARGIN
  return PANEL_KEYS.map((key) => {
    const h = effectiveRatios[key] * usable
    const grid = { left: 60, right: 60, top, height: h }
    top += h + PANEL_GAP
    return grid
  })
}

// ── 副图左上角指标名称标签（与面板高度联动，拖拽时自动更新）─────────────
const subPanelLabels = computed(() => {
  const grids = computeGrids()
  const labels = [
    { key: 'volume' as PanelKey,    name: '成交量',    top: grids[1].top + 3 },
    { key: 'adjVolume' as PanelKey, name: '还原成交量', top: grids[2].top + 3 },
    { key: 'indicator' as PanelKey, name: activeSubIndicatorLabel.value, top: grids[3].top + 3 },
  ]
  return expandedSubPanel.value
    ? labels.filter(label => label.key === expandedSubPanel.value)
    : labels
})

// 分割线的 CSS top 位置（像素）
const dividerPositions = computed(() => {
  if (expandedSubPanel.value) return []
  const usable = getUsableHeight()
  const effectiveRatios = getEffectivePanelRatios()
  const positions: number[] = []
  let top = TOP_MARGIN
  for (let i = 0; i < PANEL_KEYS.length - 1; i++) {
    top += effectiveRatios[PANEL_KEYS[i]] * usable
    positions.push(top)
    top += PANEL_GAP
  }
  return positions
})

// ============ 拖拽逻辑 ============
const isDragging = ref(false)
let dragIndex = -1
let dragStartY = 0
let dragStartRatios: Record<string, number> = {}

function startDrag(event: MouseEvent, dividerIndex: number) {
  event.preventDefault()
  isDragging.value = true
  dragIndex = dividerIndex
  dragStartY = event.clientY
  dragStartRatios = { ...panelRatios }
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
}

function onDrag(event: MouseEvent) {
  if (!isDragging.value) return
  const usable = getUsableHeight()
  const deltaRatio = (event.clientY - dragStartY) / usable
  const upperKey = PANEL_KEYS[dragIndex]
  const lowerKey = PANEL_KEYS[dragIndex + 1]
  const minRatio = MIN_PANEL_PX / usable

  if (dragIndex === 0) {
    // 主图与第一个副图之间：主图 <-> 第一副图互换
    const newUpper = dragStartRatios[upperKey] + deltaRatio
    const newLower = dragStartRatios[lowerKey] - deltaRatio
    if (newUpper >= minRatio && newLower >= minRatio) {
      panelRatios[upperKey] = newUpper
      panelRatios[lowerKey] = newLower
      scheduleGridUpdate()
    }
  } else {
    // 副图之间：只在副图预算池内重新分配，不影响主图
    // 拖动 divider 上方面板扩大/缩小，下方面板同等补偿
    const newUpper = dragStartRatios[upperKey] + deltaRatio
    const newLower = dragStartRatios[lowerKey] - deltaRatio
    if (newUpper >= minRatio && newLower >= minRatio) {
      panelRatios[upperKey] = newUpper
      panelRatios[lowerKey] = newLower
      scheduleGridUpdate()
    }
  }
}

function stopDrag() {
  isDragging.value = false
  dragIndex = -1
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
}

function updateContainerHeight() {
  if (wrapperRef.value) {
    containerHeight.value = wrapperRef.value.clientHeight
  }
}

function toFiniteNumber(value: unknown): number | null {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function sanitizeIndicator(values: unknown): Array<number | null> {
  if (!Array.isArray(values)) return []
  return values.map((item) => {
    const num = toFiniteNumber(item)
    return num === null ? null : Number(num.toFixed(2))
  })
}

function formatAxisCategory(value: unknown): string {
  const text = typeof value === 'string' ? value : value == null ? '' : String(value)
  return text.startsWith('__PAD_') ? '' : text
}

function formatSignalMarkLabel(params: any): string {
  const labelValue = params?.data?.value ?? params?.value
  return labelValue == null ? '' : String(labelValue)
}

function readDataZoomWindow(event: any, fallback: { start: number; end: number }) {
  const payload = Array.isArray(event?.batch) ? event.batch[0] : event
  const start = toFiniteNumber(payload?.start)
  const end = toFiniteNumber(payload?.end)
  return {
    start: start === null ? fallback.start : Math.max(0, Math.min(100, start)),
    end: end === null ? fallback.end : Math.max(0, Math.min(100, end)),
  }
}

function updateCursorLatestChange(rawIndex: unknown) {
  const bars = renderedBars.value
  if (!bars.length) {
    cursorLatestChange.value = null
    return
  }
  const index = Math.max(0, Math.min(bars.length - 1, Math.round(Number(rawIndex))))
  if (!Number.isFinite(index)) {
    cursorLatestChange.value = null
    return
  }
  const fromBar = bars[index]
  const latestBar = bars[bars.length - 1]
  const baseClose = Number(fromBar?.close)
  const latestClose = Number(latestBar?.close)
  if (!Number.isFinite(baseClose) || !Number.isFinite(latestClose) || baseClose <= 0) {
    cursorLatestChange.value = null
    return
  }
  const change = latestClose - baseClose
  cursorLatestChange.value = {
    fromDate: fromBar.date,
    toDate: latestBar.date,
    bars: bars.length - 1 - index,
    change,
    changePct: (change / baseClose) * 100,
  }
}

function shouldIgnoreChartPointerEvent(event: MouseEvent): boolean {
  const target = event.target as HTMLElement | null
  return !!target?.closest('button, .el-select, .zoom-presets, .sub-indicator-selector, .panel-divider, .panel-label-row, .intraday-popup, .range-stats-popup')
}

function getPanelKeyByLocalY(localY: number): PanelKey | null {
  const grids = computeGrids()
  for (let i = 1; i < grids.length; i += 1) {
    const grid = grids[i]
    if (grid.height <= 0) continue
    if (localY >= grid.top && localY <= grid.top + grid.height) {
      return PANEL_KEYS[i]
    }
  }
  return null
}

function onChartDoubleClick(event: MouseEvent) {
  if (shouldIgnoreChartPointerEvent(event) || !wrapperRef.value) return
  const rect = wrapperRef.value.getBoundingClientRect()
  const panelKey = getPanelKeyByLocalY(event.clientY - rect.top)
  if (panelKey && panelKey !== 'main') {
    event.preventDefault()
    toggleMaximizeSubPanel(panelKey)
  }
}

function normalizeBar(rawBar: any) {
  const open = toFiniteNumber(rawBar?.open)
  const close = toFiniteNumber(rawBar?.close)
  const low = toFiniteNumber(rawBar?.low)
  const high = toFiniteNumber(rawBar?.high)
  const volume = toFiniteNumber(rawBar?.volume)
  const date = typeof rawBar?.date === 'string' ? rawBar.date : ''
  if (!date || open === null || close === null || low === null || high === null) {
    return null
  }
  return {
    date, open, close, low, high,
    volume: volume === null ? null : volume,
    turnover: toFiniteNumber(rawBar?.turnover) ?? 0,
    amount: toFiniteNumber(rawBar?.amount) ?? 0,
    vol_ratio_10d: toFiniteNumber(rawBar?.vol_ratio_10d) ?? null,
    avg_volume_10d: toFiniteNumber(rawBar?.avg_volume_10d) ?? null,
  }
}

function getErrorMessage(error: any): string {
  const apiMessage = error?.response?.data?.detail || error?.response?.data?.message
  if (typeof apiMessage === 'string' && apiMessage.trim()) return apiMessage
  if (error?.message) return String(error.message)
  return '未知错误'
}

async function ensureChartContainerReady(maxRetries = 8): Promise<boolean> {
  for (let i = 0; i < maxRetries; i++) {
    await nextTick()
    if (chartRef.value) {
      const width = chartRef.value.clientWidth
      const height = chartRef.value.clientHeight
      if (width > 20 && height > 20) {
        updateContainerHeight()
        return true
      }
    }
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  }
  return false
}

function getOrCreateChart(renderer: 'canvas' | 'svg') {
  if (!chartRef.value) return null
  if (!chart || chartRenderer !== renderer) {
    chart?.dispose()
    chart = echarts.init(chartRef.value, undefined, { renderer })
    chartRenderer = renderer
  }
  return chart
}

function scheduleResize() {
  if (pendingResizeFrame !== null) return
  pendingResizeFrame = requestAnimationFrame(() => {
    pendingResizeFrame = null
    if (!chart || isApplyingOption) return
    updateContainerHeight()  // 实际渲染帧重读容器真实高度
    chart.resize()
    // canvas 尺寸变化后同步更新分栏 grid 像素高度，防止 K 线/指标错位
    try { chart.setOption({ grid: computeGrids() }, false) } catch { /* ignore race */ }
  })
}

function scheduleGridUpdate() {
  if (pendingGridFrame !== null) {
    cancelAnimationFrame(pendingGridFrame)
  }
  pendingGridFrame = requestAnimationFrame(() => {
    pendingGridFrame = null
    if (!chart || isApplyingOption) return
    try {
      chart.setOption({ grid: computeGrids() }, false)
    } catch {
      // Ignore intermediate layout updates while the chart is stabilizing.
    }
  })
}

function applyOption(chartInstance: echarts.ECharts, option: echarts.EChartsOption) {
  isApplyingOption = true
  try {
    chartInstance.setOption(option, true)
  } finally {
    isApplyingOption = false
  }
  scheduleResize()
}

function applyOptionWithFallback(option: echarts.EChartsOption) {
  try {
    const canvasChart = getOrCreateChart('canvas')
    if (canvasChart) {
      applyOption(canvasChart, option)
    }
    return
  } catch (canvasError) {
    console.warn('Canvas 渲染失败，尝试 SVG 回退', canvasError)
  }

  const svgChart = getOrCreateChart('svg')
  if (svgChart) {
    applyOption(svgChart, option)
  }
}

async function renderChart() {
  if (!chartRef.value) return

  const seq = ++renderSeq
  if (cancelPendingFullKlineRender) {
    cancelPendingFullKlineRender()
    cancelPendingFullKlineRender = null
  }
  const requestKey = buildMainKlineRequestKey(props.code, props.period, props.adjust)
  const controller = requestManager.start(requestKey)
  loading.value = true
  chartState.errorMessage = ''
  chartState.emptyMessage = ''

  try {
    const containerReady = await ensureChartContainerReady()
    if (!containerReady) {
      chart?.clear()
      chartState.errorMessage = '图表容器尺寸异常，请调整窗口后重试。'
      return
    }

    // 当前组件自己取 K 线数据，父组件只负责传入叠加用的策略信号和显示开关。
    const fullKlineParams = {
      period: props.period,
      limit: props.limit,
      adjust: props.adjust as KlineAdjust,
    }
    const hasFullKlineCache = !!getCachedKlineResponse(props.code, fullKlineParams)
    const requestLimit = selectFastKlineLimit(props.limit, hasFullKlineCache)
    const shouldWarmFullKline = requestLimit < props.limit
    const requestParams = { ...fullKlineParams, limit: requestLimit }
    const res = await getKline(
      props.code,
      requestParams,
      { signal: controller.signal },
    )
    if (!requestManager.isCurrent(requestKey, controller)) return
    if (seq !== renderSeq) return

    const data = res?.data?.data
    const normalizedBars = (Array.isArray(data?.bars) ? data.bars : [])
      .map((bar: any) => normalizeBar(bar))
      .filter((bar: any) => !!bar)

    if (!normalizedBars.length) {
      chart?.clear()
      hasRenderedChart.value = false
      chartState.emptyMessage = '当前股票暂无可展示的K线数据。'
      return
    }
    renderedBars.value = normalizedBars

    const indicators = data?.indicators || {}

    const dates = normalizedBars.map((bar: any) => bar.date)
    const dateSet = new Set(dates)
    const ohlc = normalizedBars.map((bar: any) => [bar.open, bar.close, bar.low, bar.high])
    const volumes = normalizedBars.map((bar: any) => ({
      value: bar.volume,
      itemStyle: { color: bar.close >= bar.open ? '#ef5350' : '#26a69a' },
    }))

    // 还原成交量：按收盘与前一根收盘比较确定颜色（而非与本根开盘比）
    // 即使当日阴线，只要收盘高于前日收盘，就显示为阳量（红色）
    const adjVolumes = normalizedBars.map((bar: any, i: number) => {
      const prevClose = i > 0 ? (normalizedBars[i - 1].close ?? bar.open) : (bar.open ?? 0)
      return {
        value: bar.volume,
        itemStyle: { color: (bar.close ?? 0) >= prevClose ? '#ef5350' : '#26a69a' },
      }
    })

    // 右侧补白：给最新K线预留可视空间，避免贴边显示不明显。
    const rightPadCount = 4
    const padLabels = Array.from({ length: rightPadCount }, (_, i) => `__PAD_${i}`)
    const axisDates = dates.concat(padLabels)
    axisDatesRef.value = axisDates

    // ── 周期自适应均线 ──────────────────────────────────────────────────────
    // 日线：MA10 / MA30 / MA60 / MA120；周线：MA34 / MA55 / MA144 / MA233
    // 后端在 indicators.ma_periods 中告知实际周期，前端据此动态生成图例标签。
    const maPeriods: number[] = Array.isArray(indicators.ma_periods)
      ? (indicators.ma_periods as number[])
      : (props.period === 'weekly' ? [34, 55, 144, 233] : [10, 30, 60, 120])
    const [maAData, maBData, maCData, maDData] = maPeriods.map(
      (p: number) => sanitizeIndicator((indicators as any)[`ma${p}`] ?? []),
    )
    const maColors = ['#f5c878', '#ff6d9e', '#42a5f5', '#ab47bc']
    const bbiData = sanitizeIndicator(indicators.bbi)
    const shortTrendData = sanitizeIndicator(indicators.short_term_trend)
    const bullBearData = sanitizeIndicator(indicators.bull_bear_line)
    const kData = sanitizeIndicator(indicators.K)
    const dData = sanitizeIndicator(indicators.D)
    const jData = sanitizeIndicator(indicators.J)
    const difData = sanitizeIndicator(indicators.DIF)
    const deaData = sanitizeIndicator(indicators.DEA)
    const macdBars = sanitizeIndicator(indicators.MACD).map((value: number | null) => ({
      value,
      itemStyle: { color: (value ?? 0) >= 0 ? '#ef5350' : '#26a69a' },
    }))
    const brickValues = sanitizeIndicator(indicators.brick_value)
    const brickBars = buildBrickStackedBars(brickValues)
    const subIndicatorSeries = activeSubIndicator.value === 'kdj'
      ? [
          { name: 'K', type: 'line', data: kData, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f5c878' } },
          { name: 'D', type: 'line', data: dData, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#42a5f5' } },
          { name: 'J', type: 'line', data: jData, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#ab47bc' } },
        ]
      : activeSubIndicator.value === 'brick'
        ? [
            {
              name: '砖型图基线',
              type: 'bar',
              stack: 'brick',
              data: brickBars.base,
              xAxisIndex: 3,
              yAxisIndex: 3,
              barWidth: 8,
              silent: true,
              tooltip: { show: false },
              itemStyle: { color: 'transparent', borderColor: 'transparent' },
              emphasis: { disabled: true },
            },
            {
              name: '砖型图',
              type: 'bar',
              stack: 'brick',
              data: brickBars.body,
              xAxisIndex: 3,
              yAxisIndex: 3,
              barWidth: 8,
              barMinHeight: 1,
            },
          ]
        : [
            { name: 'DIF', type: 'line', data: difData, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f5c878' } },
            { name: 'DEA', type: 'line', data: deaData, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#42a5f5' } },
            { name: 'MACD', type: 'bar', data: macdBars, xAxisIndex: 3, yAxisIndex: 3 },
          ]

    // 记录总轴长度，供时间跨度按钮 handleZoomPreset 计算百分比
    totalAxisLength.value = axisDates.length

    // 智能初始缩放窗口：日线默认最近 120 根（约半年），周线 52 根（约一年）
    // 用户点过预设按钮后 currentZoomBars 有值，保持用户选择；切换股票/周期时会重置为 0
    const defaultWindowBars = props.period === 'weekly' ? 52 : 120
    const effectiveBars = currentZoomBars.value > 0 ? currentZoomBars.value : defaultWindowBars
    const zoomStart = axisDates.length > effectiveBars
      ? Math.max(0, ((axisDates.length - effectiveBars) / axisDates.length) * 100)
      : 0
    const volumeValues = normalizedBars.map((bar: any) => bar.volume)
    const initialVolumeScale = buildVolumeAxisScaleForZoom(volumeValues, axisDates.length, zoomStart, 100)

    // 策略信号不参与后端 K 线计算，只在前端主图上追加成标注箭头。
    const signalMarks = (props.signals || [])
      .map((signal: any, index: number) => {
        const signalDate = signal?.date || signal?.signal_date || signal?.trade_date
        const signalPrice = toFiniteNumber(signal?.close ?? signal?.trigger_price)
        if (!signalDate || signalPrice === null || !dateSet.has(signalDate)) return null

        return {
          name: `${signal.label || signal.category || 'signal'}-${index}`,
          coord: [signalDate, Number((signalPrice * 0.97).toFixed(2))],
          value: signal.category?.includes('b1') ? 'B1' : signal.category?.includes('bowl') ? 'BOWL' : signal.category?.includes('brick') ? '砖' : 'B2',
          symbol: 'arrow',
          symbolSize: 12,
          symbolRotate: 180,
          itemStyle: {
            color: signal.category?.includes('b1') ? '#f5222d' : signal.category?.includes('bowl') ? '#faad14' : signal.category?.includes('brick') ? '#ef5350' : '#1890ff',
          },
          label: {
            show: true,
            formatter: (params: any) => formatSignalMarkLabel(params),
            position: 'bottom',
            color: '#fff',
            fontSize: 10,
          },
        }
      })
      .filter((mark): mark is NonNullable<typeof mark> => !!mark)

    // 均线图例标签（跟随 maPeriods 动态生成）
    const maLegendNames = maPeriods.map((p: number) => `MA${p}`)
    const legendSelected: Record<string, boolean> = {}
    maLegendNames.forEach((n: string) => { legendSelected[n] = false })
    legendSelected['BBI'] = true
    legendSelected['短期趋势线'] = props.showShortTermTrend
    legendSelected['知行多空线'] = props.showBullBearLine

    const option: echarts.EChartsOption = {
      animation: false,
      backgroundColor: '#131722',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(20,30,45,0.92)',
        borderColor: '#363a45',
        padding: [6, 8],
        textStyle: { color: '#d1d4dc', fontSize: 11, lineHeight: 14 },
        confine: true,
        position: (point: number[], _params: any, _dom: any, _rect: any, size: any) => {
          const [px] = point
          const { viewSize, contentSize } = size as { viewSize: number[]; contentSize: number[] }
          const margin = 12
          const right = px + margin
          const left = px - contentSize[0] - margin
          const x = right + contentSize[0] > viewSize[0] ? Math.max(0, left) : right
          return [x, 8]
        },
        formatter: (params: any): string => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const idx = (params[0] as any)?.dataIndex as number
          if (idx == null || idx >= normalizedBars.length) return ''
          const bar = normalizedBars[idx]
          if (!bar) return ''
          const prev = idx > 0 ? normalizedBars[idx - 1] : null
          const prevClose = prev ? (prev.close ?? bar.open) : (bar.open ?? 0)
          const change = (bar.close ?? 0) - prevClose
          const changePct = prevClose ? ((change / prevClose) * 100).toFixed(2) : '0.00'
          const changeStr = change >= 0 ? `+${change.toFixed(2)}` : change.toFixed(2)
          const changeColor = change >= 0 ? '#ef5350' : '#26a69a'
          let maLines = ''
          for (const p of params as any[]) {
            const sn: string = p?.seriesName ?? ''
            if ((sn.startsWith('MA') || sn === 'BBI' || sn === '\u77ed\u671f\u8d8b\u52bf\u7ebf' || sn === '\u77e5\u884c\u591a\u7a7a\u7ebf') && p.value != null) {
              maLines += `<tr><td style="color:${p.color};padding-right:6px">●${sn}</td><td style="text-align:right">${Number(p.value).toFixed(2)}</td></tr>`
            }
          }
          const turnoverStr = (bar as any).turnover > 0 ? `${((bar as any).turnover as number).toFixed(2)}%` : '-'
          const amountStr = (bar as any).amount > 0 ? `${((bar as any).amount as number).toFixed(2)}万` : '-'
          const volRatio = (bar as any).vol_ratio_10d
          const volRatioColor = volRatio == null ? '#d1d4dc' : volRatio >= 1.5 ? '#ef5350' : volRatio < 1.0 ? '#26a69a' : '#d1d4dc'
          const volRatioStr = volRatio != null ? `<span style="color:${volRatioColor}">x${volRatio.toFixed(2)}</span>` : ''
          return `<div style="min-width:160px;font-size:11px">
            <div style="font-weight:600;margin-bottom:3px;color:#d1d4dc">${bar.date}</div>
            <table style="border-collapse:collapse;width:100%">
              <tr><td>开</td><td style="text-align:right">${(bar.open ?? 0).toFixed(2)}</td><td style="padding-left:8px">高</td><td style="text-align:right;color:#ef5350">${(bar.high ?? 0).toFixed(2)}</td></tr>
              <tr><td>低</td><td style="text-align:right;color:#26a69a">${(bar.low ?? 0).toFixed(2)}</td><td style="padding-left:8px">收</td><td style="text-align:right;color:${changeColor}">${(bar.close ?? 0).toFixed(2)}</td></tr>
              <tr><td>涨跌</td><td colspan="3" style="text-align:right;color:${changeColor}">${changeStr} (${changePct}%)</td></tr>
              <tr><td>量</td><td colspan="3" style="text-align:right">${(bar.volume ?? 0).toLocaleString()} ${volRatioStr}</td></tr>
              <tr><td>额</td><td style="text-align:right">${amountStr}</td><td style="padding-left:8px">换手</td><td style="text-align:right">${turnoverStr}</td></tr>
              ${maLines}
            </table>
          </div>`
        },
      },
      legend: {
        data: [...maLegendNames, 'BBI', '短期趋势线', '知行多空线'],
        top: 5,
        textStyle: { color: '#787b86', fontSize: 11 },
        itemWidth: 14,
        itemHeight: 2,
        selected: legendSelected,
      },
      axisPointer: {
        link: [{ xAxisIndex: [0, 1, 2, 3] }],
      },
      // 四段 grid 分别承载主图、成交量、还原成交量、当前副图指标
      grid: computeGrids(),
      xAxis: [
        {
          type: 'category',
          data: axisDates,
          gridIndex: 0,
          axisLine: { lineStyle: { color: '#363a45' } },
          axisLabel: { show: false, formatter: (value: unknown) => formatAxisCategory(value) },
        },
        {
          type: 'category',
          data: axisDates,
          gridIndex: 1,
          axisLine: { lineStyle: { color: '#363a45' } },
          axisLabel: { show: false, formatter: (value: unknown) => formatAxisCategory(value) },
        },
        {
          type: 'category',
          data: axisDates,
          gridIndex: 2,
          axisLine: { lineStyle: { color: '#363a45' } },
          axisLabel: { show: false, formatter: (value: unknown) => formatAxisCategory(value) },
        },
        {
          type: 'category',
          data: axisDates,
          gridIndex: 3,
          axisLine: { lineStyle: { color: '#363a45' } },
          axisLabel: {
            color: '#787b86',
            fontSize: 10,
            formatter: (value: unknown) => formatAxisCategory(value),
          },
        },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        { scale: false, min: 0, max: initialVolumeScale.max, gridIndex: 1, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        { scale: false, min: 0, max: initialVolumeScale.max, gridIndex: 2, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        {
          scale: true,
          gridIndex: 3,
          splitNumber: activeSubIndicator.value === 'brick' ? 5 : 2,
          splitLine: {
            lineStyle: {
              color: '#1e222d',
              type: activeSubIndicator.value === 'brick' ? 'dotted' : 'solid',
            },
          },
          axisLabel: activeSubIndicator.value === 'brick'
            ? { show: false }
            : { color: '#787b86' },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1, 2, 3],
          start: zoomStart,
          end: 100,
          filterMode: 'weakFilter',
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
        },
        {
          type: 'slider',
          xAxisIndex: [0, 1, 2, 3],
          start: zoomStart,
          end: 100,
          filterMode: 'weakFilter',
          bottom: 5,
          height: 18,
          borderColor: '#363a45',
          fillerColor: 'rgba(41,98,255,0.2)',
          backgroundColor: 'rgba(19,23,34,0.75)',
          handleStyle: { color: '#2962ff' },
          moveHandleStyle: { color: '#5b8ff9' },
          showDataShadow: false,
          brushSelect: false,
          showDetail: false,
          labelFormatter: '',
        },
      ],
      series: [
        {
          name: 'Candles',
          type: 'candlestick',
          data: ohlc,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: {
            color: '#ef5350',
            color0: '#26a69a',
            borderColor: '#ef5350',
            borderColor0: '#26a69a',
          },
          markPoint: signalMarks.length ? { data: signalMarks as any[] } : undefined,
        },
        // 均线（周期由 maPeriods 决定，颜色固定为 maColors 四色）
        { name: maLegendNames[0], type: 'line', data: maAData, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: maColors[0] } },
        { name: maLegendNames[1], type: 'line', data: maBData, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: maColors[1] } },
        { name: maLegendNames[2], type: 'line', data: maCData, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: maColors[2] } },
        { name: maLegendNames[3], type: 'line', data: maDData, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: maColors[3] } },
        // BBI → 蓝色；短期趋势线 → 白色；知行多空线 → 黄色
        { name: 'BBI', type: 'line', data: bbiData, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.4, color: '#1e90ff' } },
        { name: '短期趋势线', type: 'line', data: shortTrendData, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#ffffff', type: 'dashed' } },
        { name: '知行多空线', type: 'line', data: bullBearData, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#ffcc00', type: 'dashed' } },
        { name: 'Volume', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1 },
        // 还原成交量：按前一日收盘与当日收盘比较确定颜色
        { name: 'AdjVolume', type: 'bar', data: adjVolumes, xAxisIndex: 2, yAxisIndex: 2 },
        ...(subIndicatorSeries as any[]),
      ],
    }

    applyOptionWithFallback(option)
    hasRenderedChart.value = true

    if (shouldWarmFullKline) {
      void getKline(props.code, fullKlineParams)
        .then(() => {
          if (seq === renderSeq) {
            cancelPendingFullKlineRender = scheduleKlineIdleWork(() => {
              cancelPendingFullKlineRender = null
              if (seq === renderSeq) {
                void safeRenderChart()
              }
            })
          }
        })
        .catch((error) => {
          if (!isAbortError(error)) {
            console.warn('后台补全K线失败', error)
          }
        })
    }

    // 日K点击开启分时K线弹窗（先清除旧监听防止重复注册）
    if (chart) {
      chart.off('click')
      chart.off('updateAxisPointer')
      chart.off('globalout')
      chart.off('datazoom')
      let currentZoomWindow = { start: zoomStart, end: 100 }
      const updateVolumeAxesForZoom = (start: number, end: number) => {
        const scale = buildVolumeAxisScaleForZoom(volumeValues, axisDates.length, start, end)
        try {
          chart?.setOption({ yAxis: [{}, { max: scale.max }, { max: scale.max }] }, false)
        } catch {
          // 拖动缩放时图表可能正在重绘，下一次 render 会重新计算成交量轴。
        }
      }
      chart.on('click', 'series', (params: any) => {
        // 跳过 markPoint（信号箭头）点击，避免 dataIndex 对应错误的日期
        if (params.seriesName === 'Candles' && props.period === 'daily' && params.dataType !== 'markPoint') {
          // params.name 是 category xAxis 的实际标签值（即日期字符串），比 axisDates[dataIndex] 更可靠
          const date = (typeof params.name === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(params.name))
            ? params.name
            : axisDates[params.dataIndex as number]
          if (typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
            openIntradayPopup(date)
          }
        }
      })
      chart.on('updateAxisPointer', (event: any) => {
        const axesInfo = Array.isArray(event?.axesInfo) ? event.axesInfo : []
        const xAxisInfo = axesInfo.find((info: any) => info?.axisDim === 'x' && Number.isFinite(Number(info?.value)))
        if (xAxisInfo) updateCursorLatestChange(xAxisInfo.value)
      })
      chart.on('globalout', () => {
        cursorLatestChange.value = null
      })
      chart.on('datazoom', (event: any) => {
        currentZoomWindow = readDataZoomWindow(event, currentZoomWindow)
        updateVolumeAxesForZoom(currentZoomWindow.start, currentZoomWindow.end)
      })
    }
  } catch (error) {
    // Ignore outdated request failures so stale errors never overwrite the latest chart state.
    if (!requestManager.isCurrent(requestKey, controller) || seq !== renderSeq) return
    throw error
  } finally {
    requestManager.clear(requestKey, controller)
    if (seq === renderSeq) {
      loading.value = false
    }
  }
}

async function retryRender() {
  await safeRenderChart()
}

// ============ 副图折叠 ============
// 默认全部展开，当前指标副图有固定大空间；用户可手动折叠任一副图。
const collapsedPanels = reactive(new Set<PanelKey>())
const savedPanelRatios: Partial<Record<PanelKey, number>> = {
  volume: 0.12,
  adjVolume: 0.12,
  indicator: 0.20,
}

// ── 副图最大化模式 ──────────────────────────────────────────────────
/** 当前最大化的副图面板（null = 无最大化） */
const expandedSubPanel = ref<PanelKey | null>(null)

/** 双击副图标签或副图区：在最大化与正常模式之间切换 */
function toggleMaximizeSubPanel(key: PanelKey) {
  collapsedPanels.delete(key)
  expandedSubPanel.value = expandedSubPanel.value === key ? null : key
  scheduleGridUpdate()
}

function togglePanelCollapse(key: PanelKey) {
  // 若处于最大化模式，折叠按钮先退出最大化再折叠
  if (expandedSubPanel.value !== null) {
    toggleMaximizeSubPanel(expandedSubPanel.value)
  }

  const usable = getUsableHeight()
  const minRatio = MIN_PANEL_PX / usable

  if (collapsedPanels.has(key)) {
    // 展开：从已保存的比例恢复，差值从 main 扣除
    collapsedPanels.delete(key)
    const restored = savedPanelRatios[key] ?? 0.12
    const delta = restored - panelRatios[key]
    if (panelRatios.main - delta >= minRatio) {
      panelRatios.main -= delta
      panelRatios[key] = restored
    }
  } else {
    // 折叠：保存当前比例，压缩到最小，释放高度还给 main
    savedPanelRatios[key] = panelRatios[key]
    const delta = panelRatios[key] - minRatio
    panelRatios.main += delta
    panelRatios[key] = minRatio
    collapsedPanels.add(key)
  }
  scheduleGridUpdate()
}

function selectSubIndicator(key: SubIndicatorKey) {
  if (activeSubIndicator.value === key) return
  activeSubIndicator.value = key
  collapsedPanels.delete('indicator')
  if (expandedSubPanel.value && expandedSubPanel.value !== 'indicator') {
    expandedSubPanel.value = null
  }
  void safeRenderChart()
}

// 时间跨度按钮点击：通过 dispatchAction 直接更新 dataZoom，无需重新请求数据
function handleZoomPreset(bars: number) {
  currentZoomBars.value = bars
  if (!chart || !totalAxisLength.value) return
  const total = totalAxisLength.value
  const effective = bars <= 0 ? total : Math.min(bars, total)
  const start = Math.max(0, ((total - effective) / total) * 100)
  chart.dispatchAction({ type: 'dataZoom', start, end: 100 })
}

// 切换股票或周期时重置缩放状态，让新图以智能默认窗口呈现
watch(() => [props.code, props.period], () => {
  currentZoomBars.value = 0
})

watch(() => [props.code, props.period, props.limit, props.adjust, props.showShortTermTrend, props.showBullBearLine], () => {
  void safeRenderChart()
})

watch(() => props.signals, () => {
  void safeRenderChart()
}, { deep: true })

function setRenderError(error: any) {
  chart?.clear()
  hasRenderedChart.value = false
  chartState.emptyMessage = ''
  chartState.errorMessage = `K线加载失败：${getErrorMessage(error)}`
  console.error('K线渲染失败', error)
}

async function safeRenderChart() {
  try {
    await renderChart()
  } catch (error) {
    if (isAbortError(error)) return
    setRenderError(error)
  }
}

// ============ 分时K线弹窗 ============
const showIntraday = ref(false)
const intradayDate = ref('')
const intradayPeriod = ref<'1' | '15'>('1')
const intradayLoading = ref(false)
const intradayError = ref('')
const intradayChartRef = ref<HTMLDivElement>()
let intradayChart: echarts.ECharts | null = null

// ── 分时弹窗拖拽 ─────────────────────────────────────────────────────
const popupPos = ref<{ x: number | null; y: number | null }>({ x: null, y: null })
let _popupDragging = false
let _popupDragStartX = 0
let _popupDragStartY = 0
let _popupDragOrigX = 0
let _popupDragOrigY = 0

function startPopupDrag(e: MouseEvent) {
  const popup = (e.target as HTMLElement).closest('.intraday-popup') as HTMLElement | null
  if (!popup) return
  e.preventDefault()
  _popupDragging = true
  _popupDragStartX = e.clientX
  _popupDragStartY = e.clientY
  // If no pos set yet, compute from current el position
  if (popupPos.value.x === null) {
    const rect = popup.getBoundingClientRect()
    _popupDragOrigX = rect.left
    _popupDragOrigY = rect.top
  } else {
    _popupDragOrigX = popupPos.value.x
    _popupDragOrigY = popupPos.value.y!
  }
  document.addEventListener('mousemove', onPopupDrag)
  document.addEventListener('mouseup', stopPopupDrag)
}

function onPopupDrag(e: MouseEvent) {
  if (!_popupDragging) return
  popupPos.value = {
    x: _popupDragOrigX + (e.clientX - _popupDragStartX),
    y: _popupDragOrigY + (e.clientY - _popupDragStartY),
  }
}

function stopPopupDrag() {
  _popupDragging = false
  document.removeEventListener('mousemove', onPopupDrag)
  document.removeEventListener('mouseup', stopPopupDrag)
}

const popupStyle = computed(() => {
  if (popupPos.value.x !== null && popupPos.value.y !== null) {
    return {
      position: 'fixed' as const,
      left: popupPos.value.x + 'px',
      top: popupPos.value.y + 'px',
      bottom: 'auto',
      right: 'auto',
    }
  }
  return {}
})

// ── 日期导航 ──────────────────────────────────────────────────────────
const axisDatesRef = ref<string[]>([])
const intradayDateIndex = ref(-1)

const intradayDateList = computed(() =>
  axisDatesRef.value.filter(d => typeof d === 'string' && !d.startsWith('__PAD_'))
)

function canGoPrev() {
  return intradayDateIndex.value > 0
}
function canGoNext() {
  return intradayDateIndex.value < intradayDateList.value.length - 1
}
function goPrevDate() {
  if (!canGoPrev()) return
  intradayDateIndex.value--
  openIntradayPopup(intradayDateList.value[intradayDateIndex.value])
}
function goNextDate() {
  if (!canGoNext()) return
  intradayDateIndex.value++
  openIntradayPopup(intradayDateList.value[intradayDateIndex.value])
}

async function openIntradayPopup(date: string) {
  intradayDate.value = date
  intradayPeriod.value = '1'
  showIntraday.value = true
  // 设置日期索引（如果从主图点击进入时更新索引）
  const idx = intradayDateList.value.indexOf(date)
  if (idx >= 0) intradayDateIndex.value = idx
  await fetchAndRenderIntraday()
}

function closeIntradayPopup() {
  showIntraday.value = false
  popupPos.value = { x: null, y: null }  // 重置拖拽位置
  intradayChart?.dispose()
  intradayChart = null
}

async function switchIntradayPeriod(period: '1' | '15') {
  intradayPeriod.value = period
  await fetchAndRenderIntraday()
}

async function fetchAndRenderIntraday() {
  intradayLoading.value = true
  intradayError.value = ''
  // 先销毁旧图表实例，避免残留
  intradayChart?.dispose()
  intradayChart = null
  try {
    const res = await getIntradayKline(props.code, intradayDate.value, intradayPeriod.value)
    const bars: any[] = res?.data?.data ?? []
    // 关闭 loading，使 v-else ref="intradayChartRef" 挂载到 DOM
    intradayLoading.value = false
    // 等待 Vue DOM 更新 + 浏览器布局完成
    await nextTick()
    await new Promise<void>(r => requestAnimationFrame(() => r()))
    await nextTick()
    renderIntradayChart(bars)
  } catch {
    intradayLoading.value = false
    intradayError.value = '分时数据获取失败，请稍候重试'
  }
}

function renderIntradayChart(bars: any[]) {
  const el = intradayChartRef.value
  if (!el) { intradayError.value = '图表容器不可用'; return }
  // 确保容器有宽高
  if (!el.clientWidth || !el.clientHeight) {
    intradayError.value = '图表容器尺寸异常'
    return
  }
  intradayChart = echarts.init(el, undefined, { renderer: 'canvas' })
  if (!bars.length) {
    intradayError.value = '暂无分时数据'
    return
  }
  // 时间标签：取 HH:mm 部分
  const times = bars.map((b: any) => {
    const t = String(b.time ?? b.datetime ?? '')
    return t.includes(' ') ? t.split(' ')[1].slice(0, 5) : t.slice(0, 5)
  })
  const closes = bars.map((b: any) => b.close ?? b.c ?? null)
  const volColors = bars.map((b: any, i: number) => {
    const prev = i > 0 ? (bars[i - 1].close ?? 0) : (b.open ?? 0)
    return (b.close ?? 0) >= prev ? '#ef5350' : '#26a69a'
  })
  const vols = bars.map((b: any, i: number) => ({
    value: b.volume ?? b.v ?? 0,
    itemStyle: { color: volColors[i] },
  }))
  // 昨收参考线（取第一根 bar 的 open 近似）
  const refPrice = bars[0]?.open ?? closes[0]
  // 最低价
  const validCloses = closes.filter((v: number | null) => v !== null) as number[]
  const minPrice = validCloses.length ? Math.min(...validCloses) : null
  // 收盘价（最后一根非 null）
  const closePrice = validCloses.length ? validCloses[validCloses.length - 1] : null

  // 构造 markLine 数据
  const markLineData: any[] = [
    { yAxis: refPrice, label: { show: true, position: 'insideEndTop', color: '#ffcc00', fontSize: 9, formatter: `昨收 ${refPrice.toFixed(2)}` } },
  ]
  if (minPrice !== null) {
    const minPct = refPrice ? ((minPrice - refPrice) / refPrice * 100) : 0
    const minPctStr = (minPct >= 0 ? '+' : '') + minPct.toFixed(2) + '%'
    markLineData.push({ yAxis: minPrice, lineStyle: { color: '#26a69a' }, label: { show: true, position: 'insideStartTop', color: '#26a69a', fontSize: 9, formatter: `低 ${minPrice.toFixed(2)} (${minPctStr})` } })
  }
  if (closePrice !== null) {
    const closePct = refPrice ? ((closePrice - refPrice) / refPrice * 100) : 0
    const closePctStr = (closePct >= 0 ? '+' : '') + closePct.toFixed(2) + '%'
    markLineData.push({ yAxis: closePrice, lineStyle: { color: '#ef5350' }, label: { show: true, position: 'insideEndBottom', color: '#ef5350', fontSize: 9, formatter: `收 ${closePrice.toFixed(2)} (${closePctStr})` } })
  }
  const option: echarts.EChartsOption = {
    animation: false,
    backgroundColor: '#1e222d',
    grid: [
      { left: 56, right: 12, top: 24, bottom: '38%' },
      { left: 56, right: 12, top: '68%', bottom: 24 },
    ],
    xAxis: [
      {
        type: 'category', data: times, gridIndex: 0,
        axisLabel: { color: '#787b86', fontSize: 9, interval: Math.floor(times.length / 5) },
        axisLine: { lineStyle: { color: '#363a45' } },
        axisTick: { show: false },
      },
      {
        type: 'category', data: times, gridIndex: 1,
        axisLabel: { color: '#787b86', fontSize: 9, interval: Math.floor(times.length / 5) },
        axisLine: { lineStyle: { color: '#363a45' } },
        axisTick: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true, gridIndex: 0, splitNumber: 4,
        splitLine: { lineStyle: { color: '#2a2e39' } },
        axisLabel: { color: '#787b86', fontSize: 10, formatter: (v: number) => v.toFixed(2) },
      },
      {
        scale: false, min: 0, max: (v: any) => (v?.max ?? 0) * 1.05,
        gridIndex: 1, splitNumber: 2,
        splitLine: { show: false },
        axisLabel: { color: '#787b86', fontSize: 9 },
      },
    ],
    axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 }],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#787b86' } },
      backgroundColor: '#1e222d',
      borderColor: '#363a45',
      textStyle: { color: '#d1d4dc', fontSize: 11 },
      formatter: (params: any) => {
        if (!Array.isArray(params) || !params.length) return ''
        const idx = params[0].dataIndex
        const bar = bars[idx]
        if (!bar) return ''
        const t = times[idx] ?? ''
        const c = (bar.close ?? 0).toFixed(2)
        const chg = refPrice ? ((bar.close - refPrice) / refPrice * 100).toFixed(2) : '0.00'
        const clr = (bar.close ?? 0) >= refPrice ? '#ef5350' : '#26a69a'
        return `<div style="line-height:1.6"><b style="color:#d1d4dc">${t}</b><br/>价格: <span style="color:${clr}">${c}</span><br/>涨幅: <span style="color:${clr}">${chg}%</span><br/>成交量: ${(bar.volume ?? 0).toLocaleString()}</div>`
      },
    },
    series: [
      {
        name: '价格', type: 'line', data: closes, xAxisIndex: 0, yAxisIndex: 0,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#5b8ff9' },
        areaStyle: { color: 'rgba(91,143,249,0.08)' },
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { type: 'dashed', color: '#ffcc00', width: 1 },
          data: markLineData,
        },
      },
      { name: '成交量', type: 'bar', data: vols, xAxisIndex: 1, yAxisIndex: 1 },
    ],
  }
  intradayChart.setOption(option, true)
}

function handleResize() {
  updateContainerHeight()
  if (!chart) return
  scheduleResize()
}

onMounted(() => {
  updateContainerHeight()
  if (wrapperRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      handleResize()
    })
    resizeObserver.observe(wrapperRef.value)
  }
  safeRenderChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  requestManager.cancelAll()
  window.removeEventListener('resize', handleResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  if (pendingResizeFrame !== null) {
    cancelAnimationFrame(pendingResizeFrame)
    pendingResizeFrame = null
  }
  if (pendingGridFrame !== null) {
    cancelAnimationFrame(pendingGridFrame)
    pendingGridFrame = null
  }
  if (cancelPendingFullKlineRender) {
    cancelPendingFullKlineRender()
    cancelPendingFullKlineRender = null
  }
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
  document.removeEventListener('mousemove', onPopupDrag)
  document.removeEventListener('mouseup', stopPopupDrag)
  intradayChart?.dispose()
  intradayChart = null
  chart?.dispose()
  chart = null
})

defineExpose({ renderChart: safeRenderChart })

// ── 长按区间统计 ─────────────────────────────────────────────────────────
const LONG_PRESS_DELAY = 300 // ms
let longPressTimer: ReturnType<typeof setTimeout> | null = null

interface RangeStats {
  barCount: number
  startDate: string
  endDate: string
  priceChange: number        // %
  high: number
  low: number
  amplitude: number          // %
  bullTurnoverSum: number    // 阳线换手率累计 %
  bearTurnoverSum: number    // 阴线换手率累计 %
}

const rangeSelecting = ref(false)
const rangeAnchorIdx = ref<number | null>(null)
const rangeCursorIdx = ref<number | null>(null)
const rangeStats = ref<RangeStats | null>(null)
const rangeStatsPos = ref({ x: 0, y: 0 })
const rangeSelectionRect = ref({ left: 0, top: 0, width: 0, height: 0, visible: false })

function getBarIdxFromPixel(clientX: number): number | null {
  if (!chart || !wrapperRef.value) return null
  const rect = wrapperRef.value.getBoundingClientRect()
  const localX = clientX - rect.left
  const result = chart.convertFromPixel({ gridIndex: 0 }, [localX, 0])
  if (!Array.isArray(result) || result[0] == null) return null
  const idx = Math.round(result[0] as number)
  return Math.max(0, Math.min(renderedBars.value.length - 1, idx))
}

function computeRangeStats(a: number, b: number): RangeStats {
  const bars = renderedBars.value
  const lo = Math.min(a, b)
  const hi = Math.max(a, b)
  const slice = bars.slice(lo, hi + 1)
  const startBar = slice[0]
  const endBar = slice[slice.length - 1]
  const priceChange = startBar?.close ? ((endBar.close - startBar.close) / startBar.close) * 100 : 0
  const allHigh = Math.max(...slice.map((b: any) => b.high ?? 0))
  const allLow = Math.min(...slice.map((b: any) => b.low ?? Infinity))
  const amplitude = allLow > 0 ? ((allHigh - allLow) / allLow) * 100 : 0
  let bullTurnover = 0, bearTurnover = 0
  for (const bar of slice) {
    const t = bar.turnover ?? 0
    if ((bar.close ?? 0) >= (bar.open ?? 0)) bullTurnover += t
    else bearTurnover += t
  }
  return {
    barCount: slice.length,
    startDate: startBar?.date ?? '',
    endDate: endBar?.date ?? '',
    priceChange,
    high: allHigh,
    low: allLow,
    amplitude,
    bullTurnoverSum: bullTurnover,
    bearTurnoverSum: bearTurnover,
  }
}

function updateSelectionRect(anchorIdx: number, cursorIdx: number) {
  if (!chart || !wrapperRef.value) return
  const lo = Math.min(anchorIdx, cursorIdx)
  const hi = Math.max(anchorIdx, cursorIdx)
  const p1 = chart.convertToPixel({ gridIndex: 0 }, [lo, 0])
  const p2 = chart.convertToPixel({ gridIndex: 0 }, [hi, 0])
  if (!p1 || !p2) return
  // Get grid top/height from chart getOption
  const option = chart.getOption() as any
  const grid = Array.isArray(option?.grid) ? option.grid[0] : option?.grid
  const topPx = typeof grid?.top === 'number' ? grid.top : 0
  const heightPx = typeof grid?.height === 'number' ? grid.height : (wrapperRef.value.clientHeight - topPx - 55)
  rangeSelectionRect.value = {
    left: (p1 as number[])[0],
    top: topPx,
    width: Math.max(1, (p2 as number[])[0] - (p1 as number[])[0]),
    height: heightPx,
    visible: true,
  }
}

function onChartMouseDown(e: MouseEvent) {
  // Only trigger on the main chart area, ignore dividers
  if (shouldIgnoreChartPointerEvent(e)) return
  longPressTimer = setTimeout(() => {
    rangeSelecting.value = true
    const idx = getBarIdxFromPixel(e.clientX)
    if (idx !== null) {
      rangeAnchorIdx.value = idx
      rangeCursorIdx.value = idx
    }
    longPressTimer = null
  }, LONG_PRESS_DELAY)
}

function onChartMouseMove(e: MouseEvent) {
  if (!rangeSelecting.value || rangeAnchorIdx.value === null) return
  const idx = getBarIdxFromPixel(e.clientX)
  if (idx !== null) {
    rangeCursorIdx.value = idx
    updateSelectionRect(rangeAnchorIdx.value, idx)
  }
}

function onChartMouseUp(e: MouseEvent) {
  if (longPressTimer !== null) {
    clearTimeout(longPressTimer)
    longPressTimer = null
    return
  }
  if (!rangeSelecting.value) return
  rangeSelecting.value = false
  const a = rangeAnchorIdx.value
  const b = rangeCursorIdx.value
  if (a !== null && b !== null && a !== b) {
    rangeStats.value = computeRangeStats(a, b)
    if (wrapperRef.value) {
      const rect = wrapperRef.value.getBoundingClientRect()
      rangeStatsPos.value = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      }
    }
  } else {
    rangeSelectionRect.value = { ...rangeSelectionRect.value, visible: false }
  }
  rangeAnchorIdx.value = null
  rangeCursorIdx.value = null
}

function closeRangeStats() {
  rangeStats.value = null
  rangeSelectionRect.value = { ...rangeSelectionRect.value, visible: false }
}

// Clean up long-press timer on unmount
onUnmounted(() => {
  if (longPressTimer !== null) clearTimeout(longPressTimer)
})
</script>

<template>
  <div
    class="kline-chart-wrapper"
    ref="wrapperRef"
    @mousedown="onChartMouseDown"
    @mousemove="onChartMouseMove"
    @mouseup="onChartMouseUp"
    @mouseleave="onChartMouseUp"
    @dblclick="onChartDoubleClick"
  >
    <div ref="chartRef" v-loading="showBlockingLoading" class="kline-chart"></div>

    <!-- 时间跨度快速缩放按钮（右上角浮层）-->
    <div class="zoom-presets">
      <button
        v-for="preset in zoomPresets"
        :key="preset.label"
        class="zoom-preset-btn"
        :class="{ active: currentZoomBars === preset.bars }"
        type="button"
        @click="handleZoomPreset(preset.bars)"
      >{{ preset.label }}</button>
    </div>

    <div class="sub-indicator-selector">
      <button
        v-for="item in SUB_INDICATOR_OPTIONS"
        :key="item.key"
        class="sub-indicator-btn"
        :class="{ active: activeSubIndicator === item.key }"
        type="button"
        :title="`切换副图指标：${item.label}`"
        @click.stop="selectSubIndicator(item.key)"
      >{{ item.label }}</button>
    </div>

    <div v-if="chartState.errorMessage || chartState.emptyMessage" class="chart-status-overlay">
      <div class="chart-status-card">
        <div class="chart-status-title">
          {{ chartState.errorMessage ? 'K线加载失败' : '暂无K线数据' }}
        </div>
        <div class="chart-status-desc">
          {{ chartState.errorMessage || chartState.emptyMessage }}
        </div>
        <button class="chart-status-retry" type="button" @click="retryRender">重试</button>
      </div>
    </div>

    <div
      v-if="cursorLatestChange"
      class="cursor-latest-change"
      :class="{ positive: cursorLatestChange.change >= 0, negative: cursorLatestChange.change < 0 }"
    >
      <span>{{ cursorLatestChange.fromDate }} → {{ cursorLatestChange.toDate }}</span>
      <strong>{{ cursorLatestChange.change >= 0 ? '+' : '' }}{{ cursorLatestChange.change.toFixed(2) }}</strong>
      <strong>{{ cursorLatestChange.changePct >= 0 ? '+' : '' }}{{ cursorLatestChange.changePct.toFixed(2) }}%</strong>
      <span>{{ cursorLatestChange.bars }}根</span>
    </div>

    <!-- 副图左上角：指标名称 + 一键折叠按钮（reactive，拖拽时自动跟随）；双击可最大化/恢复该副图 -->
    <div
      v-for="label in subPanelLabels"
      :key="label.key"
      class="panel-label-row"
      :style="{ top: label.top + 'px' }"
      @dblclick.stop="toggleMaximizeSubPanel(label.key)"
    >
      <span class="panel-label-text">{{ label.name }}</span>
      <span
        v-if="expandedSubPanel === label.key"
        class="panel-maximize-badge"
        title="双击恢复"
      >⛶</span>
      <button
        class="panel-collapse-btn"
        :class="{ collapsed: collapsedPanels.has(label.key) }"
        type="button"
        :title="collapsedPanels.has(label.key) ? '展开' : '折叠'"
        @click.stop="togglePanelCollapse(label.key)"
      >{{ collapsedPanels.has(label.key) ? '▶' : '▼' }}</button>
    </div>

    <!-- 分时K线弹窗（日K点击触发，可拖动）-->
    <div v-if="showIntraday" class="intraday-popup" :style="popupStyle">
      <div class="intraday-popup-header" @mousedown="startPopupDrag">
        <button class="intraday-nav-btn" type="button" :disabled="!canGoPrev()" @click.stop="goPrevDate">◀</button>
        <span class="intraday-popup-title">{{ props.code }} {{ intradayDate }} 分时K线</span>
        <button class="intraday-nav-btn" type="button" :disabled="!canGoNext()" @click.stop="goNextDate">▶</button>
        <span class="intraday-period-btns">
          <button
            class="intraday-period-btn"
            :class="{ active: intradayPeriod === '1' }"
            type="button"
            @click.stop="switchIntradayPeriod('1')"
          >1分</button>
          <button
            class="intraday-period-btn"
            :class="{ active: intradayPeriod === '15' }"
            type="button"
            @click.stop="switchIntradayPeriod('15')"
          >15分</button>
        </span>
        <button class="intraday-close-btn" type="button" @click.stop="closeIntradayPopup">×</button>
      </div>
      <div v-if="intradayLoading" class="intraday-body-msg">加载中…</div>
      <div v-else-if="intradayError" class="intraday-body-msg intraday-body-err">{{ intradayError }}</div>
      <div v-else ref="intradayChartRef" class="intraday-chart-body"></div>
    </div>

    <!-- 面板之间的可拖拽分割线 -->
    <div
      v-for="(top, i) in dividerPositions"
      :key="i"
      class="panel-divider"
      :class="{ 'panel-divider--active': isDragging }"
      :style="{ top: top + 'px' }"
      @mousedown="startDrag($event, i)"
    >
      <div class="divider-handle"></div>
    </div>

    <!-- 长按区间选择蒙层 -->
    <div
      v-if="rangeSelectionRect.visible"
      class="range-selection-rect"
      :style="{
        left: rangeSelectionRect.left + 'px',
        top: rangeSelectionRect.top + 'px',
        width: rangeSelectionRect.width + 'px',
        height: rangeSelectionRect.height + 'px',
      }"
    ></div>

    <!-- 区间统计浮层 -->
    <div
      v-if="rangeStats"
      class="range-stats-popup"
      :style="{
        left: Math.min(rangeStatsPos.x + 12, wrapperRef ? wrapperRef.clientWidth - 210 : 0) + 'px',
        top: Math.max(rangeStatsPos.y - 20, 0) + 'px',
      }"
    >
      <div class="range-stats-header">
        <span>区间统计</span>
        <button class="range-stats-close" type="button" @click.stop="closeRangeStats">×</button>
      </div>
      <div class="range-stats-row">
        <span class="range-stats-label">区间</span>
        <span class="range-stats-value">{{ rangeStats.startDate }} ~ {{ rangeStats.endDate }}</span>
      </div>
      <div class="range-stats-row">
        <span class="range-stats-label">K线数</span>
        <span class="range-stats-value">{{ rangeStats.barCount }} 根</span>
      </div>
      <div class="range-stats-row">
        <span class="range-stats-label">区间涨幅</span>
        <span
          class="range-stats-value"
          :style="{ color: rangeStats.priceChange >= 0 ? '#ef5350' : '#26a69a' }"
        >{{ rangeStats.priceChange >= 0 ? '+' : '' }}{{ rangeStats.priceChange.toFixed(2) }}%</span>
      </div>
      <div class="range-stats-row">
        <span class="range-stats-label">最高</span>
        <span class="range-stats-value" style="color:#ef5350">{{ rangeStats.high.toFixed(2) }}</span>
      </div>
      <div class="range-stats-row">
        <span class="range-stats-label">最低</span>
        <span class="range-stats-value" style="color:#26a69a">{{ rangeStats.low.toFixed(2) }}</span>
      </div>
      <div class="range-stats-row">
        <span class="range-stats-label">振幅</span>
        <span class="range-stats-value">{{ rangeStats.amplitude.toFixed(2) }}%</span>
      </div>
      <div class="range-stats-row">
        <span class="range-stats-label">阳线换手</span>
        <span class="range-stats-value" style="color:#ef5350">{{ rangeStats.bullTurnoverSum.toFixed(2) }}%</span>
      </div>
      <div class="range-stats-row">
        <span class="range-stats-label">阴线换手</span>
        <span class="range-stats-value" style="color:#26a69a">{{ rangeStats.bearTurnoverSum.toFixed(2) }}%</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kline-chart-wrapper {
  width: 100%;
  height: 100%;
  min-height: 500px;
  position: relative;
}
.kline-chart {
  width: 100%;
  height: 100%;
  background: #131722;
}
.chart-status-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(19, 23, 34, 0.55);
  z-index: 20;
}
.chart-status-card {
  min-width: 280px;
  max-width: 520px;
  padding: 16px 20px;
  background: rgba(16, 20, 31, 0.9);
  border: 1px solid rgba(90, 103, 130, 0.6);
  border-radius: 8px;
  color: #e8ecf3;
  text-align: center;
}
.chart-status-title {
  font-size: 15px;
  font-weight: 600;
}
.chart-status-desc {
  margin-top: 8px;
  font-size: 13px;
  color: #c6cedd;
  word-break: break-word;
}
.chart-status-retry {
  margin-top: 12px;
  border: none;
  border-radius: 4px;
  padding: 6px 14px;
  background: #3b82f6;
  color: #fff;
  cursor: pointer;
}
.chart-status-retry:hover {
  background: #2563eb;
}
.cursor-latest-change {
  position: absolute;
  right: 64px;
  bottom: 30px;
  z-index: 18;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 8px;
  border: 1px solid #363a45;
  border-radius: 4px;
  background: rgba(30, 34, 45, 0.92);
  color: #d1d4dc;
  font-size: 11px;
  line-height: 1.2;
  pointer-events: none;
  box-shadow: 0 2px 10px rgba(0,0,0,0.35);
}
.cursor-latest-change.positive strong {
  color: #ef5350;
}
.cursor-latest-change.negative strong {
  color: #26a69a;
}
.panel-divider {
  position: absolute;
  left: 60px;
  right: 60px;
  height: 10px;
  cursor: row-resize;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
}
.panel-divider:hover .divider-handle,
.panel-divider--active .divider-handle {
  background: rgba(41, 98, 255, 0.6);
  height: 3px;
}
.divider-handle {
  width: 60px;
  height: 2px;
  border-radius: 2px;
  background: rgba(120, 123, 134, 0.3);
  transition: background 0.15s, height 0.15s;
}
/* ── 长按区间选择 ────────────────────────────────────────── */
.range-selection-rect {
  position: absolute;
  pointer-events: none;
  background: rgba(91, 143, 249, 0.12);
  border: 1px solid rgba(91, 143, 249, 0.5);
  z-index: 20;
}
.range-stats-popup {
  position: absolute;
  z-index: 40;
  background: #1e222d;
  border: 1px solid #363a45;
  border-radius: 6px;
  padding: 8px 10px;
  min-width: 195px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.5);
  font-size: 12px;
  color: #d1d4dc;
}
.range-stats-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 600;
  color: #9598a1;
  border-bottom: 1px solid #2a2e39;
  padding-bottom: 5px;
}
.range-stats-close {
  background: transparent;
  border: none;
  color: #787b86;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}
.range-stats-close:hover { color: #ef5350; }
.range-stats-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 3px;
}
.range-stats-label {
  color: #787b86;
  white-space: nowrap;
}
.range-stats-value {
  font-weight: 500;
  text-align: right;
}
/* ── 时间跨度缩放按钮 ─────────────────────────────────────────── */
.zoom-presets {
  position: absolute;
  top: 6px;
  right: 64px;
  display: flex;
  gap: 3px;
  z-index: 15;
  pointer-events: all;
}
.zoom-preset-btn {
  padding: 2px 7px;
  font-size: 11px;
  line-height: 1.5;
  color: #787b86;
  background: transparent;
  border: 1px solid #363a45;
  border-radius: 3px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
  user-select: none;
}
.zoom-preset-btn:hover {
  color: #d1d4dc;
  border-color: #5b8ff9;
}
.zoom-preset-btn.active {
  color: #fff;
  background: #2962ff;
  border-color: #2962ff;
}
.sub-indicator-selector {
  position: absolute;
  top: 6px;
  right: 250px;
  z-index: 15;
  display: flex;
  gap: 3px;
  pointer-events: all;
}
.sub-indicator-btn {
  min-width: 45px;
  padding: 2px 8px;
  font-size: 11px;
  line-height: 1.5;
  color: #a8adbd;
  background: rgba(19, 23, 34, 0.72);
  border: 1px solid #363a45;
  border-radius: 3px;
  cursor: pointer;
  user-select: none;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}
.sub-indicator-btn:hover {
  color: #d1d4dc;
  border-color: #5b8ff9;
}
.sub-indicator-btn.active {
  color: #fff;
  background: #2962ff;
  border-color: #2962ff;
}
/* ── 副图指标名称标签 + 折叠按钮 ─────────────────────────────── */
.panel-label-row {
  position: absolute;
  left: 62px;
  display: flex;
  align-items: center;
  gap: 4px;
  pointer-events: all;
  z-index: 5;
}
.panel-label-text {
  font-size: 10px;
  font-weight: 500;
  color: #9598a1;
  user-select: none;
  line-height: 1;
  letter-spacing: 0.2px;
}
.panel-collapse-btn {
  font-size: 8px;
  line-height: 1;
  color: #5b607a;
  background: transparent;
  border: none;
  padding: 1px 2px;
  cursor: pointer;
  transition: color 0.15s;
  user-select: none;
}
.panel-collapse-btn:hover {
  color: #d1d4dc;
}
.panel-collapse-btn.collapsed {
  color: #5b8ff9;
}
.panel-maximize-badge {
  font-size: 10px;
  color: #f0a500;
  margin-left: 2px;
  cursor: pointer;
  user-select: none;
  line-height: 1;
}
/* ── 分时K线弹窗 ─────────────────────────────────────────── */
.intraday-popup {
  position: absolute;
  bottom: 50px;
  right: 60px;
  width: 540px;
  height: 360px;
  z-index: 30;
  background: #1e222d;
  border: 1px solid #363a45;
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 20px rgba(0,0,0,0.6);
}
.intraday-popup-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-bottom: 1px solid #2a2e39;
  flex-shrink: 0;
  cursor: move;
  user-select: none;
}
.intraday-popup-title {
  font-size: 11px;
  color: #d1d4dc;
  font-weight: 500;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.intraday-period-btns {
  display: flex;
  gap: 2px;
}
.intraday-period-btn {
  padding: 1px 6px;
  font-size: 10px;
  color: #787b86;
  background: transparent;
  border: 1px solid #363a45;
  border-radius: 2px;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s, background 0.12s;
}
.intraday-period-btn:hover {
  color: #d1d4dc;
  border-color: #5b8ff9;
}
.intraday-period-btn.active {
  color: #fff;
  background: #2962ff;
  border-color: #2962ff;
}
.intraday-close-btn {
  font-size: 14px;
  color: #787b86;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
  transition: color 0.12s;
}
.intraday-close-btn:hover {
  color: #ef5350;
}
.intraday-chart-body {
  flex: 1;
  width: 100%;
  min-height: 200px;
}
.intraday-body-msg {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #787b86;
}
.intraday-body-err {
  color: #ef5350;
}
/* ── 分时弹窗日期导航按钮 ─────────────────────────────────── */
.intraday-nav-btn {
  font-size: 10px;
  color: #787b86;
  background: transparent;
  border: 1px solid #363a45;
  border-radius: 2px;
  padding: 1px 4px;
  cursor: pointer;
  line-height: 1;
  transition: color 0.12s, border-color 0.12s;
}
.intraday-nav-btn:hover:not(:disabled) {
  color: #d1d4dc;
  border-color: #5b8ff9;
}
.intraday-nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
</style>
