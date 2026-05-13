export interface StockDetailLoadTicket {
  id: number
  code: string
}

export function normalizeStockCode(value: unknown): string {
  const text = value == null ? '' : String(value)
  const match = text.match(/\d{6}/)
  return match ? match[0] : ''
}

export function createStockDetailLoadGuard() {
  let currentId = 0

  return {
    start(code: string): StockDetailLoadTicket {
      currentId += 1
      return { id: currentId, code: normalizeStockCode(code) }
    },
    isCurrent(ticket: StockDetailLoadTicket, currentCode: string): boolean {
      return ticket.id === currentId && ticket.code === normalizeStockCode(currentCode)
    },
  }
}

export function getDisplayStockName(
  priceInfo: Record<string, any> | null | undefined,
  currentCode: string,
  fallbackName = '',
): string {
  const priceCode = normalizeStockCode(priceInfo?.code ?? priceInfo?.ts_code)
  const routeCode = normalizeStockCode(currentCode)
  if (priceCode && routeCode && priceCode !== routeCode) {
    return fallbackName
  }
  return priceInfo?.name || fallbackName
}

export function isStockDetailPayloadCurrent(
  payload: Record<string, any> | null | undefined,
  currentCode: string,
): boolean {
  const payloadCode = normalizeStockCode(payload?.code ?? payload?.ts_code)
  const routeCode = normalizeStockCode(currentCode)
  return !!payloadCode && !!routeCode && payloadCode === routeCode
}

export function shouldShowInitialStockDetailLoading(
  isLoading: boolean,
  hasLoadedInitialDetail: boolean,
): boolean {
  return isLoading && !hasLoadedInitialDetail
}

export interface StockSequenceItem {
  code?: unknown
  [key: string]: unknown
}

export interface StockSequenceState {
  codes: string[]
  currentIndex: number
  total: number
  prevCode: string
  nextCode: string
}

export function getStockSequenceState(
  items: StockSequenceItem[],
  currentCode: string,
): StockSequenceState {
  const seen = new Set<string>()
  const codes: string[] = []

  for (const item of items) {
    const code = normalizeStockCode(item?.code)
    if (!code || seen.has(code)) continue
    seen.add(code)
    codes.push(code)
  }

  const normalizedCurrent = normalizeStockCode(currentCode)
  const currentIndex = codes.indexOf(normalizedCurrent)

  return {
    codes,
    currentIndex,
    total: codes.length,
    prevCode: currentIndex > 0 ? codes[currentIndex - 1] : '',
    nextCode: currentIndex >= 0 && currentIndex < codes.length - 1 ? codes[currentIndex + 1] : '',
  }
}
