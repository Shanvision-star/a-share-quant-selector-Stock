const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')

function within(root, relative) {
  const destination = path.resolve(root, relative)
  if (!destination.startsWith(path.resolve(root) + path.sep)) throw new Error('无效的应用文件路径')
  return destination
}

function installManagedWorkspace(resources, userData) {
  const source = path.join(resources, 'app-source')
  const root = path.join(userData, 'workspace')
  const manifest = JSON.parse(fs.readFileSync(path.join(source, 'app-manifest.json'), 'utf8'))
  fs.mkdirSync(root, { recursive: true })
  for (const [relative, hash] of Object.entries(manifest.files)) {
    if (relative.startsWith('data/') || relative.startsWith('config/')) throw new Error('应用代码清单包含用户数据')
    const from = within(source, relative)
    const to = within(root, relative)
    const content = fs.readFileSync(from)
    if (crypto.createHash('sha256').update(content).digest('hex') !== hash) throw new Error(`应用文件损坏：${relative}`)
    if (fs.existsSync(to) && crypto.createHash('sha256').update(fs.readFileSync(to)).digest('hex') === hash) continue
    fs.mkdirSync(path.dirname(to), { recursive: true })
    fs.writeFileSync(`${to}.installing`, content)
    fs.renameSync(`${to}.installing`, to)
  }
  const defaults = path.join(resources, 'defaults', 'config')
  fs.mkdirSync(path.join(root, 'config'), { recursive: true })
  for (const filename of fs.readdirSync(defaults)) {
    const target = within(root, `config/${filename}`)
    if (!fs.existsSync(target)) fs.copyFileSync(within(defaults, filename), target)
  }
  fs.mkdirSync(path.join(root, 'data'), { recursive: true })
  return root
}

function mcpConfiguration(python, root) {
  // JSON 字符串也是 TOML 基本字符串，反斜线和非 ASCII 路径均可安全复制。
  return `[mcp_servers.ashare_quant]\ncommand = ${JSON.stringify(python)}\nargs = [${JSON.stringify(path.join(root, 'scripts', 'quant_mcp.py'))}]\n\n[mcp_servers.ashare_quant.env]\nQUANT_RUNTIME_FILE = ${JSON.stringify(path.join(root, 'data', 'desktop-runtime.json'))}\n`
}

module.exports = { within, installManagedWorkspace, mcpConfiguration }
