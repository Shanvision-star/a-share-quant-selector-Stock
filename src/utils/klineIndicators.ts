export interface BrickSegment {
  value: [number, number, number]
  itemStyle: {
    color: string
  }
}

export interface BrickStackedBars {
  base: Array<number | null>
  body: Array<{ value: number; itemStyle: { color: string } } | null>
}

const BRICK_UP_COLOR = '#ff2d2d'
const BRICK_DOWN_COLOR = '#15ff00'

export function buildBrickSegments(values: Array<number | null>): Array<BrickSegment | null> {
  return values.map((current, index) => {
    if (index === 0 || current == null) return null

    const previous = values[index - 1]
    if (previous == null) return null

    return {
      value: [index, previous, current],
      itemStyle: {
        color: current >= previous ? BRICK_UP_COLOR : BRICK_DOWN_COLOR,
      },
    }
  })
}

export function buildBrickStackedBars(values: Array<number | null>): BrickStackedBars {
  const base: BrickStackedBars['base'] = []
  const body: BrickStackedBars['body'] = []

  values.forEach((current, index) => {
    if (index === 0 || current == null) {
      base.push(null)
      body.push(null)
      return
    }

    const previous = values[index - 1]
    if (previous == null) {
      base.push(null)
      body.push(null)
      return
    }

    const low = Math.min(previous, current)
    const height = Math.abs(current - previous)
    base.push(Number(low.toFixed(2)))
    body.push({
      value: Number(height.toFixed(2)),
      itemStyle: {
        color: current >= previous ? BRICK_UP_COLOR : BRICK_DOWN_COLOR,
      },
    })
  })

  return { base, body }
}

// ---------------------------------------------------------------------------
// 以下指标用于 K 线副图/主图叠加：RSI / WR / DMI / BOLL
// 设计原则：
// 1. 全部返回与输入 bars 等长的数组，warm-up 阶段使用 null，避免 ECharts 画错点
// 2. 不抛异常；输入异常（NaN、缺字段）的位点退化为 null
// 3. 不依赖任何第三方库，纯函数无副作用
// ---------------------------------------------------------------------------

/** 单根 K 线最小字段集合；多余字段忽略。 */
export interface OhlcBar {
  open?: number | null
  high?: number | null
  low?: number | null
  close?: number | null
}

function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** Wilder 平滑：alpha = 1/period，用于 RSI / DMI / ATR。
 *  - 输入存在 null 视为缺失，对应位输出 null
 *  - 前 period 个位点为 warm-up，强制 null
 */
function wilderSmooth(values: Array<number | null>, period: number): Array<number | null> {
  const n = values.length
  const out: Array<number | null> = new Array(n).fill(null)
  if (period <= 0 || n === 0) return out
  let sum = 0
  let valid = 0
  let prev: number | null = null
  for (let i = 0; i < n; i++) {
    const v = values[i]
    if (!isNum(v)) {
      // 缺失：重置累计，避免污染后续平滑结果
      sum = 0
      valid = 0
      prev = null
      continue
    }
    if (valid < period) {
      sum += v
      valid += 1
      if (valid === period) {
        prev = sum / period
        out[i] = prev
      }
    } else if (prev !== null) {
      prev = (prev * (period - 1) + v) / period
      out[i] = prev
    }
  }
  return out
}

/** RSI（Wilder 平均），默认 14 周期。 */
export function computeRSI(bars: OhlcBar[], period = 14): Array<number | null> {
  const closes = bars.map((b) => (isNum(b.close) ? b.close : null))
  const gains: Array<number | null> = new Array(closes.length).fill(null)
  const losses: Array<number | null> = new Array(closes.length).fill(null)
  for (let i = 1; i < closes.length; i++) {
    const cur = closes[i]
    const prev = closes[i - 1]
    if (!isNum(cur) || !isNum(prev)) continue
    const diff = cur - prev
    gains[i] = diff > 0 ? diff : 0
    losses[i] = diff < 0 ? -diff : 0
  }
  const avgGain = wilderSmooth(gains, period)
  const avgLoss = wilderSmooth(losses, period)
  return closes.map((_, i) => {
    const g = avgGain[i]
    const l = avgLoss[i]
    if (g === null || l === null) return null
    if (l === 0) return 100
    const rs = g / l
    return Number((100 - 100 / (1 + rs)).toFixed(2))
  })
}

/** 威廉指标 %R，常用周期 10、20；越接近 0 越超买，越接近 -100 越超卖。 */
export function computeWR(bars: OhlcBar[], period = 14): Array<number | null> {
  const n = bars.length
  const out: Array<number | null> = new Array(n).fill(null)
  if (period <= 0) return out
  for (let i = period - 1; i < n; i++) {
    let hi = -Infinity
    let lo = Infinity
    let ok = true
    for (let j = i - period + 1; j <= i; j++) {
      const b = bars[j]
      if (!isNum(b.high) || !isNum(b.low)) {
        ok = false
        break
      }
      if (b.high > hi) hi = b.high
      if (b.low < lo) lo = b.low
    }
    const close = bars[i].close
    if (!ok || !isNum(close)) continue
    const range = hi - lo
    if (range === 0) {
      out[i] = -50
      continue
    }
    out[i] = Number((((hi - close) / range) * -100).toFixed(2))
  }
  return out
}

/** DMI / ADX：返回 +DI / -DI / ADX 三条线，默认 14 周期。
 *  ADX warm-up = 2 * period - 1。
 */
export function computeDMI(
  bars: OhlcBar[],
  period = 14,
): {
  pdi: Array<number | null>
  mdi: Array<number | null>
  adx: Array<number | null>
} {
  const n = bars.length
  const tr: Array<number | null> = new Array(n).fill(null)
  const plusDM: Array<number | null> = new Array(n).fill(null)
  const minusDM: Array<number | null> = new Array(n).fill(null)
  for (let i = 1; i < n; i++) {
    const cur = bars[i]
    const prev = bars[i - 1]
    if (
      !isNum(cur.high) ||
      !isNum(cur.low) ||
      !isNum(cur.close) ||
      !isNum(prev.high) ||
      !isNum(prev.low) ||
      !isNum(prev.close)
    ) {
      continue
    }
    const upMove = cur.high - prev.high
    const downMove = prev.low - cur.low
    plusDM[i] = upMove > downMove && upMove > 0 ? upMove : 0
    minusDM[i] = downMove > upMove && downMove > 0 ? downMove : 0
    tr[i] = Math.max(
      cur.high - cur.low,
      Math.abs(cur.high - prev.close),
      Math.abs(cur.low - prev.close),
    )
  }
  const atr = wilderSmooth(tr, period)
  const plusSmooth = wilderSmooth(plusDM, period)
  const minusSmooth = wilderSmooth(minusDM, period)
  const pdi: Array<number | null> = new Array(n).fill(null)
  const mdi: Array<number | null> = new Array(n).fill(null)
  const dx: Array<number | null> = new Array(n).fill(null)
  for (let i = 0; i < n; i++) {
    const a = atr[i]
    const p = plusSmooth[i]
    const m = minusSmooth[i]
    if (a === null || a === 0 || p === null || m === null) continue
    const pv = (p / a) * 100
    const mv = (m / a) * 100
    pdi[i] = Number(pv.toFixed(2))
    mdi[i] = Number(mv.toFixed(2))
    const sum = pv + mv
    dx[i] = sum === 0 ? 0 : Number(((Math.abs(pv - mv) / sum) * 100).toFixed(2))
  }
  const adx = wilderSmooth(dx, period)
  return {
    pdi,
    mdi,
    adx: adx.map((v) => (v === null ? null : Number(v.toFixed(2)))),
  }
}

/** 布林带：返回上中下三条线，默认 20 周期、2 倍标准差。 */
export function computeBOLL(
  bars: OhlcBar[],
  period = 20,
  k = 2,
): {
  upper: Array<number | null>
  middle: Array<number | null>
  lower: Array<number | null>
} {
  const n = bars.length
  const upper: Array<number | null> = new Array(n).fill(null)
  const middle: Array<number | null> = new Array(n).fill(null)
  const lower: Array<number | null> = new Array(n).fill(null)
  if (period <= 0) return { upper, middle, lower }
  for (let i = period - 1; i < n; i++) {
    let sum = 0
    let ok = true
    for (let j = i - period + 1; j <= i; j++) {
      const c = bars[j].close
      if (!isNum(c)) {
        ok = false
        break
      }
      sum += c
    }
    if (!ok) continue
    const mean = sum / period
    let varSum = 0
    for (let j = i - period + 1; j <= i; j++) {
      const c = bars[j].close as number
      varSum += (c - mean) ** 2
    }
    const std = Math.sqrt(varSum / period)
    middle[i] = Number(mean.toFixed(2))
    upper[i] = Number((mean + k * std).toFixed(2))
    lower[i] = Number((mean - k * std).toFixed(2))
  }
  return { upper, middle, lower }
}
