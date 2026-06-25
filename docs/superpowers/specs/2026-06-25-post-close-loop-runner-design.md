# Post-close Loop Runner 设计规格

> 状态：P0 执行切片。基线分支为 top-level `web`，实现分支为 `codex/post-close-loop-runner`。

## 目标

把 Tracking Agent 的收盘后人工操作串成一个可审计、可重复触发的后端 Runner：

1. 可选刷新活跃跟踪股票的近期行情并推进 `tracking_items` 状态机。
2. 对活跃跟踪项执行规则评估，幂等写入 `tracking_alert_events`。
3. 对 `post_close` slot 分发 pending 告警，继续复用缺省 NullNotifier，不默认触发真实钉钉 HTTP。
4. 记录本次 loop run 的输入、摘要、状态和错误，供前端、系统状态或 crontab 结果排查。

## 当前代码事实

- `TrackingSyncService.sync_and_evaluate()` 已负责小范围行情刷新和状态机推进，但不写 `tracking_alert_events`。
- `TrackingEvaluationService.evaluate_active_items()` 已负责规则评估和告警幂等落库，但不刷新行情、不分发通知。
- `TrackingAlertService.dispatch_pending_alerts()` 已负责 pending 告警按优先级分层分发，但不触发规则评估。
- `tracking_alert_service` 的缺省 notifier 是 NullNotifier；真实钉钉、企业微信、邮件等外部通道必须作为独立 smoke。
- FastAPI 路由顺序要求所有 `/api/tracking/<fixed>` 子路由先于 `/api/tracking/{tracking_id}` 注册。

## 方案对比

| 方案 | 做法 | 优点 | 风险 |
| --- | --- | --- | --- |
| A. crontab 直接连续调三个现有端点 | 外部脚本依次调用 sync/evaluate/dispatch | 代码最少 | 无统一 run_id，失败点难追踪，重复执行状态不清晰 |
| B. 新增后端 Runner 编排服务（推荐） | 新服务顺序调用 sync/evaluate/dispatch，并记录 run | 最小代码、可测试、可审计，未来 crontab 只调一个端点 | 需要新增轻量 run 表和路由 |
| C. 引入 APScheduler 常驻调度 | 应用进程内定时运行 | 自动化程度高 | 多进程重复调度、部署时区、启停恢复都需要额外治理，当前 P0 过重 |

选用方案 B。P0 只提供可触发 Runner，不引入常驻 scheduler。

## 运行合同

新增服务 `web/backend/services/tracking_loop_runner_service.py`：

- `run_post_close(eval_date=None, slot="post_close", per_slot_limit=8, sync_first=True, trigger="manual")`
- 同进程单飞：已有运行未结束时返回 `status="busy"`，不并发刷新 CSV 或重复分发。
- `sync_first=True` 时先调用 `tracking_sync_service.sync_and_evaluate(eval_date=eval_date)`。
- 然后调用 `tracking_evaluation_service.evaluate_active_items(eval_date=eval_date)`。
- 最后调用 `tracking_alert_service.dispatch_pending_alerts(slot=slot, per_slot_limit=per_slot_limit)`。
- 若 sync 或 evaluation 摘要中包含局部 errors，run 状态为 `partial`；若顶层异常发生，run 状态为 `error`，并保留错误摘要。
- 正常无局部 errors 时 run 状态为 `done`。

## 持久化

新增轻量表 `tracking_loop_runs`，由 runner service 在测试和生产中幂等建表：

- `run_id TEXT PRIMARY KEY`
- `loop_type TEXT NOT NULL`，当前固定 `post_close`
- `eval_date TEXT`
- `slot TEXT NOT NULL`
- `status TEXT NOT NULL`：`running|done|partial|error`
- `trigger TEXT NOT NULL`：`manual|cron|api`
- `sync_first INTEGER NOT NULL`
- `per_slot_limit INTEGER NOT NULL`
- `started_at TEXT NOT NULL`
- `completed_at TEXT`
- `sync_json TEXT`
- `evaluation_json TEXT`
- `dispatch_json TEXT`
- `error_json TEXT`

不修改已有告警表名，不新增 `tracking_alerts` 表。

## API

新增路由 `web/backend/routers/tracking_loop.py`，prefix 为 `/api/tracking/loops`：

- `POST /api/tracking/loops/post-close/run`
  - body: `{ eval_date?: string, slot?: string, per_slot_limit?: number, sync_first?: boolean, trigger?: "manual"|"cron"|"api" }`
  - 返回: `{ success: true, data: <run_summary> }`
  - busy 时仍返回 200 和 `status="busy"`，方便 crontab 幂等处理。
- `GET /api/tracking/loops/runs/latest?loop_type=post_close`
  - 返回最新 run；没有 run 时返回 `data: null`。

路由必须在 `tracking.router` 前注册，避免被 `/tracking/{tracking_id}` 通配吞掉。

## 非目标

- 不接真实券商、QMT 或自动下单。
- 不默认调用真实 LLM provider。
- 不默认真实钉钉 HTTP；真实 notifier smoke 独立执行。
- 不引入 APScheduler 或后台常驻线程。
- 不把 Zettaranc dirty worktree 中的实验功能纳入本 P0。
- 不修改前端页面；前端触发按钮和状态卡可作为后续独立任务。

## 验收

- service test 证明 runner 会按 sync → evaluate → dispatch 顺序执行，并持久化 `done` run。
- service test 证明局部 errors 会产生 `partial` run。
- service test 证明顶层异常会产生 `error` run，且 dispatch 不继续执行。
- service test 证明 single-flight busy 不并发执行。
- router test 证明 `POST /api/tracking/loops/post-close/run` 可触发 runner。
- router/order test 证明固定路径不会被 `/api/tracking/{tracking_id}` 吞掉。
- import smoke 通过：`python -c "from web.backend.main import app; print('import-ok')"`。

## 验证命令

```powershell
python -m pytest tests/test_tracking_loop_runner_service.py tests/test_tracking_loop_router.py tests/test_tracking_route_order.py -q
python -m pytest tests/test_tracking_loop_contract.py tests/test_tracking_alert_service.py tests/test_tracking_alert_router.py tests/test_tracking_evaluation_service.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check
```

真实 provider smoke、真实钉钉 smoke、浏览器手动 smoke 不属于默认自动验证；如执行必须单独记录。
