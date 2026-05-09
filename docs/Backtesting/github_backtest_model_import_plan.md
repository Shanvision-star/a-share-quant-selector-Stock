# GitHub 开源回测模型导入评估文档

日期：2026-05-10

## 结论

当前不建议把任何 GitHub 回测框架整包替换进生产回测引擎。更稳的路线是先建 `backtest_lab`，用同一份样本行情和信号对比本项目 `BacktestEngine` 与外部框架结果，再把成熟框架的规则和架构逐步迁移进现有 `backtest_engine`。

本阶段只做评估和实验，不改生产 API，不改变前端回测调用路径。

## 参考框架

| 框架 | GitHub | 适合吸收的能力 | 当前结论 |
| --- | --- | --- | --- |
| Backtrader | https://github.com/backtrader/backtrader | 事件驱动、Broker、Sizer、Analyzer | 学架构，不直接引入生产 |
| backtesting.py | https://github.com/kernc/backtesting.py | 轻量、易安装、适合最小样本对比 | 本阶段作为 lab 外部适配器 |
| RQAlpha | https://github.com/ricequant/rqalpha | A 股撮合、T+1、手续费和交易规则 | 后续重点参考 A 股规则 |
| Zipline Reloaded | https://github.com/stefan-jansen/zipline-reloaded | DataPortal、交易日历、资产生命周期 | 学数据层，不直接导入 |
| vectorbt | https://github.com/polakowo/vectorbt | 向量化参数扫描、指标批量分析 | 后续做参数扫描基准 |
| Microsoft Qlib | https://github.com/microsoft/qlib | 研究流水线、特征库、模型训练 | 等回测稳定后再接研究层 |

## 为什么不能直接替换

1. 本项目已经有 `DataPortal / SignalSource / Execution / Analyzer / OrderIntent` 边界。
2. A 股规则需要严格保留：T+1、100 股整数手、涨跌停、停牌、ST 禁买、复权一致性。
3. 前端回测、单股跟踪、OrderIntent 已经依赖现有响应结构。
4. 外部框架的成交模型、手续费字段和交易日历不同，直接替换会造成结果漂移。
5. 开源框架许可证和依赖体积需要独立评估，不能混入生产依赖。

## 导入策略

### Phase A：backtest_lab 对比层

目标：证明同一份样本数据下，本项目引擎和外部框架的核心交易结果是否一致。

范围：

- 1 只股票。
- 1 个信号。
- 20 个交易日。
- 固定买入日、卖出日和成交价。
- 比较买入日、卖出日、收益率、交易笔数。

不做：

- 不接真实 CSV 全市场数据。
- 不改 `web/backend/backtest_engine` 生产逻辑。
- 不改前端 API。
- 不引入 QMT 或券商接口。

### Phase B：规则迁移

如果样本对比能解释差异，再把成熟框架规则迁入现有引擎：

- 交易日历和资产生命周期参考 Zipline / RQAlpha。
- T+1、停牌、涨跌停、手续费参考 RQAlpha。
- Broker / Analyzer 分层参考 Backtrader。
- 参数扫描参考 vectorbt。

### Phase C：研究层

等回测结果稳定后，再评估 Qlib：

- 特征库。
- 模型训练。
- 滚动验证。
- 研究流水线。

## 最小样本验收标准

`backtest_lab` 必须输出结构化 JSON：

```json
{
  "project_engine": {
    "trade_count": 1,
    "buy_date": "2026-04-02",
    "sell_date": "2026-04-07",
    "return_pct": 6.54
  },
  "reference_event_model": {
    "trade_count": 1,
    "buy_date": "2026-04-02",
    "sell_date": "2026-04-07",
    "return_pct": 6.54
  },
  "backtesting_py": {
    "status": "passed"
  },
  "diffs": []
}
```

允许差异：

- 浮点收益率允许 `0.01%` 以内误差。
- 如果外部框架成交时点无法精确模拟本项目买卖价，必须在 diff 中写明原因。

不允许差异：

- 买入日不同。
- 卖出日不同。
- 交易笔数不同。
- T+1 被破坏。

## 本轮最小样本执行结果

命令：

```powershell
python -m backtest_lab.compare
```

结果摘要：

- 股票：`000001`
- 样本长度：20 个交易日
- 信号日：`2026-04-01`
- 买入日：`2026-04-02`
- 卖出日：`2026-04-07`
- 买入价：`10.1`
- 卖出价：`10.76`
- 收益率：`6.53%`
- `project_engine`、`reference_event_model`、`backtesting.py` 三路结果一致。
- `diffs=[]`

本机已安装 lab 可选依赖 `backtesting==0.6.5`。该依赖只用于实验层，不写入生产依赖。

## 后续决策点

1. 如果 `backtesting.py` 小样本能稳定对齐，可继续加 Backtrader/RQAlpha 适配器。
2. 如果外部框架结果和本项目差异较大，先解释差异，不急着迁移。
3. 生产引擎只吸收验证过的规则，不引入未验证的大框架依赖。
