<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import { getKline } from '@/api'

const props = withDefaults(defineProps<{
  code: string
  period?: string
  limit?: number
  signals?: Array<Record<string, any>>
  showShortTermTrend?: boolean
  showBullBearLine?: boolean
}>(), {
  period: 'daily',
  limit: 250,
  signals: () => [],
  showShortTermTrend: true,
  showBullBearLine: true,
})

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
const loading = ref(false)

async function renderChart() {
  if (!chartRef.value) return
  loading.value = true

  try {
    // 当前组件自己取 K 线数据，父组件只负责传入叠加用的策略信号和显示开关。
    const res = await getKline(props.code, { period: props.period, limit: props.limit })
    const data = res.data.data
    if (!data?.bars?.length) return

    const { bars, indicators } = data
    const dates = bars.map((bar: any) => bar.date)
    const ohlc = bars.map((bar: any) => [bar.open, bar.close, bar.low, bar.high])
    const volumes = bars.map((bar: any) => ({
      value: bar.volume,
      itemStyle: { color: bar.close >= bar.open ? '#ef5350' : '#26a69a' },
    }))

    // 策略信号不参与后端 K 线计算，只在前端主图上追加成标注箭头。
    const signalMarks = (props.signals || []).map((signal: any, index: number) => ({
      name: `${signal.label || signal.category || 'signal'}-${index}`,
      coord: [signal.date, signal.close * 0.97],
      value: signal.category?.includes('b1') ? 'B1' : signal.category?.includes('bowl') ? 'BOWL' : 'B2',
      symbol: 'arrow',
      symbolSize: 12,
      symbolRotate: 180,
      itemStyle: {
        color: signal.category?.includes('b1') ? '#f5222d' : signal.category?.includes('bowl') ? '#faad14' : '#1890ff',
      },
      label: {
        show: true,
        formatter: (params: any) => params.value,
        position: 'bottom',
        color: '#fff',
        fontSize: 10,
      },
    }))

    if (!chart) {
      chart = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
    }

    const option: echarts.EChartsOption = {
      animation: false,
      backgroundColor: '#131722',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: '#1e222d',
        borderColor: '#363a45',
        textStyle: { color: '#d1d4dc', fontSize: 12 },
      },
      legend: {
        data: ['MA5', 'MA10', 'MA20', 'MA60', '短期趋势线', '知行多空线'],
        top: 5,
        textStyle: { color: '#787b86', fontSize: 11 },
        itemWidth: 14,
        itemHeight: 2,
        selected: {
          '短期趋势线': props.showShortTermTrend,
          '知行多空线': props.showBullBearLine,
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: [0, 1, 2, 3] }],
      },
      // 四段 grid 分别承载主图、成交量、KDJ、MACD，便于统一缩放和联动十字线。
      grid: [
        { left: 60, right: 60, top: 40, height: '40%' },
        { left: 60, right: 60, top: '52%', height: '10%' },
        { left: 60, right: 60, top: '65%', height: '12%' },
        { left: 60, right: 60, top: '80%', height: '12%' },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLine: { lineStyle: { color: '#363a45' } }, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 1, axisLine: { lineStyle: { color: '#363a45' } }, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 2, axisLine: { lineStyle: { color: '#363a45' } }, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 3, axisLine: { lineStyle: { color: '#363a45' } }, axisLabel: { color: '#787b86', fontSize: 10 } },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        { scale: true, gridIndex: 1, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        { scale: true, gridIndex: 2, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
        { scale: true, gridIndex: 3, splitNumber: 2, splitLine: { lineStyle: { color: '#1e222d' } }, axisLabel: { color: '#787b86' } },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: 60, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, 2, 3], start: 60, end: 100, bottom: 5, height: 20, borderColor: '#363a45', fillerColor: 'rgba(41,98,255,0.2)', handleStyle: { color: '#2962ff' } },
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
        { name: 'MA5', type: 'line', data: indicators.ma5, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f5c878' } },
        { name: 'MA10', type: 'line', data: indicators.ma10, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#ff6d9e' } },
        { name: 'MA20', type: 'line', data: indicators.ma20, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#42a5f5' } },
        { name: 'MA60', type: 'line', data: indicators.ma60, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#ab47bc' } },
        { name: '短期趋势线', type: 'line', data: indicators.short_term_trend, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#ff9800', type: 'dashed' } },
        { name: '知行多空线', type: 'line', data: indicators.bull_bear_line, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#00bcd4', type: 'dashed' } },
        { name: 'Volume', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1 },
        { name: 'K', type: 'line', data: indicators.K, xAxisIndex: 2, yAxisIndex: 2, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f5c878' } },
        { name: 'D', type: 'line', data: indicators.D, xAxisIndex: 2, yAxisIndex: 2, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#42a5f5' } },
        { name: 'J', type: 'line', data: indicators.J, xAxisIndex: 2, yAxisIndex: 2, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#ab47bc' } },
        { name: 'DIF', type: 'line', data: indicators.DIF, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f5c878' } },
        { name: 'DEA', type: 'line', data: indicators.DEA, xAxisIndex: 3, yAxisIndex: 3, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#42a5f5' } },
        {
          name: 'MACD',
          type: 'bar',
          data: (indicators.MACD || []).map((value: number) => ({
            value,
            itemStyle: { color: value >= 0 ? '#ef5350' : '#26a69a' },
          })),
          xAxisIndex: 3,
          yAxisIndex: 3,
        },
      ],
    }

    chart.setOption(option, true)
  } finally {
    loading.value = false
  }
}

function handleResize() {
  chart?.resize()
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

watch(() => [props.code, props.period, props.limit, props.showShortTermTrend, props.showBullBearLine], () => {
  renderChart()
})

watch(() => props.signals, () => {
  renderChart()
}, { deep: true })

defineExpose({ renderChart })
</script>

<template>
  <div class="kline-chart-wrapper">
    <div ref="chartRef" v-loading="loading" class="kline-chart"></div>
  </div>
</template>

<style scoped>
.kline-chart-wrapper {
  width: 100%;
  height: 100%;
  min-height: 500px;
}
.kline-chart {
  width: 100%;
  height: 100%;
}
</style>
