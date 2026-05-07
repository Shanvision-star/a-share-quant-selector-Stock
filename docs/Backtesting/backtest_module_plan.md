# 回测模块后续计划与架构分析

日期：2026-05-07

## 零、当前优先级结论

当前主线调整为：**先完成回测模块，再推进模拟/人工执行，最后预留量化实盘接口**。

原因：

- 回测模块是策略、模拟盘、人工确认和未来实盘执行的共同底座。
- 当前银河 QMT 权限门槛与 20 万资金计划不匹配，自动交易不应抢占主线。
- 先把交易日历、A 股撮合、组合资金曲线、回测持久化、前端回测详情做稳，后续量化执行才能复用同一套规则。

当前已完成：

- 已创建 `web/backend/backtest_engine/` 包。
- 已拆出 `data_portal.py`、`signal_source.py`、`execution.py`、`portfolio.py`、`analyzer.py`、`engine.py`、`models.py`。
- 已保持现有 `/api/backtest` 外壳基本兼容。
- 已增加 `MinuteBar`、`OrderIntent` 和分钟级回测基础能力。
- 已用 `tests/test_backtest_engine.py` 和 `tests/test_backtest_service.py` 固定单日人工池回测不截断未来交易窗口。

## 一、成熟框架参考

### 1. Backtrader

Backtrader 的核心入口是 `Cerebro`，它把数据源、策略、经纪商、观察器和分析器组合到同一个运行引擎里。这个模式适合我们后续把“信号生成”和“交易撮合”拆开：策略只产出信号，Broker/Execution 层决定是否成交、以什么价格成交。

参考：https://www.backtrader.com/docu/cerebro/

项目吸收点：

- `BacktestEngine` 对应编排器，不直接写策略逻辑。
- `Execution` 和 `Portfolio` 必须独立，避免策略函数里直接改现金和持仓。
- `Analyzer` 单独输出报告，前端和文档都只消费分析结果。

### 2. Backtesting.py

Backtesting.py 的 `Backtest` 对象围绕 OHLCV 数据、策略类、手续费、滑点、交易列表、权益曲线和统计指标组织结果。它对中小型策略验证很直接，适合作为我们短期回测页面的结果结构参考。

参考：https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html

项目吸收点：

- 回测结果必须稳定包含 trades、equity_curve、summary。
- 手续费、滑点、价格字段和订单明细要进入参数快照。
- 前端回测页优先展示统计指标和交易明细，而不是只展示一个收益率。

### 3. VectorBT

VectorBT 强调向量化回测，典型入口是 `Portfolio.from_signals`。它适合做参数网格、批量信号对比和快速筛选。我们后续可以保留事件驱动撮合，但为参数优化增加一个向量化快模式。

参考：https://vectorbt.dev/api/portfolio/base/

项目吸收点：

- 参数优化和策略批量对比可以单独走向量化快路径。
- 组合信号需要处理同一天多策略重叠、买卖信号冲突和最大持仓限制。
- 向量化结果只用于研究筛选，最终 A 股撮合仍以事件/交易日引擎为准。

### 4. Zipline / Zipline Reloaded

Zipline 是事件驱动回测模型，常见结构是 `initialize`、`handle_data`、订单 API、交易日历和数据 Portal。它对避免未来函数、按交易日推进、模拟真实交易环境有借鉴意义。

参考：https://zipline.ml4trading.io/

项目吸收点：

- `DataPortal` 必须成为稳定边界，所有历史行情和交易日历都从这里取。
- 回测推进要按 A 股真实交易日，而不是自然日或简单工作日。
- 信号阶段禁止读取信号日之后的数据，执行阶段才允许读取未来成交行情。

### 5. Microsoft Qlib

Qlib 把数据、模型、回测、组合分析、报告分成流水线，适合更长远的“策略研究平台化”。当项目后续引入量化模型或机器学习打分时，可以参考 Qlib 的实验记录和报告结构。

参考：https://github.com/microsoft/qlib

项目吸收点：

- 每个回测 run 要保存参数、数据范围、策略版本和输出报告。
- 未来机器学习模型只输出 `score/rank`，不直接控制买卖。
- 研究流水线和实盘执行流水线必须分离。

## 二、当前回测模块定位

当前实现已经具备：

- 三种候选来源：策略结果、人工选股池、手输代码。
- 信号日期范围筛选。
- 买入延后交易日、持有天数、买卖价格字段。
- 手续费、滑点、固定止损、趋势线破位、分批止盈。
- 交易明细、摘要指标、简化资金曲线。

但它还不是完整组合回测引擎。当前更像“信号验证器”：验证某类信号在之后若干交易日里的表现。

## 三、推荐目标架构

建议拆成 6 层：

1. `DataPortal`
   - 负责读取日线、交易日历、复权口径、停牌状态、涨跌停状态。
   - 对外提供 `get_bar(code, date)`、`history(code, end_date, window)`。

2. `SignalSource`
   - 统一策略结果、人工池、手输代码、未来模型信号。
   - 输出标准 `Signal(code, signal_date, strategy, score, metadata)`。

3. `ExecutionEngine`
   - 根据信号生成订单。
   - 处理 T+1、涨跌停不可买卖、停牌、开盘价/收盘价/下一交易日成交。
   - 输出 `Order` 和 `Trade`。

4. `Broker / Portfolio`
   - 维护现金、持仓、冻结资金、交易成本。
   - 支持等权、固定金额、按得分加权、最大持仓数、单票仓位上限。

5. `RiskManager`
   - 统一止损、止盈、趋势线破位、最大回撤、行业集中度限制。
   - 后续支持策略间互斥和重叠信号合并。

6. `Analyzer`
   - 生成收益、回撤、胜率、盈亏比、夏普、换手率、暴露天数、逐日权益曲线。
   - 输出前端表格、图表和下载文件。

## 四、近期开发优先级

### Phase 1：正确性与 A 股撮合

- 引入交易日历，所有买入延后和持有天数都按交易日计算。
- 明确 `signal_date`、`trade_date`、`buy_date`、`sell_date` 四个日期字段。
- 增加无未来函数测试：信号日只能读取信号日及以前的数据，退出模拟才能读取未来行情。
- 增加复权口径检查：前复权、不复权、后复权不能混用。
- 增加 A 股基础撮合规则：T+1、100 股整数手、涨跌停、停牌。
- 增加订单意图和成交结果分离：`OrderIntent` 不等于 `Order`，回测成交由 `Execution` 本地模拟。

### Phase 2：组合级回测

- 建 `backtest_runs`、`backtest_orders`、`backtest_trades`、`backtest_equity_curve` 表。
- 每个回测 run 保存参数快照，保证结果可复现。
- 现金曲线改成逐交易日更新，而不是按卖出日聚合。
- 支持最大持仓、等权买入、按策略权重买入。
- 支持多策略信号去重：同一股票同一天多策略命中时合并为一笔候选，同时保留命中策略列表。
- 支持初始资金、单票最大资金、单日最大买入、最大持仓数和仓位再平衡规则。

### Phase 3：前端体验

- 增加回测历史列表：参数、日期、来源、策略、收益、回撤。
- 增加回测详情页：权益曲线、回撤曲线、交易分布、每笔退出原因。
- 支持按策略、日期、股票、退出原因筛选交易明细。
- 支持导出 CSV / Excel。
- 支持参数模板：短线、波段、趋势、保守止损。

### Phase 4：参数优化

- 增加参数网格：持有天数、买入延后、止损、止盈、趋势线破位天数。
- 输出参数热力图，找出稳健区间，而不是只看单个最优点。
- 增加样本内 / 样本外切分。
- 增加 walk-forward 验证，降低过拟合。
- 增加批量策略对比：B1、B2、碗底、砖型图、组合交集。

### Phase 5：模拟/人工执行闭环

- 基于回测引擎输出 `OrderIntent`。
- 实现 `paper` 模拟盘，验证开盘 30 分钟和收盘前 30 分钟规则。
- 实现 `confirm_manual` 人工确认流，记录用户是否执行、执行价格和成交数量。
- 支持日终导入真实成交流水，和 `OrderIntent` 关联，形成复盘闭环。
- 暂不做自动券商下单。

### Phase 6：量化程序接入预留

- 未来模型只负责产出标准 Signal，不直接操作回测内部对象。
- 回测引擎提供稳定接口：

```python
signals = signal_source.load(start_date, end_date, strategy="all")
run = backtest_engine.run(signals, params)
report = analyzer.build(run)
```

- 如果接入机器学习排序模型，模型输出 `score` 和 `rank`，Portfolio 层决定买多少。
- 如果未来接入实盘或模拟盘，ExecutionEngine 可以复用回测订单逻辑，但真实成交回报必须单独处理。
- QMT / miniQMT 只保留 `BrokerAdapter` 接口，等待资金和券商权限满足后再启用。

## 五、风险点

- 不能把候选日期范围再次当作交易模拟结束日，否则会复现“单日回测无交易”的问题。
- 不能在信号生成阶段读取信号日之后的数据，否则回测结果会虚高。
- 不能只看去重股票数，必须同时展示信号数和交易数。
- A 股停牌、涨跌停、复权口径会明显影响短线策略结果，必须尽早进入撮合模型。
- 参数优化必须输出稳定区间，不建议只展示最高收益参数。

## 六、建议的下一步任务

1. 在 `web/backend/backtest_engine/data_portal.py` 中接入 `utils/trading_calendar.py`，增加按真实交易日推进的接口。
2. 在 `web/backend/backtest_engine/execution.py` 中补 A 股撮合规则：T+1、100 股整数手、涨跌停、停牌、ST 禁买。
3. 在 `web/backend/backtest_engine/portfolio.py` 中加入初始现金、持仓、冻结资金、单票金额和最大持仓数。
4. 新建回测持久化表：`backtest_runs`、`backtest_orders`、`backtest_trades`、`backtest_equity_curve`。
5. 前端增加回测历史和回测详情页，展示权益曲线、回撤曲线、交易明细、退出原因。
6. 再做参数优化和策略组合对比。
7. 最后才推进模拟盘、人工确认和量化实盘接口预留。
