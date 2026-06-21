# 回测 Phase A：A 股撮合正确性设计

## 背景与目标

当前回测模块已经不是空白工程。仓库中已存在 `web/backend/backtest_engine/`，并拆出了 `DataPortal / SignalSource / Execution / Portfolio / Analyzer / Engine / Models`。当前回测能力更接近“信号验证器”：它能读取候选信号、按日线或分钟线模拟买卖、生成交易明细和 `OrderIntent`，但组合资金账本、回测持久化和前端历史详情还不是本阶段目标。

本阶段目标是 Phase A：先把 A 股撮合正确性做成可测试闭环。它服务后续 Phase C 的回测 run 复现与前端详情，也服务最后 Phase B 的 Portfolio 现金/持仓账本，但本阶段不提前实现 C/B。

## 需求与目标拆分

### 需求

- 每个回测任务必须按真实 A 股交易日推进，避免自然日、简单工作日或缺失 CSV 行导致买卖日期误判。
- 执行层必须明确处理 A 股基础规则：T+1、100 股整数手、停牌不可交易、涨停锁死不可买、跌停锁死不可卖、ST/退市风险默认不可买。
- 信号阶段和执行阶段必须继续分离：`SignalCandidate` 只描述候选，`OrderIntent` 只描述下单意图，回测引擎不连接 QMT 或任何真实券商接口。
- 所有新增行为必须由 focused pytest 固化，优先验证最小规则，再扩大到回测引擎整体。

### 非目标

- 不实现完整 Portfolio 现金、持仓、冻结资金和逐日权益账本。
- 不新增回测持久化表、历史列表或回测详情页。
- 不改策略选股逻辑，不修改 B1/B2/碗形策略规则。
- 不接入 QMT、miniQMT、自动下单或真实资金交易。
- 不把 LLM 放进实时交易或撮合循环。

## 当前代码事实

- `web/backend/backtest_engine/data_portal.py` 已有 `DailyDataPortal`、`MinuteDataPortal`、`CsvDailyDataPortal`、`InMemoryDailyDataPortal` 和分钟线入口。
- `web/backend/backtest_engine/execution.py` 已有日线和分钟线执行器，并已有 `_round_lot_quantity`、`_is_tradeable_row`、`_is_st_stock`、涨跌停判断和 `_find_sellable_index` 等辅助函数。
- `tests/test_backtest_engine.py` 已覆盖同日信号后续行情窗口、分钟级 T+1、ST/涨停禁买、100 股整数手、无 T+1 卖出日跳过等行为。
- `utils/trading_calendar.py` 已有 A 股节假日辅助函数，但目前只提供 `is_a_share_trading_day`、`previous_a_share_trading_day` 和 `count_a_share_trading_days`。
- `portfolio.py` 当前仍是按卖出日聚合的简化资金曲线，不是完整组合账本。

## 设计边界

### 1. DataPortal 交易日边界

Phase A 只在 DataPortal 和交易日工具层补齐“按真实交易日推进”的最小接口。

推荐接口：

- 在 `utils/trading_calendar.py` 增加 `next_a_share_trading_day(day)` 和 `advance_a_share_trading_days(day, days)`。
- 在 `DailyDataPortal` 兼容增加只读交易日解析能力，或在 `data_portal.py` 提供独立 helper，把日线 DataFrame 中的日期规范化为交易日序列。
- 执行器使用规范化后的交易日序列定位 `signal_date`、`buy_date` 和 `sell_date`，不要用自然日差值。

约束：

- CSV 中实际存在的交易行仍是最终行情依据；交易日历用于日期推进和缺口识别，不凭空制造行情。
- 如果某个理论交易日没有行情行，不能假装成交；买入或卖出只能发生在可交易行情行上。

### 2. 买入侧撮合规则

买入只允许发生在符合以下条件的日线行：

- 日期在 `signal_date` 之后按 `buy_offset_days` 推进到的可交易窗口内。
- `open/high/low/close` 为正，`volume > 0`。
- 非 ST/退市风险股票，除非参数显式允许 `allow_st_buy=True`。
- 当日不是涨停锁死状态。主板默认 10%，创业板/科创板默认 20%，ST 默认 5%。
- 下单意图数量必须按 `lot_size` 向下取整，默认 100 股。

### 3. 卖出侧撮合规则

卖出不得只在最终强平时检查可卖性，所有退出路径都必须尊重卖出侧可交易规则。

卖出只允许发生在符合以下条件的日线行：

- 必须在买入日之后，保持 T+1。
- `open/high/low/close` 为正，`volume > 0`。
- 当日不是跌停锁死状态。
- 固定止损、无收益退出、趋势破位、Profit Runner 阶梯卖出、持仓期满，都应共用同一套“寻找可卖日期”的逻辑。

如果触发退出的当天不可卖，应向后寻找下一个可卖交易行；如果模拟窗口结束仍不可卖，则该候选跳过，不生成虚假交易。

### 4. No-Future-Function 边界

信号筛选仍只能读取 `signal_date` 及以前的数据；执行模拟可以读取信号日之后的行情，因为买卖发生在未来交易日。

本阶段只强化执行层的日期边界，不改变策略扫描服务。若测试发现策略服务已经满足目标日期裁剪，只补验证；若发现缺口，先记录为独立问题，不混入 Phase A。

### 5. 输出与 API 兼容

Phase A 不要求变更 `/api/backtest` 响应结构。

允许的输出变化：

- 因真实交易限制更严格，`trade_count` 可能下降，`skipped_count` 可能上升。
- `buy_date`、`sell_date` 可能从原本不可交易日顺延到下一可交易日。
- `order_intents.quantity` 继续保持按 100 股整数手向下取整。

不允许的输出变化：

- 不删除已有 `summary / trades / equity_curve / order_intents / runtime` 字段。
- 不让 `OrderIntent` 带真实券商订单号。
- 不把 skipped candidate 伪装成收益为 0 的交易。

## Loop 提示词

下面这段作为 Phase A 每个 subagent 或执行任务的统一提示词。

```text
你是 A 股量化选股与回测系统的开发 Agent。

当前目标：
只执行 Phase A：A 股撮合正确性。
范围包括 DataPortal / Execution 的交易日推进、停牌、涨跌停、ST 禁买、T+1、100 股手数等规则。
不要实现 Portfolio 资金账本、前端历史详情、QMT 实盘、LLM 投资建议或未来层功能。

主线约束：
- 目标主分支是 web。
- 不直接在 web 上开发，必须使用 codex/* 隔离分支或 worktree。
- 不回滚用户已有 dirty files。
- 所有改动先读 agent.md 和现有代码，再判断真实缺口。
- Python 新文件需要中文模块 docstring。
- 新逻辑必须有 focused pytest。
- 修改 app 启动、service、router、类型签名时必须跑 import smoke。

循环协议：
1. Observe：确认当前任务属于 DataPortal、Execution、Portfolio、Analyzer、Frontend 还是 Docs；列出现有实现和真实缺口。
2. Plan：只为当前小任务写计划，声明允许修改的文件、禁止越界的文件、验证命令和验收条件。
3. Review：行动前检查是否误动 web、是否触碰用户未提交改动、是否混入 Phase C/B 或 QMT。
4. Act：按 TDD 或最便宜验证优先执行，每次只完成一个明确规则。
5. Verify：运行 focused pytest；涉及签名、service、router 或启动路径时加 import smoke。
6. Reflect：说明改了什么、验证了什么、没验证什么、是否需要 docs/memory 同步。

退出条件：
- 当前小任务验收通过。
- focused tests 通过。
- diff 只包含预期文件。
- 无 Critical / Important review 问题。
```

## Subagent 任务拆分

### A1：交易日工具与 DataPortal 边界

目标：补齐 A 股交易日推进 helper，并让回测执行层有稳定的交易日序列入口。

主要文件：

- `utils/trading_calendar.py`
- `tests/test_trading_calendar.py`
- `web/backend/backtest_engine/data_portal.py`
- `tests/test_backtest_engine.py`

验收：

- 五一、端午、周末等非交易日能正确跳过。
- `buy_offset_days` 按交易日推进，不按自然日推进。
- 缺失行情行不会被自动视为可成交。

### A2：买入侧 A 股规则补齐

目标：把 ST/退市风险、涨停锁死、停牌、100 股整数手和不同板块涨跌幅口径固化为执行层测试。

主要文件：

- `web/backend/backtest_engine/execution.py`
- `tests/test_backtest_engine.py`

验收：

- ST 默认不可买，显式允许后仍受 5% 涨跌停规则约束。
- 主板 10%、创业板/科创板 20% 涨停锁死不可买。
- `volume=0` 或价格缺失的停牌行不可买。
- `intent_quantity` 按 `lot_size=100` 向下取整。

### A3：卖出侧 A 股规则补齐

目标：所有退出路径都统一通过可卖性检查，不能只在持仓期满时处理跌停或停牌。

主要文件：

- `web/backend/backtest_engine/execution.py`
- `tests/test_backtest_engine.py`

验收：

- 买入当天不能卖出。
- 跌停锁死或停牌时不能卖出。
- 固定止损、趋势破位、无收益退出、Profit Runner 和持仓期满都能顺延到下一可卖交易日。
- 模拟窗口内没有可卖交易日时，候选跳过。

### A4：回归验证与文档同步

目标：确保 Phase A 没有破坏现有回测服务和 API 外壳。

主要文件：

- `tests/test_backtest_engine.py`
- `tests/test_backtest_service.py`
- `tests/test_backtest_job_service.py`
- `tests/test_backtest_router_async.py`
- `docs/BACKTEST_OVERVIEW.md` 或 `docs/Backtesting/backtest_module_plan.md`，仅当行为说明需要同步时修改。

验收：

- focused 回测测试通过。
- import smoke 通过：`python -c "from web.backend.main import app; print('import-ok')"`。
- 如只改核心引擎，前端不需要 build；如 API schema 或前端显示文本变更，再补前端测试或 build。

## 开源 agent-loop 经验如何结合本项目

- OpenHands 的价值在于任务面板和工程治理，本项目吸收为“隔离分支、任务边界、验证证据”，不照搬平台。
- Aider 的价值在于 git-native 和小步提交，本项目吸收为“每个 subagent 只交付一个可验证 diff”。
- SWE-agent / mini-swe-agent 的价值在于简单工具循环和测试反馈，本项目吸收为“Observe / Plan / Act / Verify / Reflect”。
- BMAD-METHOD 的价值在于 PRD、架构和 story 边界，本项目吸收为“先 spec，再 plan，再 subagent 执行”。
- strongdm coding-agent-loop-spec 的价值在于通用 coding loop，本项目吸收为上面的 Phase A loop 提示词。

## 验证策略

默认从最便宜验证开始：

1. `python -m pytest tests/test_trading_calendar.py -q`
2. `python -m pytest tests/test_backtest_engine.py -q`
3. `python -m pytest tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q`
4. `python -c "from web.backend.main import app; print('import-ok')"`
5. `git diff --check`

如果 Phase A 不改前端，不跑前端 build。若后续 Phase C 改回测历史详情页，再按前端变更规则补 `npm run test`、`npm run build` 和浏览器 smoke。

## 风险与处理

- 风险：更严格的撮合规则会让历史回测交易数减少。处理：在最终说明中明确这是规则修正，不是策略失效。
- 风险：CSV 缺失真实交易日行情时，按交易行推进可能隐藏数据缺口。处理：DataPortal 只把真实存在且可交易的行交给执行器，缺口识别作为 warning 或后续数据质量任务，不在 Phase A 伪造成交。
- 风险：早退逻辑路径多，容易只修持仓期满。处理：卖出侧统一 helper，每个退出原因都加测试。
- 风险：Phase C/B 诱惑强，容易提前改 API 或资金曲线。处理：Phase A 只允许可选文档同步，不新增持久化表和前端详情页。

## 用户审核点

请重点审核三点：

1. Phase A 是否只做 A 股撮合正确性，不提前进入 C/B。
2. 买入和卖出侧规则是否符合你的交易策略假设。
3. 这个 loop 提示词是否可以作为后续 subagent 的统一执行提示词。
