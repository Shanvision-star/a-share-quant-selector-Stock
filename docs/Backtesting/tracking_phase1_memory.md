# 单股跟踪 Tracking Phase 1 记忆

## 本阶段目标

把“单股回测”升级为“单股跟踪”的第一层能力：

- 回测仍负责历史模拟。
- tracking 负责从当前开始持续跟踪某只股票。
- tracking 只生成建议和 `OrderIntent`，不触达券商，不自动下单。

## 已实现内容

### 后端

新增独立模块：

- `web/backend/services/tracking_service.py`
- `web/backend/routers/tracking.py`

新增 SQLite 表：

- `tracking_items`：跟踪主表。
- `tracking_events`：跟踪事件流。

核心状态：

- `watch_buy`：待买入观察。
- `holding`：已生成买入意图并进入持有跟踪。
- `partial_sold`：达到放飞阈值后生成部分卖出建议。
- `closed`：预留结束状态。

核心接口：

- `POST /api/tracking`：创建单股跟踪。
- `GET /api/tracking`：查询跟踪列表。
- `GET /api/tracking/{tracking_id}`：查询单条跟踪。
- `POST /api/tracking/{tracking_id}/evaluate`：评估单条跟踪。
- `POST /api/tracking/evaluate`：批量评估未结束跟踪。
- `GET /api/tracking/{tracking_id}/events`：查询跟踪事件流。

### 评估逻辑

第一版只做低风险、可解释规则：

1. `watch_buy`：
   - 根据信号日和 `buy_offset_days` 找买入交易日。
   - 到达买入交易日后生成 `BUY` OrderIntent。
   - 状态转为 `holding`。

2. `holding` / `partial_sold`：
   - 计算最新收盘相对买入价收益。
   - 达到 `profit_trigger_pct` 后生成 `SELL` 部分卖出 OrderIntent。
   - 按 `profit_sell_pct` 减少剩余仓位。
   - 不低于 `profit_keep_pct` 保留底仓。

### 前端

在回测工作台增加：

- 候选列表行内“加入跟踪”按钮。
- 交易明细行内“加入跟踪”按钮。
- “单股跟踪”面板。
- 跟踪列表展示：
  - 代码、名称、状态、建议、买入价、收益、剩余仓位、评估日。
- 单条“评估”按钮。
- 批量“评估跟踪”按钮。

## 推导逻辑

tracking 不应该继续塞进 backtest：

- backtest 是历史模拟，一次请求产出结果。
- tracking 是状态机，需要持久化、每日推进、事件流。
- 后续接券商时，tracking 输出的 `OrderIntent` 可以交给 broker adapter，但 tracking 本身不应该直接下单。

因此本阶段选择新建 `tracking_items` 和 `tracking_events`，让它和回测共享参数、行情和 `OrderIntent` 模型，但不共享任务生命周期。

## 验证

### 红灯

先写失败测试：

- `tests/test_tracking_service.py`
  - 创建跟踪记录。
  - 评估待买入记录生成 BUY 意图。
  - 持有状态达到放飞阈值生成部分 SELL 意图。
- `tests/test_tracking_router.py`
  - 创建、列表、评估、事件流 API。
- `web/frontend/src/api/__tests__/trackingApi.spec.ts`
  - 前端 tracking API 调用。

初次失败原因符合预期：

- `tracking_service` 不存在。
- `tracking` router 不存在。
- 前端 tracking API 函数不存在。

### 绿灯

执行：

```text
python -m pytest tests/test_tracking_service.py tests/test_tracking_router.py tests/test_backtest_service.py tests/test_backtest_engine.py -q
```

结果：

```text
16 passed
```

执行：

```text
npm run test -- src/api/__tests__/trackingApi.spec.ts src/api/__tests__/backtestApi.spec.ts --run
```

结果：

```text
2 files passed, 7 tests passed
```

执行：

```text
npm run build
```

结果：构建通过。仅有 Vite chunk size 警告，不影响本阶段功能。

执行：

```text
python -m py_compile web/backend/services/tracking_service.py web/backend/routers/tracking.py web/backend/main.py
```

结果：通过。

执行导入 smoke：

```text
from web.backend.routers.tracking import router
from web.backend.services.tracking_service import TrackingService, tracking_service
```

结果：通过。

## 当前边界

- 不自动实盘下单。
- 不连接 QMT 或任何券商接口。
- 只按日线做跟踪评估。
- 卖出规则第一版只覆盖放飞部分卖出，完整止损/趋势破位会在后续阶段补齐。
- 当前运行中的旧后端如果没有重启，不会有 `/api/tracking` 接口；前端会提示后端需更新。

## 下一步计划

1. Tracking Phase 2：
   - 增加止损、跌破黄线、跌破短趋势线、N 天不涨退出规则。
   - 增加跟踪详情抽屉，展示事件流和 OrderIntent。
   - 增加关闭跟踪、手动确认买入/卖出动作。

2. Tracking Phase 3：
   - 数据更新后自动批量评估跟踪池。
   - 跟踪建议进入一个“待执行清单”。
   - 为未来券商接入预留执行适配器，但仍默认人工确认。

3. 回测模块联动：
   - 从回测结果批量筛选收益/回撤符合条件的股票加入 tracking。
   - 对 tracking 规则反向生成回测参数模板。
