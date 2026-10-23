// 在独立历史样本工作区中验收桌面交互和可访问名称；不连接用户数据库或行情供应商。
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const { _electron } = require(process.env.QUANT_PLAYWRIGHT_MODULE || 'playwright')
const root = path.resolve(__dirname, '../..')
const workspace = process.env.QUANT_ACCEPTANCE_WORKSPACE
assert.ok(workspace && path.resolve(workspace).startsWith(path.join(root, 'output') + path.sep), 'use isolated output workspace')
const executablePath = process.env.QUANT_ACCEPTANCE_EXE || path.join(root, 'desktop/release/win-unpacked/A-share Quant.exe')
const output = path.join(root, 'output/desktop-v2', `ui-${Date.now()}`)
fs.mkdirSync(output, { recursive: true })
const source = path.join(path.dirname(executablePath), 'resources/app-source')
for (const relative of Object.keys(JSON.parse(fs.readFileSync(path.join(source, 'app-manifest.json'), 'utf8')).files)) {
  const destination = path.join(workspace, relative)
  fs.mkdirSync(path.dirname(destination), { recursive: true })
  fs.copyFileSync(path.join(source, relative), destination)
}
const row = { code: '000001', name: '平安银行', strategy_name: 'B1CaseAnalyzer', strategy_filter: 'b1', date: '2026-08-20', close: 11.4, reason: '验收样本 · 历史候选记录', category: '', j_value: null }
fs.writeFileSync(path.join(workspace, 'data/web_strategy_results.json'), JSON.stringify({ schema_version: 1, trade_date: '2026-08-20', generated_at: '2026-08-20 17:00:00', results: [row], groups: { b1: { strategy_name: 'B1CaseAnalyzer', strategy_filter: 'b1', results: [], total: 1, scanned: 3 } }, available_groups: ['b1'], total: 1, unique_total: 1 }))
const result = { checks: [], screenshots: [], errors: [], fixture: 'historical isolated acceptance data' }
const env = { ...process.env, QUANT_USER_DATA: path.join(output, 'user'), QUANT_WORKSPACE: workspace, PATH: `${process.env.SystemRoot}\\System32;${process.env.SystemRoot}` }
for (const name of ['QUANT_PYTHON', 'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'ELECTRON_RUN_AS_NODE']) delete env[name]
let instance
const check = (name, value) => { assert.ok(value, name); result.checks.push(name) }

async function main() {
  instance = await _electron.launch({ executablePath, env, timeout: 120000 })
  const page = await instance.firstWindow({ timeout: 120000 })
  page.setDefaultTimeout(30000)
  page.on('pageerror', error => result.errors.push(error.message))
  page.on('dialog', () => {})
  await page.waitForURL(/127\.0\.0\.1/, { timeout: 120000 })
  const runtime = JSON.parse(fs.readFileSync(path.join(workspace, 'data/desktop-runtime.json'), 'utf8'))
  const go = route => page.goto(runtime.base_url + route)
  const shot = async name => { await page.screenshot({ path: path.join(output, name), fullPage: true }); result.screenshots.push(name) }
  await page.setViewportSize({ width: 1512, height: 960 })
  await page.getByRole('button', { name: '稍后再说', exact: true }).click({ timeout: 10000 }).catch(() => {})
  await page.locator('.focus-chart canvas').first().waitFor({ timeout: 90000 })
  await page.locator('.cache-strip .el-loading-mask').waitFor({ state: 'hidden' })
  await page.waitForTimeout(350)
  await shot('01-home-1512.png')
  check('home has compact cache strip and rendered chart', await page.locator('.cache-strip').count() === 1 && await page.locator('.focus-chart canvas').count() > 0)
  if (!await page.locator('.agent-panel').isVisible()) await page.locator('.agent-toggle').click()
  await page.getByLabel('Agent 任务').fill('验收：检查当前股票候选日期')
  const requestPromise = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/agent/runs'))
  await page.getByRole('button', { name: '运行 Agent', exact: true }).click()
  const researchRequest = await requestPromise
  check('home stock is passed to actual Agent request', researchRequest.postDataJSON().code === '000001')
  await page.locator('.agent-report').waitFor()
  check('record check result identifies its stock', (await page.locator('.report-context').innerText()).includes('000001'))
  await page.getByRole('button', { name: '保存复盘', exact: true }).click()
  await page.locator('#agent-review-date').fill('2026-08-21')
  await page.getByRole('button', { name: '确认追加', exact: true }).click()
  await page.getByRole('button', { name: '查看复盘 · 2026-08-21', exact: true }).waitFor()
  await page.getByRole('dialog', { name: '追加到复盘' }).waitFor({ state: 'hidden' })
  await page.waitForTimeout(350)
  await shot('02-home-agent-report.png')
  await page.getByRole('button', { name: '查看复盘 · 2026-08-21', exact: true }).click()
  await page.waitForURL(/review-library\?date=2026-08-21/)
  await page.locator('.body-editor textarea').waitFor()
  check('report opens its saved review date', (await page.locator('.body-editor textarea').inputValue()).includes('agent-run:'))
  await page.waitForTimeout(350)
  await shot('03-review-linked.png')

  await go('/stocks/688728')
  await page.locator('canvas').first().waitFor({ timeout: 90000 })
  await page.getByRole('button', { name: '稍后再说', exact: true }).click({ timeout: 1000 }).catch(() => {})
  if (!await page.locator('.agent-panel').isVisible()) await page.locator('.agent-toggle').click()
  await page.locator('.report-context').waitFor()
  check('historical report stays distinct after stock switch', (await page.locator('.report-context').innerText()).includes('历史对象') && (await page.locator('.context-stock').innerText()).includes('688728'))
  await page.getByRole('button', { name: '加入跟踪…', exact: true }).click()
  await page.getByRole('dialog', { name: '确认加入跟踪' }).waitFor()
  check('tracking confirmation uses report stock', (await page.getByRole('dialog', { name: '确认加入跟踪' }).innerText()).includes('000001'))
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '按股跟踪 ↗', exact: true }).click()
  await page.waitForURL(/tracking\?code=000001/)
  await shot('04-tracking-filter.png')

  await go('/stocks/000001')
  await page.locator('canvas').first().waitFor({ timeout: 90000 })
  if (await page.locator('.agent-panel').isVisible()) await page.getByRole('button', { name: '关闭 Agent', exact: true }).click()
  for (const width of [1366, 900, 768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.waitForTimeout(400)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
    check(`no document overflow at ${width}`, !overflow)
    await shot(`05-stock-${width}.png`)
  }
  await page.emulateMedia({ reducedMotion: 'reduce' })
  check('reduced motion preference applied', await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches))
  await page.setViewportSize({ width: 1512, height: 960 })
  for (const route of ['/strategy-results', '/manual-pool', '/tracking', '/backtest', '/review-library', '/zettaranc', '/strategy-docs', '/update', '/status', '/settings']) {
    await go(route)
    await page.locator('h1').first().waitFor()
    check(`original route reachable ${route}`, new URL(page.url()).pathname === route && await page.locator('h1').first().innerText())
  }
  await page.locator('.el-loading-mask').first().waitFor({ state: 'hidden', timeout: 90000 }).catch(() => {})
  await shot('06-settings.png')
  check('no uncaught page errors', result.errors.length === 0)
  result.passed = true
  const closed = instance.waitForEvent('close', { timeout: 20000 })
  await instance.evaluate(({ app }) => app.quit()).catch(() => {})
  await closed
}
main().catch(error => { result.passed = false; result.error = error.stack; process.exitCode = 1 }).finally(async () => {
  fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify({ output, ...result }, null, 2))
  try { await instance?.close() } catch {}
})
