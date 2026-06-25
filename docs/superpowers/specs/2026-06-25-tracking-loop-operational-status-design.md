# Tracking Loop Operational Status 设计规格

> 状态：P0.1 执行切片。基线分支为 top-level `web`，实现分支为 `codex/tracking-loop-operational-status`。

## 目标

让刚合入的 Post-close Loop Runner 在系统状态中心可观察，帮助操盘手判断“收盘循环最近有没有跑、跑到哪一步、是否 partial/error”。

本任务只做只读可见性，不新增前端 nested repo 改动，不触发真实 Runner，不调用真实钉钉/LLM/券商。

## 当前代码事实

- `POST /api/tracking/loops/post-close/run` 已能执行收盘循环，并写入 `tracking_loop_runs`。
- `TrackingLoopRunnerService.latest_run(loop_type="post_close")` 已能返回最近 run。
- `SystemStatusService._tracking_block()` 当前只展示 active tracking、pending alerts 和 alert status counts。
- `SystemStatusService` 默认读取 SQLite 时使用只读连接 `_read_only_db_rows()`，避免 import service singleton 或触发写操作。
- 当前 top-level worktree 没有展开 `web/frontend` nested repo；本切片不改前端，避免误混主工作区 Zettaranc 前端脏改动。

## 方案对比

| 方案 | 做法 | 优点 | 风险 |
| --- | --- | --- | --- |
| A. 只文档说明 Runner API | 不改代码，只告诉用户调用 run/latest | 最小 | `/status` 仍看不到 loop 状态，排障体验弱 |
| B. 在 `/api/system/status` 的 tracking block 增加 latest loop run（推荐） | 只读读取 `tracking_loop_runs`，放入 `tracking.details.latest_loop_run` | 不改前端也能被现有状态页/API 消费；保持无副作用 | 需要扩展 status service 测试 |
| C. 改前端 `/status` 页面加按钮和卡片 | 展示更直观，可手动触发 | 需要处理 nested frontend repo 和 UI 验证，本轮 P0.1 过重 |

选用方案 B。前端按钮/卡片作为后续独立切片。

## 数据合同

`/api/system/status` 的 `tracking.details` 新增：

```json
{
  "latest_loop_run": {
    "run_id": "tlr_xxx",
    "loop_type": "post_close",
    "eval_date": "2026-06-25",
    "slot": "post_close",
    "status": "done|partial|error|running",
    "trigger": "manual|cron|api",
    "sync_first": true,
    "per_slot_limit": 8,
    "started_at": "2026-06-25T15:31:00",
    "completed_at": "2026-06-25T15:31:03",
    "sync": {},
    "evaluation": {},
    "dispatch": {},
    "error": {}
  },
  "latest_loop_status": "done",
  "latest_loop_message": "最近收盘循环完成。"
}
```

没有 run 时：

```json
{
  "latest_loop_run": null,
  "latest_loop_status": "missing",
  "latest_loop_message": "尚未执行过收盘循环。"
}
```

## 状态映射

- `done`：提示“最近收盘循环完成。”
- `partial`：提示“最近收盘循环部分完成，请查看 sync/evaluation error 摘要。”
- `error`：提示“最近收盘循环失败，请查看 error.stage/message。”
- `running`：提示“收盘循环正在运行。”
- `missing`：提示“尚未执行过收盘循环。”

`tracking` block 仍是非核心模块；即使 latest loop 是 `partial/error`，也不改变 `overall_status`。核心数据/策略状态仍由 data、strategy_cache、update_pipeline 决定。

## 只读边界

- 默认 loader 直接读 SQLite 表 `tracking_loop_runs`，不 import `tracking_loop_runner_service`。
- 不调用 `run_post_close()`。
- 不创建真实 notifier，不访问真实 provider，不连接券商/QMT。
- 表不存在或 DB 不存在时返回 `None`，状态视为 `missing`。

## API Smoke

本切片允许做本地 TestClient smoke：

- `POST /api/tracking/loops/post-close/run` 使用 monkeypatch/stub runner 或测试库，不对真实数据源发请求。
- `GET /api/system/status` 读取注入或临时 SQLite 中的 latest run。

真实钉钉、真实 LLM、真实行情刷新不属于本任务验证。

## 验收

- `SystemStatusService` 测试覆盖 latest loop run 为 `done` 时的 details 输出。
- 测试覆盖 latest loop run 为 `partial/error` 时不影响 `overall_status`。
- 测试覆盖默认 loader 不 import 或构造 `TrackingLoopRunnerService`，只读读取 SQLite。
- import smoke 通过。
- `git diff --check` 通过。

## 验证命令

```powershell
python -m pytest tests/test_system_status_service.py tests/test_tracking_loop_runner_service.py tests/test_tracking_loop_router.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check
```
