# Backtest Phase B Portfolio Ledger Design

## 背景

Phase A 已收紧 A 股执行边界：真实交易日、成交量、涨跌停、T+1、停牌和退出顺延。
Phase C 已补齐异步回测任务的可复现历史：`request_hash`、`result_hash`、`engine_version`、轻量历史列表和详情事件。

当前缺口在组合层：`web/backend/backtest_engine/portfolio.py` 仍按卖出日聚合交易收益，生成的是简化收益曲线。它没有真实现金、持仓、买入占用、卖出回款、暴露资金或逐日权益。因此它还不能支撑后续 paper/manual 执行，也不能解释同一天多笔交易对账户资金的影响。

## 系统层定位

Phase B 属于 **Portfolio / Analyzer 层**，不是 Execution、Broker、Tracking 或 QMT 层。

本阶段入口仍然是现有 `BacktestEngine.run()` 和 `analyzer.build_result()`：

```text
SignalSource
  -> Execution produces trades and OrderIntent
  -> PortfolioLedger builds account-like equity curve
  -> Analyzer returns compatible result with capital summary
```

## 目标

1. 用组合资金账本替代“卖出日平均收益”曲线，输出逐日权益。
2. 在不大改 Execution 的前提下，让现有 trade 字典可以驱动现金、持仓和回款计算。
3. 支持 `initial_cash`、`position_pct`、`max_positions`、`max_weight_per_code` 的最小可验证口径。
4. 保持旧 API 兼容：`summary`、`trades`、`equity_curve` 仍存在。
5. 为后续 `Position`、`TradeJournal`、`SimBrokerAdapter` 留出字段和边界，但不在本阶段实现。

## 非目标

- 不新增前端页面或改 nested frontend gitlink。
- 不实现 `SimBrokerAdapter`、`ManualBrokerAdapter`、QMT 或真实下单。
- 不新增 `backtest_runs/backtest_orders/backtest_trades` 持久化表；Phase C 的任务历史仍是当前持久化入口。
- 不重写 `DailyExecutionSimulator` 的单股退出逻辑。
- 不做参数优化、样本外验证、walk-forward 或全市场长回测。

## 设计方案

### 1. PortfolioLedger

在 `web/backend/backtest_engine/portfolio.py` 中新增轻量账本函数和内部结构。

核心输入：

- `trades: list[dict]`
- `initial_cash: float`
- `position_pct: float`
- `max_positions: int`
- `max_weight_per_code: float`

核心输出：

```python
{
    "equity_curve": [...],
    "capital_summary": {...},
    "portfolio_events": [...],
}
```

`equity_curve` 每个交易日包含：

- `date`
- `cash`
- `market_value`
- `total_equity`
- `daily_return_pct`
- `drawdown_pct`
- `open_positions`

`capital_summary` 包含：

- `initial_cash`
- `final_equity`
- `cash`
- `market_value`
- `cumulative_return_pct`
- `max_drawdown_pct`
- `trade_count`
- `invested_count`
- `rejected_count`
- `max_open_positions`

`portfolio_events` 记录买入、卖出和因资金/持仓约束拒绝的事件，供后续详情页或调试使用。

### 2. Trade 兼容口径

现有 trade 已包含：

- `code`
- `buy_date`
- `sell_date`
- `buy_price`
- `sell_price`
- `return_pct`
- `exits`
- `weight`

Phase B 不要求 Execution 立刻输出订单事件。账本先从这些字段推导：

- 买入日：按 `buy_date` 占用资金。
- 卖出日：按 `exits` 分批释放资金；没有 `exits` 时退化为 `sell_date/sell_price` 一次卖出。
- 数量：若 trade 有 `quantity` 且大于 0，则使用；否则按目标资金和买入价折算为 100 股整数手。
- 资金比例：优先使用 `trade.weight`；否则使用 `position_pct / 100`；两者都缺失时用等权 fallback。

### 3. 资金约束

本阶段只实现最小硬约束：

- `initial_cash <= 0` 时回退 `100000.0`。
- `position_pct > 0` 时每笔目标资金为 `initial_cash * position_pct / 100`。
- `position_pct == 0` 时兼容旧 fixed slots，按 `max_positions` 等分初始资金。
- `max_positions > 0` 时，买入日前未平仓数量达到上限则拒绝该 trade。
- `max_weight_per_code > 0` 时，同一股票目标资金不能超过 `initial_cash * max_weight_per_code / 100`。
- 现金不足时拒绝该 trade，不允许负现金。

### 4. 逐日权益

账本按所有买入、卖出日期排序推进。

由于当前 trade 结构没有持仓期间每日收盘价，Phase B MVP 的 `market_value` 使用成本价或已知退出价事件更新，不承诺完整每日 mark-to-market。它的价值是比旧曲线更真实地表达：

- 现金占用何时发生。
- 卖出回款何时释放。
- 最大持仓数何时限制买入。
- 多笔交易重叠时账户权益如何变化。

完整按每日行情估值属于后续 DataPortal 估值层。

### 5. Analyzer 兼容

`web/backend/backtest_engine/analyzer.py` 继续返回旧字段：

- `summary`
- `trades`
- `equity_curve`
- `order_intents`
- `runtime`

新增：

- `capital_summary`
- `portfolio_events`

`summary.cumulative_return_pct` 和 `summary.max_drawdown_pct` 改用 PortfolioLedger 结果。旧平均收益、胜率、持仓天数等统计继续保留。

### 6. 参数入口

现有前端和后端已传递：

- `position_pct`
- `max_weight_per_code`
- `portfolio_mode`

Phase B 新增后端兼容参数：

- `initial_cash`，默认 `100000.0`
- `max_positions`，默认使用 `max_positions_per_day`，缺失时用 `20`

前端不传这些新参数时，后端必须保持可运行。

## 测试策略

新增或扩展 `tests/test_backtest_engine.py`：

1. 两笔重叠交易在同一账户中占用现金，第二笔若超过 `max_positions=1` 应被 portfolio 拒绝。
2. `position_pct=50`、`initial_cash=100000` 时，两笔非重叠交易逐日权益应按现金回款推进。
3. `max_weight_per_code` 限制同一股票重复信号的目标资金。
4. `analyzer.build_result()` 返回 `capital_summary` 和 `portfolio_events`，且旧字段仍存在。

补充 `tests/test_backtest_service.py`：

1. API result 包含 `capital_summary`。
2. 默认参数不传 `initial_cash` 时仍兼容旧请求。

验证命令：

```powershell
python -m pytest tests/test_backtest_engine.py tests/test_backtest_service.py -q
python -m pytest tests/test_trading_calendar.py tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check
```

## 风险与边界

- 当前没有持仓期间逐日行情估值，因此权益曲线不是完整 mark-to-market；文档必须写明。
- 如果旧前端只读取 `equity_curve.equity`，需保持字段存在或提供兼容别名。
- Portfolio 拒绝 trade 会让 `trade_count` 和 raw execution trade 数不同，需要在 `capital_summary.rejected_count` 中显式解释。
- 本阶段不持久化 `portfolio_events` 到独立表；它们随回测 result 一起进入 Phase C 任务历史。

## 交付判定

Phase B 完成时必须满足：

- 后端 focused regression 通过。
- `build_result()` 输出 `capital_summary` 和兼容 `equity_curve`。
- 资金约束测试证明 max positions / cash / per-code cap 生效。
- 文档说明 Phase B 是账本 MVP，不是模拟盘或实盘。
