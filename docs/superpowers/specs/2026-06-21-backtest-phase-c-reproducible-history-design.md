# Backtest Phase C Reproducible History Design

## 背景

Phase A 已把日线回测执行边界收紧到真实 A 股交易日、成交量、涨跌停、T+1 和可卖性。Phase C 的目标不是重造回测引擎，而是在现有 `backtest_tasks` / `backtest_task_events` 持久化能力上补齐“这次回测为什么可复现、在哪里能查、列表会不会过重”的产品契约。

现有代码现实：

- `web/backend/services/backtest_job_service.py` 已用 SQLite 保存异步任务、参数、结果和事件。
- `web/backend/routers/backtest.py` 已提供 `/api/backtest/tasks`、`/api/backtest/tasks/{task_id}`、`/api/backtest/tasks/{task_id}/events`。
- `POST /api/backtest` 同步接口只返回计算结果，不保存任务记录。
- 历史列表当前直接返回 `result_json`，当交易明细较大时会让列表接口变重。

## 目标

1. 每次异步回测生成稳定的复现信息：参数快照、请求哈希、引擎版本、结果哈希和摘要。
2. 历史列表默认只返回轻量摘要，不携带完整 `result_json`。
3. 单任务详情继续能返回完整结果，并能附带事件流，支持复盘。
4. 服务重启后仍可通过 SQLite 查询历史任务详情。
5. 保持同步 `/api/backtest` 兼容，不在本阶段强制保存同步结果。

## 非目标

- 不新增前端页面和 nested frontend gitlink。
- 不新增独立数据库或迁移框架。
- 不重构 `BacktestEngine` 的交易逻辑。
- 不做真实 CSV 全市场长回测验收。
- 不引入 QMT、模拟盘或实盘执行。

## 设计

### 1. Run Manifest

新增轻量 manifest helper，归属 `web/backend/services/backtest_job_service.py`，避免为单一用途创建过多模块。

Manifest 字段：

- `engine_version`: 固定字符串，例如 `backtest-engine-v1-phase-c`。当回测语义改变时手动 bump。
- `request_hash`: 对规范化后的 params 做 SHA-256，取前 16 位，确保同一参数稳定。
- `result_hash`: 任务完成后对规范化 result 做 SHA-256，取前 16 位。
- `params_snapshot`: 持久化时保留原始 params；manifest 只引用 hash，不重复塞大对象。
- `summary_snapshot`: 从 result.summary 提取轻量摘要。

JSON 规范化规则：

- 使用 `json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`。
- dict key 排序，list 顺序保持，因为候选顺序会影响结果。
- None、数字、字符串按 JSON 原样编码。

### 2. SQLite Schema

复用 `backtest_tasks`，增量添加列：

- `request_hash TEXT`
- `result_hash TEXT`
- `engine_version TEXT`
- `summary_json TEXT`

`BacktestTaskRepository._ensure_schema()` 和 `sqlite_service.init_database()` 都要幂等补列，避免新旧数据库启动失败。

索引：

- `idx_backtest_tasks_request_hash`
- `idx_backtest_tasks_finished_at`

### 3. Repository Contract

`BacktestTaskRepository.create()`:

- 创建任务时计算 `request_hash` 和 `engine_version`。
- `summary_json` 初始为空对象。

`BacktestTaskRepository.update(result=...)`:

- 完成任务时计算 `result_hash`。
- 提取 `summary_json`。
- 不改变原有 `result_json`，详情页仍可拿完整结果。

`list_recent(limit, include_result=False)`:

- 默认不返回完整 `result`，只返回 `summary`、hash、状态和进度字段。
- 如未来内部需要完整结果，可通过 `include_result=True` 使用。

`get(task_id, include_events=False)`:

- 默认返回完整 result。
- `include_events=True` 时附加 `events`，供详情页一口气加载任务和事件。

### 4. Router Contract

保持已有路径：

- `GET /api/backtest/tasks` 返回轻量历史列表。
- `GET /api/backtest/tasks/{task_id}` 返回完整详情。
- `GET /api/backtest/tasks/{task_id}/events` 保持兼容。

新增参数：

- `GET /api/backtest/tasks/{task_id}?include_events=true`

错误行为：

- 不存在的 `task_id` 仍返回 404。
- `start_date > end_date` 仍返回 400。

### 5. 文档

`docs/BACKTEST_OVERVIEW.md` 补一段 Phase C 行为：

- 异步任务历史可复现字段。
- 历史列表轻量，详情接口完整。
- 同步接口不保存历史。

## 测试策略

后端 focused tests：

- `tests/test_backtest_job_service.py`
  - 同一 params 生成稳定 `request_hash`。
  - 完成任务写入 `result_hash` 和 `summary`。
  - 新 manager 查询已完成任务可恢复 manifest。
  - `list_recent()` 不返回完整 `result`，但 `get()` 返回。
  - `get(include_events=True)` 附加事件。

- `tests/test_backtest_router_async.py`
  - 任务列表返回 summary/hash，不返回完整 result。
  - 任务详情返回 result。
  - `include_events=true` 返回 events。

验证命令：

```powershell
python -m pytest tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -m pytest tests/test_trading_calendar.py tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check
```

## 风险

- 旧 SQLite 库已有 `backtest_tasks` 表但缺新列，必须用 `ALTER TABLE` 幂等补列。
- 历史列表瘦身会改变前端如果依赖列表里 `result` 的行为；当前 worktree 没有 nested frontend `src`，因此本阶段以 API contract 和 router tests 固化，前端适配放后续。
- `result_hash` 只证明结果 JSON 一致，不证明底层 CSV 未变；完整数据源版本化属于后续 DataPortal/快照层。

