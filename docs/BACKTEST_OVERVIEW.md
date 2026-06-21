# 回测系统说明

> 本文档解释当前 Web 端回测的执行链路与参数语义，让策略开发者和使用者快速理解
> 回测产出的 `summary / trades / equity_curve / order_intents` 是怎么来的。

## 1. 执行链路

```
前端 BacktestView
  └─▶ POST /api/backtest (或 /api/backtest/tasks 异步)
        └─▶ backtest_service.run_backtest(params)
              ├─ _fetch_candidates → SignalCandidate 列表
              ├─ BacktestEngine.run
              │     ├─ SignalSource.fetch
              │     ├─ cap_positions_per_day / max_signals_per_code
              │     ├─ DailyExecutionSimulator.simulate_trade（按单股独立模拟）
              │     └─ build_result（summary + trades + equity_curve + order_intents）
              └─ 返回结构化 dict
```

## 2. 关键模块

| 模块 | 职责 |
| --- | --- |
| `web/backend/backtest_engine/models.py` | `SignalCandidate / BacktestParams / OrderIntent` 等数据类 |
| `web/backend/backtest_engine/signal_source.py` | 信号源协议、StaticSignalSource、`cap_positions_per_day`、组合策略 resolver |
| `web/backend/backtest_engine/engine.py` | 编排：信号筛选 → 执行 → 结果聚合 |
| `web/backend/backtest_engine/execution.py` | 日线 / 分钟线执行模拟，止盈止损、profit runner |
| `web/backend/backtest_engine/portfolio.py` | 资金曲线、最大回撤计算 |
| `web/backend/backtest_engine/analyzer.py` | 把执行结果包成最终响应结构 |

## 3. 单股退出规则（已固化）

执行层会先检查 A 股可交易边界：买入日必须按真实交易日推进，且目标交易日必须有
行情行、明确正成交量，并且不是涨停锁死；卖出日必须满足 T+1、非停牌、非跌停锁死。
若退出触发日不可卖，日线回测会顺延到模拟窗口内的下一可卖交易日；窗口内无可卖日时
该候选跳过。
退出条件只在可交易行情行上评估；停牌、无量或坏数据行不会触发止损、趋势退出或
Profit Runner，避免用不可成交日的价格生成顺延成交。
涨跌停锁死判断优先使用数据源 `prev_close`；缺失时只回溯最近一个可交易行情行的收盘价，
避免停牌或坏数据行污染涨跌停边界。
当前离线交易日历覆盖 2016-01-01 至 2026-12-31，超出窗口的历史或未来回测需要先补充
官方休市表；执行层会跳过超窗候选，避免把未覆盖年份的工作日静默当成 A 股交易日。

按优先级从高到低：

1. **固定止损**：跌破买入价 `stop_loss_pct`
2. **无收益退出**：持有 `no_gain_days` 仍无浮盈
3. **多空线破位**：收盘跌破 `bull_bear_line`
4. **短期趋势回撤**：收盘跌破 `short_term_trend * (1 - short_trend_drawdown_pct)`
5. **短期趋势连破**：连续 `short_trend_break_days` 收盘低于短期趋势线
6. **Profit Runner 阶梯减仓**：浮盈触发 `profit_trigger_pct` 后分批兑现
7. **持仓期满**：到达 `holding_days` 强制平仓

## 4. 组合策略模式（新增）

参见 [项目执行逻辑](project-exec) 中“组合回测”章节。

简要总结：

- `signal_merge_mode=single` → 行为与历史一致
- `signal_merge_mode=multi_strategy` → 启用同股同日多策略合成，按
  `signal_priority_mode` 选最高优先级
- `position_pct` → 每笔交易在组合中分配的资金比例
- `max_weight_per_code` → 单只股票累计资金占比上限

## 5. OrderIntent 与跟踪联动

- 每笔成功模拟的回测都会产出 `OrderIntent`
- 跟踪运营页（Tracking）从 `order_intents` 中挑选条目转为人工跟踪
- **OrderIntent 不会自动下单**，必须经人工“确认 / 否决”流程

## 6. 相关文档

- [B1 案例战法](b1-case)
- [B2 战法说明](b2-strategy)
- [跟踪 Agent](tracking-agent)
- [项目执行逻辑](project-exec)
