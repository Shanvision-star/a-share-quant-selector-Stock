# 系统状态中心与架构完善设计

## 背景与目标

当前项目已经从单一 A 股选股脚本扩展为 Web 量化工作台，包含数据更新、策略缓存、K 线浏览、回测、Tracking-Agent、LLM 建议、OrderIntent、Zettaranc 专项策略和 QMT 预留设计。功能推进速度较快，但用户在 `http://localhost:5173/` 看不到数据时，仍需要人工分别检查前端代理、后端服务、数据新鲜度、策略缓存、更新任务和运行状态。

本设计分两层：

1. 先建立全局架构蓝图，明确每个任务属于主线、实验区还是未来层。
2. 再把 P0 子项目收敛为“系统状态中心”，优先解决本地 Web 工作台没数据、数据状态不清、策略缓存和数据更新状态混淆的问题。

目标不是新增交易策略，也不是提前接入自动实盘，而是把现有能力变成可诊断、可解释、可验证的系统。

## 基于 `agent.md` 的开发底线

- 当前主线以 `web` 为准，但代码和 Markdown 改动都必须通过 `codex/*` 或明确 feature 分支承接。
- 修改前先确认 `git status --short --branch`，不能把无关未提交内容混入本次提交。
- 优先保护数据完整性和策略日期一致性。
- 数据 freshness 和策略 cache freshness 必须分开判断；数据最新不等于前端有最新策略结果。
- 策略只产生信号，不直接下单；`OrderIntent` 是自动化边界，不等于真实券商委托。
- QMT / miniQMT 只做接口预留，当前 20 万资金阶段不作为主线。
- 实时交易循环不能调用大模型；LLM 只用于建议、复盘、文档和参数解释。
- Python 后端新增文件必须有中文模块 docstring；复杂业务判断用中文注释解释意图和边界。
- 默认测试保持确定性；真实 provider smoke 与普通单元测试分开。

## 全局架构蓝图

### 1. 项目治理与发布框架

定位：主线治理能力，优先级 P0。

设计：

- 建立一份架构状态文档，记录“已落地、实验中、未来层、禁止提前实现”的模块清单。
- 当前 `web` 分支已有大量提交领先远端，并存在未提交文件；后续开发必须拆成可审查的分支或提交。
- 文档不能把计划写成已完成事实；每个阶段都要标明验证证据或未验证限制。

开发约束：

- 不直接在 `web` 上长期推进代码或文档。
- 每个任务只提交本任务相关文件。
- 完成后报告验证命令、未验证范围和剩余风险。

### 2. 系统状态中心

定位：P0 子项目，本设计的首个落地对象。

设计：

- 新增后端只读聚合服务，统一读取后端健康、数据状态、策略缓存、更新任务、Tracking 摘要和集成配置健康。
- 前端新增状态页或在设置页增加状态面板，让“没数据”变成可解释结果。
- 每个模块返回统一状态：`ready`、`stale`、`missing`、`running`、`partial`、`error`、`disabled`。

开发约束：

- 只读聚合，不改 `/api/update`、`strategy_service`、Tracking 或策略逻辑。
- `partial` 不能伪装成成功。
- 不暴露 DingTalk secret、LLM key、券商账户或本地敏感路径。

### 3. 核心对象契约

定位：架构基础能力，优先级 P0/P1。

设计：

- 固化跨模块对象：`SignalCandidate`、`StrategyResult`、`TrackingItem`、`AlertEvent`、`OrderIntent`、`Position`、`TradeJournal`、`BacktestRun`。
- 每个对象定义最小字段、来源、消费者和持久化位置。
- 后续回测、Tracking、模拟盘和 Zettaranc 都通过这些对象对接，避免各模块各自发明字段。

开发约束：

- 不能让策略直接产生真实订单。
- 新对象必须能被测试 fixture 和 API response 复用。
- 涉及签名、类型、repository、service 或 app startup 的变更必须跑 import smoke。

### 4. 数据库迁移框架

定位：稳定性基础能力，优先级 P1。

设计：

- 当前 SQLite 表已经覆盖策略 run、回测任务、Tracking、告警等能力；后续需要 schema migration runner。
- migration 应包含版本号、前置版本、执行 SQL、回滚或备份说明。
- 系统状态中心应能提示数据库版本和迁移状态。

开发约束：

- 不在业务 service 中悄悄改变表结构。
- schema 变化必须有测试和导入烟囱验证。
- 不因为迁移失败破坏已有可读数据。

### 5. 回测到模拟交易闭环

定位：核心产品主线，优先级 P1。

设计：

- 目标链路为：策略信号 -> 回测 -> OrderIntent -> paper/manual -> 成交流水 -> 复盘。
- 回测引擎继续保持 `DataPortal / SignalSource / Execution / Portfolio / Analyzer` 分层。
- 后续补 `Position`、`TradeJournal`、`SimBrokerAdapter`、`ManualBrokerAdapter`。

开发约束：

- 回测优先于模拟盘，模拟/人工确认优先于券商接口。
- A 股撮合、T+1、整手、涨跌停、停牌、ST 禁买必须由确定性代码处理。
- LLM 不进入实时交易链路。

### 6. Tracking-Agent 运营化

定位：交易跟踪工作流，优先级 P1。

设计：

- Tracking-Agent 已有单股跟踪、规则告警、LLM 建议和 OrderIntent 确认/否决。
- 下一步补告警生命周期、每日同步、DingTalk 分发、人工确认审计和操作队列。
- 告警应区分 `pending`、`dispatched`、`acknowledged`、`resolved`、`ignored`。

开发约束：

- 新增 `/api/tracking/*` 固定路由必须放在 `tracking.router` 通配路由之前。
- LLM 建议必须保持结构化输出，不能直接修改持仓或下单。
- 人工确认和否决都必须写事件，保证可审计。

### 7. Zettaranc 边界

定位：专项策略实验区，优先级 P1/P2。

设计：

- Zettaranc 保持为专项策略、专项页面和专项测试，先完成样本外验证、参数稳定性和线上扫描接入。
- 只有当它能稳定通过通用策略契约，才提升为通用策略体系的一部分。

开发约束：

- 新策略必须继承 `BaseStrategy` 并兼容自动注册。
- 不能破坏全市场扫描性能路径：单股一次读盘、共享指标复用、必要条件快筛。
- 参数扫描和优化结果不能直接写成实盘有效结论，必须标注样本和验证范围。

### 8. 前端信息架构

定位：Web 工作台体验升级，优先级 P2。

设计：

- 页面按工作流组织，而不是按功能堆叠。
- 建议导航分组：每日操作、研究验证、交易跟踪、系统管理。
- 状态中心是系统管理分组的第一块，也可在首页没数据时作为故障入口。

开发约束：

- 使用现有 Vue 3、TypeScript、Element Plus、API client 和类型模式。
- 权限、加载、错误、空数据状态必须对用户可见。
- 不重复造组件；优先复用现有 store、API 封装和布局模式。

### 9. 可观测性与错误分类

定位：长期稳定性能力，优先级 P2。

设计：

- 统一 run event、错误类别、数据源健康、外部 provider 延迟和成本记录。
- 所有用户可见错误应给出 next action，而不是只显示异常字符串。

开发约束：

- 默认测试不调用真实外部服务。
- 真实 LLM 或数据源 smoke 需要单独记录 provider、model、tokens、latency、cost 或数据源名称。

## P0 子项目：系统状态中心

### 范围

包含：

- 后端新增只读状态聚合服务。
- 后端新增统一状态 API。
- 前端新增状态展示入口。
- 首页或策略结果页在空数据时能链接到状态中心。
- 最小后端单测和前端类型验证。

不包含：

- 修改数据更新、策略重建或 Tracking 的业务行为。
- 新增自动修复按钮。
- 新增真实交易、QMT 或自动下单能力。
- 重构现有前端导航体系。
- 接入真实 LLM smoke。

### 推荐方案

采用“只读聚合服务 + 统一 API + 前端状态面板”。

后端从现有服务读取状态，聚合成一个结构化 payload。前端只消费这一个 payload，用统一视觉状态解释当前系统能否展示数据、为什么不能展示、下一步应做什么。

这个方案改动小、风险低，也符合 `agent.md` 的最小边界原则。

## 后端设计

### 新增服务

建议新增：

```text
web/backend/services/system_status_service.py
```

职责：

- 聚合状态，不执行业务写入。
- 调用现有只读函数，例如数据状态、策略缓存状态、run repository 查询。
- 将各模块状态标准化成统一结构。
- 对敏感配置只返回 `configured: true/false`，不返回原始值。

### 新增路由

建议新增：

```text
web/backend/routers/system_status.py
```

接口：

```text
GET /api/system/status
```

返回顶层结构：

```json
{
  "success": true,
  "data": {
    "checked_at": "2026-06-21T10:00:00+08:00",
    "overall_status": "ready",
    "backend": {},
    "data": {},
    "strategy_cache": {},
    "update_pipeline": {},
    "tracking": {},
    "integrations": {},
    "frontend_hints": []
  }
}
```

### 标准状态块

每个模块返回：

```json
{
  "status": "ready",
  "message": "数据已更新到最近交易日",
  "checked_at": "2026-06-21T10:00:00+08:00",
  "next_action": "无需处理",
  "details": {}
}
```

状态含义：

| 状态 | 含义 |
| --- | --- |
| `ready` | 可用且与当前目标日期一致 |
| `stale` | 有数据但不是最新或与目标日期不一致 |
| `missing` | 必要数据或缓存不存在 |
| `running` | 有相关任务正在运行 |
| `partial` | 更新或重建部分完成，不应当作可靠结果 |
| `error` | 最近任务失败或状态读取失败 |
| `disabled` | 功能被配置关闭或当前阶段不启用 |

### 聚合字段

`backend`：

- FastAPI 进程状态。
- API version。
- 启动时间，如果当前代码已有可获取来源则返回；否则第一版可省略。
- 当前工作目录摘要，不返回敏感绝对路径到前端时应做必要裁剪。

`data`：

- 本地股票 CSV 总数。
- 最新可用交易日。
- 是否新鲜。
- 数据目录是否存在。
- 状态来源为现有 `/api/data/status` 等只读能力。

`strategy_cache`：

- `strategy=all` 的缓存状态。
- latest trade date。
- latest run status。
- matched count。
- 是否与数据最新交易日一致。

`update_pipeline`：

- 最近一次 update run。
- run 状态、trade_date、matched_count、failed_count、completed_at。
- 如果存在 `running` 或历史遗留 running，明确提示。

`tracking`：

- 活跃跟踪项数量。
- pending alert 数量。
- 最近评估日期。
- Tracking 服务不可用时返回 `disabled` 或 `error`，不能影响核心数据状态。

`integrations`：

- DingTalk 是否配置。
- LLM provider 是否配置。
- QMT 是否启用；当前应为 `disabled` 或 reserved。
- 所有敏感字段只返回布尔和模式，不返回 secret、token、account_id。

`frontend_hints`：

- 给前端直接展示的诊断提示数组。
- 示例：
  - “后端可用，但策略缓存缺失，请进入策略结果页重建缓存。”
  - “数据更新最近状态为 partial，不建议使用当前结果。”
  - “数据最新交易日与策略缓存交易日不一致，请运行 update+rebuild。”

## 前端设计

### 页面入口

第一版优先选择最小改动：

- 在 `/settings` 增加“系统状态”面板，或新增 `/status` 路由。
- 首页、策略结果页空数据时，显示进入状态中心的链接。

如果新增 `/status`，导航中归入“系统管理”。

### 展示结构

页面分为：

- 总体状态条：显示 `overall_status`、检查时间和最高优先级 next action。
- 数据与策略：并排展示 data 与 strategy_cache。
- 运行任务：展示 update_pipeline。
- 跟踪与集成：展示 tracking 与 integrations。
- 诊断建议：展示 frontend_hints。

### 交互规则

- 页面加载时请求 `GET /api/system/status`。
- 提供手动刷新按钮。
- 请求失败时显示“后端不可达或代理异常”，并提示检查 `localhost:8001`。
- 不在第一版提供自动修复按钮，避免误触发数据更新或策略重建。

## 错误处理

- 聚合服务读取某个子模块失败时，只把该模块标记为 `error`，不让整个接口 500。
- 如果后端自身不可达，前端显示网络错误，而不是空页面。
- 如果数据状态 ready 但策略缓存 missing，overall 至少为 `stale` 或 `missing`，不能显示 ready。
- 如果 update 最近状态为 `partial`，overall 不能显示 ready。
- 如果 Tracking 或 LLM disabled，不影响数据和策略主链路的 ready 判断。

## 测试与验证

后端测试：

- `system_status_service` 在数据 ready、策略 ready 时返回 `overall_status=ready`。
- 数据 ready 但策略缓存 missing 时返回非 ready，并给出 next action。
- update 最近状态为 `partial` 时返回非 ready。
- 子模块抛异常时接口仍返回 200，相关模块为 `error`。
- integrations 不泄露 secret、token、account_id。

API smoke：

```bash
python -c "from web.backend.main import app; print('import-ok')"
```

```bash
pytest tests/test_system_status_service.py tests/test_system_status_router.py
```

前端验证：

```bash
cd web/frontend
npm run typecheck
```

如触及页面组件，再补：

```bash
cd web/frontend
npm run build
```

手动验证：

- 打开 `http://localhost:5173/`。
- 进入状态中心。
- 后端可用时能看到 data、strategy_cache、update_pipeline。
- 关闭后端或改错代理时，前端显示明确错误。

## 实施顺序建议

1. 新增后端服务和路由，只读聚合现有状态。
2. 补后端单测和 import smoke。
3. 新增前端 API 类型和状态页面。
4. 在首页或策略结果页空数据状态加入状态中心入口。
5. 跑前端 typecheck/build。
6. 更新 README 或项目状态文档，说明状态中心的排障入口。

## 不做事项

- 不自动触发 update 或 rebuild。
- 不改策略命中逻辑。
- 不修改 Tracking-Agent 的规则引擎。
- 不接 QMT 或真实券商。
- 不让 LLM 参与实时交易判断。
- 不把 Zettaranc 实验结论写成主线策略结论。

## 用户审核点

在进入 implementation plan 前，需要确认：

1. 状态中心第一版放在 `/settings` 面板，还是新增 `/status` 独立页面。
2. `overall_status` 是否要把 Tracking/LLM/DingTalk 纳入主链路判断；本设计默认不纳入。
3. 第一版是否允许提供“跳转到更新页/策略重建页”的导航；本设计默认允许跳转，但不自动执行。
