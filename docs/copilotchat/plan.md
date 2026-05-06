# K线交互、人工选股与回测功能实施计划

日期：2026-04-26

## 目标

1. 修复个股详情页已有问题：
   - K线副图双击后必须能真正放大，再次双击恢复。
   - 右侧策略选股列表日期下拉必须能加载可用日期，并按日期展示结果。
   - K线右下角显示“光标日期到最新K线”的涨跌结果。
2. 新增人工选股池：
   - 在右侧策略选股列表中增加勾选/取消勾选功能。
   - 将人工选出的目标股票按日期保存，作为后续回测的数据源。
3. 新增回测功能 MVP：
   - 复用现有 CSV 行情数据和 SQLite 策略结果缓存。
   - 支持从“人工选股池”或“策略结果”读取标的。
   - 前端提供参数入口，参数结构可扩展。

## Phase 1：修复现有交互

### 1.1 日期选择器修复

问题根因：后端 `/api/strategy/results/dates` 返回 `{ success, data }`，前端 store 读取了错误字段；`/api/strategy/results/history` 返回 `data.items`，前端按数组解析，导致列表为空。

改动：
- `web/frontend/src/stores/strategyList.ts`
  - 正确解析 `res.data.data`。
  - 历史结果读取 `res.data.data.items`。
  - 拉到日期后自动加载最新日期列表。

### 1.2 副图双击放大修复

问题根因：当前最大化只绑定在标签区域，用户双击副图区域不会触发；最大化比例直接写入 `panelRatios`，其他副图设置为最小高度后会导致总比例超过 1，grid 布局溢出。

改动：
- `web/frontend/src/components/KlineChart.vue`
  - 新增 `getEffectivePanelRatios()`，所有 grid、标签、分割线统一走有效比例。
   - 最大化模式下主图最多保留 48%，目标副图占满剩余预算，其他副图高度为 0。
  - wrapper 双击根据鼠标 Y 坐标识别所在副图，触发放大/恢复。

### 1.3 右下角涨跌结果

改动：
- `web/frontend/src/components/KlineChart.vue`
  - 监听 ECharts `updateAxisPointer` 或鼠标移动得到当前光标 index。
  - 使用当前光标 K 线收盘价与最新 K 线收盘价计算涨跌额、涨跌幅和间隔天数。
  - 在图表右下角以小浮层显示。

## Phase 2：人工选股池

### 2.1 后端持久化

新增表：`manual_selections`
字段：
- `selection_id`
- `selection_date`
- `code`
- `name`
- `strategy_name`
- `source_trade_date`
- `source_signal_date`
- `source_payload_json`
- `note`
- `created_at`
- `updated_at`

接口：
- `GET /api/manual-selections?date=YYYY-MM-DD`
- `POST /api/manual-selections`
- `DELETE /api/manual-selections?date=YYYY-MM-DD&code=000001`
- `GET /api/manual-selections/dates`

### 2.2 前端列表勾选

改动：
- `web/frontend/src/api/index.ts`：新增人工选股 API。
- `web/frontend/src/stores/manualSelection.ts`：新增 Pinia store。
- `web/frontend/src/views/StockDetail.vue`：右侧列表每行增加勾选按钮，勾选后写入人工选股池，取消则删除。

## Phase 3：回测 MVP

### 3.1 后端回测服务

回测数据源：
- `manual`：人工选股池。
- `strategy`：策略结果缓存。

核心参数：
- `start_date`, `end_date`
- `source`: `manual | strategy`
- `strategy`: `all | b1 | b2 | bowl`
- `holding_days`
- `buy_offset_days`
- `buy_price`: `open | close`
- `sell_price`: `close | open`
- `fee_rate`
- `slippage_rate`
- `take_profit_pct`
- `stop_loss_pct`
- `max_positions_per_day`

输出：
- summary：交易数、胜率、平均收益、累计收益、最大回撤、平均持有天数。
- trades：逐笔交易明细。
- equity_curve：按卖出日期汇总的资金曲线。

### 3.2 前端回测页面

改动：
- `web/frontend/src/views/BacktestView.vue`
  - 左侧参数面板。
  - 顶部运行按钮。
  - 中部统计卡片。
  - 下方交易明细表。
  - 参数结构保持对象化，便于后续继续扩展。

## 验证

1. 前端类型检查：`cd web/frontend && npm run build` 或项目现有 test 命令。
2. 后端接口烟测：
   - 日期接口返回非空 `data`。
   - 人工选股 POST/GET/DELETE 可往返。
   - 回测接口返回 summary/trades/equity_curve。
3. 页面手动验证：
   - 详情页日期下拉有日期，切换后列表有数据。
   - 双击副图任意区域可放大/恢复。
   - 鼠标移动时右下角显示到最新 K 线涨跌结果。
   - 右侧列表勾选后刷新页面仍保留。
   - 回测页能选择人工选股或策略结果并跑出结果。
