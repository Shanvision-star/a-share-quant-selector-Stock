# 跟踪 Agent 与提醒系统设计文档（P0）

> 分支：`codex/tracking-agent-alerts`（从 `web` 切出）
> 状态：P0 设计稿，等待用户审核后进入 P1 实施
> 适用范围：人工股票池 → 跟踪 → 短/长周期规则评估 → 钉钉+前端提醒 → OrderIntent 人工确认

---

## 0. 边界与不变量（必须先读）

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

## 1. 用户决策记录（2026-05-26）

| 议题 | 决策 |
| --- | --- |
| 手动股票池入口 | **三种全部支持**：txt 导入、从策略结果一键加入、粘贴代码框 |
| 规则优先级 | **跌破短趋势线 / 跌破多空线** 优先实现，其余延后 |
| 规则参数 | **必须可调**，存 `tracking_rule_templates` + 实例可覆盖 |
| 钉钉提醒频率 | **每日 3 次**：开盘前（09:00）、午盘（11:30）、收盘后（15:30） |
| 自动化级别 | 系统性思维、可回溯、可维护，**禁止隐藏状态** |

---

## 2. 系统数据流

```
[人工股票池入口]                  [策略结果]
  txt 导入                          已有缓存
  粘贴代码框           ───→  manual_selections (已有表)
  策略一键加入                          │
                                        ▼
                              [批量加入跟踪] (P1)
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
                          tracking_alert_events (P4 新增)
                          + tracking_events (已有，审计流水)
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  ▼                     ▼                     ▼
            [钉钉推送]            [前端提醒中心]         [LLM 解读]
       3 时段 + 去重 + 限流      待确认 / 已读 / 忽略    JSON 摘要 (P6)
                                        │
                                        ▼
                          [OrderIntent 人工确认]
                       tracking_items.latest_intent_json
                       + 状态机：WATCH → BUY_READY → HOLD → ...
```

---

## 3. 阶段切分（P0→P7）

| 阶段 | 范围 | 关键交付 | 验证 |
| --- | --- | --- | --- |
| **P0** | 本设计文档 | `docs/Tracking/tracking_agent_plan.md` | 用户审核签字 |
| **P1** | 数据模型 + 入口 | 3 种股票池导入、批量加入跟踪 API | pytest: manual_selection + tracking 路由 |
| **P2** | 规则引擎 | `tracking_rule_engine.py`，先实现 2 条优先规则 | pytest: 规则单元测试 |
| **P3** | 规则模板配置 | `tracking_rule_templates` 表 + CRUD + 实例参数覆盖 | pytest + 前端模板表单 |
| **P4** | 提醒中心 | `tracking_alert_events` + 钉钉 3 时段调度 + 去重 | pytest + 钉钉 mock |
| **P5** | 评估调度 | 手动按钮 + 可选自动级联（默认关闭） | pytest 联动 update 路径 |
| **P6** | LLM 解读 | mock LLM 接口契约，JSON schema 落库 | mock LLM pytest |
| **P7** | OrderIntent 闭环 | 前端"已执行/忽略"按钮，状态机收敛 | 端到端手工 smoke |

**当前任务范围**：P0 完成后等用户批准，再启动 P1。

---

## 4. 数据模型（P1-P4 增量）

### 4.1 已有表（不动 schema，只补字段使用约定）

- `manual_selections`：人工股票池。新增导入来源时复用 `source_payload_json` 携带 `import_type ∈ {txt, paste, strategy_pick}`。
- `tracking_items`：单股跟踪主表。`status ∈ {WATCH, BUY_READY, HOLD, NEEDS_REVIEW, CLOSED}`。
- `tracking_events`：跟踪事件流。新增 `event_type='rule_hit'` 与 `event_type='alert_sent'` 用于审计。

### 4.2 新增表（P3-P4）

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
    template_id      TEXT NOT NULL,
    signal_date      TEXT NOT NULL,           -- 触发的交易日
    action_label     TEXT NOT NULL,
    dedup_key        TEXT NOT NULL,           -- tracking_id|template_id|signal_date|action_label
    close_value      REAL,                    -- 触发时收盘价
    payload_json     TEXT,                    -- 详细数据快照（指标值、阈值）
    dingtalk_status  TEXT,                    -- pending|sent|failed|skipped
    dingtalk_slot    TEXT,                    -- pre_open|midday|post_close
    dingtalk_sent_at TEXT,
    ui_status        TEXT NOT NULL DEFAULT 'unread',  -- unread|read|acknowledged|ignored
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_dedup ON tracking_alert_events(dedup_key);
CREATE INDEX IF NOT EXISTS idx_alert_tracking ON tracking_alert_events(tracking_id);
CREATE INDEX IF NOT EXISTS idx_alert_ui_status ON tracking_alert_events(ui_status);
```

**去重 key 设计原因**：同一股票同一天同一规则只发一次；不同规则各发一次（保持可审计颗粒度）。

### 4.3 不新建 `order_intent_queue`

复用 `tracking_items.latest_intent_json` + `next_action` 字段；只在 `tracking_events` 写 `event_type='intent_confirmed'` / `'intent_ignored'` 用于回溯。

---

## 5. 优先规则定义

### 5.1 R001 跌破短趋势线（短周期，最高优先）

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `short_ma_window` | 5 | 短均线周期（日 K） |
| `confirm_close_count` | 1 | 连续收盘跌破 N 根 |
| `tolerance_pct` | 0.5 | 收盘价低于 MA 的容差比例（%） |
| `volume_filter` | false | 是否要求放量确认 |

**触发**：`close < MA(short_ma_window) * (1 - tolerance_pct/100)` 连续 `confirm_close_count` 根。
**action_label**：`TREND_BREAK`（建议减仓或退出观察）。

### 5.2 R002 跌破多空线（中周期，高优先）

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `bull_bear_source` | `zhixing` | 多空线来源，复用 `utils/technical.py` 知行双线 |
| `confirm_close_count` | 2 | 连续收盘跌破 N 根 |
| `tolerance_pct` | 0.3 | 容差比例 |

**触发**：`close < bull_bear_line` 连续 `confirm_close_count` 根。
**action_label**：`STOP_LOSS`（建议清仓重审）。

### 5.3 其余规则（P2 同步实现，权重下调）

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

## 6. 钉钉提醒调度

### 6.1 三时段定义

| 槽位 | 触发时间 | 内容范围 |
| --- | --- | --- |
| `pre_open` | 09:00 | 昨日收盘评估生成的新提醒 + 未处理的 unread |
| `midday` | 11:30 | 上午盘中如有手动评估产生的提醒（用户主动按钮才产生，自动评估不在盘中跑） |
| `post_close` | 15:30 | 当日收盘后规则评估产生的全部新提醒 |

### 6.2 限流与去重

- 单条 `dedup_key` 全生命周期只发一次。
- 单槽位单次推送最多 N 条（默认 N=20），超出按 `priority` 截断并在 markdown 末尾提示"另有 X 条待查看"。
- 钉钉失败时 `dingtalk_status='failed'`，下次同槽位补发，仍失败计入 P4 监控日志，不阻塞流程。

### 6.3 调度入口

按用户 2026-05-26 补充决策：**P4 阶段先做手动按钮，crontab 能力同步保留**，不引入 APScheduler。

| 阶段 | 触发方式 | 实现 |
| --- | --- | --- |
| P4 必交 | 手动 API + 前端按钮 | `POST /api/tracking/alerts/dispatch?slot=pre_open|midday|post_close`，幂等（基于 `dingtalk_status` 状态） |
| P4 同期产出 | crontab 模板（默认注释） | 在 `config/crontab.txt` 追加 3 行注释样例，文档说明如何取消注释启用 |
| 启用开关 | `config/strategy_params.yaml` | `tracking.alert_slots.auto_dispatch_enabled: false`，crontab 调用同一 API；前端展示当前是否已开启自动调度 |

**幂等保证**：同一 `slot` 在同一交易日多次触发，仅推送 `dingtalk_status` 为 `pending` 或 `failed` 的记录；已 `sent` 的不重复发。

---

## 7. API 设计（P1-P4 新增/扩展）

| Method | Path | 阶段 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/manual-selection/import-txt` | P1 | 上传 txt，逐行解析 6 位代码 |
| POST | `/api/manual-selection/import-paste` | P1 | 粘贴文本，正则提取代码 |
| POST | `/api/manual-selection/import-from-strategy` | P1 | 从策略结果按 trade_date 一键导入 |
| POST | `/api/tracking/batch-from-selection` | P1 | 把某日 manual_selections 整批转 tracking |
| POST | `/api/tracking/evaluate-batch` | P2 | 触发当前 active tracking 全量规则评估 |
| GET / POST / PUT / DELETE | `/api/tracking/rule-templates` | P3 | 模板 CRUD |
| GET | `/api/tracking/alerts` | P4 | 查询提醒列表，支持 ui_status 筛选 |
| POST | `/api/tracking/alerts/{alert_id}/ack` | P4 | 标记已读 / 已确认 / 忽略 |
| POST | `/api/tracking/alerts/dispatch` | P4 | 触发钉钉推送（按 slot） |

**返回结构统一**：`{success: bool, data: ..., error: str|null}`，与现有 API 一致。

---

## 8. 前端页面切分

| 视图 | 文件 | 阶段 | 说明 |
| --- | --- | --- | --- |
| 每日股票池 | `web/frontend/src/views/ManualSelectionPoolView.vue`（增强） | P1 | 三种导入入口 Tab |
| 批量加入跟踪 | 上述视图内按钮 | P1 | 选中行 → 批量加入 |
| 跟踪看板 | `web/frontend/src/views/TrackingView.vue`（新增或增强） | P2 | 按 status 分组展示 |
| 规则模板管理 | `web/frontend/src/views/TrackingRuleTemplatesView.vue`（新增） | P3 | 表单 + 启用开关 |
| 提醒中心 | `web/frontend/src/views/TrackingAlertCenterView.vue`（新增） | P4 | 提醒列表 + 已读/忽略 |

**所有按钮文案约束**（与 agent.md 一致）：
- ✅ "加入跟踪"、"评估跟踪"、"待确认"、"已处理"、"忽略"、"生成意图"
- ❌ "自动买入"、"自动卖出"、"AI 荐股"、"保证收益"

---

## 9. LLM 集成契约（P6）

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

## 10. 系统性思维落地（可回溯 / 可维护）

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

## 11. 风险登记

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| 钉钉接口限流 | 中 | 单槽 N 条上限 + 失败补发 + 监控日志 |
| 规则参数误配置 | 中 | 模板 `params_schema` 校验 + 模板更新生成新版本，旧 alert 保留快照 |
| 用户批量导入坏代码 | 低 | 6 位代码正则 + 与 `stock_names.json` 交叉校验 |
| 评估期间 CSV 仍在更新 | 中 | 复用 `update_status` gate：partial 状态拒绝评估 |
| LLM 输出与规则冲突 | 中 | 规则引擎为权威，LLM 仅作解释；冲突落事件审计 |
| 长期未处理 alert 堆积 | 低 | 提醒中心默认筛选 7 日内 unread；提供"全部忽略 X 日前"按钮 |

---

## 12. 下一步（等待用户批准）

P0 设计文档已完成。批准后进入 **P1**：

1. 扩展 `manual_selection_service.py`：三种导入入口 + 校验
2. 扩展 `tracking_service.py`：`batch_from_selection()`
3. 新增 pytest：`tests/test_manual_selection_import.py`、`tests/test_tracking_batch.py`
4. 前端 `ManualSelectionPoolView.vue` 增加三 Tab + 批量加入按钮
5. 验证命令：
   ```bash
   python -m pytest tests/test_manual_selection_import.py tests/test_tracking_batch.py -q
   python -c "import web.backend.main"
   cd web/frontend && npm run test -- --run
   ```

**需要用户在进入 P1 前确认的点**（2026-05-26 已全部答复）：

- [x] 第 1 节边界、第 4 节数据模型 → **符合预期**
- [x] 第 5 节优先规则参数 → **同意**；其余规则同期实现并按 `priority` 降权推送（见 5.3）
- [x] 第 6 节钉钉调度 → **先手动按钮，crontab 能力保留默认关闭**（见 6.3）
- [x] 第 10 节评估不级联 update → **同意**

→ 进入 P1。
