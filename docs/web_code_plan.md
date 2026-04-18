# A股量化选股 Web 图表工作台实施计划

本文档用于把现有 Web 前端升级为更接近 TradingView 工作台体验的可执行实施方案。目标不是复刻 TradingView 本身，而是借鉴其模块化布局、时间周期切换、指标叠加、观察列表和快速图表加载思路，在当前项目现有的 FastAPI + Vue 3 + ECharts 架构上完成一套适合 A 股量化选股场景的图表工作台。

---

## 1. 项目目标

本阶段重点解决四类问题：

1. 当前 K 线图只能较被动地展示最近一段数据，难以快速查看更长周期历史。
2. 前端已有“周 K”按钮，但后端没有真正提供周线聚合数据，切换并不成立。
3. 页面存在重复取数、逐条迷你图请求、详情页拉全量策略结果再过滤等慢链路，导致页面容易转圈。
4. 现有主页承担了太多职责，缺少一个专门用于图表分析和策略联动的工作台页面。

本计划的最终目标如下：

- 提供一个 TradingView 风格的图表工作台页面。
- 支持日线、周线，后续预留月线、年线。
- 主图支持多条叠加指标，副图支持成交量、KDJ、MACD 以及后续扩展指标。
- 能快速看多日 K 线，默认秒开，历史数据按需追加加载。
- 页面数据链路从“重复读 CSV + 重算指标 + 整包返回”改成“聚合层 + 缓存层 + 单次请求 + 纯渲染组件”。

---

## 2. 参考来源的理解

### 2.1 TradingView 参考含义

参考 https://www.tradingview.com/ 的核心不是视觉皮肤，而是以下交互和结构能力：

- 图表是页面主角色，不是附属组件。
- 用户可以快速切换时间周期和观察区间。
- 指标以主图叠加和副图面板两种方式组织。
- 图表周围存在辅助模块，例如观察列表、价格面板、市场摘要、相关标的。
- 首屏优先打开最近窗口，之后再逐步展开更多历史数据，保证主观加载速度。

### 2.2 你提供的标注图所表达的页面意图

你确认后的目标页面不是当前详情页的小改版，而是一个“图表工作台模式”的新页面或现有详情页的大幅升级。该模式包含以下区块：

1. 顶部控制台：显示目标日期、缓存日期、生成时间、当前策略、覆盖分组、命中数，并允许选择策略执行日期。
2. 左上策略与股票列表：用于选择当前主图展示的股票，同时保留代码、名称、最新价、涨跌幅、市值、日期和迷你走势。
3. 中央主图区域：主图使用 K 线图展示，可点击切换日线、周线，后续预留月线、年线。
4. 主图叠加指标工具条：用于选择 MA、BBI、短期趋势线、知行多空线等叠加指标。
5. 下方 1 到 4 个副图区域：用于显示成交量、KDJ、MACD 以及后续扩展指标。
6. 右侧观察区：显示策略对应股票、市场观察股票、相似行业股票或板块股票，作为次级导航和对比入口。

---

## 3. 目标页面模式

建议把其中一个页面明确升级为图表工作台模式，页面名称可暂定为 `StrategyWorkbenchView`。如果短期不新增页面，也可以先用现有股票详情页承接该模式，再逐步把主页瘦身。

### 3.1 页面职责

该页面只负责三件事：

- 股票图表分析
- 策略信号联动
- 快速切换周期与指标

不再承担首页那种缓存控制台、全市场表格主入口和大量非图表逻辑。

### 3.2 页面布局草案

#### A. 顶部控制台区

展示内容：

- 目标日期
- 缓存日期
- 生成时间
- 当前策略
- 覆盖分组
- 命中数
- 策略执行日期选择器
- 刷新状态按钮
- 重建策略缓存按钮

对应建议：

- 保留现有缓存状态能力，但从首页迁移到图表工作台或结果工作台顶部。
- 日期选择器必须能够驱动策略结果和观察列表更新。

#### B. 左侧股票列表区

展示内容：

- 代码
- 名称
- 最新价
- 涨跌幅
- 市值
- 日期
- 迷你走势

交互要求：

- 点击某支股票后，中间主图切换到该股票。
- 点击不同策略标签后，左侧列表内容联动更新。
- 迷你走势图改为批量接口返回，不能再每行单独请求。

#### C. 中央主图区

展示内容：

- K 线主图
- 日线 / 周线切换
- 后续预留月线 / 年线
- 时间范围切换，例如 3M、6M、1Y、3Y、5Y、MAX
- 策略信号标记

交互要求：

- 默认先展示最近 240 到 320 根 bars，优先保证打开快。
- 拖到左边界时可继续加载更早历史数据。
- 切换日线和周线时，图表不闪烁整页重载。

#### D. 主图叠加指标工具条

首批建议支持：

- MA5 / MA10 / MA20 / MA60
- BBI
- 短期趋势线
- 知行多空线

后续可扩展：

- 布林带
- 策略特征线
- 自定义策略线

#### E. 副图区

建议副图支持动态组合，而不是固定写死布局。首批支持：

- 副图 1：成交量
- 副图 2：KDJ
- 副图 3：MACD
- 副图 4：扩展指标占位区

要求：

- 用户可决定哪些副图显示。
- 不显示的副图不占空间。
- 副图与主图共享时间轴和十字线联动。

#### F. 右侧观察区

展示内容：

- 当前策略命中股票
- 市场观察股票
- 相似行业 / 板块股票
- 后续可扩展的 watchlist

交互要求：

- 点击右侧任一标的，可直接切换主图。
- 同板块股票可作为后续“相对强弱对比”入口。

---

## 4. 当前代码现状分析

### 4.1 已有能力

当前系统已经具备以下基础：

- [web/frontend/src/components/KlineChart.vue](../web/frontend/src/components/KlineChart.vue) 已能渲染主图、成交量、KDJ、MACD。
- [web/frontend/src/views/StockDetail.vue](../web/frontend/src/views/StockDetail.vue) 已有日 K / 周 K 切换 UI。
- [web/backend/routers/kline.py](../web/backend/routers/kline.py) 已有 `/api/kline/{code}` 接口，并接受 `period` 参数。
- [web/backend/services/kline_service.py](../web/backend/services/kline_service.py) 已能输出 OHLCV、MA、KDJ、知行双线、MACD。
- [web/frontend/src/components/StockInfoPanel.vue](../web/frontend/src/components/StockInfoPanel.vue) 已经把 K、D、J 分开展示。

### 4.2 当前主要问题

#### 1. 周线切换只是表面支持

虽然接口和页面都有 `weekly` 参数，但 [web/backend/services/kline_service.py](../web/backend/services/kline_service.py) 实际完全没有做周线聚合，返回的仍然是日线数据。

#### 2. KlineChart 自己拉数据，父组件也在拉数据

[web/frontend/src/views/StockDetail.vue](../web/frontend/src/views/StockDetail.vue) 会调用 `getKline`，而 [web/frontend/src/components/KlineChart.vue](../web/frontend/src/components/KlineChart.vue) 内部也会再调用 `getKline`。这会导致：

- period 切换时重复请求
- signals 变化时重复请求
- 开关指标时也可能重复请求

#### 3. 首页迷你图是逐行请求

[web/frontend/src/components/MiniKline.vue](../web/frontend/src/components/MiniKline.vue) 每一行单独请求 `/stock/mini-kline/{code}`，当首页展示 50 行甚至更多时，请求数会膨胀。

#### 4. 详情页策略信号是拉全量结果再前端过滤

[web/frontend/src/views/StockDetail.vue](../web/frontend/src/views/StockDetail.vue) 通过 `/api/strategy/results?strategy=all` 拉全量结果，再用 `code` 过滤当前股票，数据量越大越慢。

#### 5. 后端每次都重新读 CSV 和重算指标

[utils/csv_manager.py](../utils/csv_manager.py) 每次直接 `pd.read_csv`，没有 DataFrame 缓存。当前图表接口每次都要：

- 重新读 CSV
- 截取数据
- 重算 KDJ、MA、MACD、知行双线
- 重新反转时间顺序

这正是页面容易转圈的根本原因之一。

### 4.3 对当前计划的整体理解与可行性结论

结合现有代码结构和你补充的判断，这份计划整体上是可行的，而且问题定位基本准确。

#### 可行性判断

1. 周线切换无效的问题定位准确。
  当前问题并不是前端按钮缺失，而是后端没有真正提供聚合后的周线 bars，因此通过新增后端聚合层可以直接解决这一问题。

2. 重复取数链路判断准确。
  [web/frontend/src/views/StockDetail.vue](../web/frontend/src/views/StockDetail.vue) 和 [web/frontend/src/components/KlineChart.vue](../web/frontend/src/components/KlineChart.vue) 同时请求 K 线数据，属于明显的职责重叠，既影响性能，也会让页面状态管理变得混乱。

3. 首页迷你图逐行请求是典型瓶颈。
  对于股票表格这种高频列表，批量 mini-kline 接口是非常必要的优化项，实施成本低，收益明显，属于优先级很高的改造。

4. CSV 读取和指标重算确实是当前主要性能瓶颈之一。
  当前项目每次图表请求都会读 CSV、截取数据、重算指标、再把整包返回给前端。这种模式在多次切换 timeframe、翻页或切股票时会放大延迟，引入缓存能显著提速。

5. 计划的阶段划分是合理的。
  先冻结接口和页面职责，再处理聚合与缓存，再重构前端交互和模块边界，这个顺序能有效减少返工，是一条清晰可执行的路径。

#### 结论

该计划以用户体验和性能优化为核心，能够较完整地覆盖当前代码的真实问题，并且给出了从后端到前端逐步落地的路径，因此属于高可行性的实施方案。

---

## 5. 实施总方案

本次升级建议分为五个阶段推进。

### Phase 1: 冻结目标页面和接口契约

#### 目标

- 明确一个页面采用图表工作台模式。
- 冻结图表接口和页面状态结构，避免前后端反复返工。

#### 工作内容

1. 确定采用图表工作台模式的页面：
  - 方案 A：新增 `StrategyWorkbenchView.vue`
  - 方案 B：现有 `StockDetail.vue` 扩展为工作台模式

2. 统一图表接口参数：

- `code`
- `timeframe`，替代当前语义不清的 `period`
- `range`，例如 `3m`、`6m`、`1y`、`max`
- `bars_back`
- `end_date`
- `include_indicators`
- `load_more_cursor`

3. 统一图表接口返回结构：

```json
{
  "code": "000001",
  "name": "平安银行",
  "meta": {
   "timeframe": "daily",
   "available_bars": 1600,
   "returned_bars": 280,
   "has_more_history": true,
   "next_cursor": "2024-01-05",
   "source": "csv-cache"
  },
  "bars": [],
  "indicators": {},
  "signals": []
}
```

#### 涉及文件

- [web/backend/routers/kline.py](../web/backend/routers/kline.py)
- [web/frontend/src/api/index.ts](../web/frontend/src/api/index.ts)

---

### Phase 2: 建立真实的时间周期聚合层

#### 目标

真正实现周线切换，并为月线、年线预留空间。

#### 工作内容

1. 在后端新增时间周期聚合函数：

- 日线聚合为周线
- 日线聚合为月线
- 日线聚合为年线

2. 聚合规则：

- open：周期第一根
- close：周期最后一根
- high：周期内最高
- low：周期内最低
- volume：求和
- amount：求和
- turnover：按业务规则定义，可求和或平均
- market_cap：取周期最后一根或按业务逻辑定义

3. 所有指标在聚合后的 bars 上重新计算：

- KDJ
- MA
- MACD
- 知行短期趋势线
- 知行多空线
- 后续 BBI

4. 聚合实现建议

当前项目已经大量使用 pandas，并且 [utils/technical.py](../utils/technical.py) 的所有指标函数也都基于 pandas Series / DataFrame 设计，因此第一阶段推荐继续使用 pandas 完成时间聚合，而不是立即引入新的列式计算框架。

推荐实现方式：

- 在 [web/backend/services/kline_service.py](../web/backend/services/kline_service.py) 中抽出独立函数，例如 `aggregate_to_timeframe(df, timeframe)`。
- 将 `date` 转为 DatetimeIndex 后，通过 `resample()` 完成周线、月线、年线聚合。
- 聚合完成后再恢复为普通 DataFrame，并交给现有技术指标函数计算。

参考实现方向：

```python
def aggregate_to_timeframe(data: pd.DataFrame, timeframe: str) -> pd.DataFrame:
  rule_map = {
    'weekly': 'W',
    'monthly': 'M',
    'yearly': 'Y',
  }

  agg_rules = {
    'open': 'first',
    'close': 'last',
    'high': 'max',
    'low': 'min',
    'volume': 'sum',
    'amount': 'sum',
  }

  df = data.copy()
  df['date'] = pd.to_datetime(df['date'])
  df = df.set_index('date').sort_index()
  aggregated = df.resample(rule_map[timeframe]).agg(agg_rules).dropna(subset=['open', 'close'])
  return aggregated.reset_index()
```

关于 polars：

- 从纯计算性能角度看，polars 有潜力。
- 但当前技术指标函数和 CSV 链路均深度依赖 pandas。
- 因此在本阶段直接切换到 polars 的收益，不一定高于迁移成本。

结论：

- Phase 2 先用 pandas 落地聚合逻辑，快速完成真实周线/月线。
- 等缓存和工作台稳定后，再评估是否需要把聚合前处理迁移到 polars。

#### 注意事项

- 不能直接拿日线指标去代表周线指标。
- 周线和月线必须重新生成新的 bars 和指标数组。

#### 涉及文件

- [web/backend/services/kline_service.py](../web/backend/services/kline_service.py)
- [utils/technical.py](../utils/technical.py)

---

### Phase 3: 图表数据链路和缓存提速

#### 目标

让“快速看多日 K 线”成为默认体验，而不是重载等待。

#### 核心方法

##### 方法 1：默认只返回最近窗口

默认首屏返回最近 240 到 320 根 bars，而不是一次返回 1000 根以上。这样可以显著减少：

- CSV 处理量
- 指标计算量
- JSON 体积
- ECharts 首屏渲染负担

##### 方法 2：支持历史按需追加

当用户切换更长区间或拖动到左边界时，再按需加载更老数据，而不是默认全量返回。可用两种方案：

- `bars_back` 递增方案
- `load_more_cursor` 方案

推荐优先采用 `load_more_cursor`，它更适合增量追加。

##### 方法 3：加入三层缓存

建议缓存分为三层：

1. CSV DataFrame 缓存
2. 聚合后 bars 缓存
3. 指标计算结果缓存

推荐实现方式：

- 第一层缓存位于 [utils/csv_manager.py](../utils/csv_manager.py)，按 `code + file_mtime` 缓存 DataFrame。
- 第二层缓存位于 [web/backend/services/kline_service.py](../web/backend/services/kline_service.py)，按 `code + timeframe + bars_back + end_date` 缓存聚合后的 bars。
- 第三层缓存位于图表服务层，按 `code + timeframe + bars_back + include_indicators + file_mtime` 缓存包含指标的完整响应。

短期推荐使用 Python 进程内缓存，例如 `cachetools.LRUCache` 或一个自定义字典缓存；这是因为当前部署形态以单机本地开发和轻量服务为主，引入 Redis 并不是第一阶段的必要条件。

参考方向：

```python
from cachetools import LRUCache

bars_cache = LRUCache(maxsize=256)

def fetch_cached_bars(cache_key, compute_fn):
  if cache_key in bars_cache:
    return bars_cache[cache_key]
  result = compute_fn()
  bars_cache[cache_key] = result
  return result
```

可行性结论：

- 进程内缓存非常适合当前阶段，改造成本低。
- 如果后续切换为多实例部署，再把缓存迁移到 Redis 即可。

缓存键建议至少包含：

- `code`
- `timeframe`
- `bars_back`
- `include_indicators`
- `file_mtime`

##### 方法 4：首页迷你图改批量接口

不要再一个股票请求一次迷你图，而是新增批量接口，例如：

`POST /api/stock/mini-kline/batch`

请求示例：

```json
{
  "codes": ["000001", "000002", "000004"],
  "days": 30
}
```

##### 方法 5：详情页信号改按股票查询

新增接口，例如：

`GET /api/strategy/signals/{code}`

这样详情页只拉当前股票的信号，不再拉全量结果。

##### 方法 6：父层统一请求，子组件纯渲染

当前图表交互性能问题，不只是后端慢，也和前端请求链路重复有关。最佳策略是：

- 父层组件统一请求图表数据。
- 子组件只接收 props 做渲染。
- 指标开关、副图切换、信号显示等纯视图状态，不再重新打接口。

这也是提升“切换股票时响应速度”和“切换日线、周线时体感速度”的关键措施。

##### 方法 7：增量加载而不是整图重取

当用户向左拖动图表查看历史时，优先采用增量追加 bars 的方式，而不是整包重新请求并重绘。这样可以减少：

- 接口体积
- 前端反序列化开销
- ECharts 整图 setOption 的负担

结论：

- 默认最近窗口 + 向左追加历史，是当前项目里“快速看多日 K 线”的最优方案。
- 一次返回全量历史，只适合作为调试手段，不适合作为默认交互。

#### 涉及文件

- [utils/csv_manager.py](../utils/csv_manager.py)
- [web/backend/services/kline_service.py](../web/backend/services/kline_service.py)
- [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py)
- [web/frontend/src/components/MiniKline.vue](../web/frontend/src/components/MiniKline.vue)
- [web/frontend/src/api/index.ts](../web/frontend/src/api/index.ts)

---

### Phase 4: 前端工作台重构

#### 目标

将页面改造成真正的图表工作台，而不是现有详情页的简单图表组件堆叠。

#### 工作内容

##### 1. 改造父子取数模式

目标：`KlineChart.vue` 不再自己请求数据。

改造后：

- 父层页面统一请求图表数据
- 子组件只负责渲染
- 显示开关变化时不再重新请求后端

##### 2. 增加图表工具条

工具条建议包括：

- 时间周期切换：D、W、M、Y
- 时间范围切换：3M、6M、1Y、3Y、5Y、MAX
- 主图叠加指标切换：MA、BBI、短期趋势线、知行多空线
- 副图开关：Volume、KDJ、MACD、扩展指标

##### 3. 副图面板动态布局

当前四个 grid 固定写死，改造后：

- 如果只显示成交量，则只保留一个副图区域
- 如果显示成交量 + KDJ + MACD，则渲染三个副图区域
- 如果将来增加 RSI、布林宽度等，则直接插入额外副图

##### 4. 右侧观察区和同板块区

右侧区域建议支持三类数据源：

- 当前策略命中股票
- 市场观察股票
- 同板块或相似行业股票

该区域点击后可直接切换主图股票。

##### 5. 页面职责解耦原则

在这一阶段，必须坚持“首页轻量，工作台重型”的拆分原则。

首页负责：

- 市场概览
- 策略摘要
- 股票表格
- 批量迷你图

工作台负责：

- 大图 K 线分析
- 周线、月线切换
- 指标叠加
- 副图联动
- 右侧价格信息和观察区

这是保证首屏打开快、分析页面功能深的关键。

#### 涉及文件

- [web/frontend/src/views/StockDetail.vue](../web/frontend/src/views/StockDetail.vue)
- [web/frontend/src/components/KlineChart.vue](../web/frontend/src/components/KlineChart.vue)
- [web/frontend/src/components/StockInfoPanel.vue](../web/frontend/src/components/StockInfoPanel.vue)
- [web/frontend/src/views/HomeView.vue](../web/frontend/src/views/HomeView.vue)

---

### Phase 5: 首页瘦身与职责拆分

#### 目标

降低首页负担，让首页快、轻、可筛选，图表工作台重、深、可分析。

#### 工作内容

首页只保留：

- 市场摘要
- 策略结果摘要
- 股票表格
- 迷你图
- 跳转工作台入口

首页不再承担：

- 大型 K 线工作台
- 多副图联动分析
- 重型图表组件常驻渲染

这样首页转圈会明显减少，用户进入详情工作台时再加载完整图表链路。

---

## 6. KDJ 展示策略说明

针对“代码中的 KDJ 是一个值不是分开的”这一点，必须区分三个层面：

### 6.1 图表接口层

当前图表接口其实已经返回分开的：

- `K`
- `D`
- `J`

因此图表层没有根本性错误。

### 6.2 右侧信息面板层

[web/frontend/src/components/StockInfoPanel.vue](../web/frontend/src/components/StockInfoPanel.vue) 也已经分开展示 K、D、J，应该保留。

### 6.3 策略列表层

当前某些页面只展示 `j_value`，这是策略信号值，不等于图表指标展示错误。后续策略表如果仍然只关心触发条件，可以继续显示 `j_value`；如果要做更完整的技术快照，可新增：

- `k_value`
- `d_value`
- `j_value`

但这不是图表工作台的首要阻塞项。

---

## 7. 需要修改的代码清单

### 后端

1. [web/backend/routers/kline.py](../web/backend/routers/kline.py)
  - 扩展 timeframe、range、bars_back、load_more_cursor 参数
  - 保持旧参数兼容

2. [web/backend/services/kline_service.py](../web/backend/services/kline_service.py)
  - 增加日线到周线、月线的聚合逻辑
  - 增加 bars 元数据 `meta`
  - 增加缓存逻辑
  - 支持按需追加历史数据

3. [utils/csv_manager.py](../utils/csv_manager.py)
  - 增加 DataFrame 内存缓存
  - 基于文件修改时间进行失效

4. [utils/technical.py](../utils/technical.py)
  - 确保所有指标函数适用于聚合后 bars
  - 增加 BBI 等后续扩展指标

5. [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py)
  - 提供按股票代码查询信号的接口能力
  - 为右侧观察区提供策略股票、同板块股票数据

6. 新增批量迷你图接口
  - 批量返回表格迷你走势数据

### 前端

1. [web/frontend/src/api/index.ts](../web/frontend/src/api/index.ts)
  - 扩展图表接口参数
  - 增加批量迷你图 API
  - 增加按股票查询信号 API

2. [web/frontend/src/views/StockDetail.vue](../web/frontend/src/views/StockDetail.vue)
  - 升级为图表工作台父层
  - 增加 timeframe / range / overlay / subpanel 状态
  - 统一请求图表数据

3. [web/frontend/src/components/KlineChart.vue](../web/frontend/src/components/KlineChart.vue)
  - 移除内部 `getKline` 请求
  - 改成纯渲染组件
  - 支持动态副图 grid 布局

4. [web/frontend/src/components/MiniKline.vue](../web/frontend/src/components/MiniKline.vue)
  - 改成消费批量接口数据
  - 避免逐行单请求

5. [web/frontend/src/views/HomeView.vue](../web/frontend/src/views/HomeView.vue)
  - 首页瘦身
  - 保留股票表和轻量摘要
  - 增加跳转图表工作台入口

6. 可新增页面
  - `web/frontend/src/views/StrategyWorkbenchView.vue`

7. 可新增组件
  - `ChartToolbar.vue`
  - `WatchlistPanel.vue`
  - `SubIndicatorPanel.vue`

---

## 8. 实施顺序建议

推荐顺序如下：

1. 先冻结图表接口契约。
2. 再完成后端周线聚合和缓存。
3. 再改前端为父层单次取数模式。
4. 再做工作台页面布局和工具条。
5. 最后做首页瘦身、批量迷你图和观察区扩展。

原因：

- 不先做真实聚合，周线切换无法成立。
- 不先做缓存，快速看多日 K 线仍然会卡。
- 不先改取数模式，前端仍然会重复请求抵消缓存收益。

---

## 9. 验收标准

实施完成后，至少满足以下验收条件：

1. 图表工作台页面具备顶部控制台、左侧股票列表、中间主图、下方副图、右侧观察区五大区域。
2. 主图能切换日线和周线，且周线数据不再与日线完全一致。
3. 主图支持 MA、BBI、短期趋势线、知行多空线等叠加指标切换。
4. 副图支持成交量、KDJ、MACD，并可按需显示或隐藏。
5. 首屏默认打开最近窗口时，页面明显快于当前整包返回方式。
6. 拖到左边界或切换更长范围时，可以继续加载更早历史数据。
7. 首页迷你图请求数明显下降，分页和滚动时不再大面积转圈。
8. 详情页不再通过全量策略结果接口做前端过滤。
9. K、D、J 在图表和右侧面板中保持分离展示。

---

## 10. 本阶段结论

本项目要想实现“像 TradingView 一样快速看多日 K 线、切换周线，并扩展主图与副图指标”，真正要做的不是简单改样式，而是完成以下三个基础工程：

1. 后端时间周期聚合
2. 图表数据缓存和历史按需追加
3. 前端单次请求 + 工作台页面重构

只要这三件事按顺序落地，页面就能从当前“能看图”升级到“能分析、能切换、能扩展、打开快”的状态。

---

## 11. 进一步优化方向与取舍

以下方向值得保留在文档中，但需要区分“当前阶段可直接执行”与“中长期演进”。

### 11.1 数据库替代 CSV

可行性：中高

优势：

- 更适合做区间查询
- 更适合按股票代码和日期精确过滤
- 更适合多用户、多请求并发场景

现实取舍：

- 当前项目所有历史数据链路都围绕 CSV 构建。
- 如果本阶段直接改成 MySQL / PostgreSQL，会明显扩大改造范围。

建议：

- 本阶段先保留 CSV 作为主数据源。
- 优先解决聚合、缓存、批量接口和前端重复请求问题。
- 等图表工作台稳定后，再评估是否迁移到 SQLite / PostgreSQL。

### 11.2 WebSocket 实时推送

可行性：中等

适用场景：

- 实时价格刷新
- 策略信号动态推送
- 多页面共享同一条实时行情流

现实取舍：

- 当前主要痛点是静态历史图表慢，不是实时推送缺失。
- 如果过早引入 WebSocket，会分散主线任务。

建议：

- 当前阶段继续以 HTTP + 按需请求为主。
- 如果后续确实有实时价格和实时信号需求，再追加 WebSocket 层。

### 11.3 Redis 或跨进程缓存

可行性：高，但优先级次于进程内缓存

建议：

- 单机阶段先用内存缓存。
- 多实例或部署到生产后，再升级到 Redis。

---

## 12. 最终建议

你的补充分析和当前计划是一致的，而且能进一步增强执行层面的清晰度。最终建议保持以下优先级：

1. 先完成真实 timeframe 聚合。
2. 再完成 CSV / bars / indicators 三层缓存。
3. 再把前端改成父层一次请求、子层纯渲染。
4. 再实现图表工作台页面布局。
5. 最后再评估数据库替代、WebSocket 推送、polars 等中长期演进项。

这样可以保证每一步都有明确收益，不会在基础性能问题还未解决时就把系统复杂度推得过高。