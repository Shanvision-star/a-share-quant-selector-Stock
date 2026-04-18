# Web 策略重建提速执行方案

本文档用于把“为什么当前 Web 策略执行慢、应该先改什么、哪些先不改、每一步改完如何验收”写成一份可直接执行的方案。

目标不是泛泛而谈，而是给出一条可以按阶段落地的主线：

1. 重写 Web 重建主链路，按股票扫描一次，复用多个策略。
2. 建一份最近 250 根 K 线的轻量缓存，降低高频读取成本。
3. 给 B2 完美匹配增加并发预筛，减少重型分析的覆盖范围。
4. 前端把 SSE 的 `signal` 直接并入主表，让用户在重建过程中就看到结果。
5. 长期再评估把 CSV 主扫描源迁移到 Parquet 或 DuckDB。

---

## 1. 结论先行

当前 Web 端慢，不是单一接口慢，而是主链路结构本身偏低效。

现状可以概括为：

- Web 重建是“按策略扫全市场”，不是“按股票读一次后复用多策略”。
- 每个策略都会重复触发 `read_stock(code)`，造成重复 IO、重复指标计算、重复过滤。
- B2 完美匹配仍以串行为主，且对每只股票直接进入完整分析。
- 前端虽然已经消费 SSE，但 `signal` 只进入 `liveSignals`，主结果表仍然等历史接口返回，导致“后端在跑，主表不动”。

因此本轮优化的核心逻辑不是继续做零散微调，而是把 Web 路径改成与 CLI 更接近的“单股一次读取、多策略复用、结果增量输出”的模型。

---

## 2. 当前瓶颈与代码证据

### 2.1 Web 当前主链路的瓶颈

在 [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py) 中：

- `build_strategy_result_snapshot()` 会先拿到 `all_stocks`，再按 `selected_filters` 循环调用 `_scan_strategy()`。
- `_scan_strategy()` 内部会为当前策略把全市场股票重新提交到线程池。
- `_analyze_stock_for_strategy()` 中每次都会执行 `csv_manager.read_stock(code)`。

这意味着当前 Web 全量重建在逻辑上接近：

```text
for strategy in selected_strategies:
    for stock in all_stocks:
        df = read_stock(stock)
        analyze(strategy, df)
```

如果股票数为 `N`，策略数为 `M`，则核心读取规模接近 `N * M` 次。

### 2.2 CLI 已经有更优模型

在 [quant_system.py](../quant_system.py) 的 `select_stocks()` 中，代码已经明确写出：

```text
执行多策略联合选股（单只股票只读取一次，减少重复IO与重复指标计算）
```

它的执行模型更接近：

```text
for stock in all_stocks:
    df = read_stock(stock)
    for strategy in all_strategies:
        analyze(strategy, df)
```

也就是说，CLI 路径已经证明“单股一次读取，多策略复用”是本项目现成可借鉴的正确方向。

### 2.3 B2 当前仍偏串行重型扫描

在 [strategy/b2_strategy.py](../strategy/b2_strategy.py) 的 `scan_all()` 中：

- 外层直接 `for code in stock_list` 顺序遍历。
- 每只股票立即执行 `cm.read_stock(code)`。
- 之后对该股票依次遍历 `pattern_templates` 做完整分析。

这条链路的问题不是“算法错”，而是“所有股票都直接进入重型分析”。

### 2.4 前端当前没有把 SSE 结果并入主表

在 [web/frontend/src/views/StrategyResultsView.vue](../web/frontend/src/views/StrategyResultsView.vue) 中：

- `startRebuild()` 已经通过 SSE 接收后端事件。
- `handleEvent()` 在收到 `signal` 后，会把数据插入 `liveSignals`。
- 但正式主表 `results` 仍然要等 `loadResults()` 重新请求历史结果。

因此当前用户看到的是：

- 后端实际上已经有实时命中。
- 页面上也确实收到了命中。
- 但主表不跟着更新，导致主观感受仍然像“没结果”。

---

## 3. 本轮优化的总逻辑

### 3.1 核心思想

把当前 Web 扫描主链路从“策略中心型”改成“股票中心型”。

目标流程如下：

```text
加载股票列表
  -> 并发读取单只股票数据
  -> 在同一份 DataFrame 上复用多个策略判断
  -> 命中后立即产出 signal 事件
  -> 同步累积 groups / results / SQLite 批写数据
  -> 前端主表边接收边更新
```

### 3.2 为什么这会变快

提速来源主要有四类：

1. 少读文件：把 `N * M` 次读 CSV 尽量收敛到 `N` 次。
2. 少算指标：同一只股票在同一轮扫描里复用同一份基础数据。
3. 少做重型分析：先用轻量预筛缩小 B2 完整分析范围。
4. 少等最终结果：前端主表改成边收边渲染，而不是等整轮重建结束。

### 3.3 本轮不追求的事情

本轮不追求一次性把整个项目的数据底座推倒重来。

CSV 仍然保留为事实来源，SQLite 仍保留现有结果落库路径，前端页面结构也以当前工作台为基础增量修改，不做整站重写。

---

## 4. 边界定义

## 4.1 本轮明确纳入范围

1. 调整 [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py) 的 Web 重建主链路。
2. 新增或内聚一层“最近 250 bars 轻量缓存”。
3. 调整 [strategy/b2_strategy.py](../strategy/b2_strategy.py) 的 B2 扫描前置预筛流程。
4. 调整 [web/frontend/src/views/StrategyResultsView.vue](../web/frontend/src/views/StrategyResultsView.vue) 的 SSE 主表合并逻辑。
5. 保持现有 API 对外行为基本兼容，优先做内部重构。

## 4.2 本轮明确不纳入范围

1. 不重写现有全部策略类接口。
2. 不替换 [utils/csv_manager.py](../utils/csv_manager.py) 为全新数据层。
3. 不在本轮把 CSV 主扫描源直接迁移到 Parquet 或 DuckDB。
4. 不重构整套前端路由和页面布局。
5. 不调整 SQLite 表结构为全新模型，除非为了兼容本轮结果写入必须做最小变更。

## 4.3 必须保持兼容的边界

1. 现有 SSE 事件名继续保持兼容，至少保留 `start`、`progress`、`signal`、`strategy_complete`、`complete`、`error`。
2. `web_strategy_results.json` 的基础输出结构保持兼容，避免已有页面和脚本失效。
3. 前端现有“重建当前策略”入口不改交互位置。
4. 单策略重建时仍保留“尽量复用其他策略分组”的行为。

---

## 5. 分阶段执行方案

## 5.1 第一阶段：重写 Web 重建主链路

### 目标

把 [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py) 从“每个策略各扫一遍全市场”改成“每只股票读取一次，在内存里跑多个策略”。

### 建议改法

建议新增一组内部辅助函数，而不是在现有函数里继续堆逻辑：

1. `_resolve_selected_web_strategies(strategy_filter)`
2. `_analyze_stock_multi_strategy(code, df, stock_name, strategy_items)`
3. `_scan_all_stocks_multi_strategy(all_stocks, stock_names, strategy_items, progress_callback)`
4. `_finalize_grouped_results(group_buffers)`

建议把主流程改成：

```text
build_strategy_result_snapshot()
  -> 解析目标策略集合
  -> 并发遍历股票代码
  -> 每只股票只 read_stock 一次
  -> 复用 df 对多个 strategy 执行 analyze/select
  -> 命中后立即发 signal
  -> 扫描结束后统一生成 groups / results / snapshot
```

### 关键实现约束

1. 仍允许线程池并发，但线程池的提交粒度改为“股票”，不再是“策略-股票笛卡尔积”。
2. `overall_processed` 的定义改为“已处理股票数”，不再是“已处理策略股票任务数”。
3. `progress_callback('signal', ...)` 的数据结构尽量保持不变，避免前端联动回归。
4. `groups[selected_filter]` 最终结构保持兼容：仍保留 `strategy_filter`、`strategy_name`、`results`、`total`、`scanned`、`time`。

### 这一阶段不做什么

1. 不改各个策略类对外接口。
2. 不把 B2 的内部分析流程一起揉进第一阶段。
3. 不在第一阶段同时引入 Parquet 或 DuckDB。

### 完成标准

1. `build_strategy_result_snapshot(strategy_filter='all')` 只对每只股票发生一次主读取。
2. SSE 仍能持续输出 `progress` 和 `signal`。
3. 最终 `web_strategy_results.json` 与 SQLite 结果可被现有页面正常读取。
4. 同样股票池下，重建总耗时明显低于当前基线。

---

## 5.2 第二阶段：加入最近 250 bars 轻量缓存

### 目标

降低高频扫描、迷你图、基础列表、轻量预筛的读取开销。

### 设计原则

轻量缓存不是替代完整历史，而是为“绝大多数只需要最近窗口”的场景准备一层快速入口。

### 建议缓存内容

以股票代码为 key，缓存以下结构：

```python
{
    "code": "600000",
    "mtime": 1234567890.0,
    "recent_250": df_recent_250,
    "recent_60": df_recent_60,
}
```

### 建议落点

两种方式都可以，优先选择更小改动的一种：

1. 在 [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py) 内部先加轻量缓存工具函数。
2. 或新增 `web/backend/services/recent_window_cache.py`，专门提供窗口级缓存。

### 适用场景

1. Web 重建阶段的轻量读取。
2. B2 预筛阶段。
3. 股票列表和迷你 K 线的近端展示。
4. 详情页默认首屏图表窗口。

### 边界

1. 完整历史读取能力必须保留。
2. 缓存失效基于 CSV 文件 `mtime`，不引入复杂的人工清理机制。
3. 不在本阶段做跨进程共享缓存，先以单进程内存缓存为主。

### 完成标准

1. 重建主链路可优先使用 recent window，而不是完整历史。
2. 股票文件未变化时，同一轮或相邻轮请求不会重复截取最近窗口。
3. 迷你图与轻量分析的平均响应时间继续下降。

---

## 5.3 第三阶段：B2 完美匹配增加并发预筛

### 目标

不要让全部股票都直接进入 B2 完整分析，而是先做低成本候选筛选，再对候选做完整匹配。

### 当前问题

在 [strategy/b2_strategy.py](../strategy/b2_strategy.py) 的 `scan_all()` 中，当前是：

```text
for code in stock_list:
    df = cm.read_stock(code)
    for case in pattern_templates:
        analyzer.analyze(code, df, case)
```

这会让大量明显不可能命中的股票也进入完整分析。

### 建议改法

把 B2 扫描拆成两层：

1. 预筛层：基于最近 250 bars 做低成本规则过滤。
2. 精筛层：仅对预筛命中的股票执行当前完整 `analyzer.analyze()`。

### 预筛建议条件

预筛只做“必要但不充分”的条件，避免误伤太多：

1. 最近窗口长度足够。
2. 最近若干日存在明显放量阳线或突破候选。
3. 最近区间振幅、量能或趋势形态大致落在 B2 可疑范围内。
4. ST、退市、数据不足股票提前排除。

### 并发建议

1. 预筛阶段可并发，因为逻辑轻、互相独立。
2. 精筛阶段仍可并发，但只对候选集执行。
3. 若 B2 分析内部共享状态较少，优先用线程池；若后续确认为纯 CPU 且 GIL 成为瓶颈，再评估进程池。

### 边界

1. 不改 `B2CaseAnalyzer.analyze()` 的信号判定口径。
2. 不为了提速而放宽最终命中标准。
3. 预筛必须允许“宁可放宽一点，也不要大面积漏掉真实命中”。

### 完成标准

1. 大部分股票在预筛层被快速排除。
2. 最终 B2 命中结果与未预筛版本相比，不出现明显系统性漏报。
3. B2 全市场扫描耗时显著下降。

---

## 5.4 第四阶段：前端把 SSE `signal` 并入主表

### 目标

让用户在重建进行中就能看到主结果表持续增长，而不是只在右侧或顶部看到临时实时流。

### 当前问题

在 [web/frontend/src/views/StrategyResultsView.vue](../web/frontend/src/views/StrategyResultsView.vue) 中，`handleEvent()` 目前只把 `signal` 放进 `liveSignals`，主表 `results` 仍依赖 `loadResults()`。

### 建议改法

收到 `signal` 事件时，同时做两件事：

1. 继续维护 `liveSignals` 作为实时流。
2. 把 `data.items` 直接按主表结构 `upsert` 到 `results`。

### 建议合并规则

主键建议优先使用以下组合：

```text
code + strategy_name + date + category
```

这样可避免同一轮 SSE 重复插入，也能兼容同一股票多策略、多日期命中。

### 渲染策略

1. 重建进行中：主表优先显示“实时结果 + 当前筛选”。
2. 重建完成后：再调用一次 `loadResults()`，用后端最终持久化结果对齐主表。
3. 若用户正在分页第 2 页以后，可先提示“当前正在显示实时第一页结果”，避免复杂分页错位。

### 边界

1. 不在本阶段重写整个列表 store。
2. 不做复杂虚拟滚动改造。
3. 历史查询接口仍然是最终一致性来源。

### 完成标准

1. 重建过程中主表可实时出现新命中。
2. 重建完成后主表与后端历史结果一致。
3. 不因为 SSE 连续写入导致明显卡顿或重复行。

---

## 5.5 第五阶段：长期评估 Parquet 或 DuckDB

### 目标

为后续更大规模扫描预留数据底座升级路径，但不把它放进本轮必须完成项。

### 为什么要延后

当前最主要浪费来自“重复读取和重复扫描结构”，不是 CSV 这个格式本身已经完全不可用。

如果在主链路没有先理顺前就直接上 DuckDB 或 Parquet，收益会被结构性浪费抵消，复杂度却会大幅上升。

### 进入长期方案的前提

只有当以下条件成立时，再进入这一步：

1. 第一到第四阶段已经完成并稳定。
2. 仍然发现 CSV 扫描是剩余主要瓶颈。
3. 已经明确需要更多横截面筛选、跨股票聚合或批量回测能力。

### 长期方案边界

1. 不直接替换原始 CSV 归档。
2. 可把 Parquet 或 DuckDB 视为“扫描副本层”，不是唯一真相源。
3. Web 路径先切，CLI 路径后评估是否跟进。

---

## 6. 推荐实施顺序

严格按以下顺序执行，不建议并行开太多战线：

1. 先改 Web 重建主链路。
2. 再接最近 250 bars 轻量缓存。
3. 再做 B2 并发预筛。
4. 然后把 SSE `signal` 并入主表。
5. 最后才评估 Parquet 或 DuckDB。

原因很直接：

- 第一阶段决定主链路是否还在重复读。
- 第二阶段决定高频窗口是否还能继续降成本。
- 第三阶段决定最重的 B2 是否被大面积削峰。
- 第四阶段决定用户体感是否立刻改善。
- 第五阶段是数据底座升级，属于长期优化，不应抢在结构重构之前。

---

## 7. 验收标准

## 7.1 性能验收

至少记录以下指标，形成改造前后对比：

1. `strategy=all` 全量重建总耗时。
2. 单策略重建总耗时。
3. 每轮重建触发的 `read_stock` 次数。
4. B2 全市场扫描耗时。
5. 前端从点击“重建当前策略”到主表出现第一条结果的时间。

## 7.2 功能验收

1. 重建期间 SSE 事件正常输出。
2. 主表在重建期间能实时增长。
3. 重建完成后历史结果查询正常。
4. `web_strategy_results.json` 可被现有接口继续读取。
5. SQLite 双写仍然正常，不影响主流程成功。

## 7.3 回归验收

1. 单策略重建不会清空同交易日其他策略已有分组。
2. `strategy=all` 与单策略模式的结果结构一致。
3. B2 优化后不应出现明显异常漏报。
4. StockDetail、股票列表、迷你图现有接口不被本轮破坏。

---

## 8. 风险与回滚策略

### 主要风险

1. 主链路改造后，`groups` 或 `results` 结构与现有页面不完全兼容。
2. SSE 实时并表后，主表排序、分页和筛选逻辑出现错位。
3. B2 预筛过严导致漏掉真实命中。
4. 轻量缓存失效逻辑处理不好，导致读到过期数据。

### 回滚原则

1. 每个阶段独立提交，避免多阶段混在一个大改里。
2. 第一阶段优先保留旧接口结构，新旧差异尽量收敛在内部实现。
3. 第三阶段为 B2 预筛保留开关，必要时可快速退回“全量精筛”。
4. 第四阶段若前端实时并表不稳定，可先保留 `liveSignals`，主表只在完成后刷新。

---

## 9. 直接可执行的任务清单

### 第一批

- [ ] 重构 [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py) 为“按股票扫描一次”的主链路。
- [ ] 在重构后保持 snapshot 与 SSE 数据结构兼容。
- [ ] 给重建过程补充 `read_stock` 次数统计，便于验收。

### 第二批

- [ ] 新增 recent 250 bars 轻量缓存工具。
- [ ] 让 Web 重建、迷你图、轻量预筛优先走 recent window。

### 第三批

- [ ] 给 [strategy/b2_strategy.py](../strategy/b2_strategy.py) 增加预筛阶段。
- [ ] 给 B2 预筛和精筛增加独立耗时统计。
- [ ] 用历史样本验证预筛前后命中差异。

### 第四批

- [ ] 修改 [web/frontend/src/views/StrategyResultsView.vue](../web/frontend/src/views/StrategyResultsView.vue) 的 `handleEvent()`，把 `signal` 同步并入 `results`。
- [ ] 做去重、排序、分页边界处理。
- [ ] 在重建完成后统一再拉一次历史结果对齐。

### 长期跟踪

- [ ] 在完成前四阶段后，再评估 Parquet 或 DuckDB 的真实收益。

---

## 10. 最终判断

这次优化的主线应该非常明确：

先解决“重复扫描结构”问题，再解决“轻量窗口复用”问题，然后削减 B2 的重型覆盖范围，最后把 SSE 结果真正反馈到主表上。

如果顺序做反了，例如还没改主链路就先做 DuckDB，或者还没把 SSE 并表就先做复杂前端重构，投入会明显高于收益。

因此，当前最值得立即开工的第一项，不是继续调单个接口参数，而是重写 [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py) 的 Web 重建主链路。

---

## 11. Claude 可直接实现的代码逻辑与结构

这一节不是需求描述，而是给实现者直接落代码用的结构蓝图。

目标是让 Claude 在不重新推导架构的前提下，直接知道：

1. 先改哪些文件。
2. 每个文件应该新增什么函数。
3. 哪些函数保留不动，哪些函数只做内聚重构。
4. 前后端数据结构如何对齐。

### 11.1 本轮优先修改的文件

#### 后端

1. [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py)
2. [strategy/b2_strategy.py](../strategy/b2_strategy.py)
3. 可选新增 [web/backend/services/recent_window_cache.py](../web/backend/services/recent_window_cache.py)

#### 前端

1. [web/frontend/src/views/StrategyResultsView.vue](../web/frontend/src/views/StrategyResultsView.vue)

#### 尽量不改的文件

1. [utils/csv_manager.py](../utils/csv_manager.py)
2. [web/backend/services/strategy_result_repository.py](../web/backend/services/strategy_result_repository.py)
3. 各个现有策略类的对外接口

### 11.2 第一阶段的后端函数拆分方案

在 [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py) 中，保留以下现有函数作为稳定基础：

1. `_extract_signal_items()`
2. `_flatten_grouped_results()`
3. `_write_results_to_sqlite()`
4. `stream_strategy_cache_rebuild()`
5. `run_strategy()`

重点改造 `build_strategy_result_snapshot()` 的内部执行模型，不先改它的对外签名。

### 11.3 建议新增的后端辅助函数

建议在 [web/backend/services/strategy_service.py](../web/backend/services/strategy_service.py) 新增以下函数。

#### A. 解析目标策略集合

```python
def _resolve_selected_web_strategies(resolved_strategies: dict, strategy_filter: str) -> list[tuple[str, str, object]]:
  ...
```

返回结构建议为：

```python
[
  ("b1", "B1CaseStrategy", strategy_obj),
  ("b2", "B2Strategy", strategy_obj),
  ("bowl", "BowlReboundStrategy", strategy_obj),
]
```

这样后续扫描层不需要再反复解析字典。

#### B. 初始化分组缓冲区

```python
def _init_group_buffers(selected_items: list[tuple[str, str, object]], existing_snapshot: dict | None, strategy_filter: str, effective_date: str) -> dict:
  ...
```

职责：

1. 初始化每个策略分组的结果容器。
2. 当 `strategy_filter != 'all'` 且已有同日快照时，复用其他策略已有分组。
3. 只为本轮实际重建的策略创建空缓冲区。

#### C. 单只股票读取与预校验

```python
def _prepare_stock_context(code: str, stock_names: dict) -> tuple[str, str, object | None, str | None]:
  ...
```

返回值建议含义：

1. `status`: `ok` / `skip` / `invalid`
2. `name`: 股票名称
3. `df`: 读取后的 DataFrame 或 `None`
4. `reason`: 跳过原因

职责：

1. 读取股票名。
2. 过滤 ST、退市、未知股票。
3. 执行一次 `csv_manager.read_stock(code)`。
4. 过滤空数据和长度不足数据。

#### D. 单只股票复用多策略分析

```python
def _analyze_stock_multi_strategy(code: str, name: str, df, strategy_items: list[tuple[str, str, object]]) -> dict:
  ...
```

返回结构建议为：

```python
{
  "code": "600000",
  "name": "浦发银行",
  "hits": {
    "b1": {
      "strategy_name": "B1CaseStrategy",
      "stock_result": {...}
    },
    "b2": {
      "strategy_name": "B2Strategy",
      "stock_result": {...}
    }
  }
}
```

内部逻辑建议：

1. 对每个策略循环判断。
2. 若策略具备 `calculate_indicators()` 和 `select_stocks()`，则沿用当前 `_analyze_stock_for_strategy()` 的逻辑。
3. 否则走 `strategy.analyze_stock(code, name, df)`。
4. 某个策略失败只跳过该策略，不中断该股票其他策略。

#### E. 合并单股结果到分组缓冲区

```python
def _merge_stock_hits_into_groups(group_buffers: dict, stock_analysis: dict) -> tuple[int, list[dict]]:
  ...
```

返回值建议：

1. `matched_row_count`: 本只股票新增多少条 signal row
2. `emitted_rows`: 供 SSE 直接发送的行列表

职责：

1. 把命中的 `stock_result` 写入对应 `group_buffers[strategy_filter]['results']`。
2. 用 `_extract_signal_items()` 转成 SSE / 扁平结果需要的行结构。
3. 补上 `strategy_filter` 字段。

#### F. 从缓冲区生成最终 groups

```python
def _finalize_grouped_results(group_buffers: dict, scanned_total: int) -> dict:
  ...
```

职责：

1. 为每个分组补齐 `total`、`scanned`、`time`。
2. 生成与当前接口兼容的 `groups` 结构。

### 11.4 第一阶段的主函数伪代码

`build_strategy_result_snapshot()` 建议按下面结构重写内部流程：

```python
def build_strategy_result_snapshot(target_date=None, strategy_filter='all', progress_callback=None, run_id=None):
  effective_date = ...
  resolved_strategies = _resolve_web_strategies(registry)
  selected_items = _resolve_selected_web_strategies(resolved_strategies, strategy_filter)
  existing_snapshot = _read_strategy_snapshot()
  group_buffers = _init_group_buffers(selected_items, existing_snapshot, strategy_filter, effective_date)

  stock_names = _load_stock_names()
  all_stocks = csv_manager.list_all_stocks()
  total_stocks = len(all_stocks)
  processed = 0
  matched_rows = 0

  emit strategy_start for selected_items

  with ThreadPoolExecutor(max_workers=worker_count) as executor:
    futures = [executor.submit(_process_one_stock, code, stock_names, selected_items) for code in all_stocks]

    for future in as_completed(futures):
      processed += 1
      stock_analysis = future.result()
      added_rows, emitted_rows = _merge_stock_hits_into_groups(group_buffers, stock_analysis)
      matched_rows += added_rows

      if emitted_rows:
        progress_callback('signal', {..., 'items': emitted_rows, ...})

      progress_callback('progress', {..., 'processed': processed, 'total': total_stocks, 'matched': matched_rows})

  groups = _finalize_grouped_results(group_buffers, total_stocks)
  flat_results = _flatten_grouped_results(groups)
  snapshot = ...
  write json
  write sqlite
  return snapshot
```

注意这里的 `total` 应改成“股票总数”，不是“策略股票笛卡尔积总数”。

### 11.5 建议新增的内部包装函数

为了减少 `build_strategy_result_snapshot()` 主函数体积，建议再加一个小包装：

```python
def _process_one_stock(code: str, stock_names: dict, strategy_items: list[tuple[str, str, object]]) -> dict:
  status, name, df, reason = _prepare_stock_context(code, stock_names)
  if status != 'ok':
    return {
      'code': code,
      'name': name,
      'status': status,
      'reason': reason,
      'hits': {},
    }
  return {
    'code': code,
    'name': name,
    'status': 'ok',
    'reason': None,
    'hits': _analyze_stock_multi_strategy(code, name, df, strategy_items).get('hits', {}),
  }
```

这样主线程只负责：

1. 收 future
2. 合并结果
3. 发事件
4. 生成 snapshot

### 11.6 recent 250 轻量缓存建议结构

如果新增 [web/backend/services/recent_window_cache.py](../web/backend/services/recent_window_cache.py)，建议只做一件事：

```python
_RECENT_WINDOW_CACHE = {
  '600000': {
    'mtime': 1710000000.0,
    'recent_250': df250,
    'recent_60': df60,
  }
}
```

建议暴露一个最小 API：

```python
def get_recent_stock_windows(code: str, csv_manager, recent_sizes: tuple[int, ...] = (60, 250)) -> dict:
  ...
```

返回建议：

```python
{
  'full_df': df,
  'recent_60': df.tail(60),
  'recent_250': df.tail(250),
  'mtime': mtime,
}
```

注意：

1. 第一版可以继续读完整 DataFrame 后切片，不需要一上来改 CSVManager。
2. 这一步的价值先来自“跨调用复用已切好的窗口”，不是先追求极限 IO 最优。

### 11.7 B2 预筛的代码结构

在 [strategy/b2_strategy.py](../strategy/b2_strategy.py) 中，建议保留 `scan_all(stock_list, cm, progress_callback=None)` 这个对外签名不变，只在内部改成两段式。

建议新增：

```python
def _prefilter_candidate(self, code: str, df) -> bool:
  ...

def _analyze_candidate(self, code: str, df):
  ...
```

新的 `scan_all()` 内部结构建议为：

```python
def scan_all(self, stock_list, cm, progress_callback=None):
  candidates = []
  for code in stock_list:
    df = cm.read_stock(code)
    if df is None or df.empty:
      continue
    if self._prefilter_candidate(code, df):
      candidates.append((code, df))

  results = []
  for code, df in candidates:
    best_result = self._analyze_candidate(code, df)
    if best_result:
      results.append(best_result)
```

如果要加并发，优先加在预筛层；如果第二步候选仍然很多，再给候选分析层加线程池。

### 11.8 前端实时并表的实现结构

在 [web/frontend/src/views/StrategyResultsView.vue](../web/frontend/src/views/StrategyResultsView.vue) 中，建议新增 3 个函数，不要把逻辑直接塞进 `handleEvent()`。

#### A. 把 SSE 行转成主表行

```ts
function normalizeRealtimeResultItem(item: any) {
  return {
  ...item,
  signal_date: item.signal_date || item.date || '',
  trade_date: item.trade_date || cacheStatus.value?.trade_date || cacheStatus.value?.requested_date || '',
  }
}
```

这里必须补一个兼容层，因为当前 SSE 行来自后端 `_extract_signal_items()`，字段是 `date`，而主表历史接口字段是 `signal_date`。

#### B. 生成去重 key

```ts
function makeResultKey(row: any) {
  return [row.code, row.strategy_name, row.signal_date, row.category].join('|')
}
```

#### C. 把实时结果 merge 到主表

```ts
function mergeRealtimeItemsIntoResults(items: any[]) {
  const normalized = items.map(normalizeRealtimeResultItem)
  const map = new Map(results.value.map((row: any) => [makeResultKey(row), row]))
  for (const row of normalized) {
  map.set(makeResultKey(row), { ...map.get(makeResultKey(row)), ...row })
  }
  results.value = Array.from(map.values()).sort(sortResults)
  resultsTotal.value = results.value.length
  resultsUniqueTotal.value = new Set(results.value.map((row: any) => row.code)).size
}
```

`sortResults` 建议优先按以下顺序：

1. `signal_date` 倒序
2. `code` 升序
3. `strategy_name` 升序

#### D. `handleEvent()` 的修改方式

当前 `handleEvent()` 不要重写，只做两处增量修改：

1. `eventName === 'signal'` 时，除了写 `liveSignals`，再调用 `mergeRealtimeItemsIntoResults(data.items)`。
2. `status === 'done'` 时，保留现有 `loadResults()`，用后端持久化结果做最终对齐。

### 11.9 关键兼容点

Claude 在实现时必须注意以下兼容点，否则前后端会对不上。

1. SSE 行里的日期字段当前叫 `date`，主表历史行常用 `signal_date`。
2. `results` 表格列里已有 `trade_date`、`strategy_name`、`category` 等字段，不要让实时行缺这些基础字段。
3. `groups` 里的 `results` 当前是按股票聚合结果，不是扁平 signal rows；不要把这两个层级混掉。
4. `_write_results_to_sqlite()` 依赖的是 `groups -> stock_result -> signals` 这层结构，不能只保留扁平行。

### 11.10 第一阶段完成后应立即验证的点

1. `build_strategy_result_snapshot('all')` 是否仍能生成合法 `groups` 与 `results`。
2. SSE 是否仍然正常输出 `signal`。
3. `signal` 的 `items` 是否还能被前端 `liveSignals` 正常展示。
4. SQLite 结果表是否还能正常插入。
5. 进度条的 `total` 是否已经切换为股票总数，而不是旧的笛卡尔积。

---

## 12. 可直接复制给 Claude 的执行指令

下面这段可以直接给 Claude 执行，目标是减少它自行补架构时产生的偏差。

```text
请在当前仓库中实现“Web 策略重建提速第一阶段 + 前端 SSE 主表实时并入”的代码改造，严格按以下约束执行：

一、目标
1. 将 web/backend/services/strategy_service.py 的 Web 重建主链路从“按策略扫描全市场”改成“按股票读取一次并复用多个策略”。
2. 保持 build_strategy_result_snapshot()、stream_strategy_cache_rebuild()、run_strategy() 的对外签名不变。
3. 保持 web_strategy_results.json 的输出结构兼容，groups 仍按策略分组，组内 results 仍是 stock_result 列表。
4. 保持 SQLite 双写逻辑兼容，不要破坏 _write_results_to_sqlite() 依赖的数据层级。
5. 修改 web/frontend/src/views/StrategyResultsView.vue，让 SSE 的 signal 事件除了写入 liveSignals，还能实时 merge 到主表 results。

二、文件范围
1. 必改：web/backend/services/strategy_service.py
2. 必改：web/frontend/src/views/StrategyResultsView.vue
3. 暂不改 utils/csv_manager.py
4. 暂不引入 Parquet 或 DuckDB

三、后端实现要求
1. 新增 _resolve_selected_web_strategies()、_init_group_buffers()、_prepare_stock_context()、_analyze_stock_multi_strategy()、_merge_stock_hits_into_groups()、_finalize_grouped_results()。
2. build_strategy_result_snapshot() 内部改为：并发遍历股票代码，每只股票只 read_stock 一次，然后在同一份 df 上复用多个策略执行。
3. progress_callback 的 signal 事件结构尽量保持不变，尤其保留 items 列表。
4. progress 里的 total 改为股票总数，不再使用策略数 * 股票数。
5. 单策略重建时，若已有同交易日快照，继续保留未重建策略的原有 groups。

四、前端实现要求
1. 在 StrategyResultsView.vue 中新增 normalizeRealtimeResultItem()、makeResultKey()、mergeRealtimeItemsIntoResults()。
2. SSE signal 项里的 date 字段需要映射为主表使用的 signal_date。
3. handleEvent() 在收到 signal 后，同时更新 liveSignals 和 results。
4. 重建完成后仍调用 loadResults() 做最终一致性对齐。

五、约束
1. 不重写整个页面。
2. 不删除现有 liveSignals 展示区。
3. 不修改现有 API 路由。
4. 不为了简化逻辑而改变 groups / results / SQLite 的兼容结构。

六、完成后请自检
1. 检查 strategy_service.py 是否仍能生成 snapshot。
2. 检查 SSE signal 是否仍能推送。
3. 检查主表是否能在重建过程中实时增加结果。
4. 检查最终 loadResults() 后页面结果与后端持久化结果一致。
```