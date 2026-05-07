export interface VolumeAxisScale {
  max: number
  rawMax: number
  capped: boolean
  count: number
}

function clampPercent(value: unknown, fallback: number): number {
  const num = Number(value)
  if (!Number.isFinite(num)) return fallback
  return Math.max(0, Math.min(100, num))
}

function toPositiveFiniteValues(values: unknown[]): number[] {
  return values
    .map(value => Number(value))
    .filter(value => Number.isFinite(value) && value > 0)
}

function percentile(sortedValues: number[], ratio: number): number {
  if (!sortedValues.length) return 0
  const index = Math.max(0, Math.min(sortedValues.length - 1, Math.floor((sortedValues.length - 1) * ratio)))
  return sortedValues[index]
}

export function calculateVolumeAxisScale(values: unknown[]): VolumeAxisScale {
  const positiveValues = toPositiveFiniteValues(values).sort((a, b) => a - b)
  if (!positiveValues.length) {
    return { max: 1, rawMax: 0, capped: false, count: 0 }
  }

  const rawMax = positiveValues[positiveValues.length - 1]
  const p90 = percentile(positiveValues, 0.90)
  const p95 = percentile(positiveValues, 0.95)
  const median = percentile(positiveValues, 0.50)
  const regularMax = positiveValues[Math.max(0, positiveValues.length - 2)]
  const capBase = Math.max(p95, p90 * 1.15, median * 4)

  // 成交量偶尔会出现一两根极端巨量，直接用全局最大值会把普通柱压扁。
  const shouldCap = positiveValues.length >= 16 && rawMax > capBase * 2.2
  const max = shouldCap
    ? Math.max(regularMax * 1.15, capBase * 1.2)
    : rawMax * 1.08

  return {
    max: Math.max(1, Number(max.toFixed(2))),
    rawMax,
    capped: shouldCap,
    count: positiveValues.length,
  }
}

export function pickVisibleVolumeValues(
  values: unknown[],
  axisLength: number,
  startPercent: unknown,
  endPercent: unknown,
): unknown[] {
  if (!values.length) return []
  const safeAxisLength = Math.max(values.length, Math.floor(Number(axisLength) || values.length))
  const start = clampPercent(startPercent, 0)
  const end = Math.max(start, clampPercent(endPercent, 100))
  const startIndex = Math.max(0, Math.min(values.length - 1, Math.floor(safeAxisLength * start / 100)))
  const endIndex = Math.max(startIndex, Math.min(values.length - 1, Math.ceil(safeAxisLength * end / 100) - 1))
  return values.slice(startIndex, endIndex + 1)
}

export function buildVolumeAxisScaleForZoom(
  values: unknown[],
  axisLength: number,
  startPercent: unknown,
  endPercent: unknown,
): VolumeAxisScale {
  return calculateVolumeAxisScale(pickVisibleVolumeValues(values, axisLength, startPercent, endPercent))
}
