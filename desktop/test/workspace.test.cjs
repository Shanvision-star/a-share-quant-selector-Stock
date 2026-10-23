const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const crypto = require('node:crypto')
const { installManagedWorkspace, mcpConfiguration, within } = require('../workspace.cjs')

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'quant-bundle-test-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const resources = path.join(root, 'resources')
  fs.mkdirSync(path.join(resources, 'app-source', 'scripts'), { recursive: true })
  fs.mkdirSync(path.join(resources, 'defaults', 'config'), { recursive: true })
  fs.writeFileSync(path.join(resources, 'defaults/config/config.yaml'), 'data_dir: data')
  return { root, resources, user: path.join(root, 'user') }
}
function version(resources, text) {
  fs.writeFileSync(path.join(resources, 'app-source/scripts/run.py'), text)
  fs.writeFileSync(path.join(resources, 'app-source/app-manifest.json'), JSON.stringify({ files: {
    'scripts/run.py': crypto.createHash('sha256').update(text).digest('hex'),
  } }))
}

test('upgrade updates code and preserves edited config, reviews and database', t => {
  const { resources, user } = fixture(t)
  version(resources, 'first')
  const workspace = installManagedWorkspace(resources, user)
  fs.writeFileSync(path.join(workspace, 'config/config.yaml'), 'user-setting')
  fs.writeFileSync(path.join(workspace, 'data/review.md'), 'user-review')
  fs.writeFileSync(path.join(workspace, 'data/cache.db'), 'user-db')
  version(resources, 'second')
  assert.equal(installManagedWorkspace(resources, user), workspace)
  assert.equal(fs.readFileSync(path.join(workspace, 'scripts/run.py'), 'utf8'), 'second')
  assert.equal(fs.readFileSync(path.join(workspace, 'config/config.yaml'), 'utf8'), 'user-setting')
  assert.equal(fs.readFileSync(path.join(workspace, 'data/review.md'), 'utf8'), 'user-review')
  assert.equal(fs.readFileSync(path.join(workspace, 'data/cache.db'), 'utf8'), 'user-db')
})

test('rejects corrupt resources and manifest paths outside managed workspace', t => {
  const { resources, user } = fixture(t)
  version(resources, 'first')
  fs.writeFileSync(path.join(resources, 'app-source/scripts/run.py'), 'corrupt')
  assert.throws(() => installManagedWorkspace(resources, user), /损坏/)
  assert.throws(() => within(user, '../outside'), /无效/)
  fs.writeFileSync(path.join(resources, 'app-source/app-manifest.json'), JSON.stringify({ files: { 'data/cache.db': 'fake' } }))
  assert.throws(() => installManagedWorkspace(resources, user), /用户数据/)
})

test('MCP configuration uses explicit bundled Python and instance discovery without secrets', () => {
  const config = mcpConfiguration('C:\\量化 空间\\python.exe', 'C:\\数据 空间')
  assert.ok(config.includes('QUANT_RUNTIME_FILE'))
  assert.ok(config.includes('quant_mcp.py'))
  assert.ok(config.includes(JSON.stringify('C:\\量化 空间\\python.exe')))
  assert.ok(!config.includes('QUANT_API_TOKEN'))
})
