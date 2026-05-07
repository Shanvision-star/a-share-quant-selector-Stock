# Agent 工作说明

本文档给后续开发者和 Agent 使用。目标是用最少 token 快速理解项目、做对修改、讲清技术逻辑，并保持代码注释为中文。

## 项目定位

本项目是 A 股量化选股系统，核心链路是：

1. 更新本地日线数据。
2. 基于本地 CSV 运行 B1、B2、碗形等策略。
3. 将策略结果写入 JSON/TXT 缓存并推送通知。
4. 前端展示策略列表、K 线、回测结果，并支持 txt 导出。
5. 后续扩展回测模块与银河 QMT / miniQMT 实盘执行，但策略、回测和券商下单必须分层。

做任何修改时，优先保护两件事：数据完整性和策略日期一致性。

## 主要模块

| 模块 | 作用 | 关键点 |
| --- | --- | --- |
| `main.py` | CLI 入口 | run/backtest/web/schedule 统一从这里调度 |
| `quant_system.py` | 量化主编排 | 数据更新、并发策略扫描、B1/B2匹配、通知和导出 |
| `utils/akshare_fetcher.py` | 行情数据更新 | 快路径、慢路径、快照通道、节假日 gap 判断 |
| `utils/csv_manager.py` | 本地 CSV 读写 | 去重、倒序、单日 prepend、幂等写入、近期窗口读取 |
| `utils/technical.py` | 共享指标 | KDJ、知行双线、共享指标缓存标记 |
| `utils/trading_calendar.py` | A 股交易日判断 | 周末和节假日都要排除 |
| `strategy/base_strategy.py` | 策略抽象 | 新策略必须继承 BaseStrategy 并兼容自动注册 |
| `strategy/bowl_rebound.py` | 碗形反弹 | 复用共享 KDJ/知行基础指标 |
| `strategy/b1_case_analyzer.py` | B1阶段与案例分析 | 复用共享指标，按目标日期视角输出信号 |
| `strategy/b2_strategy.py` | B2三分类策略 | 并发扫描、必要条件快筛、三类模板复用 prepared DataFrame |
| `web/backend/services/strategy_service.py` | 策略扫描与缓存 | 按目标日期裁剪数据，避免未来函数 |
| `web/backend/services/data_service.py` | 更新作业编排 | SSE 进度、更新后自动策略重建 |
| `web/backend/routers/update.py` | 更新 API | 前端参数传入和流式事件输出 |
| `web/frontend/src/views/UpdateView.vue` | 更新页面 | 用户选择日期、策略范围、盘中快路径 |
| `web/frontend/src/views/StrategyResultsView.vue` | 策略结果页 | 分类展示、txt 导出、结果去重 |
| `web/frontend/src/views/StockDetail.vue` | K 线详情页 | K 线缓存、预热、请求竞态保护 |
| `docs/QMT/qmt_backtest_live_execution_plan.md` | QMT 落地计划 | 银河 QMT / miniQMT、回测、分时买点和实盘风控路线 |

## QMT 回测与实盘执行约定

银河证券账户已开通 QMT；若实际可用客户端为 miniQMT，只要能使用 `xtquant`，项目仍统一走 QMT 适配层。后续接入时必须按“信号、回测、风控、券商适配”分层，不允许策略代码直接调用 QMT 下单。

核心术语：

- **Signal**：策略信号，只描述 `code`、`signal_date`、`strategy`、`score`、`reason`，不代表一定买入。
- **MinuteBar**：分时行情，包含分钟级 OHLCV，用于盘中买点确认。
- **OrderIntent**：下单意图，表示通过分时规则和风控后的候选订单，还不是券商委托。
- **BrokerAdapter**：券商适配器接口。`SimBrokerAdapter` 用于模拟盘，`QmtBrokerAdapter` 用于银河 QMT / miniQMT。
- **execution_mode**：执行模式，必须支持 `readonly`、`paper`、`confirm`、`auto`。默认只能是 `readonly` 或 `paper`。

强制规则：

- 实时交易循环不能调用大模型。大模型只做总结、复盘、文档和参数解释。
- QMT 账户号、客户端路径、资金限制等写本地配置，不提交真实账户信息。
- 实盘前先完成 QMT 只读模式，确认账户、持仓、行情、委托查询都正常。
- 自动交易必须有硬风控：单票最大金额、单日最大买入金额、最大持仓数、涨跌停/停牌/ST 禁买、一键停止。
- 回测、模拟盘、实盘应共用同一套买卖规则，避免回测逻辑和实盘逻辑分叉。

推荐开发顺序：

1. 拆出 `backtest_engine`：`DataPortal`、`SignalSource`、`ExecutionEngine`、`Portfolio`、`Analyzer`。
2. 增加分时 `MinuteDataPortal` 和 `intraday_entry` 买点确认。
3. 先写 `SimBrokerAdapter`，再写 `QmtBrokerAdapter`。
4. QMT 先只读，再人工确认下单，最后才允许小资金自动模式。

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" -> "Write tests for invalid inputs, then make them pass"
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
- "Refactor X" -> "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
## 数据更新逻辑

### 快路径

快路径用于“本地数据只缺 1 个真实交易日”的情况。它通过全市场快照一次性拿到当天 OHLCV、成交额、换手率、市值，然后并发写入各股票 CSV 文件头部。

专业术语：

- **OHLCV**：open、high、low、close、volume，即开高低收和成交量。
- **快照行情**：某一时刻全市场最新报价，适合补当天日线。
- **幂等写入**：重复执行不会写入重复日期。
- **并发写入**：多线程处理多个 CSV，减少串行小文件 IO 等待。

为什么这样用：

- 全市场快照是“一次请求覆盖多只股票”，比逐股请求快很多。
- 只缺 1 个真实交易日时，用快照补最新一行不会丢历史数据。
- 并发写 CSV 可以降低 Windows 小文件写入的总等待时间。

约束：

- 15:00 后自动快路径，因为日线已基本完整。
- 15:00 前只有用户手动勾选“盘中也允许极速快路径”才写当天快照，避免未收盘数据污染日线。
- 如果缺口大于 1 个真实交易日，不能只写当天，必须走慢路径补齐历史。

### 慢路径

慢路径用于多日缺口、快照缺失、停牌、无本地历史等情况。它会按股票抓取近期 K 线，再合并到 CSV。

专业术语：

- **回填**：补齐历史缺口。
- **fallback**：主通道失败后自动切换备用通道。
- **熔断**：某接口连续失败后短时间停止调用，避免无限拖慢。

为什么保留慢路径：

- 快路径只能补当天一行。
- 策略指标依赖连续历史 K 线，多日缺口会影响均线、KDJ、成交量比较。
- 保留慢路径可以保证数据内容和历史逻辑一致。

### 交易日 gap

不能只用周一到周五判断交易日。A 股有节假日，例如 2026 年五一期间 `2026-04-30 -> 2026-05-06` 只缺 1 个真实交易日，而不是 4 个工作日。

实现要求：

- 统一使用 `utils/trading_calendar.py`。
- 计算缺口时使用真实 A 股交易日。
- 策略默认日期也要使用同一套交易日判断。

## 策略逻辑

策略扫描必须遵守“目标日期视角”。

关键规则：

- 回测某一天，只能使用这一天及以前的数据。
- 前端选择 `2026-04-30`，后端扫描和导出都要基于同一个目标日期。
- 策略命中结果要记录 `strategy_filter`、`strategy_name`、`signal_date`、`code`、`name`、`category`。

专业术语：

- **未来函数**：回测时使用了目标日期之后的数据，会导致结果失真。
- **signal_date**：策略实际触发日期。
- **trade_date**：本次策略作业的目标交易日。
- **category**：策略内部分类，例如 B1 setup、B2 breakout、碗形反弹等。

为什么要区分 `trade_date` 和 `signal_date`：

- 一个作业可以在某个交易日扫描，但信号可能来自策略允许的观察窗口。
- 导出和前端筛选需要知道“这次作业日期”和“信号触发日期”各自是什么。

## 策略选股性能规则

当前目标：本地 CSV 缓存完整时，全市场策略选股总耗时应控制在 10 分钟内。后续 Agent 修改策略时，必须保护这条性能路径，不要重新引入按策略重复读盘或按模板重复算指标。

核心实现：

- `quant_system.py` 和 `web/backend/services/strategy_service.py` 默认按最近 `320` 行读取 CSV；配置项是 `config/config.yaml` 顶层 `strategy_scan_rows`，代码最低保护值为 `160`。
- `CSVManager.read_stock()` 默认不解析日期。只有需要日期比较、回测裁剪、图表展示时才显式转换日期。
- 单只股票在一次扫描中只读一次 CSV，再把 DataFrame 传给多个策略。
- `utils/technical.py` 的 `prepare_shared_indicators()` 负责预计算 KDJ 和知行双线；BowlRebound、B1、B2 应优先复用已有列，缺少阈值状态时只补算状态列。
- B2 扫描必须先做必要条件快筛：近期没有达到 `b2_min_pct` 涨幅门槛的阳线时，直接跳过重分析。
- B2 三分类模板必须复用同一份 prepared DataFrame，不要对横盘突破、灾后重建、平行重炮分别重复准备指标。
- `--workers` 要从 CLI 传到主流程、B1/B2 匹配和 Web 缓存重建相关路径；单核设备允许自动降级。

性能验证建议：

- 小样本正确性：`python main.py run --help`，再运行 `QuantSystem.select_stocks(max_stocks=20, max_workers=2)`。
- B2速度验证：用 `B2PatternLibrary().scan_all(codes[:200], cm, max_workers=8, recent_rows=320)`，当前参考结果约 `12.9` 秒 / 200 只，折算 5157 只约 `5.6` 分钟。
- 如果全量超过 10 分钟，先检查 `--workers`、`strategy_scan_rows`、CSV 所在磁盘和同步软件，再考虑修改策略逻辑。
- 如果必须放大窗口或增加新指标，先用 200 只股票估算全量耗时，并在 README 记录新基线。

## 前端 K 线逻辑

K 线页面重点是快和不串数据。

实现方法：

- 使用请求缓存，避免重复拉同一个股票的 K 线。
- 对当天策略列表中的股票提前预热 K 线。
- 点击股票时使用 load guard，只允许最后一次请求更新页面标题、价格和策略详情。

专业术语：

- **prefetch / 预热**：用户点击前先拉取可能要看的数据。
- **cache hit**：命中缓存，不需要重新请求。
- **race condition / 请求竞态**：先点 A 再点 B，但 A 的慢请求后回来覆盖 B 的页面。
- **load guard**：给每次加载分配令牌，旧请求返回时自动丢弃。

为什么这样用：

- 预热能让策略列表点击接近即时显示。
- load guard 能解决代码和名称不匹配的问题。
- 缓存要有上限，避免长时间使用导致内存膨胀。

## txt 导出逻辑

txt 导出要基于最新策略结果，而不是前端临时列表。

要求：

- 按策略分类导出。
- 汇总导出时要做代码去重。
- 分类数量之和可能大于去重总数，因为同一股票可被多个策略命中。
- 前端展示必须同时给出“分类条数”和“去重股票数”，避免误导。

专业术语：

- **去重**：同一个股票代码只保留一次。
- **策略交集**：同一股票同时命中多个策略。
- **分类导出**：按 B1、B2、碗形分别生成 txt。

## 代码中文注释规范

注释必须解释“为什么”和“边界条件”，不要解释显而易见的赋值。

推荐写法：

```python
# 只缺 1 个真实交易日时才能快路径写当天快照，避免多日缺口丢历史行。
if trading_day_gap == 1 and can_use_spot_fast_path:
    fast_path_stocks.append(code)
```

不推荐写法：

```python
# 把 code 加入列表
fast_path_stocks.append(code)
```

注释规则：

- 复杂业务判断必须有中文注释。
- 专业术语第一次出现要解释。
- 不要大段注释重复代码。
- 修 bug 时注释应写清触发条件和保护目标。

## 方法推导逻辑

排查问题时按这个顺序写和想：

1. 现象：用户看到了什么异常。
2. 数据：当前页面、接口返回、CSV 首行、策略缓存分别是什么。
3. 假设：可能是日期、缓存、请求竞态、数据缺口、策略逻辑中的哪一类。
4. 验证：用最小命令或最小测试证明假设。
5. 方案：先修根因，再优化体验。
6. 回归：跑相关测试，必要时补充新测试。

示例：

- 现象：4 月 30 日结果数量和前端显示不一致。
- 数据：分类结果 186 条，去重后 154 只。
- 推导：不是策略多选错，而是不同策略命中同一股票。
- 方案：前端按策略分类展示，同时显示去重总数和交集说明。

## 专业名词使用要求

使用专业词时必须做到三点：

1. 中文名词优先，英文缩写第一次出现时解释。
2. 说明技术特点。
3. 说明为什么本项目要这样用。

常用词表：

| 术语 | 含义 | 本项目用途 |
| --- | --- | --- |
| 快路径 | 最短处理链路 | 单交易日缺口用快照快速补数据 |
| 慢路径 | 完整抓取链路 | 多日缺口补齐历史 |
| SSE | Server-Sent Events，服务端事件流 | 后端实时推送更新进度 |
| 缓存 | 保存近期结果复用 | K 线、策略结果、股票列表、市值 |
| 幂等 | 重复执行结果一致 | 防止重复写入同一日期 |
| 回填 | 补历史缺口 | 保证均线和策略指标连续 |
| 竞态 | 异步返回顺序错乱 | 防止股票名称和 K 线错配 |
| 预热 | 提前加载数据 | 提升策略列表点击速度 |
| 去重 | 合并重复代码 | 解释分类数量和最终股票数差异 |

## 节省 token 的要求

后续 Agent 必须节省 token，规则如下：

- 先读最相关文件，不全仓库扫描。
- 不把大段日志、CSV、构建输出贴给用户，只总结关键结果。
- 文件引用用路径和行号，不复制整段代码。
- 问题已明确时直接执行，不长篇讨论方案。
- 最终回复只写改了什么、验证了什么、剩余风险。
- 专业解释要短，但必须包含“是什么、为什么、怎么用”。
- 复杂任务先列 3 到 6 个步骤，执行中只更新关键进展。
- 测试失败时只贴失败核心行和判断，不贴完整堆栈。

## 推荐最终回复格式

小改动：

```text
已完成：说明 1-2 个关键变化。
验证：列出测试命令和结果。
```

复杂改动：

```text
已完成：
- 改动点 1
- 改动点 2

验证：
- 命令：结果

注意：
- 剩余风险或使用方式
```

回复不要堆砌实现细节。用户需要深挖时，再按模块展开。
