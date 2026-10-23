// 原生 Electron 验收：隔离数据目录、无系统 Python、真实页面未保存保护与后台任务退出确认。
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const { spawnSync } = require('node:child_process')
const { _electron } = require(process.env.QUANT_PLAYWRIGHT_MODULE || 'playwright')
const project = path.resolve(__dirname, '../..')
const executablePath = process.env.QUANT_ACCEPTANCE_EXE || path.join(project, 'desktop/release/win-unpacked/A-share Quant.exe')
const output = path.join(project, 'output/desktop-v2', `native-${Date.now()}`)
const userData = path.join(output, 'user')
fs.mkdirSync(output, { recursive: true })
const env = { ...process.env, QUANT_USER_DATA: userData, PATH: `${process.env.SystemRoot}\\System32;${process.env.SystemRoot}`, MPLBACKEND: 'Agg' }
for (const key of ['QUANT_WORKSPACE', 'QUANT_PYTHON', 'QUANT_RUNTIME_FILE', 'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'ELECTRON_RUN_AS_NODE']) delete env[key]
const result = { executablePath, userData, systemPythonOnPath: false, checks: [] }
let instance
const check = (name, value) => { assert.ok(value, name); result.checks.push(name) }

async function launch() {
  instance = await _electron.launch({ executablePath, env, timeout: 120000 })
  const page = await instance.firstWindow({ timeout: 120000 })
  // Electron 原生 will-prevent-unload 负责处理，避免 Playwright 再自动关闭同一个对话框。
  page.on('dialog', () => {})
  await page.waitForURL(/127\.0\.0\.1/, { timeout: 120000 })
  await page.locator('h1').waitFor()
  await instance.evaluate(({ dialog }) => {
    globalThis.acceptanceDialogs = []
    globalThis.acceptanceDiscard = false
    globalThis.acceptanceStopTasks = false
    dialog.showMessageBox = async (_window, options) => {
      globalThis.acceptanceDialogs.push(options.message)
      return { response: globalThis.acceptanceStopTasks ? 1 : 0 }
    }
    dialog.showMessageBoxSync = (_window, options) => {
      globalThis.acceptanceDialogs.push(options.title)
      return globalThis.acceptanceDiscard ? 1 : 0
    }
  })
  return page
}

async function main() {
  const page = await launch()
  const workspace = path.join(userData, 'workspace')
  const runtimeFile = path.join(workspace, 'data/desktop-runtime.json')
  const runtime = JSON.parse(fs.readFileSync(runtimeFile, 'utf8'))
  const headers = { 'X-Quant-Token': runtime.token }
  const api = async endpoint => fetch(`${runtime.base_url}/api/${endpoint}`, { headers })
  check('packaged managed workspace booted', fs.existsSync(path.join(workspace, 'config/config.yaml')))
  check('unauthenticated API rejected', (await fetch(`${runtime.base_url}/api/health`)).status === 401)
  check('authenticated API healthy', (await api('health')).status === 200)
  check('renderer has no Node', await page.evaluate(() => typeof require === 'undefined'))
  await page.goto(`${runtime.base_url}/review-library`)
  const create = page.getByRole('button', { name: /^创建 .* 复盘$/ })
  await page.locator('.document-area .el-loading-mask').waitFor({ state: 'hidden' })
  if (await create.isVisible()) await create.click()
  await page.locator('.body-editor textarea').fill('桌面验收：未保存的草稿')
  await page.locator('.dirty-indicator').waitFor()
  await instance.evaluate(({ app }) => { app.quit() })
  await page.waitForTimeout(1500)
  check('menu quit invokes unsaved guard', (await instance.evaluate(() => globalThis.acceptanceDialogs)).includes('尚未保存'))
  check('cancel quit keeps editor and backend alive', !page.isClosed() && (await api('health')).ok)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.locator('.dirty-indicator').waitFor({ state: 'hidden' })

  const python = path.join(path.dirname(executablePath), 'resources/python/python.exe')
  const fixture = "import os,sys; sys.path.insert(0,sys.argv[1]); from web.backend.services.workspace_agent import AgentStore,AgentRequest; s=AgentStore(); r=s.create(AgentRequest(question='native-acceptance-fixture')); s.patch(r['run_id'],status='running',owner_pid=int(sys.argv[2])); print(r['run_id'])"
  const seeded = spawnSync(python, ['-c', fixture, workspace, String(runtime.pid)], { env, encoding: 'utf8', windowsHide: true })
  assert.equal(seeded.status, 0, seeded.stderr)
  const runId = seeded.stdout.trim()
  check('active task fixture visible', (await (await api('agent/active')).json()).total >= 1)
  await instance.evaluate(({ app }) => { app.quit() })
  await page.waitForTimeout(1000)
  check('active task quit asks before shutdown', (await instance.evaluate(() => globalThis.acceptanceDialogs)).some(text => text.includes('任务正在运行')))
  check('cancel active quit keeps backend healthy', (await api('health')).ok)
  await fetch(`${runtime.base_url}/api/agent/runs/${runId}/cancel`, { method: 'POST', headers })
  // 用当前后端 PID 的持久化运行夹具验证真实退出/重启后的恢复，不冒充耗时回测已执行。
  const backtestFixture = `import sys, json
sys.path.insert(0, sys.argv[1])
from web.backend.services.backtest_job_service import BacktestTaskRepository
from web.backend.services.workspace_actions import claim_request, complete_request
from web.backend.services.workspace_agent import now
task_id='bt_native_exit_fixture'
BacktestTaskRepository().create({'task_id':task_id,'status':'running','params':{},'message':'native exit fixture'})
claim_request('action','native-exit-backtest',{'fixture':True})
complete_request('action','native-exit-backtest',{'action_id':'native-exit-action','request_id':'native-exit-backtest','kind':'backtest','status':'running','business_id':task_id,'owner_pid':int(sys.argv[2]),'created_at':now(),'parameters':{},'events':[]})
`
  const backtestSeeded = spawnSync(python, ['-c', backtestFixture, workspace, String(runtime.pid)], { env, encoding: 'utf8', windowsHide: true })
  assert.equal(backtestSeeded.status, 0, backtestSeeded.stderr)
  check('live-owner backtest fixture remains active', (await (await api('agent/active')).json()).items.some(item => item.id === 'bt_native_exit_fixture'))
  await page.locator('.body-editor textarea').fill('桌面验收：放弃这次修改')
  await instance.evaluate(() => { globalThis.acceptanceDiscard = true; globalThis.acceptanceStopTasks = true })
  await page.screenshot({ path: path.join(output, 'review-unsaved.png') })
  const closed = instance.waitForEvent('close', { timeout: 20000 })
  await instance.evaluate(({ app }) => { app.quit() }).catch(() => {})
  await closed
  check('confirmed discard exits application', page.isClosed())
  check('owned runtime discovery removed', !fs.existsSync(runtimeFile))
  check('backend port closed', await fetch(`${runtime.base_url}/api/health`).then(() => false).catch(() => true))

  const reopened = await launch()
  const nextRuntime = JSON.parse(fs.readFileSync(runtimeFile, 'utf8'))
  const nextApi = async endpoint => fetch(`${nextRuntime.base_url}/api/${endpoint}`, { headers: { 'X-Quant-Token': nextRuntime.token } })
  check('dead-owner backtest absent from first active query', (await (await nextApi('agent/active')).json()).total === 0)
  const interrupted = await (await nextApi('agent/actions/native-exit-action')).json()
  check('interrupted backtest has audited terminal status', ['failed', 'interrupted'].includes(interrupted.status) && interrupted.events.some(event => event.type === 'owner_interrupted'))
  await reopened.goto(`${nextRuntime.base_url}/review-library`)
  await reopened.locator('.body-editor textarea').waitFor()
  const restoredBody = await reopened.locator('.body-editor textarea').inputValue()
  check('saved review persists across restart', restoredBody.includes('桌面验收：未保存的草稿') && !restoredBody.includes('放弃这次修改'))
  const ended = instance.waitForEvent('close', { timeout: 20000 })
  await instance.evaluate(({ app }) => { app.quit() }).catch(() => {})
  await ended
  result.passed = true
}
main().catch(error => { result.passed = false; result.error = error.stack; process.exitCode = 1 }).finally(async () => {
  fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify({ output, ...result }, null, 2))
  try { await instance?.evaluate(() => { globalThis.acceptanceDiscard = true }) } catch {}
  try { await instance?.close() } catch {}
})
