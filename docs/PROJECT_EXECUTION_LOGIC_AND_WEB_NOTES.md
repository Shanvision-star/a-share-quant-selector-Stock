# A股量化选股系统全景理解与 Web 关键代码注释

> 本文档基于当前仓库代码、现有 Web 规划文档和实际运行结果整理。
> 目标不是重复写需求，而是把“这个项目现在到底怎么跑、关键代码各自负责什么、Web 端为什么这样设计”讲清楚。

---

## 1. 文档目的

本文档解决四个问题：

1. 项目整体是做什么的。
2. CLI 与 Web 两条执行链路是如何工作的。
3. 当前项目里最关键的代码文件分别承担什么职责。
4. Web 端当前已经实现了什么、哪里是下一阶段改造重点。

说明：

- 本文档以“代码注释版说明书”的方式组织内容。
- 这里的“注释”主要体现在对关键文件、关键函数、关键数据流的解释，不等同于直接往源码里加大量中文注释。
- 当前最值得优先理解的是 Web 端，因为它已经不是空壳，而是一个可运行的 MVP。

---

## 2. 项目一句话概述

这是一个基于 A 股历史行情数据的量化选股系统。它通过本地 CSV 数据、策略引擎、技术指标计算和通知/展示层，把“每日更新数据 -> 扫描策略 -> 输出候选股票 -> 在 Web 上查看图表和结果”串成一条完整链路。

从代码现状看，项目有两条主要使用方式：

1. CLI 模式：用于批处理、定时任务、全流程运行、钉钉通知、文件导出。
2. Web 模式：用于查看股票列表、K 线图、技术指标、策略命中结果、数据更新状态。

---

## 3. 当前架构分层

可以把项目拆成 6 层理解：

```text
展示层
├─ CLI: main.py
└─ Web: FastAPI + Vue 3 + Element Plus + ECharts

路由/接口层
├─ web/backend/routers/*.py
└─ web/frontend/src/router + src/api

业务服务层
├─ web/backend/services/data_service.py
├─ web/backend/services/kline_service.py
└─ web/backend/services/strategy_service.py

策略引擎层
├─ strategy/base_strategy.py
├─ strategy/strategy_registry.py
├─ strategy/bowl_rebound.py
├─ strategy/b1_case_analyzer.py
└─ strategy/b2_strategy.py

数据访问层
├─ utils/csv_manager.py
├─ utils/technical.py
└─ utils/akshare_fetcher.py

存储层
├─ data/**/*.csv
├─ data/web_strategy_results.json
└─ 规划中: data/web_strategy_cache.db
```

这个分层的核心要点是：

- CLI 和 Web 不是两套完全独立系统，它们共用策略层、数据层和技术指标层。
- Web 端目前不是实时逐次跑策略，而是以“离线缓存快照”思路读取策略结果。
- 当前 Web 结果缓存的核心载体还是 JSON 文件，而不是数据库。

---

## 4. 当前项目需求主线

结合代码与 [docs/WEB_INTERFACE_PLAN.md](docs/WEB_INTERFACE_PLAN.md)，当前项目的主线不是“继续堆页面”，而是把下面三条线打通：

1. 数据更新完成后，自动生成当天的策略缓存结果。
2. Web 端从首页附属展示升级为正式结果工作台。
3. 把当前 JSON 结果缓存逐步升级到 SQLite，补齐历史查询和运行记录。

换句话说，项目已经过了“能不能做页面”的阶段，现在更关注：

- 结果如何生产
- 结果如何缓存
- 结果如何展示
- 结果如何回看

---

## 5. 当前运行现状

基于本次实际运行和接口测试，当前仓库状态可以概括为：

- Python 虚拟环境可用。
- 关键依赖已安装：akshare、fastapi、uvicorn、pandas、sse-starlette。
- 本地 CSV 数据存在，数量约 5157 只股票。
- 数据状态接口可返回最新交易日，当前样本显示最新日期为 2026-04-10。
- Web API 可以启动并正常响应健康检查、数据状态、股票详情、K 线数据接口。
- `data/web_strategy_results.json` 当前可能不存在，因此策略结果接口会返回“缓存缺失”，这是预期行为，不是接口代码本身崩溃。

这说明：

- Web 底层框架是能工作的。
- 当前主要短板不在“服务起不来”，而在“策略结果缓存还没有被正式生成和持久化管理”。

---

## 6. CLI 执行逻辑详解

CLI 主入口在 `main.py`，核心调度在 `quant_system.py`。

### 6.1 CLI 主流程

当执行如下命令时：

```bash
python main.py run
```

整体流程是：

```text
main.py
  -> 解析命令行参数
  -> 初始化 QuantSystem
  -> 检查交易日/收盘时间
  -> 执行数据更新
  -> 执行策略扫描
  -> 导出文件
  -> 发送钉钉通知
```

### 6.2 `main.py` 的作用

文件：`main.py`

它负责三件事：

1. 作为统一命令行入口解析命令。
2. 在执行前做环境和时间判断。
3. 把具体业务委托给 `QuantSystem`。

可以把它理解成“命令分发器”，而不是策略本体。

### 6.3 `quant_system.py` 的作用

文件：`quant_system.py`

它是整个 CLI 模式下的总调度器，负责：

- 加载 YAML 配置。
- 初始化 CSV 管理器和 AKShare 抓取器。
- 初始化钉钉通知器。
- 初始化策略注册中心。
- 在数据更新、选股、导出、通知之间组织顺序。

这个类的定位很明确：

- 它不是某一个具体策略。
- 它也不是底层数据访问层。
- 它负责把多个模块编排成一条业务流水线。

### 6.4 CLI 模式的设计特点

- 适合批量任务与定时任务。
- 输出面向“执行结果”，而不是“交互体验”。
- 更接近离线生产链路。
- Web 端很多能力，实际上都可以视为从 CLI 这套逻辑里拆出来的在线版视图。

---

## 7. Web 执行逻辑详解

Web 模式是当前最需要理解的一部分。

它的主链路是：

```text
浏览器页面
  -> Vue Router 路由切换
  -> API 层发请求
  -> FastAPI Router 接口收请求
  -> Service 层组织业务逻辑
  -> CSV / JSON / 技术指标 / 策略引擎
  -> 返回 JSON 或 SSE 流
  -> 前端页面更新表格 / 图表 / 进度条
```

### 7.1 Web 后端主入口

文件：`web/backend/main.py`

这个文件的职责：

- 创建 FastAPI 应用。
- 配置 CORS。
- 注册所有业务路由。
- 在生产环境挂载前端构建产物。

它的重要意义在于：

- 把 Web 后端变成一个清晰的 API 服务。
- 通过 `app.include_router(...)` 把不同业务拆到不同 router 文件中。
- 通过静态文件挂载把前后端发布整合到一个服务入口。

### 7.2 Web 路由结构

当前前端路由在 `web/frontend/src/router/index.ts`，包括：

- `/`：首页
- `/stocks/:code`：股票详情页
- `/update`：数据更新页
- `/settings`：配置页
- `/backtest`：回测页占位

这说明当前前端结构已经具备“结果查看 + 详情分析 + 更新管理 + 参数配置”的基本骨架。

### 7.3 Web 后端接口分工

当前后端 router 的职责划分比较清晰：

- `routers/kline.py`：K 线、价格面板、迷你 K 线。
- `routers/stock.py`：股票列表分页查询。
- `routers/strategy.py`：策略结果、缓存状态、缓存重建 SSE。
- `routers/update.py`：数据更新 SSE 和数据状态。
- `routers/config_api.py`：策略参数读取和更新。
- `routers/backtest.py`：回测接口占位。

这套接口结构已经说明项目不是“把所有逻辑写在一个大接口里”，而是按照业务边界做了基础拆分。

---

## 8. Web 后端关键代码注释

本节重点解释 Web 后端的关键文件和关键逻辑。

### 8.1 `web/backend/main.py`

角色：FastAPI 入口。

关键含义：

- `project_root = Path(__file__).resolve().parents[2]`
  - 作用是把项目根目录加入 `sys.path`，保证后面可以直接导入顶层模块。
- `app = FastAPI(...)`
  - 这里定义的是整个 Web 后端应用实例。
- `CORSMiddleware`
  - 开发阶段允许全部来源访问，方便前端本地调试。
- `app.include_router(...)`
  - 这里是业务装配点，决定哪些接口真正对外暴露。
- `app.mount(...)`
  - 如果前端已构建，会把 Vue 的 `dist` 目录作为静态站点挂载。

可以把这个文件理解为：Web 服务的“总开关”和“装配台”。

### 8.2 `web/backend/routers/kline.py`

角色：图表和行情相关接口。

关键逻辑：

- `/api/kline/{code}`
  - 提供主图数据。
  - 参数校验已经写在 Query 上，`limit` 只能在 30 到 1000 之间。
  - `period` 接口层允许 `daily|weekly`，但当前 service 实现里还没有真正做周线聚合。
- `/api/stock/price/{code}`
  - 提供右侧价格信息面板。
- `/api/stock/mini-kline/{code}`
  - 提供首页表格里的迷你走势。

这部分的设计是正确的：

- 主 K 线、右侧价格面板、迷你走势是三类不同粒度的数据。
- 它们被拆成不同接口，避免一个接口返回过多无关字段。

### 8.3 `web/backend/routers/stock.py`

角色：股票列表接口。

关键逻辑：

- 分页、搜索、基础行情摘要都在这个接口里完成。
- 返回的数据不是完整 K 线，只是列表页需要的摘要字段。
- 搜索时支持股票代码和股票名称模糊匹配。

这说明当前首页表格不是直接把所有 CSV 全量发给前端，而是先做服务端分页。

### 8.4 `web/backend/routers/strategy.py`

角色：策略缓存与结果读取接口。

关键逻辑：

- `GET /api/strategy/results`
  - 用于读取策略结果。
  - 当前调用的是 `run_strategy()`，它本质上是“读取离线缓存”，不是实时重新执行策略。
- `GET /api/strategy/cache/status`
  - 用于判断缓存是否可用、是否过期、是否缺失某个策略组。
- `POST /api/strategy/cache/rebuild`
  - 通过 SSE 返回重建进度。

这说明 Web 端当前采用的不是“实时算结果”，而是“先批量生成快照，再供页面消费”。

### 8.5 `web/backend/routers/update.py`

角色：数据更新接口。

关键逻辑：

- `POST /api/update`
  - 触发 AKShare 数据更新。
  - 返回的是 SSE 流而不是一次性 JSON。
- `GET /api/data/status`
  - 读取当前数据是否新鲜。

它的业务定位很明确：

- 这个页面关注的是“原始行情数据有没有更新”。
- 还没有升级成“更新 + 自动重建策略缓存”的统一作业页。

### 8.6 `web/backend/services/data_service.py`

角色：数据状态和数据更新服务。

关键函数含义：

- `get_data_status()`
  - 抽样检查各板块股票数据的最新日期。
  - 不是逐只股票全量检查，而是抽样估算整体新鲜度。
  - 这样做是为了速度更快，适合页面刷新。
- `run_data_update()`
  - 把同步的 `fetcher.daily_update()` 包装成异步 SSE 输出。
  - 通过 `ThreadPoolExecutor` 避免阻塞事件循环。

这段逻辑的业务含义是：

- Web 接口要保留“可流式更新进度”的体验。
- 但底层抓数逻辑仍然是同步的，因此需要线程池桥接。

### 8.7 `web/backend/services/kline_service.py`

角色：K 线与技术指标服务。

这是 Web 图表体验的核心文件之一。

关键逻辑：

- `get_kline(code, period, limit)`
  - 从 CSV 中读取数据。
  - 当前 CSV 是倒序存储，最新一天在前。
  - 先在倒序数据上计算技术指标，再翻转成升序返回给前端图表。
  - 返回内容包括：
    - OHLC K 线
    - MA5/10/20/60
    - K/D/J
    - 短期趋势线
    - 知行多空线
    - DIF/DEA/MACD
- `get_stock_price_info(code)`
  - 专门给详情页右侧面板用。
  - 只提取最新行情 + 涨跌额/涨跌幅 + 均线/KDJ摘要。
- `get_mini_kline(code, days)`
  - 专门给首页每行缩略图使用。

这段代码有两个很重要的设计点：

1. 图表指标计算在后端完成，前端只负责渲染。
2. 后端会把倒序行情转换成前端图表需要的时间正序。

当前限制：

- `period` 参数虽然存在，但当前实现没有真正做周线转换，仍主要使用日线数据。

### 8.8 `web/backend/services/strategy_service.py`

角色：Web 策略结果服务。

这是当前 Web 端最关键的后端文件。

它做的不是单一事情，而是同时承担：

- Web 策略结果快照生成
- JSON 缓存读写
- 内存缓存
- 缓存状态检查
- SSE 重建进度输出
- 参数配置读取/更新

建议把它拆成 4 块理解。

#### A. 状态和缓存

关键对象：

- `_STRATEGY_CACHE`
  - 进程内缓存，TTL 300 秒。
  - 作用是避免高频重复读取 JSON 文件。
- `_STRATEGY_REBUILD_STATE`
  - 记录当前是否正在重建、进度多少、扫描到哪个策略、命中多少条。
  - 作用是给 Web 页面显示重建状态，并防止并发重复重建。

这部分代码说明当前服务采用的是“单进程内状态机”思路，而不是数据库任务队列。

#### B. 扫描与快照生成

关键函数：

- `_analyze_stock_for_strategy()`
  - 单股、单策略分析函数。
  - 会过滤退市/ST/数据不足的股票。
- `_scan_strategy()`
  - 对某个策略并发扫描所有股票。
  - 通过线程池并发执行。
- `build_strategy_result_snapshot()`
  - Web 策略结果的生产总入口。
  - 会加载策略、读取全部股票、逐策略扫描、实时回调进度、最后写入 `data/web_strategy_results.json`。

这里要特别理解：

- 这个函数相当于“离线构建器”。
- 页面读取结果时，不是临时现算，而是优先依赖它生成的快照。

#### C. 缓存状态与结果读取

关键函数：

- `_read_strategy_snapshot()`
  - 读取当前 JSON 快照。
- `get_strategy_cache_status()`
  - 判断缓存是否存在、是否过期、是否缺某个策略组。
- `run_strategy()`
  - 对前端来说它叫“获取策略结果”。
  - 但它不会直接跑策略，而是：
    1. 先查内存缓存
    2. 再读 JSON 快照
    3. 根据日期和策略过滤返回结果

这说明当前 Web 结果接口是“快照读取接口”，不是“实时计算接口”。

#### D. SSE 重建

关键函数：

- `stream_strategy_cache_rebuild()`
  - 把重建过程包装成 SSE 事件流。
  - 用后台线程执行重建，并把事件放入队列供异步生成器不断往前端输出。

这部分代码的实际含义是：

- 后端允许前端实时看到“开始扫描 -> 扫描中 -> 新命中 -> 扫描完成”的过程。
- 这是当前 Web 端最接近“实时任务观测”的能力。

#### E. 当前结构问题

这个文件功能太多，已经有明显膨胀趋势：

- 既管扫描，又管缓存，又管状态，又管配置。
- 后续如果上 SQLite，最好优先拆出 repository 层和 sqlite service 层。

---

## 9. Web 前端关键代码注释

本节重点解释 Vue 前端的页面和组件关系。

### 9.1 `web/frontend/src/api/index.ts`

角色：前端统一 API 访问层。

关键含义：

- 所有请求都通过 axios 实例走 `/api` 前缀。
- 页面层不直接手写每个 URL，而是调用封装函数，例如：
  - `getStockList()`
  - `getKline()`
  - `getStrategyResults()`
  - `getDataStatus()`

这样做的好处是：

- 页面更干净。
- 接口变动时只需要改一层。
- 更适合后续补充参数类型和统一错误处理。

### 9.2 `web/frontend/src/router/index.ts`

角色：前端页面入口表。

关键含义：

- 定义了当前 Web 站点能进入哪些页面。
- 当前还没有 `/strategy-results`，说明独立策略结果工作台还未落地。

换句话说，路由文件本身就是“项目功能边界”的缩影。

### 9.3 `web/frontend/src/views/HomeView.vue`

角色：当前首页，兼顾股票列表、策略切换、缓存状态和重建控制。

这是当前 Web 前端最“重”的页面。

关键逻辑：

- `loadData()`
  - 先拉股票分页列表。
  - 列表本身不包含策略命中信息，只包含基础行情摘要。
- `loadStrategySignals()`
  - 再单独拉当前策略结果。
  - 然后用 `code` 把策略结果合并进表格数据。
- `loadCacheStatus()`
  - 读取缓存状态卡片信息。
- `startStrategyRebuild()`
  - 直接用 `fetch()` 消费 SSE 流。
  - 手动解析 `event:` 和 `data:` 片段。
  - 把日志、进度、实时命中分别落到不同状态里。

这个页面的实际职责是三合一：

1. 股票列表页
2. 策略缓存控制台
3. 重建实时观测页

这也是为什么它会显得偏重。根据规划文档，后续这部分应该拆到独立的策略结果页中。

### 9.4 `web/frontend/src/views/StockDetail.vue`

角色：股票详情页。

关键逻辑：

- `loadAll(code)`
  - 并发拉取 K 线数据和价格面板数据。
- `loadSignals(code)`
  - 读取所有策略结果，再按股票代码筛选出当前股票的命中记录。
- `showShortTermTrend` / `showBullBearLine`
  - 控制主图里短期趋势线和知行多空线的显示。

这个页面目前已经有不错的分析能力：

- 主图 K 线
- 日/周切换入口
- 主图均线
- 短期趋势线开关
- 知行多空线开关
- 策略命中标注
- 右侧价格面板

当前值得注意的地方：

1. `StockDetail.vue` 自己请求了一次 `getKline()`。
2. `KlineChart.vue` 内部又会再次请求 `getKline()`。

这意味着当前详情页存在重复取数，可以后续优化为：

- 页面层取数
- 图表组件只负责渲染

### 9.5 `web/frontend/src/views/UpdateView.vue`

角色：数据管理页。

关键逻辑：

- 页面加载时调用 `getDataStatus()`，展示各板块是否新鲜。
- 点击更新按钮后，使用 `fetch('/api/update')` 读取 SSE。
- 用进度条 + 日志区展示更新过程。

这个页面的业务定位目前还比较单纯：

- 只负责行情数据更新。
- 还没有接入“更新后自动重建策略缓存”的统一作业模型。

### 9.6 `web/frontend/src/components/KlineChart.vue`

角色：主 K 线图组件。

这是当前 Web 前端最关键的可视化组件。

关键逻辑：

- 组件内部调用 `getKline()` 获取数据。
- 把后端返回的 bars 和 indicators 转成 ECharts 需要的 series。
- 用四个 grid 组成多面板图：
  - 主图 K 线 + 均线 + 趋势线
  - 成交量
  - KDJ
  - MACD
- 通过 `signals` 渲染策略命中箭头。
- 通过 legend 的 `selected` 控制短期趋势线和知行多空线显示状态。

这个组件已经有比较完整的 TradingView 式 K 线面板结构，说明图表层基础能力已经不弱。

当前值得注意的点：

- 它既是“图表组件”，又承担了“自己拉数据”的职责。
- 如果未来要做更复杂的结果页，最好逐步把“拉数据”和“渲染图表”分离。

### 9.7 `web/frontend/src/components/StockTable.vue`

角色：首页股票表格组件。

关键逻辑：

- 展示基础字段：代码、名称、价格、涨跌幅、市值、日期。
- 每行嵌一个 `MiniKline` 组件显示缩略走势。
- 提供分页和排序事件发射能力。

当前含义：

- 这是一个偏展示型组件。
- 业务合并逻辑并不在它这里，而在 HomeView 里。

### 9.8 `web/frontend/src/components/MiniKline.vue`

角色：列表页缩略图组件。

关键逻辑：

- 每个组件挂载时单独请求一次 `/api/stock/mini-kline/{code}`。
- 使用 ECharts SVG 渲染很小的一段 K 线。

这能带来更直观的列表页体验，但也意味着：

- 一页 50 行时，可能触发 50 次迷你图请求。
- 这是一个明显的性能关注点。

### 9.9 `web/frontend/src/components/StockInfoPanel.vue`

角色：详情页右侧信息面板。

关键逻辑：

- 纯展示组件。
- 不承担数据加载。
- 只负责把 `priceInfo` 结构渲染成价格、成交、均线、KDJ信息块。

这是一个比较干净的组件设计，职责边界明确。

---

## 10. 端到端数据流说明

本节把几个最重要的页面交互串起来看。

### 10.1 首页数据流

```text
HomeView.vue
  -> getStockList()
  -> 后端 stock router
  -> CSVManager 读取分页股票摘要
  -> 返回股票列表

HomeView.vue
  -> getStrategyResults()
  -> strategy_service.run_strategy()
  -> 读 JSON 快照 / 内存缓存
  -> 返回命中结果

HomeView.vue
  -> 用 code 把策略结果合并进表格
```

这个设计的含义是：首页的“股票列表”和“策略结果”并不是一个接口返回的，而是前端二次拼装。

### 10.2 策略重建流

```text
HomeView.vue 点击重建
  -> POST /api/strategy/cache/rebuild
  -> strategy_service.stream_strategy_cache_rebuild()
  -> 后台线程执行 build_strategy_result_snapshot()
  -> 并发扫描全部股票
  -> 事件队列不断产出 start/progress/signal/complete
  -> 前端实时更新进度条、日志和新增命中
```

这是当前最重要的长任务链路。

### 10.3 股票详情页数据流

```text
StockDetail.vue
  -> getStockPrice(code)
  -> 右侧面板数据

StockDetail.vue / KlineChart.vue
  -> getKline(code)
  -> bars + indicators
  -> ECharts 渲染主图/KDJ/MACD

StockDetail.vue
  -> getStrategyResults({ strategy: 'all' })
  -> 前端按 code 过滤出当前股票命中信号
  -> 用 signals 传给 KlineChart 标记箭头
```

这个设计说明详情页目前是“先拿全量策略结果，再筛当前股票”，因此后续优化方向非常明确：

- 改成按 `code + date` 精确查询。

### 10.4 数据更新页数据流

```text
UpdateView.vue 点击更新
  -> POST /api/update
  -> data_service.run_data_update()
  -> 线程池执行 fetcher.daily_update()
  -> SSE 返回 start/progress/complete
  -> 前端更新进度条和日志
```

这里还没接入策略结果重建，因此当前系统还缺一条真正的一体化作业链路。

---

## 11. 当前 Web 端的关键限制与真实问题

这一节非常重要，因为它回答的是“项目下一步为什么要那样改”。

### 11.1 结果缓存仍以 JSON 为主

当前策略结果主要来自：

- `data/web_strategy_results.json`

问题：

- 不适合做历史查询。
- 不适合做运行记录查询。
- 不适合做多维筛选。
- 不适合做更复杂的结果页。

### 11.2 更新流和重建流是分开的

当前：

- `/api/update` 只更新原始数据。
- `/api/strategy/cache/rebuild` 只重建策略结果缓存。

这意味着用户仍需要把两个动作串起来理解，而不是一次作业完成。

### 11.3 首页承担职责过重

当前首页同时负责：

- 股票列表
- 策略切换
- 缓存状态
- 重建控制
- 实时命中
- 重建日志

这会让页面越来越重，也会阻碍后续结果页的独立演进。

### 11.4 详情页存在重复请求

当前：

- `StockDetail.vue` 请求 K 线。
- `KlineChart.vue` 又请求一次 K 线。

这属于结构上可以优化的地方。

### 11.5 详情页信号查询方式偏粗

当前：

- 先读全部策略结果
- 再前端按股票代码过滤

这在结果量变大后会越来越低效。

### 11.6 周线入口已存在，但后端尚未真正聚合周线

前端已提供日 K / 周 K 切换入口，后端接口也接受 `weekly` 参数。

但当前 `kline_service.py` 还没有真正把日线聚合成周线，因此这部分仍属于“接口语义预留先于能力完整实现”。

### 11.7 列表页迷你图请求较多

`MiniKline.vue` 每行单独发请求，这在大页码或频繁翻页时会增加前后端压力。

---

## 12. 当前项目最核心的理解结论

可以把当前系统理解成这样：

### 12.1 它已经不是原型空壳

因为以下能力已经存在：

- CLI 全流程执行
- Web API 服务
- 首页列表
- 详情图表
- 数据更新 SSE
- 策略缓存重建 SSE
- 技术指标可视化
- 策略参数配置接口

### 12.2 它也还不是完整平台

因为以下能力尚未成型：

- SQLite 正式结果存储
- 历史结果查询
- 运行记录归档
- 统一作业流
- 独立策略结果工作台

### 12.3 当前阶段最重要的不是继续造新页面

而是把“数据更新 -> 结果重建 -> 结果查询 -> 运行回看”做成一条真正闭环。

这也是为什么 `docs/WEB_INTERFACE_PLAN.md` 把后续阶段重点定义为：

- Phase 6：数据持久化与作业编排
- Phase 7：正式结果工作台
- Phase 8：历史查询与运行观测

---

## 13. 推荐阅读顺序

如果后续要继续开发或交接给其他代理，建议按下面顺序读代码：

1. `main.py`
   - 先理解 CLI 总入口。
2. `quant_system.py`
   - 理解离线执行链路。
3. `strategy/base_strategy.py`
   - 理解策略接口抽象。
4. `strategy/strategy_registry.py`
   - 理解策略如何被动态加载。
5. `web/backend/main.py`
   - 理解 Web 后端装配方式。
6. `web/backend/services/kline_service.py`
   - 理解图表数据是怎么从 CSV 变成指标序列的。
7. `web/backend/services/strategy_service.py`
   - 理解 Web 结果快照、缓存状态、重建 SSE。
8. `web/frontend/src/views/HomeView.vue`
   - 理解当前首页为什么重。
9. `web/frontend/src/views/StockDetail.vue`
   - 理解详情页的数据组合方式。
10. `web/frontend/src/components/KlineChart.vue`
   - 理解图表层如何消费指标。
11. `docs/WEB_INTERFACE_PLAN.md`
   - 理解下一阶段架构演进方向。

---

## 14. 对后续开发最有价值的改造方向

结合当前代码状态，优先级应当是：

1. 把 `web_strategy_results.json` 升级为 SQLite 结果存储。
2. 为 update 和 rebuild 统一引入 `run_id`。
3. 新增独立策略结果页，承接正式结果、运行记录、历史查询。
4. 让详情页按 `code + date` 精确查信号，而不是全量拉结果。
5. 逐步把 `KlineChart.vue` 从“数据获取 + 图表渲染二合一”调整为更纯粹的展示组件。

---

## 15. 总结

当前项目的真实状态，可以用一句话概括：

**它已经具备可运行的量化选股 Web MVP，但下一阶段的关键不是继续补零散界面，而是把结果生产、结果持久化、结果展示和运行观测打通。**

如果站在代码角度看，当前最关键的 Web 资产有三个：

1. `kline_service.py`：负责图表数据和技术指标的可靠输出。
2. `strategy_service.py`：负责 Web 结果快照、缓存状态和 SSE 重建。
3. `HomeView.vue + StockDetail.vue + KlineChart.vue`：构成当前前端主体验。

如果站在演进角度看，下一阶段最关键的不是“再做一个页面”，而是：

1. 统一作业流
2. 引入 SQLite
3. 建独立结果工作台

这三件事完成后，这个系统才会从“有页面的量化工具”升级为“有正式结果工作台的策略平台雏形”。
