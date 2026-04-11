# A股量化选股系统 — Web 界面开发计划

> 参考目标：TradingView（https://www.tradingview.com/symbols/NASDAQ-AAPL/）  
> 核心诉求：在网页上直观查看**策略选出的股票 K 线**、指标、以及未来的回测结果。

---

## 1. 产品目标

| 目标 | 说明 |
|------|------|
| 策略结果可视化 | B1 / B2 选股结果以列表 + K 线方式展示 |
| 数据实时感知 | 显示数据最后更新时间，支持手动触发更新 |
| 多策略对比 | 同一页面切换 B1 / B2 / 碗底策略结果 |
| 回测模块（预留） | 为未来的回测功能留接口，前端已有占位页 |

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

## 3. 页面详细设计

### 3.1 首页 `/`

- **策略标签栏**：`全部 | B1形态 | B2突破 | 碗底反弹`
- **股票列表**（表格）：
  - 代码 / 名称 / 最新收盘价 / 涨跌幅 / 策略得分 / 触发日期 / 市值
  - 支持：排序、按涨跌幅/市值过滤、关键词搜索
- **迷你 K 线缩略图**：每行右侧展示最近 30 日迷你 K 线（参考 TradingView 列表视图）
- **数据状态徽章**：显示最后数据更新时间，过期则警告

### 3.2 股票详情页 `/stocks/:code`

- **主 K 线区（参考 TradingView）**：
  - 日 / 周 K 线切换
  - 叠加均线（MA5 / MA10 / MA20 / MA60）
  - 成交量柱状图
  - **策略信号标注**：在 K 线上用箭头/标记标出 B1 / B2 触发点
- **指标面板**（下方子图）：
  - KDJ
  - MACD
  - RSI（可选）
- **策略详情卡片**：显示该股的匹配策略、相似度得分、触发条件描述
- **回测占位区（预留）**：显示"回测功能即将上线"的卡片入口

### 3.3 数据管理页 `/update`

- 显示各板块（00/30/60/68）数据更新状态
- **一键更新按钮**：调用后端 `/api/update`，前端 SSE 实时显示进度
- 显示数据新鲜度抽样报告（旧数据比例）

### 3.4 回测页 `/backtest`（预留模块）

- **输入区**：选择股票代码、起始日期、结束日期、策略
- **结果展示区**：
  - 净值曲线图（与沪深300对比）
  - 胜率 / 最大回撤 / 年化收益等指标卡片
  - 每笔交易明细表格
- **状态**：`MVP预留，接口已设计，逻辑待实现`

---

## 4. 技术方案

### 4.1 后端（Python）

| 层次 | 选型 | 说明 |
|------|------|------|
| Web 框架 | **FastAPI** | 已有 `web_server.py` 可迁移；异步性能好，SSE 天然支持 |
| 数据层 | 现有 CSV + `csv_manager.py` | 短期直接复用，无需改数据源 |
| K 线接口 | `/api/kline/:code?period=daily` | 返回 OHLCV JSON |
| 策略接口 | `/api/strategy/results?strategy=b1` | 返回当日选股列表 |
| 更新接口 | `POST /api/update`（SSE 推进度） | 调用 `AKShareFetcher.daily_update()` |
| 回测接口（预留） | `POST /api/backtest` | 接口已设计，逻辑后续填充 |

### 4.2 前端

| 层次 | 选型 | 说明 |
|------|------|------|
| 框架 | **Vue 3 + Vite** | 轻量，快速启动 |
| UI 库 | **Element Plus** | 已成熟，表格/筛选组件完善 |
| K 线图 | **Apache ECharts** (`echarts` + `echarts-gl`) | 国内数据库对 ECharts 支持最好；支持 K 线、成交量、指标叠加 |
| 迷你缩略图 | ECharts 小实例（`renderer: 'svg'`） | 轻量，每行渲染一个 |
| 状态管理 | Pinia | Vue 3 标准 |
| HTTP 客户端 | axios | 统一封装 |

> **为什么选 ECharts 而非 TradingView Lightweight Charts？**  
> ECharts 对中文标注、策略信号箭头、自定义 Tooltip 支持更灵活，且无 GPL 限制。

### 4.3 部署

```
Nginx (反向代理)
  ├── /api/*  → FastAPI (uvicorn)  :8000
  └── /*      → Vue 3 静态构建产物 (dist/)
```

---

## 5. API 接口设计

```
GET  /api/strategy/results          # 获取当日所有策略选股结果
     ?strategy=b1|b2|bowl|all
     ?date=YYYY-MM-DD               # 默认最近交易日

GET  /api/kline/:code               # 获取 K 线数据
     ?period=daily|weekly
     ?limit=250                     # 返回条数

GET  /api/stock/list                # 所有股票列表（代码+名称）

GET  /api/data/status               # 数据新鲜度报告

POST /api/update                    # 触发数据更新（SSE 流式返回进度）

POST /api/backtest (预留)           # 回测接口
     body: {code, start, end, strategy}

GET  /api/backtest/:taskId (预留)   # 查询回测任务状态
```

---

## 6. K 线图策略信号标注方案

参考 TradingView 的 `markPoint`，在 ECharts K 线系列上叠加：

```js
// ECharts markPoint 示例（B1信号箭头）
series: [{
  type: 'candlestick',
  markPoint: {
    data: b1Signals.map(d => ({
      coord: [d.date, d.low * 0.98],
      value: 'B1',
      itemStyle: { color: '#f5222d' },
      symbol: 'arrow', symbolRotate: 180
    }))
  }
}]
```

---

## 7. 开发阶段

| 阶段 | 任务 | 状态 |
|------|------|------|
| **Phase 1** | FastAPI 后端骨架 + K线/策略接口 | 待开始 |
| **Phase 2** | Vue 3 项目初始化 + ECharts K线组件 | 待开始 |
| **Phase 3** | 首页列表 + 迷你K线 + 策略筛选 | 待开始 |
| **Phase 4** | 股票详情页 + 信号标注 + 指标面板 | 待开始 |
| **Phase 5** | 数据更新页 + SSE 进度推送 | 待开始 |
| **Phase 6** | 部署配置（Nginx + uvicorn） | 待开始 |
| **Phase 7（预留）** | 回测页面完整实现 | 预留接口 |

---

## 8. 目录结构规划

```
web/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── routers/
│   │   ├── strategy.py      # 策略选股接口
│   │   ├── kline.py         # K线数据接口
│   │   ├── update.py        # 数据更新 SSE 接口
│   │   └── backtest.py      # 回测接口（预留，返回501）
│   └── services/
│       ├── kline_service.py   # 调用 csv_manager 转 JSON
│       └── strategy_service.py # 调用 quant_system 获取结果
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── HomeView.vue       # 首页选股列表
│   │   │   ├── StockDetail.vue    # 详情 K线页
│   │   │   ├── UpdateView.vue     # 数据更新页
│   │   │   └── BacktestView.vue   # 回测页（预留）
│   │   ├── components/
│   │   │   ├── KlineChart.vue     # ECharts K线组件
│   │   │   ├── MiniKline.vue      # 迷你缩略K线
│   │   │   └── StockTable.vue     # 可排序/筛选列表
│   │   └── api/
│   │       └── index.ts           # axios 封装
│   └── vite.config.ts
└── nginx.conf
```

---

## 9. 回测模块预留说明

回测接口已在 Phase 1 中占位（返回 HTTP 501 Not Implemented），前端已有路由和页面框架。  
当 `utils/backtrace_analyzer.py` 的逻辑完善后，只需：
1. 实现 `POST /api/backtest` 接口逻辑
2. 前端 `BacktestView.vue` 接入接口即可激活

---

## 10. 技术与逻辑说明

### 10.1 产品目标与技术实现

| 目标             | 技术与逻辑                                                                 |
|------------------|----------------------------------------------------------------------------|
| 策略结果可视化   | 后端：FastAPI 提供 `/api/strategy/results` 接口，返回选股结果；前端：Vue 3 渲染表格与 K 线图，使用 ECharts 实现动态图表。 |
| 数据实时感知     | 后端：FastAPI 提供 `/api/data/status` 接口，返回数据更新时间；前端：通过定时轮询或 SSE 实现实时更新。 |
| 多策略对比       | 后端：策略逻辑封装在 `strategy_service.py` 中，支持多策略切换；前端：通过 Vue 组件动态渲染不同策略结果。 |
| 回测模块（预留） | 后端：预留 `/api/backtest` 接口，调用回测逻辑；前端：占位页面，待逻辑完善后接入。                     |

### 10.2 页面结构与技术实现

| 页面             | 技术与逻辑                                                                 |
|------------------|----------------------------------------------------------------------------|
| 首页 `/`         | 后端：FastAPI 提供策略结果接口；前端：Vue 3 渲染表格，ECharts 渲染迷你 K 线图。                     |
| 股票详情页 `/stocks/:code` | 后端：FastAPI 提供 `/api/kline/:code` 接口，返回 K 线数据；前端：ECharts 渲染主图与指标图，支持动态切换。 |
| 数据管理页 `/update` | 后端：FastAPI 提供 `/api/update` 接口，触发数据更新；前端：通过 SSE 显示更新进度。                 |
| 参数配置页 `/settings` | 后端：读取配置文件（如 `config.yaml`）；前端：表单组件动态绑定参数，支持保存与重置。               |
| 回测页 `/backtest`（预留） | 后端：预留回测接口；前端：占位页面，待逻辑完善后接入。                                     |

### 10.3 技术栈与逻辑说明

| 层次             | 技术栈与逻辑                                                             |
|------------------|------------------------------------------------------------------------|
| 后端             | FastAPI 提供 RESTful API；使用 `csv_manager.py` 处理数据；策略逻辑封装在 `strategy_service.py` 中。 |
| 前端             | Vue 3 + Vite 构建；使用 Element Plus 提供 UI 组件；ECharts 渲染图表；Pinia 管理状态。               |
| 部署             | 使用 Nginx 作为反向代理；后端通过 Gunicorn 部署；前端静态文件托管在 Nginx。                       |
| 测试             | 后端：使用 `pytest` 进行单元测试；前端：使用 `Jest` 和 `Cypress` 进行组件测试与端到端测试。         |

---

*文档创建时间：2026-04-12*
