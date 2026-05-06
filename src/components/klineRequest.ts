const MAIN_KLINE_REQUEST_KEY = 'kline:render'
const DEFAULT_FAST_KLINE_LIMIT = 500

export function buildMainKlineRequestKey(_code: string, _period: string, _adjust: string): string {
  return MAIN_KLINE_REQUEST_KEY
}

export function shouldShowBlockingKlineLoading(isLoading: boolean, hasRenderedChart: boolean): boolean {
  return isLoading && !hasRenderedChart
}

export function selectFastKlineLimit(requestedLimit: number | undefined, hasFullCache: boolean): number {
  const limit = typeof requestedLimit === 'number' && Number.isFinite(requestedLimit) && requestedLimit > 0
    ? Math.floor(requestedLimit)
    : DEFAULT_FAST_KLINE_LIMIT
  if (hasFullCache || limit <= DEFAULT_FAST_KLINE_LIMIT) return limit
  return DEFAULT_FAST_KLINE_LIMIT
}

export function getNeighborCodes(codes: string[], currentCode: string, radius: number): string[] {
  const uniqueCodes = Array.from(new Set(codes.filter(Boolean)))
  const centerIndex = uniqueCodes.indexOf(currentCode)
  if (centerIndex === -1) return uniqueCodes.slice(0, Math.max(0, radius * 2))

  const start = Math.max(0, centerIndex - radius)
  const end = Math.min(uniqueCodes.length, centerIndex + radius + 1)
  return uniqueCodes.slice(start, end).filter(code => code !== currentCode)
}
