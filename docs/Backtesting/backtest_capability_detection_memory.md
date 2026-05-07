# 回测后端能力检测阶段记忆

## 任务目标

页面启动时直接检测当前后端是否支持异步回测任务接口：

- 支持时显示“异步任务模式”，保留任务历史、事件流、取消任务和详情抽屉。
- 不支持时显示“同步兼容模式”，自动使用旧同步回测接口，并隐藏取消任务按钮。

## 技术判断

### 为什么需要能力检测

上一个问题的根因是前端已升级到异步任务接口，但当前运行中的 8001 后端仍是旧同步接口版本。

如果只在点击“开始回测”时遇到 405 再降级，用户会在页面上先看到异步任务 UI，包括“取消任务”等旧后端不能支持的操作，容易误解。

因此本阶段把判断提前到页面启动阶段。

### 为什么用空 payload 探测 `POST /api/backtest/tasks`

探测请求：

```text
POST /api/backtest/tasks
Body: {}
```

推导：

- 新后端存在该路由时，空 body 会在参数校验阶段返回 422，不会真正创建任务。
- 旧后端没有该 POST 路由时，会返回 405。
- 因此可以用状态码区分能力：
  - `400/422/2xx`：认为异步任务接口存在。
  - `404/405`：认为进入同步兼容模式。

这样比用 `GET /api/backtest/tasks` 更可靠，因为旧后端可能把 `tasks` 当成 `/api/backtest/{task_id}` 的 path 参数。

## 实现摘要

### API 层

新增：

```text
detectBacktestCapabilities()
```

返回：

```text
{ asyncTasks: true, mode: "async_tasks", reason: "async_task_endpoint_available" }
```

或：

```text
{ asyncTasks: false, mode: "sync_compat", reason: "async_task_endpoint_missing" }
```

`startBacktestTaskCompatible(payload, capabilities)` 现在会读取检测结果：

- `asyncTasks=true`：优先走 `/api/backtest/tasks`。
- `asyncTasks=false`：直接走 `/api/backtest`，不再先打一次一定会 405 的异步接口。

### 页面层

回测工作台新增启动初始化：

```text
initializeBacktestPage()
```

执行：

1. 检测后端能力。
2. 异步任务模式下加载任务历史。
3. 同步兼容模式下清空异步历史和事件流。

页面展示：

- 任务面板右上角显示模式标签：
  - 异步任务模式
  - 同步兼容模式
  - 能力检测中
- 同步兼容模式下显示黄色提示：
  - 当前后端未提供异步回测任务接口。
  - 页面会自动使用同步回测。
  - 任务取消、异步历史和事件流暂不可用。
  - 重启后端到当前 web 代码后恢复异步任务模式。
- 同步兼容模式下隐藏取消按钮。
- 同步兼容模式下不再加载异步任务历史。

### 状态判断模块

新增：

```text
web/frontend/src/views/backtestState.ts
```

把“任务是否可取消”的判断集中为：

```text
isBacktestTaskCancelable(task, capabilities)
```

原因：

- 避免多个模板位置重复写 `queued/running` 判断。
- 让同步兼容模式隐藏取消按钮有单元测试保护。

## 验证

### 红灯

新增测试后先失败：

- `detectBacktestCapabilities is not a function`
- `backtestState` 模块不存在
- 旧后端能力下仍会走异步启动

### 绿灯

执行：

```text
npm run test -- src/api/__tests__/backtestApi.spec.ts src/views/__tests__/backtestState.spec.ts --run
```

结果：

```text
2 files passed, 7 tests passed
```

### 构建

执行：

```text
npm run build
```

结果：构建通过。仅有 Vite chunk size 警告，不影响本阶段功能。

### 当前真实 8001 验证

当前运行后端：

```text
POST /api/backtest/tasks  -> 405
POST /api/backtest        -> 200
```

因此页面启动后应进入“同步兼容模式”，隐藏取消任务按钮，并继续允许同步回测。

## 防复发规则

1. 前端新增依赖后端能力的按钮时，先做 capability 检测或从已有 capability 状态读取。
2. 不要用可能被 path 参数吞掉的 GET 路径做能力探测。
3. 探测接口必须避免产生真实业务副作用，本阶段用空 body 触发校验失败就是为了不创建回测任务。
4. 页面上不能展示旧后端无法支持的操作按钮。
5. API 层兼容逻辑要配单元测试，不只靠人工点击验证。

## 下一步计划

1. 把能力检测扩展为统一的 `backendCapabilities` 模块，覆盖数据更新快路径、异步任务、TXT 导出等关键能力。
2. 页面顶部可以加一个全局后端版本/能力状态，避免用户不知道当前后端是否已重启到最新代码。
3. 后端可新增只读版本接口，例如 `/api/capabilities`，替代前端探测式判断。
