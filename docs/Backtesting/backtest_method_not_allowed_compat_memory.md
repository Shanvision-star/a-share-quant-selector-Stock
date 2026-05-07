# 回测 Method Not Allowed 兼容修复记忆

## 问题现象

前端回测工作台点击“开始回测”后弹出：

```text
Method Not Allowed
```

页面当时使用的是异步回测任务逻辑，会向后端发送：

```text
POST /api/backtest/tasks
```

## 根因推导

### 证据 1：当前运行中的 8001 后端返回 405

对当前浏览器使用的后端执行同样请求：

```text
POST http://127.0.0.1:8001/api/backtest/tasks
```

返回：

```json
{"detail":"Method Not Allowed"}
```

### 证据 2：当前运行中后端的 OpenAPI 没有异步任务接口

`http://127.0.0.1:8001/openapi.json` 中只存在：

```text
POST /api/backtest
GET  /api/backtest/{task_id}
```

没有：

```text
POST /api/backtest/tasks
GET  /api/backtest/tasks
```

说明浏览器连到的是旧版后端进程，旧进程还没有加载当前代码里的异步任务路由。

### 证据 3：同一个 payload 调旧同步接口可以成功

同一个人工选股回测 payload 调用：

```text
POST http://127.0.0.1:8001/api/backtest
```

返回 200。

所以问题不是回测参数错误，也不是人工选股池数据无法回测，而是“前端新版本调用异步任务接口，后端运行进程仍是旧同步接口版本”的前后端接口版本漂移。

## 修复方案

### 前端 API 层增加兼容启动函数

新增：

```text
startBacktestTaskCompatible(payload)
```

执行逻辑：

1. 优先调用新版异步任务接口：
   `POST /api/backtest/tasks`
2. 如果后端返回 405，判断为旧版同步后端。
3. 自动退回：
   `POST /api/backtest`
4. 把同步回测结果包装成页面可识别的完成态任务：
   - `status = done`
   - `progress_pct = 100`
   - `message = 兼容同步回测完成`

### 前端页面使用兼容函数

回测工作台不再直接调用 `startBacktestTask`，而是调用 `startBacktestTaskCompatible`。

新版后端存在时：

- 继续走异步任务。
- 保留任务轮询、取消任务、详情抽屉。

旧版后端存在时：

- 不再弹出 Method Not Allowed。
- 自动走同步回测。
- 页面显示回测结果和一个本地完成态任务。
- 给用户提示：后端异步任务接口不可用，已自动切换到同步回测。

## 为什么这样做

- 直接要求重启后端可以临时解决，但无法防止“前端构建已更新、后端进程未重启”的再次发生。
- 把兼容逻辑放在 API 层，可以用单测锁住行为，避免页面到处写 405 判断。
- 旧后端同步接口仍可完成小规模回测，至少能保证用户不被 405 阻断。
- 新后端上线后仍优先使用异步任务，不影响取消任务和任务详情抽屉。

## 防复发规则

以后修改前端 API 调用方式时，必须同时检查：

1. 当前运行后端的 OpenAPI 是否包含目标接口。
2. 前端是否需要兼容旧后端进程。
3. 如果新接口替代旧接口，是否有 405/404 兼容降级或清晰提示。
4. 页面错误提示不能只显示原始英文错误，要尽量说明“接口版本不一致”或“后端未重启到新版本”。

## 验证

### 红灯

新增前端测试：

```text
web/frontend/src/api/__tests__/backtestApi.spec.ts
```

先运行失败，原因：

```text
startBacktestTaskCompatible is not a function
```

### 绿灯

实现兼容函数后运行：

```text
npm run test -- src/api/__tests__/backtestApi.spec.ts --run
```

结果：

```text
2 passed
```

### 真实接口验证

当前 8001 旧后端：

- `POST /api/backtest/tasks` 返回 405。
- `POST /api/backtest` 对同一 payload 返回 200。

这证明兼容路径能覆盖截图中的实际故障。

### 构建验证

```text
npm run build
```

结果：构建通过。仅有 Vite chunk size 警告，不影响本次修复。

## 下一步建议

1. 后端进程仍建议重启到当前 `web` 代码，这样可以恢复异步任务、取消任务、详情抽屉完整能力。
2. 后续可在页面顶部增加“后端能力检测”，启动时主动检测 `/api/backtest/tasks` 是否存在。
3. 如果检测到旧后端，任务面板应明确显示“同步兼容模式”，并隐藏取消任务按钮。
