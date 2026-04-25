# B2策略修复与K线交互升级 实施日志

> 创建日期：2026-04-25  
> 方案来源：plan.md  
> 实施顺序：后端语义/契约 → 量比数据 → 前端右侧日期 → 副图布局 → 区间统计

---

## 总体目标

| # | 需求 | 优先级 | 状态 |
|---|------|--------|------|
| 1 | B2 当日可命中：把"站稳多空线"从前置阻塞改为后验质量字段 | P0 | ✅ 完成 |
| 2 | B2参数名口径统一：strategy_service.py → b2_min_pct / vol_multiplier | P0 | ✅ 完成 |
| 3 | K线量比字段：kline_service 补充 vol_ratio_10d、avg_volume_10d | P1 | ✅ 完成 |
| 4 | K线副图量比显示：KlineChart.vue tooltip 显示量比 | P1 | ✅ 完成 |
| 5 | 个股详情右侧策略列表日期选择器 | P1 | ✅ 完成 |
| 6 | 副图自由布局+最大化模式 | P2 | ✅ 完成 |
| 7 | K线长按拖动区间统计 | P2 | ✅ 完成 |

---

## Phase 1: B2信号语义与参数契约

### Step 1.1 — B2语义修复

**问题根因**  
`_check_hold_above_bullbear()` 在 `analyze()` 主流程中作为硬门槛（第6步），要求  
B2突破日起的后续 `b2_hold_days=3` 根K线全部收在多空线以上。这意味着：  
- 当日扫描时，B2当天没有后续数据 → 直接返回 `False` → 信号被丢弃  
- 即使当日是真实的突破日，也无法在当天命中

同时，`b2_must_follow_b1_days=1` 硬约束要求 B2 与 B1 的间隔恰好等于1，任何 gap≠1 的情况均被过滤。

**方案A（已实施）**  
1. `_check_hold_above_bullbear()` 不再作为硬门槛阻塞命中  
2. 将其改为**后验质量标签**，计算实际观察到的站稳天数  
3. 在返回结果字典中新增 3 个字段：  
   - `hold_above_confirmed: bool` — 是否已完成 `b2_hold_days` 根站稳  
   - `hold_days_observed: int` — 实际观察到的连续站稳天数  
   - `is_fresh_signal: bool` — B2日是否为数据集中最新的交易日  
4. `b2_must_follow_b1_days` 由精确等于改为**最大间隔**（≤N），宽松化为"N天内任何突破均有效"  
5. 在结果字典中新增 `b1_b2_gap: int` 字段，记录实际间隔

**改动文件**  
- `strategy/b2_strategy.py`  
  - `analyze()` 主流程：移除第6步硬门槛调用  
  - `analyze()` 结果字典：新增 `hold_above_confirmed`、`hold_days_observed`、`is_fresh_signal`、`b1_b2_gap`  
  - `_check_hold_above_bullbear()` → 改为返回 `(bool, int)` 的质量计算函数

**技术要点**  
- 保留 `b2_hold_days` 参数（用于判断 `hold_above_confirmed`）  
- `is_fresh_signal` 计算：`b2_idx == len(working_df) - 1`  
- `b1_b2_gap` 直接记录 `b2_idx - b1_idx`  
- 旧扫描行为兼容：`b2_must_follow_b1_days` 现在是上限（max_gap），默认从1改为5

---

### Step 1.2 — 参数口径统一

**问题根因**  
`strategy_service.py` 中的 `_PARAM_META['B2Strategy']` 使用 `b2_breakout_pct` / `b2_volume_ratio`，  
但 `B2CaseAnalyzer` 实际运行时读取的是 `b2_min_pct` / `vol_multiplier`（来自 `B2_DEFAULT_PARAMS`）。  
前端调参 → 发给后端 → 传给策略，但 key 不匹配 → 调参无效，用的是默认值。

**改动文件**  
- `web/backend/services/strategy_service.py`  
  - `b2_breakout_pct` → `b2_min_pct`  
  - `b2_volume_ratio` → `vol_multiplier`  
  - `b2_must_follow_b1_days` 的 label 改为"B2距B1最大天数"、desc 改为"B2突破距B1触发最多N个交易日"  
  - 新增 `b2_hold_days` 参数元数据（后验质量门槛天数）

**技术要点**  
- sessionStorage 向后兼容注意：浏览器端若有旧的 `b2_breakout_pct` key，需要在前端参数绑定时做一次  
  `if key === 'b2_breakout_pct' return 'b2_min_pct'` 的向下兼容映射（后续考虑）  
- 本次只改服务器端 meta，不引入迁移脚本（低风险：参数面板仅影响用户手动调参，默认值由 `B2_DEFAULT_PARAMS` 保护）

---

## Phase 2: 量比数据与K线显示

### Step 2.1 — kline_service.py 补充量比字段

**问题根因**  
`_build_kline_result()` 返回的每个 bar 只有 `volume`（原始成交量），没有量比信息。  
前端没有足够信息判断"当日量是否为放量"，无法展示相对量能。

**改动文件**  
- `web/backend/services/kline_service.py`  
  - 在构建 `bars` 前，先计算 `vol_ma10`（10日均量，滚动窗口 = 10，倒序数据需特殊处理）  
  - 在每个 bar 字典中增加：  
    - `vol_ratio_10d: float | None` — 当日量 / 10日均量  
    - `avg_volume_10d: int | None` — 10日平均成交量  
  - 对第一批没有足够历史的 bar，设 `vol_ratio_10d = None`

**技术要点**  
- df_slice 是倒序（最新在前），计算滑动均值时需先翻转，计算后再翻转回去  
- 使用 `pandas.Series.rolling(10).mean()` 在正序数据上计算，结果对应 df_slice 倒序的正确位置  
- 避免 `shift` 错位：均量取当天前10日（不含当日），等价于 `rolling(10).mean().shift(0)` 正序（含当日）  
  本次取**含当日的10日均量**（与策略 B2CaseAnalyzer 保持一致：`vol > avg_vol_10d * vol_multiplier`）

---

### Step 2.2 — KlineChart.vue tooltip 量比显示

**改动文件**  
- `web/frontend/src/components/KlineChart.vue`  
  - 在 tooltip formatter 中，当 `vol_ratio_10d` 存在时，在成交量行追加量比信息  
  - 格式：`成交量: 1,234万手 (量比:2.31x)`  
  - 量比 ≥ 1.5 时文字标红，< 1.0 时标蓝（视觉区分放量/缩量）

---

## Phase 3: 个股详情右侧策略列表日期选择

### Step 3.1 — strategyList.ts 扩展日期状态

**问题根因**  
`strategyList` store 只缓存当前列表和最近一次日期，没有"可用交易日列表"、"当前选中日期"的独立状态，  
也没有按指定日期重新加载列表的 action。

**改动文件**  
- `web/frontend/src/stores/strategyList.ts`  
  - 新增 state：`selectedDate: string`、`availableDates: string[]`、`isLoadingDates: boolean`  
  - 新增 action：`fetchAvailableDates()` — 调用 `GET /api/strategy/results/dates`，写入 `availableDates`  
  - 新增 action：`fetchListByDate(date: string, strategy?: string)` — 按日期拉列表，写入 `items` 和 `selectedDate`  
  - 修改 `setList()` 同步更新 `selectedDate`

---

### Step 3.2 — StockDetail.vue 右侧添加日期选择器

**改动文件**  
- `web/frontend/src/views/StockDetail.vue`  
  - 在右侧策略列表头部插入 `el-select`（下拉选择器），选项来自 `availableDates`  
  - 默认日期优先级：`route.query.date` > `tradeDate`（store cache）> `availableDates[0]`（最新）  
  - 选择日期后调用 `fetchListByDate(date)` 更新列表  
  - 加载态：显示 `el-skeleton` 占位  
  - 空态：显示"该日期无策略结果"

**技术要点**  
- 复用 `/api/strategy/results/dates` 接口（已存在，`strategy.py` 中的 `GET /api/strategy/results/dates`）  
- 复用 `/api/strategy/results/history` 接口获取历史日期结果  
- 避免与 `StrategyResultsView` 的 `filterDateRange` 状态产生冲突（两者 store 独立）

---

## Phase 4: K线副图自由布局与最大化

### Step 4.1 — Pane Manager 重构

**问题根因**  
- 当前 `panelRatios` 是一个 flat Record，主图 + 4个副图共用一个比例池  
- 拖拽交互是"相邻面板交换高度"，无法跨越面板  
- 双击只能折叠/展开到 `MIN_PANEL_PX`，无法占满全部副图区域

**改动文件**  
- `web/frontend/src/components/KlineChart.vue`  
  - 新增 `expandedSubPanel: PanelKey | null` — 当前最大化的副图  
  - 新增 `savedSubRatios: Record<PanelKey, number>` — 最大化前的比例快照  
  - 重构 `computeGrids()`：主图高度固定（`mainRatio` 不变），副图区域由剩余高度动态分配  
  - 重构拖拽：divider 拖拽只影响副图内的高度分配，不影响主图  
  - 重构 `togglePanelCollapse()` → `handleSubPanelDblClick()`:  
    - 若 `expandedSubPanel === null`：保存当前副图比例，设置 `expandedSubPanel = panelKey`，  
      该副图占满所有副图区域（其他副图 ratio=0 但不折叠，只是隐藏）  
    - 若 `expandedSubPanel === panelKey`：恢复 `savedSubRatios`，清空 `expandedSubPanel`  
    - 若 `expandedSubPanel === otherPanel`：切换到本面板最大化

**技术要点**  
- 主图高度保持 `mainRatio * chartHeight`，不参与副图预算池  
- 副图预算 = `chartHeight - mainHeight - TOP_MARGIN - BOTTOM_MARGIN - (numVisibleSubPanels + 1) * PANEL_GAP`  
- 折叠状态保留：已折叠的副图在最大化模式下也保持折叠，最大化只影响未折叠的副图

---

## Phase 5: K线长按拖动区间统计

### Step 5.1 — 长按交互与区间统计浮层

**问题根因**  
当前 `KlineChart.vue` 没有"区间统计"功能：  
- `brushSelect: false` 在 dataZoom 中  
- 没有鼠标长按计时器  
- 没有选区状态管理  
- 没有统计计算逻辑

**改动文件**  
- `web/frontend/src/components/KlineChart.vue`  
  - 新增状态：`isRangeSelecting`, `rangeAnchorIdx`, `rangeEndIdx`, `rangeStats`  
  - `onMousedown`：启动 300ms 定时器，超时后进入选区模式  
  - `onMousemove`：在选区模式下绘制半透明矩形覆盖层（用 `div` absolute 定位，非 ECharts 层）  
  - `onMouseup`：结束选区，用 `rangeAnchorIdx..rangeEndIdx` 对 `normalizedBars` 计算统计  
  - `onMousedown` 短点击（<300ms）：取消选区模式，保持原有点击行为（分时跳转等）  
  - 统计计算：从 `normalizedBars` 切片，计算：  
    - 区间涨幅：`(endBar.close - startBar.close) / startBar.close * 100`  
    - 阳线换手率累计：`sum(bar.turnover for bar if bar.close >= bar.open)`  
    - 阴线换手率累计：`sum(bar.turnover for bar if bar.close < bar.open)`  
    - K线根数：`rangeEndIdx - rangeAnchorIdx + 1`  
    - 区间最高/最低：`max(bar.high)` / `min(bar.low)`  
    - 振幅：`(high - low) / startBar.close * 100`  
  - 浮层：使用 `v-if="rangeStats"` 显示的绝对定位 `div`，可拖动，右上角有关闭按钮  
  - ESC键 / 点击外部：关闭统计浮层并清除选区

**技术要点**  
- 长按判断：300ms 阈值，避免与普通点击冲突  
- 坐标映射：鼠标 X 坐标 → ECharts 数据 index（通过 `chartInstance.convertFromPixel({gridIndex: 0}, [x, y])`）  
- 选区覆盖层用纯 CSS `div`（不用 ECharts brush），避免与 dataZoom 冲突  
- 移动端兼容：也监听 `touchstart` / `touchmove` / `touchend`

---

## 验证计划

### 后端验证
```bash
# B2当日命中验证（应能命中已知案例的当日）
$env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -u .\utils\backtrace_analyzer.py --code 688031 --start 2025-12-04 --end 2025-12-06 --strategy b2
$env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -u .\utils\backtrace_analyzer.py --code 601778 --start 2025-08-06 --end 2025-08-08 --strategy b2
$env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -u .\utils\backtrace_analyzer.py --code 300852 --start 2025-09-09 --end 2025-09-11 --strategy b2
```

### 前端验证
1. 启动 backend + frontend  
2. 进入任意股票详情页，右侧列表头部应出现日期下拉框  
3. 切换日期后列表更新  
4. K线副图双击放大，再次双击恢复  
5. K线上长按（>300ms）拖动，松开后弹出区间统计浮层  

### 单元测试
```bash
cd web/frontend && npm run test
```

---

## 变更记录

| 日期 | 步骤 | 文件 | 变更摘要 |
|------|------|------|---------|
| 2026-04-25 | Step 1.1 | strategy/b2_strategy.py | B2语义修复：站稳多空线改为后验质量标签，b2_must_follow_b1_days改为最大间隔 |
| 2026-04-25 | Step 1.2 | web/backend/services/strategy_service.py | 参数名口径统一：b2_breakout_pct→b2_min_pct，b2_volume_ratio→vol_multiplier |
| 2026-04-25 | Step 2.1 | web/backend/services/kline_service.py | 每个bar补充vol_ratio_10d、avg_volume_10d字段 |
| 2026-04-25 | Step 2.2 | web/frontend/src/components/KlineChart.vue | tooltip量比显示（量比≥1.5标红，<1.0标蓝） |
| 2026-04-25 | Step 3.1 | web/frontend/src/stores/strategyList.ts | 新增selectedDate/availableDates/isLoadingDates状态及fetch actions |
| 2026-04-25 | Step 3.2 | web/frontend/src/views/StockDetail.vue | 右侧策略列表头部新增日期选择器 |
| 2026-04-25 | Step 4.1 | web/frontend/src/components/KlineChart.vue | Pane Manager重构：副图自由布局+双击最大化/恢复 |
| 2026-04-25 | Step 5.1 | web/frontend/src/components/KlineChart.vue | 长按拖动区间统计浮层 |
