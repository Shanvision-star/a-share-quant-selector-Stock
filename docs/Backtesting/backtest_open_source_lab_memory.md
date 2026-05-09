# 开源回测模型 lab 记录（2026-05-10）

## 任务总结

已完成“开源回测模型导入评估文档 + backtest_lab 小样本对比”。本轮没有修改生产回测引擎，只新增实验层和测试。

## 问题推导

现象：希望引入 GitHub 上成熟回测模型，但不能破坏当前 `backtest_engine` 和前端回测 API。

数据：本机初始没有安装 Backtrader、vectorbt、RQAlpha、Zipline Reloaded、backtesting.py。

假设：直接导入大型框架会带来依赖、许可证、成交规则和响应结构冲突。

验证：先安装轻量 `backtesting.py==0.6.5` 作为 lab 依赖，构造 1 只股票、1 个信号、20 个交易日样本，对比本项目引擎、参考事件模型和 `backtesting.py`。

根因：外部框架价值主要在架构和规则，不适合直接替换生产引擎。

方案：建立 `backtest_lab`，先做样本对比和差异解释，再决定迁移哪些规则。

## 当前结果

`python -m backtest_lab.compare` 输出三路一致：

- `project_engine`: passed
- `reference_event_model`: passed
- `backtesting_py`: passed
- 买入日：`2026-04-02`
- 卖出日：`2026-04-07`
- 收益率：`6.53%`
- `diffs=[]`

## 下一步计划

1. 加 Backtrader 适配器，验证事件驱动模型下买卖日和成交价是否仍可对齐。
2. 加 RQAlpha 评估文档和最小适配方案，重点参考 A 股 T+1、停牌、涨跌停和手续费。
3. 将当前固定样本扩展为 3 类样本：普通盈利、止损、涨停禁买。
4. 只有当 lab 能解释差异后，才把规则迁回 `web/backend/backtest_engine`。

## 解决方案边界

- `backtest_lab` 不接生产 API。
- 外部依赖写在 `backtest_lab/requirements.txt`，不写入生产 requirements。
- 生产引擎只吸收通过 lab 验证的规则。
- 任何外部框架结果差异都必须先写明原因，再考虑迁移。
