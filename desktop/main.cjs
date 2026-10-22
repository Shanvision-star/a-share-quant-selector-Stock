const { app, BrowserWindow, dialog, session, shell, Menu } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')

let backend
let window
let origin
let quitting = false
let backendLog
const token = crypto.randomBytes(32).toString('hex')
const smoke = process.argv.includes('--smoke-test')

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
    process.env.QUANT_PYTHON ||
    path.join(
      root,
      '.venv',
      process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
    )
  if (!fs.existsSync(python))
    throw new Error('项目缺少 .venv Python 环境，请先按 README 安装依赖。')
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
    fs.mkdirSync(path.join(root, 'output', 'desktop'), { recursive: true })
    fs.writeFileSync(
      path.join(root, 'output', 'desktop', 'desktop-smoke.png'),
      png.toPNG(),
    )
    fs.writeFileSync(
      path.join(root, 'output', 'desktop', 'smoke.json'),
      JSON.stringify(
        { ...result, backendPid: backend.pid, port: new URL(origin).port },
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
  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', (event) => {
    if (!backend || backend.exitCode !== null || quitting) return
    event.preventDefault()
    quitting = true
    const timeout = setTimeout(() => {
      backend.kill()
      app.exit(0)
    }, 7000)
    backend.once('exit', () => {
      clearTimeout(timeout)
      backendLog?.end()
      app.exit(0)
    })
    backend.stdin.end()
  })
}
