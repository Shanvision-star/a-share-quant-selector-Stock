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
