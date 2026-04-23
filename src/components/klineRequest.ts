const MAIN_KLINE_REQUEST_KEY = 'kline:render'

export function buildMainKlineRequestKey(_code: string, _period: string, _adjust: string): string {
  return MAIN_KLINE_REQUEST_KEY
}
