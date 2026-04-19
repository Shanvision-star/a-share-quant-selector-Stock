<script setup lang="ts">
import { ref, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import { getMiniKline } from '@/api'

const props = withDefaults(defineProps<{
  code: string
  days?: number
  dataPoints?: any[]
}>(), {
  days: 30,
  dataPoints: () => [],
})

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function getChartDataPayload(data: any[]) {
  return {
    categories: data.map((d: any) => d[0]),
    ohlc: data.map((d: any) => [d[1], d[2], d[3], d[4]]),
  }
}

async function renderMiniKline() {
  if (!chartRef.value) return

  let data = Array.isArray(props.dataPoints) ? props.dataPoints : []
  try {
    if (!data.length) {
      const res = await getMiniKline(props.code, props.days)
      data = res.data.data
    }

    if (!data || data.length === 0) return

    const payload = getChartDataPayload(data)

    if (!chart) {
      chart = echarts.init(chartRef.value, undefined, { renderer: 'svg', width: 120, height: 30 })
    }

    chart.setOption({
      animation: false,
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: 'category', show: false, data: payload.categories },
      yAxis: { type: 'value', show: false, scale: true },
      series: [{
        type: 'candlestick',
        data: payload.ohlc,
        itemStyle: {
          color: '#ef5350',
          color0: '#26a69a',
          borderColor: '#ef5350',
          borderColor0: '#26a69a',
        },
        barWidth: 2,
      }],
    })
  } catch {
    // 静默失败
  }
}

watch(
  () => [props.code, props.days, props.dataPoints],
  () => {
    void renderMiniKline()
  },
  { immediate: true, deep: true },
)

onUnmounted(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="chartRef" class="mini-kline"></div>
</template>

<style scoped>
.mini-kline {
  width: 120px;
  height: 30px;
}
</style>
