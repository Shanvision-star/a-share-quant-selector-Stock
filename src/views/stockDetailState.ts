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
