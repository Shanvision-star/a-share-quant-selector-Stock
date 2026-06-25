# 跟踪 Agent 与提醒系统设计文档（历史 P0 基线）

> 分支：`codex/tracking-agent-alerts`（从 `web` 切出）
> 状态更新（2026-06-25）：本文是 Tracking Agent Loop MVP 的历史设计基线；当前 `web` 主线已合入 MVP，不再把 P1-P7 当待实施清单。
> 适用范围：人工股票池 → 跟踪 → 短/长周期规则评估 → 钉钉+前端提醒 → OrderIntent 人工确认

---

## 0. Closeout Note（2026-06-25）

当前代码事实以 `web` 主线为准：

- 已落地：manual selection 导入/批量入跟踪、规则评估、`tracking_alert_events` 持久化、ack/ignore/dispatch、LLM advice、`suggested_intent` 人工确认/否决、system status tracking 计数。
- 实际 manual selection API 使用 `/api/manual-selections/*` 复数路径，不使用 `/api/manual-selection/*`。
- 实际告警表/服务使用 `tracking_alert_events`，不要写 `tracking_alerts` 作为表名。
- `OrderIntent` 不自动下单，只进入人工确认或否决；真实 provider smoke 不进入默认测试。
- 本 top-level worktree 未展开 `web/frontend` nested repo；本文不作为前端代码修改依据。

保留本文件的目的：记录 P0 设计意图、边界与阶段拆分，帮助后续审计为什么这样实现；后续 agent 不应按旧阶段表重复实现已完成能力。

## 1. 边界与不变量（必须先读）

按 [agent.md](../../agent.md) 的 QMT 与执行约定，本系统必须遵守：

| 项目 | 允许 | 不允许 |
| --- | --- | --- |
| 信号生成 | 规则引擎按本地 CSV 计算 | LLM 直接生成买卖指令 |
| 提醒推送 | 钉钉 markdown、前端提醒中心 | 自动下单、绕过人工 |
| LLM 角色 | 解释规则、归纳风险、生成 JSON 摘要 | 进入实时交易循环、给出仓位承诺 |
| 执行模式 | `paper` / `confirm_manual` | `auto` / `confirm_broker` |
| 数据源 | 本地 `data/*.csv` + `manual_selections` + `tracking_items` | 实时分钟级（暂不接入） |

**核心不变量**：
- 一条提醒必须能回溯到：`tracking_id + rule_template_id + signal_date + close_value`。
- 任何"买/卖"按钮的最终态都是 `OrderIntent`，等待用户在前端点"已执行/忽略"。
- 数据更新 `partial` 状态绝不触发跟踪评估（与现有 data_service 一致）。

---

## 2. 用户决策记录（2026-05-26）

| 议题 | 决策 |
| --- | --- |
| 手动股票池入口 | **三种全部支持**：txt 导入、从策略结果一键加入、粘贴代码框 |
| 规则优先级 | **跌破短趋势线 / 跌破多空线** 优先实现，其余延后 |
| 规则参数 | **必须可调**，存 `tracking_rule_templates` + 实例可覆盖 |
| 钉钉提醒频率 | **每日 3 次**：开盘前（09:00）、午盘（11:30）、收盘后（15:30） |
| 自动化级别 | 系统性思维、可回溯、可维护，**禁止隐藏状态** |

---

## 3. 系统数据流

```
[人工股票池入口]                  [策略结果]
  txt 导入                          已有缓存
  粘贴代码框           ───→  manual_selections (已有表)
  策略一键加入                          │
                                        ▼
                              [批量加入跟踪]（已在 MVP 落地）
                                        │
                                        ▼
                              tracking_items (已有表)
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  ▼                     ▼                     ▼
        [短周期规则评估]      [长周期规则评估]        [规则模板配置]
         1/3/5/10 日             20/60/120 日       tracking_rule_templates
                  └─────────────────────┼─────────────────────┘
                                        ▼
                          [规则命中 → action_label]
                                        │
                                        ▼
                          tracking_alert_events
                          + tracking_events (已有，审计流水)
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  ▼                     ▼                     ▼
            [钉钉推送]            [前端提醒中心]         [LLM 解读]
       3 时段 + 去重 + 限流      pending / acknowledged / ignored    JSON 摘要 (P6)
                                        │
                                        ▼
                          [OrderIntent 人工确认]
                       tracking_items.latest_intent_json
                       + 状态机：WATCH → BUY_READY → HOLD → ...
```

---

## 4. 阶段切分（历史 P0→P7）

| 阶段 | 范围 | 关键交付 | 验证 |
| --- | --- | --- | --- |
| **P0** | 本设计文档 | `docs/Tracking/tracking_agent_plan.md` | 已作为历史设计基线保留 |
| **P1** | 数据模型 + 入口 | 3 种股票池导入、批量加入跟踪 API | 已在 MVP 落地；实际 API 为 `/api/manual-selections/*` |
| **P2** | 规则引擎 | `tracking_rule_engine.py`，先实现 2 条优先规则 | 已在 MVP 落地 |
| **P3** | 规则模板配置 | `tracking_rule_templates` 表 + CRUD + 实例参数覆盖 | 已在 MVP 落地 |
| **P4** | 提醒中心 | `tracking_alert_events` + 手动 dispatch + 去重 | 已在 MVP 落地；ack/ignore/dispatch 使用告警事件状态，真实钉钉外发未在本次 closeout 验证 |
| **P5** | 评估调度 | 手动按钮 + 可选自动级联（默认关闭） | 已在 MVP 落地到手动/状态可见范围 |
| **P6** | LLM 解读 | mock LLM 接口契约，JSON schema 落库 | 已在 MVP 落地；真实 provider smoke 单独执行 |
| **P7** | OrderIntent 闭环 | 前端确认/否决按钮，状态机收敛 | 已在 MVP 落地；不自动下单 |

**当前任务范围**：closeout 文档同步；不改代码、不重跑大测试；通过分支提交文档事实。

---

## 5. 数据模型（历史 P1-P4 增量）

### 5.1 已有表（不动 schema，只补字段使用约定）

- `manual_selections`：人工股票池。新增导入来源时复用 `source_payload_json` 携带 `import_type ∈ {txt, paste, strategy_pick}`。
- `tracking_items`：单股跟踪主表。当前代码使用 `status ∈ {watch_buy, holding, partial_sold, closed}`。
- `tracking_events`：跟踪事件流。`intent_confirmed`、`intent_rejected`、`llm_mismatch` 等事件用于审计。

### 5.2 已落地表（P3-P4 设计基线）

```sql
-- 表 12: tracking_rule_templates - 跟踪规则模板（可参数化）
CREATE TABLE IF NOT EXISTS tracking_rule_templates (
    template_id      TEXT PRIMARY KEY,        -- 例：rule_break_short_trend
    name             TEXT NOT NULL,           -- 显示名："跌破短趋势线"
    category         TEXT NOT NULL,           -- short_term | long_term | risk
    priority         INTEGER NOT NULL,        -- 数字越小越优先
    action_label     TEXT NOT NULL,           -- WAIT_BUY|BUY_READY|HOLD|SELL_PARTIAL|STOP_LOSS|TREND_BREAK
    params_schema    TEXT NOT NULL,           -- JSON：参数定义和默认值
    enabled          INTEGER NOT NULL DEFAULT 1,
    description      TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- 表 13: tracking_alert_events - 提醒事件流（用于去重与审计）
CREATE TABLE IF NOT EXISTS tracking_alert_events (
    alert_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_id      TEXT NOT NULL,
    rule_id          TEXT NOT NULL,
    code             TEXT NOT NULL,
    eval_date        TEXT NOT NULL,           -- 触发的交易日
    priority         INTEGER NOT NULL,
    category         TEXT,
    action_label     TEXT,
    name             TEXT,
    message          TEXT,
    evidence_json    TEXT,                    -- 详细数据快照（指标值、阈值）
    dedup_key        TEXT NOT NULL UNIQUE,    -- tracking_id|rule_id|eval_date
    dingtalk_slot    TEXT,                    -- pre_open|midday|post_close
    ui_status        TEXT DEFAULT 'pending',  -- pending|dispatched|aggregated|acknowledged|ignored
    created_at       TEXT NOT NULL,
    dispatched_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_events_tracking_id ON tracking_alert_events(tracking_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_eval_date ON tracking_alert_events(eval_date);
CREATE INDEX IF NOT EXISTS idx_alert_events_priority ON tracking_alert_events(priority);
CREATE INDEX IF NOT EXISTS idx_alert_events_dingtalk_slot ON tracking_alert_events(dingtalk_slot);
```

**去重 key 设计原因**：同一股票同一天同一规则只发一次；不同规则各发一次（保持可审计颗粒度）。

### 5.3 不新建 `order_intent_queue`

复用 `tracking_items.latest_intent_json` + `next_action` 字段；只在 `tracking_events` 写 `event_type='intent_confirmed'` / `'intent_rejected'` 用于回溯。

---

## 6. 优先规则定义

### 6.1 R001 跌破短趋势线（短周期，最高优先）

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `short_ma_window` | 5 | 短均线周期（日 K） |
| `confirm_close_count` | 1 | 连续收盘跌破 N 根 |
| `tolerance_pct` | 0.5 | 收盘价低于 MA 的容差比例（%） |
| `volume_filter` | false | 是否要求放量确认 |

**触发**：`close < MA(short_ma_window) * (1 - tolerance_pct/100)` 连续 `confirm_close_count` 根。
**action_label**：`TREND_BREAK`（建议减仓或退出观察）。

### 6.2 R002 跌破多空线（中周期，高优先）

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `bull_bear_source` | `zhixing` | 多空线来源，复用 `utils/technical.py` 知行双线 |
| `confirm_close_count` | 2 | 连续收盘跌破 N 根 |
| `tolerance_pct` | 0.3 | 容差比例 |

**触发**：`close < bull_bear_line` 连续 `confirm_close_count` 根。
**action_label**：`STOP_LOSS`（建议清仓重审）。

### 6.3 其余规则（P2 同步实现，权重下调）

按用户 2026-05-26 补充决策：**其余规则也参与推送**，但通过 `priority` 数字下调权重，提醒中心按 `priority` 升序排序、钉钉超限时优先截断这些低权重项。

| 模板 ID | 名称 | 类别 | 默认 priority | action_label | 说明 |
| --- | --- | --- | --- | --- | --- |
| `rule_break_short_trend` | 跌破短趋势线 | short_term | 10 | `TREND_BREAK` | 5.1 节，最高优先 |
| `rule_break_bull_bear` | 跌破多空线 | short_term | 20 | `STOP_LOSS` | 5.2 节，高优先 |
| `rule_short_overshoot` | 短期放飞（偏离短均线过大） | short_term | 50 | `SELL_PARTIAL` | 偏离短均线 > overshoot_pct 触发 |
| `rule_stall_exit` | N 日不涨退出 | short_term | 60 | `WAIT_BUY` | 跟踪后 N 日累计涨幅 < stall_pct |
| `rule_long_dead_cross` | 长周期均线死叉 | long_term | 70 | `TREND_BREAK` | 60/120 日死叉 |

**权重规则**：
- `priority < 30`：必发，钉钉超限时也保留
- `30 ≤ priority < 60`：按规模发，钉钉超限优先截断
- `priority ≥ 60`：仅在提醒中心展示，钉钉默认聚合为"另有 N 条低优提醒"一行

所有低权重规则的参数同样存 `tracking_rule_templates.params_schema`，用户可在前端模板管理页随时启用/禁用或调权重。

---

## 7. 钉钉提醒调度

本节保留历史调度设计口径。当前 MVP 已有告警分发/聚合状态与缺省空 notifier；真实钉钉外发、crontab 启用和外部 webhook smoke 不在本次 closeout 验证范围内。

### 7.1 三时段定义

| 槽位 | 触发时间 | 内容范围 |
| --- | --- | --- |
| `pre_open` | 09:00 | 昨日收盘评估生成的新提醒 + 未处理的 pending/dispatched |
| `midday` | 11:30 | 上午盘中如有手动评估产生的提醒（用户主动按钮才产生，自动评估不在盘中跑） |
| `post_close` | 15:30 | 当日收盘后规则评估产生的全部新提醒 |

### 7.2 限流与去重

- 单条 `dedup_key` 全生命周期只发一次。
- 单槽位单次推送最多 N 条（默认 N=20），超出按 `priority` 截断并在 markdown 末尾提示"另有 X 条待查看"。
- 钉钉失败时保持 `ui_status='pending'`，下次同槽位仍可分发；分发成功写 `dispatched`，聚合类写 `aggregated`，不阻塞提醒中心查看。

### 7.3 调度入口

按用户 2026-05-26 补充决策：**P4 阶段先做手动按钮，crontab 能力同步保留**，不引入 APScheduler。

| 阶段 | 触发方式 | 实现 |
| --- | --- | --- |
| P4 必交 | 手动 API + 前端按钮 | `POST /api/tracking/alerts/dispatch?slot=pre_open|midday|post_close`，幂等（基于 `ui_status` 状态） |
| P4 同期产出 | crontab 模板（默认注释） | 在 `config/crontab.txt` 追加 3 行注释样例，文档说明如何取消注释启用 |
| 启用开关 | `config/strategy_params.yaml` | `tracking.alert_slots.auto_dispatch_enabled: false`，crontab 调用同一 API；前端展示当前是否已开启自动调度 |

**幂等保证**：同一 `slot` 在同一交易日多次触发，仅分发 `ui_status='pending'` 的记录；已 `dispatched` / `aggregated` / `acknowledged` / `ignored` 的不重复发。

---

## 8. API 设计（当前路径同步）

| Method | Path | 当前状态 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/manual-selections/import-txt` | 已落地 | 上传 txt，逐行解析 6 位代码 |
| POST | `/api/manual-selections/import-paste` | 已落地 | 粘贴文本，正则提取代码 |
| POST | `/api/manual-selections/import-from-strategy` | 已落地 | 从策略结果按 trade_date 一键导入 |
| POST | `/api/tracking/batch-from-selection` | 已落地 | 把某日 manual_selections 整批转 tracking；前端运营桥接另开任务 |
| POST | `/api/tracking/evaluate-rules` | 已落地 | 触发当前 active tracking 全量规则评估 |
| GET / POST / PUT / DELETE | `/api/tracking/rule-templates` | 已落地 | 模板 CRUD；独立前端管理页不在本次 closeout 验证 |
| GET | `/api/tracking/alerts` | 已落地 | 查询提醒列表，支持 ui_status 筛选 |
| POST | `/api/tracking/alerts/{alert_id}/ack` | 已落地 | 标记已确认 |
| POST | `/api/tracking/alerts/{alert_id}/ignore` | 已落地 | 标记忽略 |
| POST | `/api/tracking/alerts/dispatch` | 已落地 | 触发告警分发/聚合（按 slot；真实钉钉外发另行配置和 smoke） |

**返回结构统一**：`{success: bool, data: ..., error: str|null}`，与现有 API 一致。

---

## 9. 前端页面切分（历史设计与当前边界）

| 视图 | 文件 | 当前状态 / 边界 | 说明 |
| --- | --- | --- | --- |
| 每日股票池 | `web/frontend/src/views/ManualSelectionPoolView.vue`（增强） | 已有基础页面；运营桥接另开任务 | 三种导入入口与池子查看是历史设计目标；本次未验证 nested frontend |
| 批量加入跟踪 | 上述视图内按钮 | 后续任务：Manual Pool → Tracking Intake Bridge | 后端 `/api/tracking/batch-from-selection` 已落地；前端选择/失败反馈体验另行实现 |
| 跟踪看板 | `web/frontend/src/views/TrackingView.vue`（新增或增强） | MVP 已落地 | 按 status 分组展示、评估、告警与意图动作 |
| 规则模板管理 | `web/frontend/src/views/TrackingRuleTemplatesView.vue`（新增） | 后续独立 UI；后端 CRUD 已落地 | 表单 + 启用开关不在本次 closeout 验证 |
| 提醒中心 | `web/frontend/src/views/TrackingAlertCenterView.vue`（新增） | 后续独立 UI；TrackingView 行内告警已落地 | 独立全局队列不在本次 closeout 验证 |

**所有按钮文案约束**（与 agent.md 一致）：
- ✅ "加入跟踪"、"评估跟踪"、"待确认"、"已处理"、"忽略"、"生成意图"
- ❌ "自动买入"、"自动卖出"、"AI 荐股"、"保证收益"

---

## 10. LLM 集成契约（P6）

**输入**（后端构造 evidence pack）：
```json
{
  "code": "603920",
  "name": "...",
  "signal_date": "2026-05-26",
  "tracking_status": "HOLD",
  "latest_close": 12.34,
  "latest_return_pct": -3.2,
  "rule_hits": [{"template_id": "rule_break_short_trend", "params": {...}}],
  "indicators": {"ma5": 12.50, "ma20": 12.10, "zhixing_bull": 12.45, ...},
  "recent_events": [...]
}
```

**输出 JSON schema**（严格校验，校验失败丢弃）：
```json
{
  "summary": "string, <=80 字",
  "action_label": "WAIT_BUY|BUY_READY|HOLD|SELL_PARTIAL|STOP_LOSS|TREND_BREAK|NO_ACTION",
  "evidence": ["string, <=5 条"],
  "risk_tags": ["string, <=5 个"],
  "question_for_user": "string, 可为空"
}
```

**关键约束**：
- `action_label` 必须与规则引擎给出的一致；不一致时记 `event_type='llm_mismatch'`，**以规则引擎为准**。
- LLM 输出只进 `tracking_events.payload_json`，不直接驱动提醒。
- P6 起步只做 mock，真实 LLM 调用在用户提供 key + 成本预算后启动。

---

## 11. 系统性思维落地（可回溯 / 可维护）

| 维度 | 实现 |
| --- | --- |
| **可回溯** | 每条提醒可追溯到：tracking_id → rule_template + params 快照 → signal_date 当日 close + 指标 → 推送状态 + 用户操作 |
| **幂等** | `tracking_alert_events.dedup_key` 唯一索引；批量加入跟踪以 `(code, source_date)` 去重 |
| **状态机** | `tracking_items.status` 与 `tracking_alert_events.ui_status` 都有显式枚举，禁止隐式状态 |
| **故障隔离** | 钉钉失败、LLM 失败、单股评估失败都不阻塞批量评估；失败明细写 `tracking_events` |
| **配置外置** | 规则参数 → `tracking_rule_templates`；钉钉时段 → `config/strategy_params.yaml` 新增 `tracking.alert_slots` |
| **可测试** | 每条规则独立 pytest；评估器以 DataFrame 入参，便于注入历史数据 |
| **不污染主链路** | 跟踪评估默认不在 `/api/update` 自动级联；通过独立 `evaluate-batch` 手动触发 |

---

## 12. MVP Loop Execution Contract

Tracking Agent Loop MVP 以规则引擎为权威，Zettaranc 只作为建议 profile 与技术上下文来源。
闭环顺序固定为：人工选股池或策略结果 → tracking_items → evaluate-rules →
tracking_alert_events → LLM/mock advice → OrderIntent → 人工确认或否决 →
tracking_events。

约束：

- `zettaranc_style` 不能覆盖规则引擎的 `action_label`。
- `suggested_intent` 必须进入人工确认，不能触发自动下单。
- 告警处理状态只允许 pending / dispatched / aggregated / acknowledged / ignored。
- 默认测试使用 mock provider；真实 provider smoke 必须单独执行和记录。

---

## 13. Closeout 验证矩阵（2026-06-25 文档同步）

| 项目 | 当前状态 | 本次验证方式 |
| --- | --- | --- |
| manual selection API 路径 | 使用 `/api/manual-selections/*` 复数路径 | `rg` 静态检查 |
| 告警表/服务命名 | 使用 `tracking_alert_events` | `rg` 静态检查 |
| ack/ignore/dispatch | MVP 已落地，作为告警状态动作而非交易动作 | 文档与代码路径静态核对 |
| `suggested_intent` | 进入人工确认/否决，不自动下单 | 文档同步；未跑端到端代码测试 |
| system status tracking 计数 | MVP 已落地 | 文档同步；未跑后端 pytest |
| 真实 provider smoke | 不进入默认测试 | 明确边界；本次未执行 |

未验证项：本次是文档 closeout，不运行后端 pytest、前端 build、真实 provider smoke、钉钉真实推送或 nested frontend repo 检查。

---

## 14. 风险登记

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| 钉钉接口限流 | 中 | 单槽 N 条上限 + 失败补发 + 监控日志 |
| 规则参数误配置 | 中 | 模板 `params_schema` 校验 + 模板更新生成新版本，旧 alert 保留快照 |
| 用户批量导入坏代码 | 低 | 6 位代码正则 + 与 `stock_names.json` 交叉校验 |
| 评估期间 CSV 仍在更新 | 中 | 复用 `update_status` gate：partial 状态拒绝评估 |
| LLM 输出与规则冲突 | 中 | 规则引擎为权威，LLM 仅作解释；冲突落事件审计 |
| 长期未处理 alert 堆积 | 低 | 提醒中心默认筛选 7 日内 pending/dispatched；提供"全部忽略 X 日前"按钮 |

---

## 15. 下一步任务边界（Post-closeout）

P0/P1/P2/P3/P4/P5/P6/P7 不再作为待实施清单。下一步只在明确新任务中推进：

1. **Manual Pool → Tracking Intake Bridge**：只处理人工池到跟踪池的运营桥接体验、重复项/失败项可见性和日期选择，不重做已落地 API。
2. **Post-close Loop Runner**：只处理收盘后评估/推送调度；必须保持 mock provider 默认测试与真实 provider smoke 分离。
3. **Frontend nested repo**：若需要 UI 改动，先展开并进入 `web/frontend` nested repo，按 nested repo 提交，再提交 top-level gitlink。

**需要用户在进入 P1 前确认的点**（2026-05-26 已全部答复）：

- [x] 边界与数据模型 → **符合预期**
- [x] 优先规则参数 → **同意**；其余规则同期实现并按 `priority` 降权推送
- [x] 钉钉调度 → **先手动按钮，crontab 能力保留默认关闭**
- [x] 评估不级联 update → **同意**

→ 历史结论保留；当前不再据此进入 P1。
