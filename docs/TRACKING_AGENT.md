# Tracking-Agent 总览

> 单股跟踪 + 规则评估 + LLM 建议 + OrderIntent 操盘闭环。  
> 对应分支 `codex/tracking-agent-alerts`；后端入口在 `web/backend/main.py`，前端入口在 `web/frontend/src/views/TrackingView.vue`。  
> 配套设计文档：`docs/B2_STRATEGY.md`、`docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md`。

---

## 1. 概述

Tracking-Agent 把"选股池命中 → 持续观察 → 规则告警 → LLM 建议 → 人工确认下单意图"串成一条可审计、可回放的链路：

1. 人工选股池或外部信号将股票登记为 `tracking_items`（`watch_buy` / `holding` 等状态）。
2. 调度或前端主动触发**规则引擎**评估，生成 `tracking_alerts`（按优先级去重）。
3. **LLM mock 服务**根据当前持仓状态与告警优先级给出确定性建议（decision / suggested_action / suggested_intent）。
4. 操盘手在前端**确认**或**否决** OrderIntent；事件全部落 `tracking_events`，下游可对接券商或回测。

设计目标：上线初期不依赖真实 LLM 和真实下单通道，但接口形态保持与未来真实接入一致，便于无痛切换。

---

## 2. 数据模型（落盘字段速查）

| 表 / 实体 | 关键字段 | 说明 |
|---|---|---|
| `tracking_items` | `tracking_id`、`code`、`name`、`strategy_name`、`source`、`signal_date`、`status`、`last_eval_date`、`params`、`next_action`、`current_qty`、`latest_intent` | 单股跟踪主表；`status ∈ {watch_buy, holding, closed, ...}`，`next_action ∈ {HOLD, BUY, SELL, REDUCE, ...}`。 |
| `tracking_alerts` | `alert_id`、`tracking_id`、`rule_id`、`eval_date`、`priority`、`message`、`ui_status` | 评估生成的告警事件；优先级数字越小越紧急。 |
| `tracking_rule_templates` | `template_id`、`name`、`rule_id`、`params`、`enabled`、`note` | 前端可视化编辑的规则参数模板，覆盖引擎默认值。 |
| `OrderIntent`（嵌入 `latest_intent` / 事件 payload） | `intent_id`、`code`、`side`、`qty_hint` / `quantity`、`target_price`、`execution_mode`、`status`、`reason` | 上线初期 `execution_mode=backtest`、`status ∈ {generated, confirmed, executed, rejected}`。 |
| `tracking_events` | `event_id`、`tracking_id`、`type`、`payload`、`created_at` | 所有评估、LLM 建议、确认/否决动作都写事件，可审计回放。 |

---

## 3. 接口清单

所有路由统一前缀 `/api`，FastAPI `include_router` 顺序在 [`web/backend/main.py`](../web/backend/main.py) L154-160。**特化前缀必须先于 `tracking.router`**（详见第 8 节）。

| Method | 路径 | 路由文件 | Service | 用途 |
|---|---|---|---|---|
| POST | `/api/tracking` | `tracking.py` | `tracking_service.create_item` | 创建跟踪记录 |
| POST | `/api/tracking/batch-from-selection` | `tracking.py` | `tracking_service.batch_from_selection` | 从人工选股池批量入跟踪（全量或勾选） |
| GET  | `/api/tracking` | `tracking.py` | `tracking_service.list_items` | 列表查询（支持 status/code/limit） |
| GET  | `/api/tracking/{tracking_id}` | `tracking.py` | `tracking_service.get_item` | 单条详情 |
| POST | `/api/tracking/{tracking_id}/evaluate` | `tracking.py` | `tracking_service.evaluate_item` | 单股评估并刷新 `next_action` |
| POST | `/api/tracking/evaluate` | `tracking.py` | `tracking_service.evaluate_items` | 批量评估未结束的跟踪项 |
| GET  | `/api/tracking/{tracking_id}/events` | `tracking.py` | `tracking_service.list_events` | 事件流回放 |
| GET  | `/api/tracking/alerts` | `tracking_alert.py` | `tracking_alert_service.list_alerts` | 按 tracking_id / eval_date / ui_status 列告警 |
| POST | `/api/tracking/alerts/dispatch` | `tracking_alert.py` | `tracking_alert_service.dispatch_pending_alerts` | 按 slot 推送钉钉告警（去重 + 限额） |
| POST | `/api/tracking/evaluate-rules` | `tracking_evaluation.py` | `tracking_evaluation_service.evaluate_active_items` | 触发活跃跟踪项的规则评估，返回 evaluated/alerts_created/alerts_skipped_dup |
| POST | `/api/tracking/{tracking_id}/llm-advice` | `tracking_llm.py` | `tracking_llm_service.propose_action` | 生成确定性 LLM 建议（decision/suggested_action/suggested_intent） |
| POST | `/api/tracking/{tracking_id}/confirm-intent` | `tracking_intent.py` | `tracking_service.confirm_intent` | 确认 OrderIntent，写事件并更新 `latest_intent` |
| POST | `/api/tracking/{tracking_id}/reject-intent` | `tracking_intent.py` | `tracking_service.reject_intent` | 否决 OrderIntent，`next_action` 回落 HOLD |
| GET  | `/api/tracking/rule-templates/rules` | `tracking_rule_template.py` | `RULE_META + DEFAULT_PARAMS` | 引擎注册表元数据，前端规则编辑器下拉源 |
| GET  | `/api/tracking/rule-templates` | `tracking_rule_template.py` | `tracking_rule_template_service.list` | 模板列表（支持 rule_id / enabled_only） |
| POST | `/api/tracking/rule-templates` | `tracking_rule_template.py` | `tracking_rule_template_service.create` | 新建规则模板 |
| GET  | `/api/tracking/rule-templates/{template_id}` | `tracking_rule_template.py` | `tracking_rule_template_service.get` | 单模板详情 |
| PUT  | `/api/tracking/rule-templates/{template_id}` | `tracking_rule_template.py` | `tracking_rule_template_service.update` | 修改模板 |
| DELETE | `/api/tracking/rule-templates/{template_id}` | `tracking_rule_template.py` | `tracking_rule_template_service.delete` | 删除模板 |

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
  - `priority < 30` → 必发钉钉；
  - `30 ≤ priority < 60` → 中等档，可聚合；
  - `priority ≥ 60` → 仅入库，常态观察。

---

## 6. LLM mock 决策表

[`tracking_llm_service.py`](../web/backend/services/tracking_llm_service.py) 用确定性桩对齐未来真实 LLM 输出结构：

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
suggested_intent ──► JSON 面板 ──► 确认 OrderIntent ──►  latest_intent.status = generated → confirmed
                                                          tracking_events += confirm_intent
                                ──► 否决并重置 HOLD ──►   next_action = HOLD
                                                          tracking_events += reject_intent (reason)
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

E2E 烟囱测试通过证据：`intent_id=oi_059ea60b9776`、`target_price=16.09`、`execution_mode=backtest`、`status=generated`，可在 `tracking_intents` 表中查询。

---

## 8. 路由顺序契约（重要）

FastAPI 按 `include_router` 顺序匹配路径。`tracking.router` 中存在 `/tracking/{tracking_id}` 通配，若放在 `tracking_alert.router`、`tracking_evaluation.router` 等前，会把 `/api/tracking/alerts`、`/api/tracking/evaluate-rules` 等固定段当作 `tracking_id` 吃掉，返回 404 `跟踪记录不存在: alerts`。

**正确顺序**（commit `1ab0e69`，`web/backend/main.py` L154-160）：

```
manual_selection.router
tracking_alert.router            # /api/tracking/alerts*
tracking_rule_template.router    # /api/tracking/rule-templates*
tracking_evaluation.router       # /api/tracking/evaluate-rules
tracking_llm.router              # /api/tracking/{id}/llm-advice
tracking_intent.router           # /api/tracking/{id}/confirm-intent | reject-intent
tracking.router                  # 通配兜底
```

新增 `/api/tracking/<固定段>` 子路由时**必须**插在 `tracking.router` 之前，否则会被通配吞掉。

---

## 9. 扩展点

- **真实 LLM 接入**：替换 `tracking_llm_service.propose_action`，保持返回结构不变即可被前端复用。
- **真实下单通道**：消费 `tracking_events` 中 `type=confirm_intent` 的事件，把 `latest_intent` 推送到券商 / QMT；`execution_mode` 从 `backtest` 切到实盘。
- **告警分发渠道**：当前 `dispatch_pending_alerts` 默认钉钉；可在 service 内扩展企业微信、邮件等通道，复用同一 slot 限额。
- **规则扩展**：在 `tracking_rule_engine.py` 注册新 rule_id → `RULE_META` / `DEFAULT_PARAMS` / 评估函数，前端模板编辑器零改动自动接入。

---

## 10. 烟囱测试与回归

- E2E 烟囱测试已走通：批量评估 → 展开行 → LLM 建议 → 否决（带原因）→ 单条评估 → 确认 OrderIntent（`intent_id=oi_059ea60b9776`）。
- 后端单测：`pytest -W error::pytest.PytestUnhandledThreadExceptionWarning`（165 用例通过）。
- 路由契约回归建议：在新增任何 `/api/tracking/*` 路由后，至少 curl 一次 `GET /api/tracking/alerts` 确认未被通配吞掉。
