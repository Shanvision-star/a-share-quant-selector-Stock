# 统一回溯/回测基础引擎设计

## 背景与目标

当前项目已有 CLI `backtrace` 命令、Web `/api/backtest` 接口和前端回测页，但回溯判断、候选回测、交易模拟、结果持久化分散在不同模块中。`utils/backtrace_analyzer.py` 仍使用旧式策略调用方式，和现有 `BaseStrategy`/`StrategyRegistry` 自动注册流程不一致，容易导致历史诊断结果不可信或无法覆盖新策略。

本设计聚焦第一阶段的基础能力：抽出一套统一回溯/回测核心引擎，同时支撑单股历史诊断、全市场历史扫描、现有候选批量回测、CLI、Web API 和异步任务。前端工作台完整重设计另开后续规格，本阶段只定义后端 API/CLI 返回结构，保证前端后续有稳定数据契约可用。

## 范围

### 包含

- 单只股票 + 单个日期：严格按历史日期截断行情，判断当天命中哪些已注册策略。
- 某个日期 + 全市场：异步重跑当天全市场策略，生成历史候选和任务进度。
- 现有策略候选、人工选股池、输入股票池的批量交易模拟。
- 覆盖现有自动注册的全部 `BaseStrategy` 策略，避免为 B1/B2/Bowl 单独维护并行逻辑。
- 结果写入现有 `data/web_strategy_cache.db`，便于历史查看、筛选和复盘。
- CLI 与 Web API 双入口。
- 明确记录命中原因、交易明细、汇总指标、资金曲线、跳过原因和策略异常。

### 不包含

- 前端回测工作台的完整布局重设计。
- 新数据库或独立存储服务。
- 重新设计策略接口。策略仍以当前 `BaseStrategy` 和 `StrategyRegistry` 为准。
- 实盘交易、账户资金管理和真实撮合系统。

## 推荐方案

采用“统一引擎 + 适配层”。

核心计算能力集中在新的回溯/回测引擎模块中；CLI、Web API 和异步任务只负责参数校验、调度、进度记录和返回格式转换。这样可以修复旧 `BacktraceAnalyzer` 与当前策略注册机制不一致的问题，也能避免后续前端、CLI、异步任务各自重复实现策略判断和交易模拟。

## 核心组件

### HistoricalDataProvider

负责读取本地 `data/` CSV 行情，标准化日期和 OHLCV 字段，并按目标日期或日期范围严格截断数据。

关键规则：

- 历史策略重跑必须只看到目标日期及以前的数据，防止未来函数。
- 交易模拟只能使用信号日之后、回测结束日之前的有效交易日。
- CSV 缺失、数据为空、目标日期不存在、价格字段无效都返回结构化 diagnostics，不伪造成空成功。

### StrategySignalRunner

负责通过 `StrategyRegistry` 获取全部自动注册策略，并在截断后的行情上执行策略判断。

关键规则：

- 默认覆盖全部 `BaseStrategy` 策略，也支持按策略过滤。
- 单个策略或单只股票异常不应中断全市场任务，应记录到 diagnostics 并继续处理其他任务。
- 输出统一的 signal 结构，包含 `code`、`name`、`trade_date`、`signal_date`、`strategy_name`、`category`、`score/similarity_score`、`reason` 和原始策略 payload。

### BacktestSimulator

负责从信号列表生成交易结果。现有 `web/backend/services/backtest_service.py` 中的买入延后、持有天数、手续费、滑点、固定止盈止损、利润放飞、跌破短期趋势线/多空线退出等逻辑应迁移或复用到该组件。

关键规则：

- 买入日按信号日后的第 N 个交易日计算，超过数据范围则跳过并记录原因。
- 买入价和卖出价只能来自有效 `open`/`close` 字段。
- 支持分批退出，保留每次退出的日期、价格、仓位比例、退出原因和成本。
- 汇总净收益时扣除买入和卖出侧手续费/滑点。

### ResultExplainer

负责统一输出可解释信息。

至少包含：

- 命中原因：策略返回的 reason、category、相似度或信号字段。
- 未交易原因：无买入日、无卖出日、价格无效、日期越界、CSV 缺失。
- 策略异常：策略名、股票代码、异常类型和安全化后的错误信息。
- 任务摘要：候选数、信号数、交易数、跳过数、策略异常数。

### BacktestRepository

负责写入和查询 `data/web_strategy_cache.db`。

复用现有 `strategy_runs` 和 `strategy_run_events` 保存全市场异步任务状态与进度；新增回测/回溯结果表保存摘要、信号、交易和资金曲线。

建议新增表：

- `backtest_runs`：保存 `run_id`、来源、参数 JSON、状态、摘要 JSON、创建/完成时间。
- `backtest_signals`：保存每条历史策略信号。
- `backtest_trades`：保存每笔交易和退出摘要。
- `backtest_equity_points`：保存资金曲线点。
- 必要索引：`run_id`、`trade_date`、`signal_date`、`code`、`strategy_name`。

## CLI 设计

保留并升级现有入口：

```bash
python main.py backtrace --stock-code 000001 --date 2026-04-01
```

行为：

- 读取并截断 `000001` 到 `2026-04-01`。
- 运行所有已注册策略或指定策略过滤。
- 输出命中的策略信号、未命中/跳过原因摘要和 `run_id`。
- 默认保存到 SQLite，便于 Web 端后续查看。

新增全市场历史扫描入口：

```bash
python main.py backtrace --date 2026-04-01 --workers 8
```

行为：

- 对全市场 CSV 股票池执行目标日期历史扫描。
- 使用异步任务模型记录进度。
- 输出任务 `run_id`，并在结束后输出信号数、异常数和保存位置。

候选回测仍可通过 Web API 调用；如需 CLI 批量回测，可在后续计划中增加显式 `backtest` 参数与输入文件支持。

## Web API 设计

### 单股历史诊断

`POST /api/backtrace/diagnose`

请求字段：

- `stock_code`
- `date`
- `strategy_filter`
- `save_result`

返回字段：

- `success`
- `data.run_id`
- `data.signals`
- `data.diagnostics`
- `data.summary`

### 全市场历史扫描

`POST /api/backtrace/runs`

请求字段：

- `date`
- `strategy_filter`
- `stock_pool`
- `max_workers`
- `save_result`

返回字段：

- `success`
- `data.run_id`
- `data.status`

`GET /api/backtrace/runs/{run_id}`

返回任务状态、进度、摘要和最近事件。进度事件复用 `strategy_run_events` 的 `stage`、`processed_count`、`total_count`、`matched_count`、`message`。

### 候选回测

现有 `POST /api/backtest` 保持兼容，但内部改为调用统一引擎。

返回结构统一为：

- `run_id`
- `signals`
- `trades`
- `summary`
- `equity_curve`
- `diagnostics`
- `params`

## 返回结构

### summary

至少包含：

- `candidate_count`
- `signal_count`
- `trade_count`
- `skipped_count`
- `strategy_error_count`
- `win_rate_pct`
- `avg_return_pct`
- `cumulative_return_pct`
- `max_drawdown_pct`
- `avg_hold_days`
- `best_return_pct`
- `worst_return_pct`

### diagnostics

按类型分组：

- `missing_data`
- `date_not_found`
- `invalid_price`
- `out_of_range`
- `strategy_errors`
- `simulation_skipped`

每条 diagnostics 至少包含 `code`、`date`、`stage`、`reason`，策略错误额外包含 `strategy_name`。

## 异步任务规则

全市场历史扫描第一版直接按异步任务设计。

状态流：

- `queued`
- `running`
- `completed`
- `failed`

任务开始时写入 `strategy_runs`，每个阶段写入 `strategy_run_events`。单只股票或单个策略失败不会让任务进入 `failed`，只有任务初始化失败、数据库不可写、全局参数非法等不可恢复错误才使任务失败。

## 错误处理

- 日期必须符合 `YYYY-MM-DD`。
- 开始日期不能晚于结束日期。
- 股票代码必须是 6 位数字。
- 策略过滤值必须能映射到已注册策略或预定义分组。
- 不吞掉异常：单项异常写 diagnostics，任务级异常写 `error_message` 并返回明确错误。
- 不用空成功掩盖数据问题：无数据、无目标日期、无有效价格都进入 diagnostics。

## 测试与验证

核心引擎测试：

- 使用小型 DataFrame 或临时 CSV 验证严格日期截断。
- 验证策略只能看到目标日期及以前的数据。
- 验证单股诊断能返回 signals 和 diagnostics。
- 验证交易模拟的买入延后、持有天数、手续费/滑点、分批退出和跳过原因。

API 测试：

- 验证非法日期、非法股票代码、开始日期晚于结束日期返回 400。
- 验证 `POST /api/backtrace/diagnose` 返回统一结构。
- 验证 `POST /api/backtest` 保持兼容并新增 `run_id`、`diagnostics`。

CLI 验证：

```bash
python main.py backtrace --stock-code 000001 --date 2026-04-01
```

全市场任务验证：

- 创建任务后可查询 `run_id`。
- 任务进度随处理数量更新。
- 完成后 SQLite 中可查到摘要、信号和交易记录。

## 后续规格

基础引擎完成后，再分别设计：

- 前端回测工作台体验和结果展示优化。
- 大范围/长周期批量回测的调度、取消、分页和导出。
- 策略命中/未命中的更细粒度解释能力。
