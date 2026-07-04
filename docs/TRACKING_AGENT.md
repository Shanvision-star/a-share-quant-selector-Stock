# Tracking-Agent 总览

> 单股跟踪 + 规则评估 + LLM 建议 + OrderIntent 操盘闭环。  
> 状态更新（2026-06-25）：Tracking Agent Loop MVP 已合入当前 `web` 主线；本文是运行/回归速查，不再是待实施清单。
> 后端入口在 `web/backend/main.py`，前端入口在 `web/frontend/src/views/TrackingView.vue`。
> 配套设计文档：`docs/B2_STRATEGY.md`、`docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md`。

---

## 1. 概述

Tracking-Agent 把"选股池命中 → 持续观察 → 规则告警 → LLM 建议 → 人工确认下单意图"串成一条可审计、可回放的链路：

1. 人工选股池或外部信号将股票登记为 `tracking_items`（`watch_buy` / `holding` 等状态）。
2. 调度或前端主动触发**规则引擎**评估，生成 `tracking_alert_events`（按优先级去重）。
3. **LLM mock 服务**根据当前持仓状态与告警优先级给出确定性建议（decision / suggested_action / suggested_intent）。
4. 操盘手在前端**确认**或**否决** OrderIntent；事件全部落 `tracking_events`。当前闭环不自动下单，后续券商/QMT 只作为独立边界评估。

设计目标：默认回归不依赖真实 LLM 和真实下单通道；真实 provider smoke 必须单独执行和记录。

---

## 2. 数据模型（落盘字段速查）

| 表 / 实体 | 关键字段 | 说明 |
|---|---|---|
| `tracking_items` | `tracking_id`、`code`、`name`、`strategy_name`、`source`、`signal_date`、`status`、`last_eval_date`、`params`、`next_action`、`current_qty`、`latest_intent` | 单股跟踪主表；`status ∈ {watch_buy, holding, closed, ...}`，`next_action ∈ {HOLD, BUY, SELL, REDUCE, ...}`。 |
| `tracking_alert_events` | `alert_id`、`tracking_id`、`rule_id`、`eval_date`、`priority`、`message`、`ui_status` | 评估生成的告警事件；优先级数字越小越紧急。 |
| `tracking_rule_templates` | `template_id`、`name`、`rule_id`、`params`、`enabled`、`note` | 前端可视化编辑的规则参数模板，覆盖引擎默认值。 |
| `tracking_loop_runs` | `run_id`、`loop_type`、`eval_date`、`slot`、`status`、`trigger`、`sync_first`、`per_slot_limit`、`started_at`、`completed_at`、`sync_json`、`evaluation_json`、`dispatch_json`、`error_json` | Post-close Loop Runner 运行记录；`status ∈ {running, done, partial, error}`，同进程已有运行时 API 直接返回 `busy` 且不写入新行。 |
| `OrderIntent`（嵌入 `latest_intent` / 事件 payload） | `intent_id`、`code`、`side`、`qty_hint` / `quantity`、`target_price`、`execution_mode`、`status`、`reason` | 当前只作为人工动作候选；`status ∈ {generated, confirmed, rejected}`，不代表券商订单。 |
| `tracking_events` | `event_id`、`tracking_id`、`event_type`、`payload`、`created_at` | 所有评估、LLM 建议、确认/否决动作都写事件，可审计回放。 |

---

## 3. 接口清单

所有路由统一前缀 `/api`，FastAPI `include_router` 顺序在 [`web/backend/main.py`](../web/backend/main.py)。**特化前缀必须先于 `tracking.router`**（详见路由顺序契约）。

| Method | 路径 | 路由文件 | Service | 用途 |
|---|---|---|---|---|
| GET/POST/DELETE | `/api/manual-selections` | `manual_selection.py` | `manual_selection_service` | 人工选股池列表、新增、删除 |
| POST | `/api/manual-selections/import-txt` | `manual_selection.py` | `manual_selection_service.import_txt` | 从 txt 导入人工选股池 |
| POST | `/api/manual-selections/import-paste` | `manual_selection.py` | `manual_selection_service.import_paste` | 从粘贴文本导入人工选股池 |
| POST | `/api/manual-selections/import-from-strategy` | `manual_selection.py` | `manual_selection_service.import_from_strategy` | 从策略结果导入人工选股池 |
| POST | `/api/tracking` | `tracking.py` | `tracking_service.create_item` | 创建跟踪记录 |
| POST | `/api/tracking/batch-from-selection` | `tracking.py` | `tracking_service.batch_from_selection` | 从人工选股池批量入跟踪（全量或勾选） |
| GET  | `/api/tracking` | `tracking.py` | `tracking_service.list_items` | 列表查询（支持 status/code/limit） |
| GET  | `/api/tracking/{tracking_id}` | `tracking.py` | `tracking_service.get_item` | 单条详情 |
| POST | `/api/tracking/{tracking_id}/evaluate` | `tracking.py` | `tracking_service.evaluate_item` | 单股评估并刷新 `next_action` |
| POST | `/api/tracking/evaluate` | `tracking.py` | `tracking_service.evaluate_items` | 批量评估未结束的跟踪项 |
| GET  | `/api/tracking/{tracking_id}/events` | `tracking.py` | `tracking_service.list_events` | 事件流回放 |
| GET  | `/api/tracking/alerts` | `tracking_alert.py` | `tracking_alert_service.list_alerts` | 按 tracking_id / eval_date / ui_status 列告警 |
| POST | `/api/tracking/alerts/{alert_id}/ack` | `tracking_alert.py` | `tracking_alert_service.update_alert_status` | 标记告警已确认 |
| POST | `/api/tracking/alerts/{alert_id}/ignore` | `tracking_alert.py` | `tracking_alert_service.update_alert_status` | 标记告警已忽略 |
| POST | `/api/tracking/alerts/dispatch` | `tracking_alert.py` | `tracking_alert_service.dispatch_pending_alerts` | 按 slot 分发/聚合告警（去重 + 限额；缺省 notifier 为空实现） |
| POST | `/api/tracking/loops/post-close/run` | `tracking_loop.py` | `tracking_loop_runner_service.run_post_close` | 收盘后编排 sync-close、evaluate-rules 和 alerts dispatch |
| GET  | `/api/tracking/loops/runs/latest` | `tracking_loop.py` | `tracking_loop_runner_service.latest_run` | 读取最近一次 Tracking Loop 运行摘要 |
| POST | `/api/tracking/evaluate-rules` | `tracking_evaluation.py` | `tracking_evaluation_service.evaluate_active_items` | 触发活跃跟踪项的规则评估，返回 evaluated/alerts_created/alerts_skipped_dup |
| POST | `/api/tracking/{tracking_id}/llm-advice` | `tracking_llm.py` | `tracking_llm_service.propose_action` | 生成确定性 LLM 建议（decision/suggested_action/suggested_intent） |
| POST | `/api/tracking/{tracking_id}/confirm-intent` | `tracking_intent.py` | `tracking_service.confirm_intent` | 确认 OrderIntent，写 `intent_confirmed` 事件；显式传入 intent 时更新 `latest_intent` |
| POST | `/api/tracking/{tracking_id}/reject-intent` | `tracking_intent.py` | `tracking_service.reject_intent` | 否决 OrderIntent，`next_action` 回落 HOLD |
| GET  | `/api/tracking/rule-templates/rules` | `tracking_rule_template.py` | `RULE_META + DEFAULT_PARAMS` | 引擎注册表元数据，前端规则编辑器下拉源 |
| GET  | `/api/tracking/rule-templates` | `tracking_rule_template.py` | `tracking_rule_template_service.list` | 模板列表（支持 rule_id / enabled_only） |
| POST | `/api/tracking/rule-templates` | `tracking_rule_template.py` | `tracking_rule_template_service.create` | 新建规则模板 |
| GET  | `/api/tracking/rule-templates/{template_id}` | `tracking_rule_template.py` | `tracking_rule_template_service.get` | 单模板详情 |
| PUT  | `/api/tracking/rule-templates/{template_id}` | `tracking_rule_template.py` | `tracking_rule_template_service.update` | 修改模板 |
| DELETE | `/api/tracking/rule-templates/{template_id}` | `tracking_rule_template.py` | `tracking_rule_template_service.delete` | 删除模板 |

### Post-close Loop Runner

- `POST /api/tracking/loops/post-close/run` 编排 sync-close、evaluate-rules 和 alerts dispatch。
- 默认 `sync_first=true`、`slot=post_close`、`per_slot_limit=8`。
- Runner 写入 `tracking_loop_runs`，终态为 `done|partial|error`；同进程已有运行时返回 `busy`。
- 缺省 notifier 仍为空实现；真实钉钉 smoke 必须单独执行，不属于默认自动化回归。
- `tracking_loop.router` 是 `/api/tracking/loops*` 固定前缀路由，必须在 generic `tracking.router` 前注册，避免被 `/api/tracking/{tracking_id}` 通配吞掉。
- `/api/system/status` 的 `tracking.details.latest_loop_run` 只读展示最近一次 `tracking_loop_runs`，不会触发 runner。
- `latest_loop_status=partial|error` 只提示 Tracking 运维风险，不改变 data/strategy 的 `overall_status`。

---

## 4. 前端面板

[`web/frontend/src/views/TrackingView.vue`](../web/frontend/src/views/TrackingView.vue) 提供：

- **列表与筛选**：按 status / code 过滤；展示 `signal_date`、`last_eval_date`、`next_action`、`latest_intent` 摘要。
- **顶部动作**：「批量规则评估」调用 `POST /api/tracking/evaluate-rules`，toast 显示 `已评估 N 条；新增告警 M（去重 K）`。
- **行展开**：
  - 「近期告警」列表（调用 `GET /api/tracking/alerts?tracking_id=...`）；
  - 「LLM 操盘建议」JSON 块（按需调用 `POST /{id}/llm-advice`）；
  - 「操盘手动作」三按钮：
    - **单条评估** → `POST /{id}/evaluate`；
    - **确认 OrderIntent** → `POST /{id}/confirm-intent`；
    - **否决并重置 HOLD** → 弹窗输入原因后 `POST /{id}/reject-intent`。

---

## 5. 规则模板与优先级

引擎注册表见 [`tracking_rule_engine.py`](../web/backend/services/tracking_rule_engine.py) `RULE_META`：

| rule_id | 名称 | 类别 | priority | action_label |
|---|---|---|---|---|
| `rule_break_short_trend` | 跌破短趋势线 | short_term | 10 | TREND_BREAK |
| `rule_break_bull_bear` | 跌破多空线 | short_term | 20 | STOP_LOSS |
| `rule_short_overshoot` | 短期放飞 | short_term | 50 | SELL_PARTIAL |
| `rule_stall_exit` | N 日不涨退出 | short_term | 60 | WAIT_BUY |
| `rule_long_dead_cross` | 长周期均线死叉 | long_term | 70 | TREND_BREAK |

- **默认参数**由 `DEFAULT_PARAMS` 提供；`tracking_rule_templates` 可按 rule_id 覆写。
- **告警去重**：相同 `(tracking_id, rule_id, eval_date)` 仅写一次，重复评估时计入 `alerts_skipped_dup`。
- **分发阈值**（与 LLM mock 同步）：
  - `priority < 30` → 进入高优先分发集合；
  - `30 ≤ priority < 60` → 中等档，可按 slot 限额分发或聚合；
  - `priority ≥ 60` → 仅入库，常态观察。

---

## 6. LLM provider 与 mock 决策表

[`tracking_llm_service.py`](../web/backend/services/tracking_llm_service.py) 用确定性桩对齐未来真实 LLM 输出结构：

- `provider=mock`：默认回归路径，完全确定性，不调用外部服务。
- `provider=deepseek`：调用 DeepSeek OpenAI-compatible 接口，失败回退 mock。
- `provider=codex_cli`：调用本机/服务器 `codex exec`，用于受控真实 LLM smoke；执行参数固定为只读 sandbox，失败回退 mock。该 provider 依赖 CLI 登录态或服务器环境，不进入默认 pytest/CI；ChatGPT 登录态建议显式配置 `codex_cli.model`，避免 CLI 默认模型与账号权限不兼容。

| 输入条件 | decision | confidence | suggested_action | suggested_intent.side | qty_hint |
|---|---|---|---|---|---|
| 最高优先级告警 `<30` | `cut` | 0.85 | SELL | SELL | `current_qty`（清仓） |
| 最高优先级告警 `30~59` | `reduce` | 0.65 | REDUCE | SELL | `current_qty // 2` |
| 无告警 / 仅 ≥60 且 `status=watch_buy` | `watch` | 0.50 | WAIT | BUY | 0 |
| 无告警 / 仅 ≥60 且其它 status | `hold` | 0.70 | HOLD | HOLD | `current_qty` |

输出额外字段：`rationale`（中文说明）、`alerts_summary.{count, min_priority, triggering_rule}`。

---

## 7. OrderIntent 流转

```
LLM 建议         前端展示          人工动作                落库
─────────       ─────────         ────────────           ──────────────────────
suggested_intent ──► JSON 面板 ──► 确认 OrderIntent ──►  latest_intent_json 保存显式 intent
                                                          tracking_events += intent_confirmed
                                ──► 否决并重置 HOLD ──►   next_action = HOLD
                                                          tracking_events += intent_rejected (reason)
```

落地字段示例（P1.5 e2e 实测，000559 走通后）：

```json
{
  "intent_id": "oi_059ea60b9776",
  "code": "000559",
  "side": "BUY",
  "qty_hint": 0,
  "quantity": 0,
  "target_price": 16.09,
  "execution_mode": "backtest",
  "status": "generated",
  "reason": "awaiting_entry"
}
```

历史 E2E 烟囱测试通过证据：`intent_id=oi_059ea60b9776`、`target_price=16.09`、`execution_mode=backtest`、`status=generated`。当前持久化边界是 `tracking_items.latest_intent_json` 与 `tracking_events.event_type ∈ {intent_confirmed, intent_rejected}`，没有独立 `tracking_intents` 表。

---

## 8. 路由顺序契约（重要）

FastAPI 按 `include_router` 顺序匹配路径。`tracking.router` 中存在 `/tracking/{tracking_id}` 通配，若放在 `tracking_alert.router`、`tracking_evaluation.router` 等前，会把 `/api/tracking/alerts`、`/api/tracking/evaluate-rules` 等固定段当作 `tracking_id` 吃掉，返回 404 `跟踪记录不存在: alerts`。

**正确顺序**（`web/backend/main.py` 路由注册段）：

```
manual_selection.router
tracking_loop.router             # /api/tracking/loops*
tracking_alert.router            # /api/tracking/alerts*
tracking_rule_template.router    # /api/tracking/rule-templates*
tracking_evaluation.router       # /api/tracking/evaluate-rules
tracking_llm.router              # /api/tracking/{id}/llm-advice
tracking_intent.router           # /api/tracking/{id}/confirm-intent | reject-intent
tracking.router                  # 通配兜底
```

新增 `/api/tracking/<固定段>` 子路由时**必须**插在 `tracking.router` 之前，否则会被通配吞掉。`tracking_loop.router` 同样受此约束，不能放到 generic `tracking.router` 后面。

---

## 9. 扩展点

- **真实 LLM 接入**：替换 `tracking_llm_service.propose_action`，保持返回结构不变即可被前端复用。
- **真实下单通道**：未来若启用券商 / QMT，只能消费 `tracking_events.event_type='intent_confirmed'` 这类人工确认事件；是否把 `latest_intent` 转成券商委托必须另开规格和风控验证。
- **告警分发渠道**：当前 `dispatch_pending_alerts` 的缺省 notifier 为空实现；真实钉钉、企业微信、邮件等通道需要单独配置和 smoke，复用同一 slot 限额。
- **规则扩展**：在 `tracking_rule_engine.py` 注册新 rule_id → `RULE_META` / `DEFAULT_PARAMS` / 评估函数，前端模板编辑器零改动自动接入。

---

## 10. 烟囱测试与回归

- E2E 烟囱测试已走通：批量评估 → 展开行 → LLM 建议 → 否决（带原因）→ 单条评估 → 确认 OrderIntent（`intent_id=oi_059ea60b9776`）。
- 后端单测：`pytest -W error::pytest.PytestUnhandledThreadExceptionWarning`（165 用例通过）。
- 2026-06-30 Completion Loop fresh verification：
  - Tracking focused backend regression：84 passed。
  - Backtest compatibility regression：60 passed。
  - Backend import smoke：`import-ok`。
  - Nested frontend tracking API：5 passed。
  - Nested frontend build：通过，仅 Vite chunk-size warning。
- 2026-07-04 Codex CLI 真实 LLM smoke：见 `docs/Tracking/2026-07-04-codex-cli-real-llm-smoke.md`。
  - API path smoke：`provider=codex_cli`、`provider_fallback=False`、`decision=hold`、`suggested_action=HOLD`、latency `31.59s`。
  - Direct CLI usage capture：`input_tokens=19954`、`cached_input_tokens=2432`、`output_tokens=161`、`reasoning_output_tokens=83`；CLI 未返回价格，未计算成本。
- 路由契约回归建议：在新增任何 `/api/tracking/*` 路由后，至少 curl 一次 `GET /api/tracking/alerts` 确认未被通配吞掉。
- Post-close Loop Runner focused regression：
  - `python -m pytest tests/test_tracking_loop_runner_service.py tests/test_tracking_loop_router.py tests/test_tracking_route_order.py -q`
  - `python -m pytest tests/test_tracking_loop_contract.py tests/test_tracking_alert_service.py tests/test_tracking_alert_router.py tests/test_tracking_evaluation_service.py -q`
  - `python -c "from web.backend.main import app; print('import-ok')"`
  - `git diff --check HEAD~3..HEAD`
- 真实 LLM、真实钉钉、券商/QMT smoke 不进入默认回归命令，必须单独开任务、单独记录 provider / 通道 / 成本或外部副作用证据。

---

## 11. Post-closeout 边界

- **Manual Pool → Tracking Intake Bridge**：后续若要增强人工池到跟踪池的运营体验，应只围绕 `/api/manual-selections/*` 与 `/api/tracking/batch-from-selection` 的错误反馈、重复项展示和日期选择展开。
- **Post-close Loop Runner**：P0 后端入口已落地为 `POST /api/tracking/loops/post-close/run`，当前只做手动/API 触发的收盘后编排与运行记录。后续若要接入 cron、前端按钮或真实钉钉通道，应另开规格；默认测试仍使用 mock provider，真实 provider smoke 单独记录。
- **券商/QMT/自动下单**：不属于当前 Tracking Agent Loop MVP。`OrderIntent` 只允许人工确认或否决，不自动提交订单。
