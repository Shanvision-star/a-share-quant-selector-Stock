<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { getMiniKline } from '@/api'

const props = withDefaults(defineProps<{
  code: string
  days?: number
}>(), {
  days: 30,
})

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

onMounted(async () => {
  if (!chartRef.value) return
  try {
    const res = await getMiniKline(props.code, props.days)
    const data = res.data.data
    if (!data || data.length === 0) return

    // data: [[date, open, close, high, low], ...]
    const ohlc = data.map((d: any) => [d[1], d[2], d[3], d[4]])

    chart = echarts.init(chartRef.value, undefined, { renderer: 'svg', width: 120, height: 30 })
    chart.setOption({
      animation: false,
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: 'category', show: false, data: data.map((d: any) => d[0]) },
      yAxis: { type: 'value', show: false, scale: true },
      series: [{
        type: 'candlestick',
        data: ohlc,
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
})

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
