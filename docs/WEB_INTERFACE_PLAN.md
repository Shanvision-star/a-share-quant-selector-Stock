# A股量化选股系统 — Web 界面开发计划

> 参考目标：TradingView（https://www.tradingview.com/symbols/NASDAQ-AAPL/）  
> 核心诉求：在网页上直观查看**策略选出的股票 K 线**、指标、以及未来的回测结果。

---

## 1. 文档目标

本文件用于统一说明以下内容：

1. 当前项目已经实现到什么程度。
2. 哪些能力已经在代码中落地，不应重复实现。
3. 下一阶段应该优先开发什么，以及为什么这样排。
4. 后端数据模型、API 契约、页面职责和验收标准。
5. 哪些内容属于本轮范围，哪些内容明确不在本轮范围。

本轮规划的三条主线必须视为同一阶段的一体化工程，而不是三个彼此独立的小需求：

1. 把数据更新流程和策略缓存重建串成一次完整作业。
2. 把策略运行结果从首页附属日志区升级成独立结果页。
3. 把当天缓存从 JSON 升级到 SQLite，并补齐历史日期查询和运行记录。

---

## 2. 页面结构

```
/                         首页 — 策略选股结果总览
/stocks/:code             股票详情页 — K线 + 指标 + 策略标注
/update                   数据管理页 — 手动触发更新、查看进度
/settings                 参数配置页 — 策略参数调整
/backtest (预留)           回测页 — 选定股票区间回测（后续实现）
```

---

## 3. 当前代码基线说明

本节用于明确告诉后续实现代理：哪些基础已经有了，不要重复搭建。

### 3.1 后端关键文件

- `web/backend/main.py`
  - FastAPI 入口。
  - 已注册现有路由。
- `web/backend/routers/strategy.py`
  - 已提供策略结果、缓存状态、缓存重建接口。
- `web/backend/routers/update.py`
  - 已提供数据更新 SSE 接口。
- `web/backend/services/strategy_service.py`
  - 已负责策略扫描、结果快照构建、缓存状态判断、缓存重建 SSE。
- `web/backend/services/data_service.py`
  - 已负责数据状态和数据更新流程。
- `web/backend/services/kline_service.py`
  - 已返回 K 线、均线、KDJ、MACD、短期趋势线、知行多空线等数据。

### 3.2 前端关键文件

- `web/frontend/src/views/HomeView.vue`
  - 已接入缓存控制台、策略切换、实时命中、执行日志。
- `web/frontend/src/views/StockDetail.vue`
  - 已接入主 K 线图、策略信号、主图线开关。
- `web/frontend/src/views/UpdateView.vue`
  - 已接入数据更新 SSE。
- `web/frontend/src/components/KlineChart.vue`
  - 已支持主图均线、短期趋势线、知行多空线、成交量、KDJ、MACD、信号箭头。
- `web/frontend/src/components/StockTable.vue`
  - 已存在基础分页表格，可作为结果页表格的基础壳。
- `web/frontend/src/api/index.ts`
  - 已封装基础 API。

### 3.3 当前缓存现状

- 当前 Web 结果缓存文件：`data/web_strategy_results.json`
- 当前策略结果读取逻辑仍以 JSON 文件快照为中心。
- 当前缓存状态接口与重建接口已可用。

### 3.4 当前项目真实阶段

如果用新的阶段定义，当前更准确的判断是：

- 原始 Phase 1 到 Phase 5：基本已完成或接近完成。
- 当前处于：**Phase 5.5 到 Phase 6 的过渡期**。
- 下一阶段重点：数据持久化、作业编排、结果工作台、历史查询、运行观测。

---

## 4. 新阶段划分

| 阶段 | 名称 | 目标 |
|------|------|------|
| Phase 6 | 数据持久化与作业编排 | 引入 SQLite，统一 update + rebuild 作业链路 |
| Phase 7 | 正式结果工作台 | 增加独立结果页，首页职责收缩 |
| Phase 8 | 历史查询与运行观测 | 支持历史日期、运行记录、单次作业回看 |
| Phase 9 | 性能与部署增强 | 批量写入、事件聚合、部署与运维增强 |

说明：后续开发不再沿用从零创建 Web 项目的阶段命名，统一使用以上阶段定义。

---

## 5. 产品目标

### 5.1 交互目标

- 用户在一次操作中完成“数据更新 + 当天缓存生成”。
- 用户在独立结果页中查看正式命中结果，而不是只看首页日志区。
- 用户可以按日期、策略、股票代码、关键词等条件查询结果。
- 用户可以查看最近运行记录与单次作业详情。
- 用户可以在任务执行时实时看到新增命中，并在完成后查看正式结果表。

### 5.2 性能目标

- 提升结果查询速度，减少对单个 JSON 文件的依赖。
- 提升长任务期间的进度透明度和结果可见性。
- 通过批量写入、事件聚合和轻量缓存降低 I/O 开销。
- 为未来的增量扫描、股票池剪枝、结果导出和回测联动提供结构化基础。

### 5.3 长远目标

- 把系统从“有页面可看”的工具升级为“可长期维护的策略工作台”。
- 为导出报表、回测联动、告警中心、移动端查询打下统一数据基础。
- 为多实例部署、任务协调和平台化扩展预留空间。

---

## 6. 本轮范围与非范围

### 6.1 本轮范围

- 更新完成后自动生成当天策略缓存。
- 新增独立结果页。
- 将 Web 结果缓存从 JSON 升级到 SQLite。
- 支持历史日期查询。
- 支持运行记录与事件归档。
- 统一 update 与 rebuild 的作业流。
- 重写与同步相关文档，保证后续代理理解一致。

### 6.2 明确不在本轮范围

- 回测模块完整实现。
- 用户系统、权限系统。
- 移动端实现。
- B1/B2 图形库特征缓存迁移到 SQLite。
- 分布式任务系统。
- 多实例锁协调方案。

说明：本轮重点是结果如何生产、如何展示、如何回看，不是一次性做成平台全家桶。

---

## 7. 页面结构（更新版）

```text
/                         首页总览
/stocks/:code             股票详情页
/update                   统一作业页（更新 + 自动重建）
/strategy-results         策略结果工作台（新增）
/settings                 参数配置页
/backtest                 回测页（预留）
```

---

## 8. 页面职责详细设计

### 8.1 首页

保留：

- 当日缓存状态摘要
- 今日命中统计
- 策略摘要
- 跳转到结果页和更新页的入口

移除：

- 实时命中主列表
- 执行日志主面板
- 手动重建主控制区

定位：

- 首页只负责总览和导航。
- 不再承担正式结果和任务观察的主职责。

### 8.2 股票详情页

当前已具备：

- 主 K 线图
- 日 K / 周 K 切换
- MA5 / MA10 / MA20 / MA60
- 策略信号箭头
- 成交量
- KDJ
- MACD
- 短期趋势线开关
- 知行多空线开关

下一步优化：

- 信号查询改为按 code 和 date 精确过滤。
- 避免全量拉取全部策略结果再前端筛选。

### 8.3 数据更新页

当前已具备：

- 显示各板块数据状态
- 一键更新
- SSE 进度展示

下一步改造：

- 升级为统一作业页。
- 同时显示更新阶段和自动重建阶段。
- 作业完成后提供跳转到结果页的入口。

### 8.4 策略结果页（新增）

这是本轮的核心新增页面。

建议区块：

1. 缓存状态卡
2. 重建控制区
3. 实时命中表
4. 正式结果表
5. 历史查询面板
6. 运行记录列表
7. 单次作业详情抽屉或侧栏

建议筛选项：

- 交易日期
- 策略类型
- 股票代码
- 股票名称关键词
- J 值范围
- 相似度范围
- 命中分类

定位：

- 正式结果工作台
- 后续导出、统计、回放、回测联动都应从此页扩展

### 8.5 设置页

本轮不作为重点改造页面，但应保留现有策略参数调节能力。

建议后续预留：

- 参数版本号
- 最近一次参数修改记录
- 作业记录和参数快照关联

### 8.6 回测页

继续保留为预留模块，本轮不实现完整回测逻辑。

---

## 9. 当前技术架构

### 9.1 后端

- 框架：FastAPI
- 数据源：CSV
- 当前缓存：JSON 快照
- 进度推送：SSE
- 核心服务：`kline_service.py`、`data_service.py`、`strategy_service.py`

### 9.2 前端

- 框架：Vue 3 + Vite
- UI：Element Plus
- 图表：ECharts
- 状态管理：Pinia
- HTTP：axios

### 9.3 当前部署思路

- Nginx 反向代理
- FastAPI 提供 `/api/*`
- 前端静态产物提供页面访问

---

## 10. 本轮技术路线

### 10.1 核心决策

1. 不推翻现有 FastAPI + Vue 结构。
2. 不重复搭建现有页面和基础 API。
3. 只把 Web 结果缓存、历史查询和运行记录迁到 SQLite。
4. 保留 B1/B2 图形特征缓存的现有文件缓存方案。
5. 统一作业流，以 run_id 串联 update 和 rebuild。
6. 首页收缩职责，结果页承担正式结果展示。

### 10.2 为什么这样做

- 当前瓶颈主要在结果承载方式和作业链路，而不是在 Web 基础框架本身。
- SQLite 可以显著改善结果查询、历史查询和运行记录查询。
- 不把 B1/B2 图形特征缓存一起迁移，可以控制改造范围和风险。
- 统一作业流能显著提升用户感知速度与系统可理解性。

---

## 11. SQLite 设计

### 11.1 数据库文件

建议路径：

- `data/web_strategy_cache.db`

### 11.2 初始化建议

建议 SQLite PRAGMA：

- `journal_mode = WAL`
- `synchronous = NORMAL`
- `temp_store = MEMORY`

### 11.3 设计原则

- 一条命中记录一行。
- 尽量使用扁平字段做筛选和排序。
- 保留原始信号 JSON 字段用于兼容不同策略。
- 作业记录、事件记录、正式结果和缓存摘要分表存储。
- 快照状态查询不要依赖每次扫全量结果表。

### 11.4 核心表

#### 表 1：`strategy_runs`

用途：记录每次作业的总体状态。

建议字段：

- `run_id TEXT PRIMARY KEY`
- `run_type TEXT NOT NULL`
- `trade_date TEXT NOT NULL`
- `strategy_filter TEXT NOT NULL`
- `status TEXT NOT NULL`
- `started_at TEXT NOT NULL`
- `completed_at TEXT`
- `stage TEXT`
- `message TEXT`
- `processed_count INTEGER DEFAULT 0`
- `total_count INTEGER DEFAULT 0`
- `matched_count INTEGER DEFAULT 0`
- `error_message TEXT`
- `host TEXT`

建议取值：

- `run_type`: `update_and_rebuild`、`rebuild_only`、`update_only`
- `status`: `queued`、`running`、`done`、`error`、`cancelled`

#### 表 2：`strategy_run_events`

用途：记录作业过程中的事件流。

建议字段：

- `event_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `run_id TEXT NOT NULL`
- `event_type TEXT NOT NULL`
- `strategy_filter TEXT`
- `strategy_name TEXT`
- `progress INTEGER`
- `message TEXT`
- `payload_json TEXT`
- `created_at TEXT NOT NULL`

典型事件类型：

- `job_start`
- `update_start`
- `update_progress`
- `update_complete`
- `rebuild_start`
- `strategy_start`
- `progress`
- `signal`
- `strategy_complete`
- `job_complete`
- `error`

#### 表 3：`strategy_results`

用途：存储正式结果。

建议字段：

- `result_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `run_id TEXT NOT NULL`
- `trade_date TEXT NOT NULL`
- `strategy_filter TEXT NOT NULL`
- `strategy_name TEXT NOT NULL`
- `code TEXT NOT NULL`
- `name TEXT`
- `category TEXT`
- `signal_date TEXT`
- `trigger_price REAL`
- `close REAL`
- `j_value REAL`
- `similarity_score REAL`
- `reason TEXT`
- `signal_json TEXT`
- `created_at TEXT NOT NULL`

说明：

- 每条命中一行。
- 用扁平字段支撑查询和展示。
- 用 `signal_json` 保留完整策略信号结构。

#### 表 4：`strategy_cache_snapshots`

用途：存储某次运行生成的缓存摘要。

建议字段：

- `snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `run_id TEXT NOT NULL`
- `trade_date TEXT NOT NULL`
- `strategy_filter TEXT NOT NULL`
- `generated_at TEXT NOT NULL`
- `total_results INTEGER DEFAULT 0`
- `available_groups_json TEXT`
- `group_totals_json TEXT`
- `summary_json TEXT`

作用：

- 给首页和结果页快速展示缓存状态。
- 避免为拿到摘要再全表扫描结果。

#### 可选表：`app_meta`

用途：记录 schema_version、初始化时间和迁移标志。

### 11.5 索引建议

建议至少建立以下索引：

- `trade_date`
- `trade_date + strategy_filter`
- `code`
- `run_id`
- `started_at`
- `created_at`

建议唯一约束维度：

- `run_id + strategy_filter + code + signal_date + category`

---

## 12. API 契约规划

### 12.1 当前已存在接口

- `GET /api/strategy/results`
- `GET /api/strategy/cache/status`
- `POST /api/strategy/cache/rebuild`
- `GET /api/kline/:code`
- `GET /api/stock/list`
- `GET /api/stock/price/:code`
- `GET /api/stock/mini-kline/:code`
- `GET /api/data/status`
- `POST /api/update`
- `GET /api/config`
- `POST /api/config`
- `GET /api/health`

### 12.2 保留并升级的接口

#### `GET /api/strategy/results`

用途：

- 返回指定日期的正式结果。
- 保留 `strategy` 和 `date` 参数语义。
- 读取层从 JSON 切换到 SQLite，过渡期允许回退 JSON。

#### `GET /api/strategy/cache/status`

用途：

- 返回指定日期与策略范围的缓存状态。

建议新增字段：

- `last_run_id`
- `latest_run_status`
- `source`
- `exists`
- `available_groups`
- `missing_groups`
- `group_totals`

#### `POST /api/strategy/cache/rebuild`

用途：

- 继续保留手动重建。
- 改为复用统一作业模型。
- `run_type = rebuild_only`

#### `POST /api/update`

用途：

- 从只更新数据升级为更新数据 + 自动重建当天缓存。
- `run_type = update_and_rebuild`

### 12.3 新增接口

#### `GET /api/strategy/results/history`

用途：历史结果分页查询。

建议参数：

- `strategy`
- `start_date`
- `end_date`
- `page`
- `per_page`
- `code`
- `keyword`
- `min_j_value`
- `max_j_value`
- `min_similarity`
- `max_similarity`

#### `GET /api/strategy/runs`

用途：查询最近运行记录。

建议参数：

- `run_type`
- `status`
- `date`
- `page`
- `per_page`

#### `GET /api/strategy/runs/{run_id}`

用途：查询单次作业摘要。

#### `GET /api/strategy/runs/{run_id}/events`

用途：查询单次作业事件归档。

### 12.4 可选但非本轮必做接口

- `GET /api/strategy/results/export`

说明：导出功能建议在 SQLite 和正式结果页稳定后再做。

---

## 13. 统一作业流设计

### 13.1 作业定义

统一作业 = 一次完整的当天结果生产过程：

1. 启动数据更新
2. 更新完成
3. 自动进入策略缓存重建
4. 写入正式结果、快照、运行记录
5. 输出最终状态

### 13.2 run_id

每次作业都生成唯一 `run_id`，用于串联：

- 更新阶段
- 重建阶段
- 运行记录
- 事件归档
- 正式结果
- 快照摘要

### 13.3 SSE 事件结构

统一建议字段：

- `event`
- `data.run_id`
- `data.stage`
- `data.status`
- `data.progress`
- `data.message`
- `data.processed`
- `data.total`
- `data.matched`
- `data.items`

说明：

- `signal` 事件使用 `items` 承载新增命中列表。
- 其他事件统一描述阶段状态。

### 13.4 推荐事件顺序

1. `job_start`
2. `update_start`
3. `update_progress`
4. `update_complete`
5. `rebuild_start`
6. `strategy_start`
7. `progress`
8. `signal`
9. `strategy_complete`
10. `job_complete`
11. `error`

---

## 14. 前端结果页与交互规划

### 14.1 结果页区块建议

#### 区块 A：缓存状态卡

展示：

- 当前日期
- 缓存状态
- 数据来源
- 最新生成时间
- 可用策略分组
- 今日命中数

#### 区块 B：重建控制区

提供：

- 重建全部策略
- 重建当前策略
- 刷新状态

#### 区块 C：实时命中表

展示：

- 股票代码
- 股票名称
- 策略名称
- 分类
- 信号日期
- 触发价

行为：

- SSE 收到 `signal` 事件后插入顶部
- 完成后可同步刷新正式结果表

#### 区块 D：正式结果表

建议列：

- 股票代码
- 股票名称
- 策略名称
- 分类
- 信号日期
- 触发价
- J 值
- 相似度
- 原因
- 最新价
- 涨跌幅

#### 区块 E：历史查询面板

建议筛选：

- 日期范围
- 策略
- 代码/名称关键词
- J 值范围
- 相似度范围

#### 区块 F：运行记录列表

建议列：

- 开始时间
- 结束时间
- 作业类型
- 策略范围
- 扫描数
- 命中数
- 状态
- 错误摘要

### 14.2 组件建议

建议新增：

- `StrategyResultsView.vue`
- `StrategyResultsTable.vue`
- `StrategyRunList.vue`
- `StrategyRunDetailDrawer.vue`
- `CacheStatusCard.vue`
- `RebuildControlPanel.vue`

建议复用：

- 现有 `StockTable.vue` 的基础表格结构
- 现有 `KlineChart.vue`
- 现有 `MiniKline.vue`

---

## 15. 详细实施顺序

### Phase 6A：落 SQLite 基础层

目标：

- 建数据库文件与 schema
- 增加 repository 层
- 实现 JSON 与 SQLite 双写
- 建查询与快照读取能力

建议新增后端文件：

- `web/backend/services/sqlite_service.py`
- `web/backend/services/strategy_result_repository.py`

说明：

- 不建议把大量 SQL 直接继续堆在 `strategy_service.py` 中。
- 应尽量把扫描编排和存储读写职责拆开。

### Phase 6B：统一作业流

目标：

- `POST /api/update` 变成更新 + 自动重建
- 为整次作业生成 `run_id`
- SSE 输出统一作业事件流
- 写入 `strategy_runs` 和 `strategy_run_events`

### Phase 7A：建设正式结果页

目标：

- 新增 `/strategy-results`
- 把首页日志与实时命中迁出
- 首页回归总览角色
- 更新页变成统一作业页

### Phase 7B：历史查询与运行观测

目标：

- 新增历史结果查询
- 新增最近运行列表
- 新增单次作业详情
- 优化股票详情页的精确结果读取

### Phase 8：性能与稳定性收尾

目标：

- 批量写事务
- 事件聚合
- 轻量查询缓存
- 一致性校验
- 错误兜底
- 回归测试

---

## 16. 并行开发建议

### 可并行

后端 A 线：

- SQLite schema
- repository
- 双写与读切换

后端 B 线：

- 统一作业流
- run_id
- 运行记录

前端线：

- 结果页页面骨架
- 更新页升级
- 首页摘要化调整

### 必须串行

1. 先确定 SQLite 数据模型
2. 再调整后端读写逻辑
3. 再让前端全面切换新接口

说明：前端可以提前做页面骨架，但 API 契约必须在数据模型稳定后冻结。

---

## 17. 风险与规避

### 风险 1：JSON 与 SQLite 双写不一致

规避：

- 增加一致性校验脚本
- 先比总数，再比抽样记录
- 双写过渡期保留 JSON 回退能力

### 风险 2：SQLite 锁竞争

规避：

- WAL 模式
- 批量事务
- signal 事件聚合写入

### 风险 3：首页、更新页、结果页职责重叠

规避：

- 首页只做总览
- 更新页只看统一作业过程
- 结果页只看正式结果与历史回看

### 风险 4：详情页继续全量拉结果

规避：

- 按 code 和 date 精确查询
- 不要默认拉全部结果再前端过滤

### 风险 5：执行速度提升不明显

说明：

- 本轮主要提升结果查询速度和用户感知速度
- 真正提升扫描耗时需要后续做增量扫描和股票池剪枝

---

## 18. 验收标准

### 18.1 后端验收

- `POST /api/update` 能一次完成更新和自动重建
- 每次作业都有唯一 `run_id`
- `GET /api/strategy/cache/status` 能返回最新缓存状态与最近作业信息
- `GET /api/strategy/results` 能返回当天正式结果
- `GET /api/strategy/results/history` 能按日期范围分页查询
- `GET /api/strategy/runs` 能返回最近作业列表
- `GET /api/strategy/runs/{run_id}` 能返回作业摘要
- `GET /api/strategy/runs/{run_id}/events` 能返回事件归档

### 18.2 前端验收

- 首页只保留摘要和入口，不再承担主日志区
- 更新页能展示统一作业全过程
- 结果页能展示正式结果表、实时命中表、运行记录
- 作业运行中，结果页能实时展示新增命中
- 作业完成后，正式结果表能自动刷新
- 股票详情页继续保留：
  - 日 K / 周 K
  - 策略信号标记
  - 短期趋势线开关
  - 知行多空线开关

### 18.3 数据一致性验收

- 同日同策略下，SQLite 与 JSON 总数一致
- 抽样记录字段一致
- 快照统计与结果表统计一致

### 18.4 性能验收

- 当天结果查询优于原始 JSON 全量读取方案
- 历史结果与运行记录查询稳定
- 长任务期间前端进度展示无明显卡顿
- 批量写入不会显著拖慢总任务时间

---

## 19. 给 Claude Opus 的实施指令摘要

如果后续将本项目继续交给 Claude Opus 编码，应该明确以下约束：

1. 不要重复搭建现有 FastAPI 和 Vue 项目骨架。
2. 不要删除已经可用的缓存状态接口与重建 SSE 能力，应在此基础上演进。
3. 不要把首页继续做重，首页应该收缩为总览页。
4. 不要推翻现有 `KlineChart.vue`，它已经支持短期趋势线和知行多空线开关。
5. 不要优先迁移 B1/B2 图形特征缓存到 SQLite，本轮重点是 Web 结果缓存与运行记录。
6. 优先完成：
   - SQLite 结果存储层
   - update + rebuild 统一作业流
   - 独立结果页
   - 历史查询与运行记录
7. 在修改后端时，优先拆出 repository 层，避免继续让 `strategy_service.py` 无限膨胀。
8. 所有新接口和新页面，都必须围绕 `run_id`、`trade_date`、`strategy_filter` 三个核心维度设计。

---

## 20. 长远演进建议

### 20.1 下一轮真正提升扫描速度的方向

当本轮完成后，如需进一步提升真实执行速度，应优先考虑：

- 增量扫描
- 按数据变更过滤未变股票
- 分策略股票池剪枝
- 复用上一轮结果与中间特征

### 20.2 多实例部署预留

当前可以按单实例实现。

如果未来做多实例部署，需要补：

- 文件锁或数据库锁
- `run_id` 对应的 `host` 字段
- 更稳的任务协调机制

### 20.3 后续自然扩展能力

当 SQLite 结果模型与运行记录稳定后，可自然扩展到：

- 导出报表
- 回测联动
- 告警中心
- 移动端结果查询
- 参数快照与运行记录绑定

---

## 21. 结论

当前项目最值得投入的方向，不是继续增加零散页面，而是把“当天结果如何生产、如何展示、如何回看”这条主线做完整。

因此，以下三项必须合并理解并一起推进：

1. 更新完成后自动生成当天缓存
2. 独立策略结果页承载正式结果
3. SQLite 统一承载缓存、历史查询与运行记录

完成这三项后，系统会从“已有页面和接口的 Web MVP”升级为“具备正式结果工作台、统一作业流和历史运行观测能力的策略平台雏形”。

---

*文档更新时间：2026-04-12*