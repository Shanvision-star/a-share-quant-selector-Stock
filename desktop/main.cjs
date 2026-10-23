const { app, BrowserWindow, dialog, session, shell, Menu, clipboard } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { installManagedWorkspace, mcpConfiguration } = require('./workspace.cjs')

let backend
let window
let origin
let quitting = false
let shutdownDone = false
let closeApproved = false
let closeRequestPending = false
let activeRoot
let activePython
let backendLog
const token = crypto.randomBytes(32).toString('hex')
const smoke = process.argv.includes('--smoke-test')
if (process.env.QUANT_USER_DATA) app.setPath('userData', path.resolve(process.env.QUANT_USER_DATA))

function validWorkspace(root) {
  return (
    typeof root === 'string' &&
    fs.existsSync(path.join(root, 'scripts', 'run_desktop_backend.py')) &&
    fs.existsSync(path.join(root, 'web', 'frontend', 'dist', 'index.html'))
  )
}
async function workspace() {
  const settingsPath = path.join(app.getPath('userData'), 'workspace.json')
  let saved
  try {
    saved = JSON.parse(fs.readFileSync(settingsPath, 'utf8')).workspace
  } catch {}
  const options = [
    process.env.QUANT_WORKSPACE,
    app.isPackaged ? null : path.resolve(__dirname, '..'),
    saved,
  ]
  for (const candidate of options)
    if (validWorkspace(candidate)) return candidate
  if (app.isPackaged) return installManagedWorkspace(process.resourcesPath, app.getPath('userData'))
  const selected = await dialog.showOpenDialog({
    title: '选择量化项目目录',
    properties: ['openDirectory'],
  })
  const root = selected.filePaths[0]
  if (selected.canceled || !validWorkspace(root))
    throw new Error(
      '请选择包含 scripts/run_desktop_backend.py 和 web/frontend/dist 的项目目录。',
    )
  fs.mkdirSync(path.dirname(settingsPath), { recursive: true })
  fs.writeFileSync(settingsPath, JSON.stringify({ workspace: root }))
  return root
}
async function launchBackend(root) {
  const python =
    (app.isPackaged ? path.join(process.resourcesPath, 'python', 'python.exe') : process.env.QUANT_PYTHON) ||
    path.join(
      root,
      '.venv',
      process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
    )
  if (!fs.existsSync(python))
    throw new Error(app.isPackaged ? '内置运行环境缺失，请重新安装应用。' : '开发环境缺少 .venv，请先安装项目依赖。')
  activeRoot = root
  activePython = python
  fs.mkdirSync(path.join(root, 'data'), { recursive: true })
  backendLog = fs.createWriteStream(
    path.join(root, 'data', 'desktop-backend.log'),
    { flags: 'a' },
  )
  backend = spawn(
    python,
    ['-u', path.join(root, 'scripts', 'run_desktop_backend.py')],
    {
      cwd: root,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        QUANT_DESKTOP_TOKEN: token,
        PYTHONIOENCODING: 'utf-8',
        PYTHONNOUSERSITE: '1',
        MPLBACKEND: 'Agg',
      },
    },
  )
  backend.stderr.pipe(backendLog)
  const port = await new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('后端启动超时，详情见 data/desktop-backend.log')),
      60000,
    )
    let pending = ''
    backend.once('error', (err) => {
      clearTimeout(timeout)
      reject(err)
    })
    backend.once('exit', () => {
      clearTimeout(timeout)
      reject(new Error('后端启动失败，详情见 data/desktop-backend.log'))
    })
    backend.stdout.on('data', (chunk) => {
      pending += chunk.toString()
      let index
      while ((index = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, index)
        pending = pending.slice(index + 1)
        try {
          const handshake = JSON.parse(line)
          if (Number.isInteger(handshake.port)) {
            clearTimeout(timeout)
            resolve(handshake.port)
          }
        } catch {}
      }
    })
  })
  origin = `http://127.0.0.1:${port}`
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      const health = await fetch(`${origin}/api/health`, {
        headers: { 'x-quant-token': token },
        signal: AbortSignal.timeout(1500),
      })
      if (health.ok) return
    } catch {}
    if (backend.exitCode !== null)
      throw new Error('后端已退出，详情见 data/desktop-backend.log')
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  throw new Error('后端尚未就绪，详情见 data/desktop-backend.log')
}
async function api(endpoint, payload) {
  const response = await fetch(`${origin}/api/agent/${endpoint}`, {
    method: payload ? 'POST' : 'GET',
    headers: { 'X-Quant-Token': token, 'Content-Type': 'application/json' },
    body: payload ? JSON.stringify(payload) : undefined,
    signal: AbortSignal.timeout(4000),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

async function requestClose() {
  if (closeRequestPending || quitting) return
  if (!window || window.isDestroyed()) return shutdownBackend()
  closeRequestPending = true
  try {
    if (backend && backend.exitCode === null) {
      let detail
      try {
        const active = await api('active')
        if (active.total > 0) detail = `还有 ${active.total} 个任务正在运行。退出将中断本地任务，已发送的模型请求可能仍消耗用量。`
      } catch {
        detail = '暂时无法确认后台任务状态。退出可能中断正在进行的工作。'
      }
      if (detail) {
        const answer = await dialog.showMessageBox(window, { type: 'question', title: '退出工作台', message: detail,
          buttons: ['继续工作', '仍要退出'], defaultId: 0, cancelId: 0, noLink: true })
        if (answer.response !== 1) return
      }
    }
    closeApproved = true
    window.close()
  } finally {
    closeRequestPending = false
  }
}

async function shutdownBackend() {
  if (quitting) return
  quitting = true
  const finish = () => {
    if (shutdownDone) return
    shutdownDone = true
    backendLog?.end()
    const runtime = activeRoot && path.join(activeRoot, 'data', 'desktop-runtime.json')
    try {
      if (runtime && JSON.parse(fs.readFileSync(runtime, 'utf8')).pid === backend?.pid) fs.unlinkSync(runtime)
    } catch {}
    app.quit()
  }
  if (!backend || backend.exitCode !== null) return finish()
  // 窗口卸载保护和活动任务确认均已完成，此时才能中断本实例任务。
  try { await api('shutdown', { confirmed: true }) } catch {}
  const timeout = setTimeout(() => { backend.kill(); finish() }, 10000)
  backend.once('exit', () => { clearTimeout(timeout); finish() })
  backend.stdin.end()
}

async function chooseWorkspace(managed = false) {
  let selected
  if (!managed) {
    const result = await dialog.showOpenDialog(window, { title: '连接已有量化项目', properties: ['openDirectory'] })
    if (result.canceled) return
    selected = result.filePaths[0]
    if (!validWorkspace(selected)) return dialog.showErrorBox('无法连接', '请选择包含后端脚本与前端构建的量化项目目录。')
  }
  const settings = path.join(app.getPath('userData'), 'workspace.json')
  fs.mkdirSync(path.dirname(settings), { recursive: true })
  fs.writeFileSync(settings, JSON.stringify({ workspace: selected || null }))
  await dialog.showMessageBox(window, { message: '已保存，下次启动使用此数据空间。', buttons: ['好'] })
}
function secureSession() {
  session.defaultSession.setPermissionRequestHandler(
    (_contents, _permission, callback) => callback(false),
  )
  session.defaultSession.setPermissionCheckHandler(() => false)
  session.defaultSession.webRequest.onBeforeSendHeaders(
    { urls: [`${origin}/*`] },
    (details, callback) => {
      callback({
        requestHeaders: { ...details.requestHeaders, 'X-Quant-Token': token },
      })
    },
  )
  session.defaultSession.webRequest.onHeadersReceived(
    { urls: [`${origin}/*`] },
    (details, callback) =>
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
          ],
        },
      }),
  )
}
async function openWindow(root) {
  window = new BrowserWindow({
    width: 1512,
    height: 960,
    minWidth: 900,
    minHeight: 640,
    title: 'A-share Quant',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    backgroundColor: '#f8f9fc',
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  })
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
  window.webContents.on('will-navigate', (event, url) => {
    if (new URL(url).origin !== origin) {
      event.preventDefault()
      if (/^https:\/\//.test(url)) void shell.openExternal(url)
    }
  })
  window.webContents.on('will-attach-webview', (event) =>
    event.preventDefault(),
  )
  window.on('close', (event) => {
    if (!closeApproved) { event.preventDefault(); void requestClose() }
  })
  window.webContents.on('will-prevent-unload', (event) => {
    const answer = dialog.showMessageBoxSync(window, { type: 'question', title: '尚未保存',
      message: '当前修改尚未保存。', buttons: ['继续编辑', '放弃修改并退出'], defaultId: 0, cancelId: 0, noLink: true })
    if (answer === 1) event.preventDefault()
    else closeApproved = false
  })
  window.on('closed', () => { window = null; void shutdownBackend() })
  await window.loadURL(origin)
  if (!smoke) window.show()
  if (smoke) {
    await new Promise((resolve) => setTimeout(resolve, 4000))
    await window.webContents.executeJavaScript(
      `Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='稍后再说')?.click()`,
    )
    await new Promise((resolve) => setTimeout(resolve, 800))
    const result = await window.webContents.executeJavaScript(
      `({title:document.title,heading:document.querySelector('h1')?.textContent,links:document.querySelectorAll('nav a').length,nodeExposed:typeof require !== 'undefined',agent:!!document.querySelector('.agent-panel')})`,
    )
    result.unauthenticatedStatus = (await fetch(`${origin}/api/health`)).status
    result.authenticatedStatus = (
      await fetch(`${origin}/api/agent/capabilities`, {
        headers: { 'X-Quant-Token': token },
      })
    ).status
    const png = await window.webContents.capturePage()
    const smokeOutput = process.env.QUANT_SMOKE_OUTPUT || path.join(root, 'output', 'desktop')
    fs.mkdirSync(smokeOutput, { recursive: true })
    fs.writeFileSync(
      path.join(smokeOutput, 'desktop-smoke.png'),
      png.toPNG(),
    )
    fs.writeFileSync(
      path.join(smokeOutput, 'smoke.json'),
      JSON.stringify(
        { ...result, backendPid: backend.pid, port: new URL(origin).port, workspace: root, python: activePython, packaged: app.isPackaged },
        null,
        2,
      ),
    )
    app.quit()
  }
}

if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', () => {
    if (window) {
      if (window.isMinimized()) window.restore()
      window.focus()
    }
  })
  app
    .whenReady()
    .then(async () => {
      Menu.setApplicationMenu(
        Menu.buildFromTemplate([
          {
            label: '工作台',
            submenu: [
              { role: 'reload', label: '重新加载' },
              { role: 'togglefullscreen', label: '全屏' },
              { type: 'separator' },
              { label: '打开数据目录', click: () => activeRoot && shell.openPath(path.join(activeRoot, 'data')) },
              { label: '连接已有项目…', click: () => chooseWorkspace() },
              { label: '使用独立数据空间', enabled: app.isPackaged, click: () => chooseWorkspace(true) },
              { label: '复制 Codex MCP 配置', click: () => {
                if (activePython && activeRoot) {
                  clipboard.writeText(mcpConfiguration(activePython, activeRoot))
                  void dialog.showMessageBox(window, { message: 'Codex MCP 配置已复制。', detail: '使用应用自带的 Python，工作台保持打开即可调用。', buttons: ['好'] })
                }
              } },
              { type: 'separator' },
              { role: 'quit', label: '退出' },
            ],
          },
          {
            label: '编辑',
            submenu: [
              { role: 'undo' },
              { role: 'redo' },
              { type: 'separator' },
              { role: 'cut' },
              { role: 'copy' },
              { role: 'paste' },
              { role: 'selectAll' },
            ],
          },
        ]),
      )
      const root = await workspace()
      await launchBackend(root)
      secureSession()
      await openWindow(root)
      backend.once('exit', () => {
        if (!quitting) {
          dialog.showErrorBox(
            '本地服务已退出',
            '请重启工作台，详情见 data/desktop-backend.log。',
          )
          app.quit()
        }
      })
    })
    .catch((error) => {
      dialog.showErrorBox('启动失败', error.message)
      app.quit()
    })
  app.on('window-all-closed', () => { void shutdownBackend() })
  app.on('before-quit', (event) => {
    if (shutdownDone) return
    event.preventDefault()
    void requestClose()
  })
}
