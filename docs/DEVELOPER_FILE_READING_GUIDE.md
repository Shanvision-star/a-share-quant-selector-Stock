# A股量化选股系统开发者逐文件阅读手册

> 本文档面向开发者、维护者和后续代理。
> 目标是回答一个实际问题：进入这个仓库后，应该先读哪些文件、每个关键文件负责什么、修改某类需求应该从哪里下手。

配套文档：

- 总体说明见 [docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md](docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md)
- Web 演进方向见 [docs/WEB_INTERFACE_PLAN.md](docs/WEB_INTERFACE_PLAN.md)

---

## 1. 建议阅读顺序

如果是第一次接手本项目，建议按下面顺序阅读：

1. `README.md`
2. `main.py`
3. `quant_system.py`
4. `strategy/base_strategy.py`
5. `strategy/strategy_registry.py`
6. `web/backend/main.py`
7. `web/backend/routers/`
8. `web/backend/services/kline_service.py`
9. `web/backend/services/strategy_service.py`
10. `web/frontend/src/router/index.ts`
11. `web/frontend/src/api/index.ts`
12. `web/frontend/src/views/HomeView.vue`
13. `web/frontend/src/views/StockDetail.vue`
14. `web/frontend/src/components/KlineChart.vue`
15. `docs/WEB_INTERFACE_PLAN.md`

这条顺序的逻辑是：

- 先理解项目入口。
- 再理解离线业务链路。
- 再理解策略抽象。
- 最后再进入 Web 展示与后续架构演进。

---

## 2. 根目录关键文件

### `main.py`

定位：CLI 总入口。

什么时候读它：

- 想知道项目有哪些命令可执行。
- 想知道 CLI 模式下的启动顺序。
- 想排查为什么某个命令没有触发预期流程。

关键点：

- 命令行参数解析都在这里。
- `init / run / web / schedule / backtest / backtrace` 的入口都从这里分发。
- 真正业务逻辑不在这里实现，而是继续下沉到 `QuantSystem`。

### `quant_system.py`

定位：CLI 业务总调度器。

什么时候读它：

- 想理解“完整选股流程”如何组织。
- 想知道数据更新、选股、导出、钉钉通知的顺序。
- 想修改 CLI 批处理行为。

关键点：

- 初始化配置、CSV、AKShare、钉钉、策略注册中心。
- 提供 `init_data()`、`update_data()`、`select_stocks()`、`run_full()` 等主流程。
- 是 CLI 模式下最核心的业务编排层。

### `requirements.txt`

定位：Python 依赖清单。

什么时候读它：

- 首次配置环境。
- 发现新机器无法启动。
- 需要确认某个库是否已经是项目标准依赖。

### `config/config.yaml`

定位：基础运行配置。

什么时候读它：

- 调整数据目录、钉钉、调度时间。
- 排查部署环境差异。

### `config/strategy_params.yaml`

定位：策略参数配置源。

什么时候读它：

- 调参。
- 理解当前 B1/B2/碗底策略使用的参数值。
- 对接 Web 设置页。

---

## 3. 策略层关键文件

### `strategy/base_strategy.py`

定位：策略接口抽象。

什么时候读它：

- 新增策略类。
- 看不懂策略类为什么要实现某些方法。

关键点：

- 定义了 `calculate_indicators()` 和 `select_stocks()` 两个核心抽象方法。
- `analyze_stock()` 提供了一层通用分析流程。

### `strategy/strategy_registry.py`

定位：策略注册中心。

什么时候读它：

- 想知道策略是怎么被动态发现的。
- 想知道 Web/CLI 为什么不手动 new 每个策略类。

关键点：

- 自动扫描 `strategy/` 目录。
- 找出所有继承 `BaseStrategy` 的类并实例化。
- 读取 `strategy_params.yaml` 把参数注入策略实例。

### `strategy/bowl_rebound.py`

定位：碗底反弹策略实现。

什么时候读它：

- 想理解碗底策略的具体选股规则。
- 调整 `N / M / J_VAL / CAP / duokong_pct / short_pct` 等参数逻辑。

### `strategy/b1_case_analyzer.py`

定位：B1 形态分析策略实现。

什么时候读它：

- 想理解锚点、突破、回踩、买点这套 B1 规则。
- 调整 B1 参数与匹配窗口。

### `strategy/b2_strategy.py`

定位：B2 规则扫描和相关图形匹配能力。

什么时候读它：

- 想理解 B2 突破策略。
- 处理 B2 规则扫描、图形库、相似度打分相关逻辑。

---

## 4. 数据与工具层关键文件

### `utils/csv_manager.py`

定位：本地 CSV 读写与股票数据访问入口。

什么时候读它：

- 排查某只股票数据为什么读取异常。
- 理解 CSV 的数据顺序和字段。
- 想优化批量读写性能。

关键点：

- 项目大量业务最终都依赖它读股票历史数据。
- Web 图表、CLI 选股、数据状态检查都会经过它。

### `utils/akshare_fetcher.py`

定位：行情抓取器。

什么时候读它：

- 数据更新失败。
- 想知道 `daily_update()` 实际做了什么。
- 想调抓取策略或失败处理逻辑。

### `utils/technical.py`

定位：技术指标计算工具。

什么时候读它：

- 指标结果不对。
- 想改 MA / KDJ / MACD / 知行多空线 / 短期趋势线计算方式。

关键点：

- Web 图表和部分策略逻辑都依赖这里。
- `calculate_zhixing_trend()` 是短期趋势线与知行多空线的重要来源。

### `utils/dingtalk_notifier.py`

定位：钉钉消息发送。

什么时候读它：

- 钉钉推送失败。
- 想改通知格式。

---

## 5. Web 后端阅读指南

### `web/backend/main.py`

定位：FastAPI 应用装配入口。

什么时候读它：

- Web 服务启动失败。
- 想知道目前有哪些后端接口模块被挂载。

关键点：

- CORS 在这里配置。
- 所有 router 在这里注册。
- 前端构建产物 `dist` 也在这里挂载。

### `web/backend/routers/kline.py`

定位：K 线和行情面板接口。

适合解决的问题：

- 详情页 K 线不显示。
- 迷你走势图异常。
- 某个股票价格面板字段缺失。

### `web/backend/routers/stock.py`

定位：首页股票列表接口。

适合解决的问题：

- 分页错误。
- 搜索逻辑不符合预期。
- 首页某列字段不正确。

### `web/backend/routers/strategy.py`

定位：策略结果和缓存相关接口。

适合解决的问题：

- 首页为什么没有策略结果。
- 缓存状态为什么显示缺失、过期、部分可用。
- 手动重建为什么失败。

### `web/backend/routers/update.py`

定位：数据更新接口。

适合解决的问题：

- 更新页的进度流为什么不动。
- 数据状态卡片为什么不对。

### `web/backend/routers/config_api.py`

定位：策略配置接口。

适合解决的问题：

- 设置页为什么读不到参数。
- 更新参数后没有落盘。

### `web/backend/routers/backtest.py`

定位：回测接口占位。

适合解决的问题：

- 想确认回测为什么返回 501。

### `web/backend/services/data_service.py`

定位：数据状态与数据更新服务。

适合解决的问题：

- 数据状态如何计算。
- 为什么更新接口用 SSE。

阅读重点：

- `get_data_status()`
- `run_data_update()`

### `web/backend/services/kline_service.py`

定位：K 线与技术指标服务。

适合解决的问题：

- 图表数据与价格面板数据从哪里来。
- 指标为什么是这些字段名。

阅读重点：

- `get_kline()`
- `get_stock_price_info()`
- `get_mini_kline()`

注意：

- 这里目前默认处理日线序列。
- 接口层虽支持 `weekly` 参数，但 service 还没有完整周线聚合逻辑。

### `web/backend/services/strategy_service.py`

定位：Web 策略结果核心服务。

这是当前 Web 后端最值得精读的文件。

适合解决的问题：

- Web 结果是怎么生成的。
- 首页读的策略结果从哪里来。
- 缓存状态如何判断。
- SSE 重建是怎么推送事件的。

阅读重点：

- `_STRATEGY_REBUILD_STATE`
- `_scan_strategy()`
- `build_strategy_result_snapshot()`
- `get_strategy_cache_status()`
- `stream_strategy_cache_rebuild()`
- `run_strategy()`

注意：

- 当前它既管理扫描、缓存、SSE、配置，又承担结果读取，职责偏重。
- 后续接 SQLite 时，优先拆 repository 层会更稳。

---

## 6. Web 前端阅读指南

### `web/frontend/src/router/index.ts`

定位：前端页面路由入口。

什么时候读它：

- 想知道系统当前有哪些页面。
- 想新增结果页或其他新页面。

### `web/frontend/src/api/index.ts`

定位：统一 API 访问层。

什么时候读它：

- 新增接口。
- 统一修改 baseURL、超时、请求方式。

### `web/frontend/src/views/HomeView.vue`

定位：当前首页。

适合解决的问题：

- 首页表格数据怎么来的。
- 为什么策略结果和股票列表要二次合并。
- 为什么首页可以手动重建并看到实时命中。

阅读重点：

- `loadData()`
- `loadStrategySignals()`
- `loadCacheStatus()`
- `startStrategyRebuild()`

注意：

- 这是当前最重的页面。
- 后续规划里，这部分职责应迁移到独立策略结果页。

### `web/frontend/src/views/StockDetail.vue`

定位：股票详情页。

适合解决的问题：

- 详情页的 K 线、右侧价格面板、策略命中卡片是怎么拼出来的。
- 短期趋势线和知行多空线开关从哪里控制。

阅读重点：

- `loadAll()`
- `loadSignals()`
- `onPeriodChange()`

注意：

- 当前详情页会请求全量策略结果再按 code 过滤。
- 这属于后续应优化的点。

### `web/frontend/src/views/UpdateView.vue`

定位：数据更新页。

适合解决的问题：

- 板块状态卡片怎么来的。
- 更新进度条和日志为什么这样变化。

阅读重点：

- `loadStatus()`
- `startUpdate()`

### `web/frontend/src/views/SettingsView.vue`

定位：策略参数设置页。

什么时候读它：

- 调整 Web 端参数配置 UI。
- 想知道参数元数据如何映射为表单控件。

### `web/frontend/src/components/KlineChart.vue`

定位：主 K 线图组件。

适合解决的问题：

- 图表为何显示 4 个 panel。
- 指标序列如何映射到 ECharts。
- 策略箭头标记为什么出现在主图上。

阅读重点：

- `renderChart()`
- `signalMarks` 构造
- `grid / xAxis / yAxis / series` 配置

注意：

- 当前组件自己拉 K 线数据。
- 如果后续做更复杂的页面组合，可以考虑让父组件取数，图表只渲染。

### `web/frontend/src/components/StockTable.vue`

定位：首页表格组件。

适合解决的问题：

- 列表列定义在哪里。
- 分页和排序事件是怎么往外抛的。

### `web/frontend/src/components/MiniKline.vue`

定位：缩略 K 线组件。

适合解决的问题：

- 为什么首页每行都有小图。
- 为什么列表页请求数比较多。

注意：

- 每行一个请求的模式在大数据量时会放大请求数。

### `web/frontend/src/components/StockInfoPanel.vue`

定位：详情页右侧信息面板。

适合解决的问题：

- 价格、涨跌、均线、KDJ 面板内容从哪里展示。

这个组件本身比较简单，属于展示层终点。

---

## 7. 按需求类型定位修改入口

如果你的任务是下面这些类型，可以直接从对应文件入手。

### A. 改策略规则

先读：

- `strategy/base_strategy.py`
- 对应策略文件：`bowl_rebound.py` / `b1_case_analyzer.py` / `b2_strategy.py`
- `config/strategy_params.yaml`

### B. 改 CLI 执行流程

先读：

- `main.py`
- `quant_system.py`

### C. 改首页展示

先读：

- `web/frontend/src/views/HomeView.vue`
- `web/frontend/src/components/StockTable.vue`
- `web/backend/routers/stock.py`
- `web/backend/services/strategy_service.py`

### D. 改详情页图表或指标

先读：

- `web/frontend/src/views/StockDetail.vue`
- `web/frontend/src/components/KlineChart.vue`
- `web/backend/services/kline_service.py`
- `utils/technical.py`

### E. 改更新页流程

先读：

- `web/frontend/src/views/UpdateView.vue`
- `web/backend/routers/update.py`
- `web/backend/services/data_service.py`

### F. 改策略缓存与结果读取

先读：

- `web/backend/routers/strategy.py`
- `web/backend/services/strategy_service.py`
- `data/web_strategy_results.json`

### G. 做下一阶段 SQLite 改造

先读：

- `docs/WEB_INTERFACE_PLAN.md`
- `web/backend/services/strategy_service.py`
- `web/backend/routers/strategy.py`
- `web/backend/routers/update.py`

---

## 8. 当前最值得优先理解的 5 个文件

如果时间有限，最优先读这 5 个文件：

1. `quant_system.py`
2. `web/backend/services/strategy_service.py`
3. `web/backend/services/kline_service.py`
4. `web/frontend/src/views/HomeView.vue`
5. `web/frontend/src/components/KlineChart.vue`

原因：

- 它们分别代表调度、策略结果、图表数据、首页业务和图表渲染五个核心中枢。

---

## 9. 新人接手时的常见误区

### 误区 1：以为 Web 结果接口会实时跑策略

实际不是。

- 当前 `run_strategy()` 在 Web 语义上主要是“读快照”。
- 真正的重建入口是 `build_strategy_result_snapshot()` 和 `stream_strategy_cache_rebuild()`。

### 误区 2：以为首页表格已经是最终结果工作台

实际不是。

- 当前首页是 MVP 阶段的综合页。
- 后续规划中它会收缩职责。

### 误区 3：以为 Web 端已经完全数据库化

实际不是。

- 结果缓存当前仍以 JSON 文件为主。
- SQLite 仍属于下一阶段重点。

### 误区 4：以为周线已经完整实现

实际不是。

- 路由和页面已经有周线入口。
- 但后端 K 线 service 还没有完整做周线聚合。

---

## 10. 结语

这份手册的核心目标不是提供面面俱到的设计文档，而是让维护者能快速回答三个问题：

1. 这个功能归谁管。
2. 我应该先看哪个文件。
3. 改一处逻辑时还要联动哪些文件。

如果配合 [docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md](docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md) 一起阅读，基本可以在较短时间内建立对整个项目的执行链路和 Web 结构的完整认知。
