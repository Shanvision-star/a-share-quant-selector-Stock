# 回测异步任务 Phase 1 说明

## Original

前端回测页直接调用同步 `/api/backtest`。长区间、多候选或分钟级回测时，请求会一直等待后端完成，页面容易表现为卡住，也不利于后续显示进度、排队和失败原因。

## Revised

当前新增任务式接口：

- `POST /api/backtest/tasks`：提交回测任务，立即返回 `task_id` 和任务状态。
- `GET /api/backtest/tasks/{task_id}`：查询任务状态、错误或最终回测结果。
- `GET /api/backtest/{task_id}`：保留为兼容旧路径的任务查询。

前端回测页已改为提交任务后轮询状态，任务完成后再展示 `summary`、交易明细、资金曲线和运行保护提示。同步 `/api/backtest` 仍保留，用于兼容旧调用和测试。

## Impact

当前任务队列是进程内 `ThreadPoolExecutor`，适合本地单机使用和 Phase 1 验证。它能避免单次 HTTP 请求被长回测阻塞，但服务重启后任务状态不会保留。后续如果要支持历史任务列表、跨进程恢复、取消任务或更细进度，应把任务表迁移到 SQLite/Redis，并让执行器按候选回写进度。

