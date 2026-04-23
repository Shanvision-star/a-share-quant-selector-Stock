<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { getKline, getIntradayKline } from '@/api'
import { createRequestManager, isAbortError } from '@/api/requestManager'
import { buildMainKlineRequestKey } from '@/components/klineRequest'

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
const containerHeight = ref(600)
const requestManager = createRequestManager()
const chartState = reactive({
  errorMessage: '',
  emptyMessage: '',
})

// ============ 可拖拽面板尺寸状态 ============
const PANEL_KEYS = ['main', 'volume', 'adjVolume', 'kdj', 'macd'] as const
type PanelKey = typeof PANEL_KEYS[number]
const TOP_MARGIN = 40
const BOTTOM_MARGIN = 55   // 增大底部留白，避免横向时间轴与 dataZoom 滑块重叠
const PANEL_GAP = 10
const MIN_PANEL_PX = 40

// 五个面板的高度比例（加起来 = 1.0）
// main=主图, volume=成交量, adjVolume=还原成交量, kdj, macd
// 副图默认折叠，主图占据大部分空间
const panelRatios = reactive<Record<PanelKey, number>>({
  main: 0.80,
  volume: 0.05,
  adjVolume: 0.05,
  kdj: 0.05,
  macd: 0.05,
})

function getUsableHeight() {
  return containerHeight.value - TOP_MARGIN - BOTTOM_MARGIN - (PANEL_KEYS.length - 1) * PANEL_GAP
}

function computeGrids() {
  const usable = getUsableHeight()
  let top = TOP_MARGIN
  return PANEL_KEYS.map((key) => {
    const h = panelRatios[key] * usable
    const grid = { left: 60, right: 60, top, height: h }
    top += h + PANEL_GAP
    return grid
  })
}

// ── 副图左上角指标名称标签（与面板高度联动，拖拽时自动更新）─────────────
const subPanelLabels = computed(() => {
  const grids = computeGrids()
  return [
    { key: 'volume' as PanelKey,    name: '成交量',    top: grids[1].top + 3 },
    { key: 'adjVolume' as PanelKey, name: '还原成交量', top: grids[2].top + 3 },
    { key: 'kdj' as PanelKey,       name: 'KDJ',       top: grids[3].top + 3 },
    { key: 'macd' as PanelKey,      name: 'MACD',      top: grids[4].top + 3 },
  ]
})

// 分割线的 CSS top 位置（像素）
const dividerPositions = computed(() => {
  const usable = getUsableHeight()
  const positions: number[] = []
  let top = TOP_MARGIN
  for (let i = 0; i < PANEL_KEYS.length - 1; i++) {
    top += panelRatios[PANEL_KEYS[i]] * usable
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

  const newUpper = dragStartRatios[upperKey] + deltaRatio
  const newLower = dragStartRatios[lowerKey] - deltaRatio

  if (newUpper >= minRatio && newLower >= minRatio) {
    panelRatios[upperKey] = newUpper
    panelRatios[lowerKey] = newLower
    scheduleGridUpdate()
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
    const res = await getKline(
      props.code,
      { period: props.period, limit: props.limit, adjust: props.adjust as 'qfq' | 'hfq' | 'nfq' },
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
      chartState.emptyMessage = '当前股票暂无可展示的K线数据。'
      return
    }

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

    // 记录总轴长度，供时间跨度按钮 handleZoomPreset 计算百分比
    totalAxisLength.value = axisDates.length

    // 智能初始缩放窗口：日线默认最近 120 根（约半年），周线 52 根（约一年）
    // 用户点过预设按钮后 currentZoomBars 有值，保持用户选择；切换股票/周期时会重置为 0
    const defaultWindowBars = props.period === 'weekly' ? 52 : 120
    const effectiveBars = currentZoomBars.value > 0 ? currentZoomBars.value : defaultWindowBars
    const zoomStart = axisDates.length > effectiveBars
      ? Math.max(0, ((axisDates.length - effectiveBars) / axisDates.length) * 100)
      : 0

    // 策略信号不参与后端 K 线计算，只在前端主图上追加成标注箭头。
    const signalMarks = (props.signals || [])
      .map((signal: any, index: number) => {
        const signalDate = signal?.date || signal?.signal_date || signal?.trade_date
        const signalPrice = toFiniteNumber(signal?.close ?? signal?.trigger_price)
        if (!signalDate || signalPrice === null || !dateSet.has(signalDate)) return null

        return {
          name: `${signal.label || signal.category || 'signal'}-${index}`,
          coord: [signalDate, Number((signalPrice * 0.97).toFixed(2))],
          value: signal.category?.includes('b1') ? 'B1' : signal.category?.includes('bowl') ? 'BOWL' : 'B2',
          symbol: 'arrow',
          symbolSize: 12,
          symbolRotate: 180,
          itemStyle: {
            color: signal.category?.includes('b1') ? '#f5222d' : signal.category?.includes('bowl') ? '#faad14' : '#1890ff',
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
        backgroundColor: '#1e222d',
        borderColor: '#363a45',
        textStyle: { color: '#d1d4dc', fontSize: 12 },
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
              maLines += `<div><span style="color:${p.color}">●</span> ${sn}: ${Number(p.value).toFixed(2)}</div>`
            }
          }
          const turnoverStr = (bar as any).turnover > 0 ? `${((bar as any).turnover as number).toFixed(2)}%` : '-'
          const amountStr = (bar as any).amount > 0 ? `${((bar as any).amount as number).toFixed(2)}万` : '-'
          return `<div style="min-width:190px;line-height:1.7">
            <div style="font-weight:600;margin-bottom:4px;color:#d1d4dc">${bar.date}</div>
            <div>开: ${(bar.open ?? 0).toFixed(2)}&nbsp; 高: <span style="color:#ef5350">${(bar.high ?? 0).toFixed(2)}</span></div>
            <div>低: <span style="color:#26a69a">${(bar.low ?? 0).toFixed(2)}</span>&nbsp; 收: <span style="color:${changeColor}">${(bar.close ?? 0).toFixed(2)}</span></div>
            <div>涨跌: <span style="color:${changeColor}">${changeStr} (${changePct}%)</span></div>
            <div>成交量: ${(bar.volume ?? 0).toLocaleString()}</div>
            <div>成交额: ${amountStr}</div>
            <div>换手率: ${turnoverStr}</div>
            ${maLines}
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
        link: [{ xAxisIndex: [0, 1, 2, 3, 4] }],
      },
      // 五段 grid 分别承载主图、成交量、还原成交量、KDJ、MACD
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
          axisLabel: { show: false, formatter: (value: unknown) => formatAxisCategory(value) },
        },
        {
          type: 'category',
          data: axisDates,
          gridIndex: 4,
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
        { scale: true, gridIndex: 1, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        { scale: true, gridIndex: 2, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        { scale: true, gridIndex: 3, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        { scale: true, gridIndex: 4, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1, 2, 3, 4],
          start: zoomStart,
          end: 100,
          filterMode: 'weakFilter',
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
        },
        {
          type: 'slider',
          xAxisIndex: [0, 1, 2, 3, 4],
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
        { name: 'K', type: 'line', data: kData, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f5c878' } },
        { name: 'D', type: 'line', data: dData, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#42a5f5' } },
        { name: 'J', type: 'line', data: jData, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#ab47bc' } },
        { name: 'DIF', type: 'line', data: difData, xAxisIndex: 4, yAxisIndex: 4, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f5c878' } },
        { name: 'DEA', type: 'line', data: deaData, xAxisIndex: 4, yAxisIndex: 4, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#42a5f5' } },
        {
          name: 'MACD',
          type: 'bar',
          data: macdBars,
          xAxisIndex: 4,
          yAxisIndex: 4,
        },
      ],
    }

    applyOptionWithFallback(option)

    // 日K点击开启分时K线弹窗（先清除旧监听防止重复注册）
    if (chart) {
      chart.off('click')
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
// 默认所有副图均折叠，保存原始比例以便展开时恢复
const collapsedPanels = reactive(new Set<PanelKey>(['volume', 'adjVolume', 'kdj', 'macd']))
const savedPanelRatios: Partial<Record<PanelKey, number>> = {
  volume: 0.12,
  adjVolume: 0.12,
  kdj: 0.17,
  macd: 0.17,
}

function togglePanelCollapse(key: PanelKey) {
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
        scale: true, gridIndex: 1, splitNumber: 2,
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
</script>

<template>
  <div class="kline-chart-wrapper" ref="wrapperRef">
    <div ref="chartRef" v-loading="loading" class="kline-chart"></div>

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

    <!-- 副图左上角：指标名称 + 一键折叠按钮（reactive，拖拽时自动跟随）；双击可展开折叠面板 -->
    <div
      v-for="label in subPanelLabels"
      :key="label.key"
      class="panel-label-row"
      :style="{ top: label.top + 'px' }"
      @dblclick="togglePanelCollapse(label.key)"
    >
      <span class="panel-label-text">{{ label.name }}</span>
      <button
        class="panel-collapse-btn"
        :class="{ collapsed: collapsedPanels.has(label.key) }"
        type="button"
        :title="collapsedPanels.has(label.key) ? '展开' : '折叠'"
        @click="togglePanelCollapse(label.key)"
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
