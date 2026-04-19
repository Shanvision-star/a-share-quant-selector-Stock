<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, shallowRef } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'

const EARTH_SPIN_SYMBOL = 'path://M-12 0C-9-8-4-12 0-12C4-12 9-8 12 0C9 8 4 12 0 12C-4 12-9 8-12 0ZM-5-11C-8-6-8 6-5 11M5-11C8-6 8 6 5 11M-11 0H11'
const MOON_CRATER_SYMBOL = 'path://M-8-1C-6-6-1-8 4-7C7-5 8-1 7 3C5 6 1 8-3 8C-7 8-9 5-9 2C-9 0-8 0-8-1ZM2-6C3-7 5-7 6-6C7-5 7-3 6-2C5-1 3-1 2-2C1-3 1-5 2-6ZM-5 2C-4 1-2 1-1 2C0 3 0 5-1 6C-2 7-4 7-5 6C-6 5-6 3-5 2Z'

// ── state ──────────────────────────────────────────────────────────────────────
const chartEl = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
const loading = ref(true)
const error = ref('')

// animation
const animating = ref(false)
const frameIdx = ref(0)
const frameCursor = ref(0)
const speedLevel = ref(6)
const maxSpeedLevel = 20
const totalFrames = ref(0)

let traj: [number, number][] = []
let phaseEnds: number[] = []
let phases: { idx: number; name: string; color: string }[] = []
let rafId: number | undefined
let lastTickTs: number | undefined

// ── helpers ────────────────────────────────────────────────────────────────────
/** Return which phase index a trajectory-point belongs to */
function phaseOf(idx: number): number {
  for (let i = 0; i < phaseEnds.length; i++) {
    if (idx <= phaseEnds[i]) return i
  }
  return phaseEnds.length - 1
}

/** Colour by phase */
function colorOf(idx: number): string {
  return phases[phaseOf(idx)]?.color ?? '#ffffff'
}

function progressOf(idx: number): number {
  if (totalFrames.value <= 0) return 0
  return Math.max(0, Math.min(1, idx / totalFrames.value))
}

function earthSpinOf(idx: number): number {
  return progressOf(idx) * 2160
}

function moonAngleOf(idx: number): number {
  return progressOf(idx) * Math.PI * 2 * 0.9
}

function moonPositionOf(idx: number): [number, number] {
  const angle = moonAngleOf(idx)
  return [Number(Math.cos(angle).toFixed(6)), Number(Math.sin(angle).toFixed(6))]
}

function craftRotationOf(slice: [number, number][]): number {
  if (slice.length < 2) return 45
  const [x0, y0] = slice[Math.max(0, slice.length - 2)]
  const [x1, y1] = slice[slice.length - 1]
  return (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI + 90
}

function pointsPerSecond(): number {
  return 8 + (speedLevel.value - 1) * 2
}

function keyTrajectoryIndices() {
  const phase1End = phaseEnds[0] ?? 0
  const phase2End = phaseEnds[1] ?? phase1End
  const tliIdx = Math.min(Math.max(10, Math.round(phase1End * 0.18)), phase1End)
  const slingEnterIdx = Math.max(phase1End - 10, 0)
  const slingApexIdx = Math.round((phase1End + phase2End) / 2)
  const slingExitIdx = Math.min(phase2End + 24, traj.length - 1)
  return { tliIdx, slingEnterIdx, slingApexIdx, slingExitIdx }
}

function normalizeAxisRange(axisRange: any) {
  if (Array.isArray(axisRange)) {
    return {
      x: [axisRange[0] ?? -2.5, axisRange[1] ?? 2.5],
      y: [axisRange[2] ?? -2.0, axisRange[3] ?? 2.0],
    }
  }

  return {
    x: [axisRange?.x?.[0] ?? -2.5, axisRange?.x?.[1] ?? 2.5],
    y: [axisRange?.y?.[0] ?? -2.0, axisRange?.y?.[1] ?? 2.0],
  }
}

function normalizePayload(payload: any) {
  const raw = Array.isArray(payload) ? payload[0] : payload
  if (!raw || !Array.isArray(raw.trajectory) || raw.trajectory.length === 0) {
    throw new Error('后端未返回有效轨迹数据')
  }
  if (!Array.isArray(raw.phase_ends) || !Array.isArray(raw.phases)) {
    throw new Error('后端返回的阶段数据不完整')
  }

  return {
    ...raw,
    axis_range: normalizeAxisRange(raw.axis_range),
  }
}

// ── ECharts init ───────────────────────────────────────────────────────────────
function buildOption(data: any, trailLen: number): echarts.EChartsOption {
  const slice = traj.slice(0, trailLen + 1)
  const moonPosition = moonPositionOf(trailLen)
  const earthSpin = earthSpinOf(trailLen)
  const craftRotation = craftRotationOf(slice)
  const { tliIdx, slingEnterIdx, slingApexIdx, slingExitIdx } = keyTrajectoryIndices()

  // Build colour-coded segments for completed path
  const segSeries: any[] = []
  let seg: [number, number][] = []
  let prevPhase = -1
  for (let i = 0; i < slice.length; i++) {
    const ph = phaseOf(i)
    if (ph !== prevPhase && seg.length > 0) {
      segSeries.push({
        type: 'line',
        name: phases[prevPhase]?.name ?? '',
        data: seg,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: phases[prevPhase]?.color ?? '#fff', width: 2, opacity: 0.85 },
        emphasis: { disabled: true },
        z: 4,
      })
      seg = []
    }
    if (seg.length === 0 && i > 0) seg.push(traj[i - 1])
    seg.push(traj[i])
    prevPhase = ph
  }
  if (seg.length > 1) {
    segSeries.push({
      type: 'line',
      name: phases[prevPhase]?.name ?? '',
      data: seg,
      smooth: true,
      symbol: 'none',
      lineStyle: { color: phases[prevPhase]?.color ?? '#fff', width: 2, opacity: 0.85 },
      emphasis: { disabled: true },
      z: 4,
    })
  }

  // Spacecraft head
  const head = slice[slice.length - 1]
  const headColor = colorOf(slice.length - 1)

  const tliPath = traj.slice(0, Math.min(trailLen, tliIdx) + 1)
  const slingshotPath = trailLen >= slingEnterIdx
    ? traj.slice(slingEnterIdx, Math.min(trailLen, slingExitIdx) + 1)
    : []

  const tliMarker = traj[tliIdx]
  const slingMarker = traj[slingApexIdx]
  const slingExitMarker = traj[slingExitIdx]
  const axisRange = normalizeAxisRange(data?.axis_range)

  return {
    backgroundColor: '#05060f',
    animation: false,
    grid: { top: 50, right: 30, bottom: 50, left: 30, containLabel: true },
    xAxis: {
      type: 'value',
      min: axisRange.x[0],
      max: axisRange.x[1],
      splitLine: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
    },
    yAxis: {
      type: 'value',
      min: axisRange.y[0],
      max: axisRange.y[1],
      splitLine: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
    },
    legend: {
      data: phases.map(p => p.name),
      top: 8,
      textStyle: { color: '#aaa', fontSize: 11 },
      itemWidth: 18,
      inactiveColor: '#333',
    },
    series: [
      // Stars
      {
        type: 'scatter',
        name: '星空',
        data: data.stars,
        symbol: 'circle',
        symbolSize: (_, params: any) => (params.dataIndex % 3 === 0 ? 2 : 1),
        itemStyle: { color: '#ffffff', opacity: 0.45 },
        emphasis: { disabled: true },
        z: 1,
        silent: true,
      },
      // Moon orbit (background circle)
      {
        type: 'line',
        name: '月球轨道',
        data: data.moon_orbit,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: '#2a2a3a', width: 1, type: 'dashed' },
        emphasis: { disabled: true },
        z: 2,
        silent: true,
      },
      // TLI energy injection from Earth
      {
        type: 'lines',
        coordinateSystem: 'cartesian2d',
        name: 'TLI 能量注入',
        polyline: true,
        data: tliPath.length > 1 ? [{ coords: tliPath }] : [],
        lineStyle: { color: '#6ce2ff', width: 3, opacity: 0.4, curveness: 0 },
        effect: {
          show: tliPath.length > 1,
          period: 2.8,
          trailLength: 0.25,
          symbol: 'arrow',
          symbolSize: 9,
          color: '#9df3ff',
        },
        z: 3,
        silent: true,
      },
      // Lunar slingshot acceleration highlight
      {
        type: 'lines',
        coordinateSystem: 'cartesian2d',
        name: '月球弹弓加速',
        polyline: true,
        data: slingshotPath.length > 1 ? [{ coords: slingshotPath }] : [],
        lineStyle: {
          color: '#b7ff6c',
          width: 4,
          opacity: 0.55,
          shadowBlur: 12,
          shadowColor: 'rgba(183, 255, 108, 0.55)',
        },
        effect: {
          show: slingshotPath.length > 1,
          period: 2.1,
          trailLength: 0.3,
          symbol: 'arrow',
          symbolSize: 10,
          color: '#e6ff9b',
        },
        z: 6,
        silent: true,
      },
      // Earth
      {
        type: 'scatter',
        name: '地球',
        data: [data.earth],
        symbol: 'circle',
        symbolSize: 28,
        itemStyle: {
          color: new echarts.graphic.RadialGradient(0.4, 0.35, 1, [
            { offset: 0, color: '#5bc8fa' },
            { offset: 0.6, color: '#1565c0' },
            { offset: 1, color: '#0d2759' },
          ]),
        },
        label: { show: true, formatter: '地球', color: '#81d4fa', fontSize: 11, position: 'bottom', distance: 6 },
        emphasis: { disabled: true },
        z: 5,
        silent: true,
      },
      // Earth rotation overlay
      {
        type: 'scatter',
        name: '_earth_spin',
        data: [data.earth],
        symbol: EARTH_SPIN_SYMBOL,
        symbolSize: 24,
        symbolRotate: earthSpin,
        itemStyle: {
          color: 'rgba(180, 235, 255, 0.72)',
          borderColor: 'rgba(255, 255, 255, 0.35)',
          borderWidth: 0.5,
        },
        z: 6,
        silent: true,
      },
      // Moon
      {
        type: 'scatter',
        name: '月球',
        data: [moonPosition],
        symbol: 'circle',
        symbolSize: 20,
        itemStyle: {
          color: new echarts.graphic.RadialGradient(0.45, 0.35, 1, [
            { offset: 0, color: '#d0d0d0' },
            { offset: 0.7, color: '#909090' },
            { offset: 1, color: '#555' },
          ]),
        },
        label: { show: true, formatter: '月球', color: '#ccc', fontSize: 11, position: 'bottom', distance: 6 },
        emphasis: { disabled: true },
        z: 5,
        silent: true,
      },
      // Moon crater overlay
      {
        type: 'scatter',
        name: '_moon_crater',
        data: [moonPosition],
        symbol: MOON_CRATER_SYMBOL,
        symbolSize: 16,
        itemStyle: { color: 'rgba(72, 72, 72, 0.55)' },
        z: 6,
        silent: true,
      },
      // Completed path segments (colour by phase)
      ...segSeries,
      // Spacecraft head dot
      {
        type: 'scatter',
        name: 'Orion 飞船',
        data: trailLen > 0 ? [head] : [],
        symbol: 'triangle',
        symbolSize: 12,
        symbolRotate: craftRotation,
        itemStyle: { color: headColor },
        z: 8,
        silent: true,
      },
      // Spacecraft glow halo
      {
        type: 'scatter',
        name: '_halo',
        data: trailLen > 0 ? [head] : [],
        symbol: 'circle',
        symbolSize: 24,
        itemStyle: { color: headColor, opacity: 0.18 },
        z: 7,
        silent: true,
      },
      // TLI explanation marker
      {
        type: 'effectScatter',
        name: 'TLI 点火',
        data: trailLen >= tliIdx && tliMarker
          ? [{
              value: tliMarker,
              label: {
                show: true,
                position: 'top',
                distance: 12,
                formatter: 'TLI 点火\n摆脱地球引力井',
                color: '#d8f7ff',
                fontSize: 11,
                backgroundColor: 'rgba(4, 25, 38, 0.78)',
                borderColor: 'rgba(108, 226, 255, 0.45)',
                borderWidth: 1,
                borderRadius: 8,
                padding: [6, 8],
              },
            }]
          : [],
        symbolSize: 10,
        rippleEffect: { scale: 3, brushType: 'stroke' },
        itemStyle: { color: '#6ce2ff' },
        z: 9,
        silent: true,
      },
      // Lunar slingshot explanation
      {
        type: 'effectScatter',
        name: '月球引力弹弓',
        data: trailLen >= slingApexIdx && slingMarker
          ? [{
              value: slingMarker,
              label: {
                show: true,
                position: 'top',
                distance: 14,
                formatter: '月球引力弹弓\n贴近飞掠后提速转向',
                color: '#efffd6',
                fontSize: 11,
                backgroundColor: 'rgba(22, 36, 6, 0.8)',
                borderColor: 'rgba(183, 255, 108, 0.45)',
                borderWidth: 1,
                borderRadius: 8,
                padding: [6, 8],
              },
            }]
          : [],
        symbolSize: 12,
        rippleEffect: { scale: 4, brushType: 'stroke' },
        itemStyle: { color: '#b7ff6c' },
        z: 9,
        silent: true,
      },
      // Post-sling acceleration annotation
      {
        type: 'scatter',
        name: '出地球奔月加速',
        data: trailLen >= slingExitIdx && slingExitMarker
          ? [{
              value: slingExitMarker,
              label: {
                show: true,
                position: 'bottom',
                distance: 12,
                formatter: '速度矢量被改写\n沿切线抬升远月能量',
                color: '#f7ffd8',
                fontSize: 11,
                backgroundColor: 'rgba(24, 38, 10, 0.75)',
                borderColor: 'rgba(215, 255, 130, 0.3)',
                borderWidth: 1,
                borderRadius: 8,
                padding: [6, 8],
              },
            }]
          : [],
        symbol: 'diamond',
        symbolSize: 8,
        itemStyle: { color: '#ddff8c' },
        z: 8,
        silent: true,
      },
    ],
  }
}

// ── data fetch ─────────────────────────────────────────────────────────────────
async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await axios.get('/api/trajectory/artemis-data')
    const data = normalizePayload(res.data)
    traj = data.trajectory
    phaseEnds = data.phase_ends
    phases = data.phases
    totalFrames.value = traj.length - 1

    if (chartEl.value) {
      if (!chart.value) {
        chart.value = echarts.init(chartEl.value, 'dark')
      }
      chart.value.setOption(buildOption(data, 0))

      // store for animation frames
      ;(chart.value as any).__artemisData = data
    }
  } catch (e: any) {
    error.value = '轨迹数据加载失败：' + (e?.message ?? '未知错误')
  } finally {
    loading.value = false
  }
}

// ── animation loop ─────────────────────────────────────────────────────────────
function tick() {
  if (!chart.value || !animating.value) return
  const data = (chart.value as any).__artemisData
  if (!data) return

  const now = performance.now()
  if (lastTickTs === undefined) lastTickTs = now
  const deltaMs = Math.min(64, now - lastTickTs)
  lastTickTs = now

  frameCursor.value = Math.min(
    frameCursor.value + (deltaMs / 1000) * pointsPerSecond(),
    totalFrames.value,
  )
  frameIdx.value = Math.floor(frameCursor.value)
  chart.value.setOption(buildOption(data, frameIdx.value), { replaceMerge: ['series'] })

  if (frameCursor.value >= totalFrames.value) {
    animating.value = false
    lastTickTs = undefined
    return
  }
  rafId = requestAnimationFrame(tick)
}

function play() {
  if (frameIdx.value >= totalFrames.value) {
    frameCursor.value = 0
    frameIdx.value = 0
  }
  animating.value = true
  lastTickTs = undefined
  rafId = requestAnimationFrame(tick)
}

function pause() {
  animating.value = false
  lastTickTs = undefined
  if (rafId !== undefined) cancelAnimationFrame(rafId)
}

function reset() {
  pause()
  frameCursor.value = 0
  frameIdx.value = 0
  const data = (chart.value as any).__artemisData
  if (data && chart.value) chart.value.setOption(buildOption(data, 0), { replaceMerge: ['series'] })
}

// ── resize ─────────────────────────────────────────────────────────────────────
function onResize() {
  chart.value?.resize()
}

onMounted(async () => {
  await fetchData()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  pause()
  window.removeEventListener('resize', onResize)
  chart.value?.dispose()
})

const progressPct = () => totalFrames.value > 0
  ? Math.round((frameIdx.value / totalFrames.value) * 100)
  : 0
</script>

<template>
  <div class="artemis-page">
    <!-- 标题栏 -->
    <div class="page-header">
      <h2>🚀 阿尔忒弥斯 I — 环月轨迹可视化</h2>
      <span class="subtitle">Artemis I · 2022年11月 · 远距逆行轨道 (DRO)</span>
    </div>

    <!-- 图表容器 -->
    <div class="chart-wrapper" v-loading="loading" element-loading-background="#05060f">
      <div v-if="error" class="error-msg">{{ error }}</div>
      <div ref="chartEl" class="chart-canvas" />
    </div>

    <!-- 控制栏 -->
    <div class="control-bar">
      <el-button
        v-if="!animating"
        type="primary"
        size="default"
        :disabled="loading || !!error"
        @click="play"
      >
        ▶ 播放
      </el-button>
      <el-button v-else size="default" @click="pause">⏸ 暂停</el-button>
      <el-button size="default" @click="reset" :disabled="loading || !!error">↺ 重置</el-button>

      <span class="speed-label">速度档位 {{ speedLevel }}/{{ maxSpeedLevel }}</span>
      <el-slider
        v-model="speedLevel"
        :min="1"
        :max="maxSpeedLevel"
        :step="1"
        :show-tooltip="true"
        class="speed-slider"
      />

      <span class="progress-label">进度 {{ progressPct() }}%</span>
      <el-progress
        :percentage="progressPct()"
        :stroke-width="6"
        :show-text="false"
        class="progress-bar"
      />
    </div>

    <!-- 阶段说明 -->
    <div class="phase-legend">
      <div v-for="p in phases" :key="p.idx" class="phase-item">
        <span class="phase-dot" :style="{ background: p.color }" />
        <span class="phase-name">{{ p.name }}</span>
      </div>
    </div>

    <!-- 任务说明 -->
    <el-collapse class="mission-info" accordion>
      <el-collapse-item title="📋 任务背景与轨迹说明" name="1">
        <div class="info-body">
          <p>
            <strong>阿尔忒弥斯 I（Artemis I）</strong>于 2022 年 11 月 16 日发射，是 NASA 重返月球计划的首次无人飞行测试任务，旨在验证 SLS 火箭与猎户座（Orion）飞船。
          </p>
          <ul>
            <li><strong>TLI 出发</strong>：猎户座从地球近地轨道点燃发动机，进入月球转移轨道。</li>
            <li><strong>月球飞掠（去）</strong>：距月球约 100 km 近距飞掠，借助月球引力加速并调整轨道。</li>
            <li><strong>远距逆行轨道（DRO）</strong>：猎户座进入距月球约 60,000–70,000 km 的逆行稳定轨道，绕月飞行约 1.5 圈（约 10 天），创下载人飞船距地最远纪录（约 432,210 km）。</li>
            <li><strong>月球飞掠（返）</strong>：再次借助月球引力弹弓，降低速度，进入返回轨道。</li>
            <li><strong>TEI 返回</strong>：猎户座发动机点燃，返回地球，于 2022 年 12 月 11 日溅落太平洋。</li>
          </ul>
          <p>
            图中坐标系为 <strong>地月旋转参考系</strong>，地球固定在原点，月球固定在右侧，轨迹为简化模型。
          </p>
          <p>
            当前动画额外叠加了 <strong>地球自转、月球公转</strong> 以及 <strong>月球引力弹弓加速示意</strong>，用于帮助理解“近月飞掠如何把速度矢量改写成奔向远月轨道的增益”。
          </p>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.artemis-page {
  padding: 20px;
  max-width: 1200px;
}

.page-header {
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0 0 4px;
  font-size: 22px;
  color: var(--el-text-color-primary);
}

.subtitle {
  font-size: 13px;
  color: #888;
}

/* 图表容器 */
.chart-wrapper {
  border: 1px solid #1e2030;
  border-radius: 12px;
  overflow: hidden;
  background: #05060f;
  min-height: 520px;
}

.chart-canvas {
  width: 100%;
  height: 520px;
}

.error-msg {
  padding: 20px;
  color: #ef5350;
}

/* 控制栏 */
.control-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 0;
  flex-wrap: wrap;
}

.speed-label,
.progress-label {
  font-size: 13px;
  color: #888;
  white-space: nowrap;
}

.speed-slider {
  width: 180px;
}

.progress-bar {
  flex: 1;
  min-width: 120px;
}

/* 阶段图例 */
.phase-legend {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  padding: 8px 0 16px;
}

.phase-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.phase-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
}

.phase-name {
  font-size: 13px;
  color: #ccc;
}

/* 任务说明 */
.mission-info {
  margin-top: 4px;
}

.info-body {
  line-height: 1.8;
  color: #bbb;
  font-size: 14px;
}

.info-body p { margin: 0 0 10px; }
.info-body ul { margin: 0 0 10px; padding-left: 20px; }
.info-body li { margin-bottom: 4px; }
.info-body strong { color: #e0e0e0; }
</style>
