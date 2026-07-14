import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const trackingViewSource = readFileSync(
  resolve(__dirname, '../TrackingView.vue'),
  'utf8',
)

describe('TrackingView action column layout contract', () => {
  it('keeps review and delete actions on one stable line', () => {
    expect(trackingViewSource).toMatch(
      /<el-table-column label="操作" width="180" fixed="right">/,
    )
    expect(trackingViewSource).toMatch(
      /<div class="tracking-row-actions">\s*<AddToTodayReviewButton[\s\S]*?<el-button[\s\S]*?删除[\s\S]*?<\/el-button>\s*<\/div>/,
    )
    expect(trackingViewSource).toMatch(
      /\.tracking-row-actions\s*\{[^}]*display:\s*inline-flex;[^}]*gap:\s*\d+px;[^}]*align-items:\s*center;[^}]*white-space:\s*nowrap;/s,
    )
  })

  it('surfaces the post-close loop action and latest operational state', () => {
    expect(trackingViewSource).toMatch(/data-test="tracking-loop-status"/)
    expect(trackingViewSource).toMatch(/data-test="run-tracking-loop"/)
    expect(trackingViewSource).toContain('运行收盘循环')
    expect(trackingViewSource).toContain('trackingLoopSummary(latestLoopRun)')
  })
})
