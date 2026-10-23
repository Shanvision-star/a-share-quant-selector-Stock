const labels: Record<string, string> = {
  b1: 'B1 突破', b2: 'B2 回踩', bowl: '碗形反弹', brick: '砖型策略', zettaranc: 'Zettaranc',
  B1CaseStrategy: 'B1 阶段分析', B1CaseAnalyzer: 'B1 阶段分析', B1Strategy: 'B1 突破', B2Strategy: 'B2 回踩', BowlReboundStrategy: '碗形反弹', BrickStrategy: '砖型策略', BrickPatternStrategy: '砖型策略', ZettarancComboStrategy: 'Zettaranc 综合',
}
export const strategyLabel = (value?: string) => value ? labels[value] || value : '—'

export function displayStrategyText(text: string) {
  return text.replace(/B1CaseAnalyzer|B1CaseStrategy|B1Strategy|B2Strategy|BowlReboundStrategy|BrickPatternStrategy|BrickStrategy|ZettarancComboStrategy/g, value => labels[value] || value)
}
