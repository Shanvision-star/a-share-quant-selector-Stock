# Tracking Phase 2 记录（2026-05-08）

## 本阶段目标

把单股跟踪从“能保存、能评估”推进到“更接近回测引擎的动态放飞逻辑”，同时让前端能查看单条跟踪记录的意图、参数和事件流。

## 已解决的问题

1. 原跟踪逻辑达到 `profit_trigger_pct` 就立刻部分卖出，没有等待 `profit_step_pct` 阶梯。
2. 同一个评估日重复点击“评估”会再次扣减 `remaining_pct`，可能造成误导。
3. 前端表格只有汇总状态，无法查看最新 `OrderIntent` 和事件流，不利于复盘。

## 实现逻辑

1. `runner_triggered` 写入 `params`，表示已进入放飞跟踪。
2. `next_profit_ladder_pct` 写入 `params`，表示下一次允许部分卖出的阶梯涨幅。
3. 首次达到触发线只进入 `HOLD_RUNNER`，不立刻卖出。
4. 达到阶梯涨幅后才生成 `SELL_PARTIAL` 意图，并按 `profit_sell_pct` 扣减剩余仓位，不能低于 `profit_keep_pct` 底仓。
5. 如果 `last_eval_date` 等于本次评估日，直接返回当前记录，避免同日重复评估继续扣仓。
6. 前端新增单股跟踪详情抽屉，展示状态、最新意图、参数和事件流。

## 验证

1. `python -m pytest tests/test_tracking_service.py tests/test_tracking_router.py -q`
   - 7 个用例通过。
2. `npm run test -- src/views/__tests__/backtestState.spec.ts src/api/__tests__/trackingApi.spec.ts --run`
   - 5 个用例通过。
3. `npm run build`
   - 通过，保留既有 Vite 大 chunk 警告。

## 下一步计划

1. 把 tracking 的退出规则继续对齐回测引擎：短期趋势破位、多空线破位、无收益退出、止损。
2. 给跟踪记录增加“手动关闭/归档”能力，防止长期表格堆积。
3. 引入分钟线跟踪评估时，只生成盘中买卖意图，不接真实券商下单。
