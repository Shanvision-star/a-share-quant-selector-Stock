# 回测 API 和前端工作台更新

**日期：** 2026年4月26日

## 概述
本文档记录了近期对A股量化选股系统的回测API和前端工作台所做的更新和更改。

---

## 后端更新

### 文件：`web/backend/routers/backtest.py`

1. **新增功能：**
   - 在回测API中增加了对逐行候选个股选择的支持。
   - 引入了高级止盈和止损逻辑，新增以下参数：
     - `take_profit_pct`：可选参数，用于设置止盈百分比。
     - `stop_loss_pct`：可选参数，用于设置止损百分比。
     - `profit_run_enabled`：布尔值，启用利润追踪逻辑。
     - `profit_trigger_pct`，`profit_step_pct`，`profit_sell_pct`：配置利润追踪行为的参数。
     - `enable_no_gain_exit`，`no_gain_days`：设置无收益退出的天数。
     - `exit_on_bull_bear_break`，`exit_on_short_trend_break`，`short_trend_break_days`：基于趋势突破退出的参数。
     - `exit_on_short_trend_drawdown`，`short_trend_drawdown_pct`：基于短期趋势回撤退出的参数。
   - 使用 `pydantic` 增强了输入参数的验证。

2. **错误处理：**
   - 增加了验证逻辑，确保 `start_date` 不晚于 `end_date`。

3. **API端点：**
   - `POST /api/backtest`：同步回测端点，返回摘要、交易明细和资金曲线。
   - `GET /api/backtest/{task_id}`：异步任务查询的占位符（当前版本未实现）。

---

## 前端更新

### 文件：`web/frontend/src/views/BacktestView.vue`

1. **新增功能：**
   - 集成了逐行候选个股选择功能。
   - 增加了高级控制，用于配置止盈和止损逻辑。
   - 更新了UI以支持新的后端参数，包括：
     - 止盈和止损百分比。
     - 利润追踪配置（触发、步进和卖出百分比）。
     - 无收益退出设置。
     - 基于趋势突破和回撤的退出条件。

2. **增强功能：**
   - 改善了参数输入和验证的用户体验。
   - 增强了图表渲染功能，以显示详细的回测结果。

---

## 验证

1. **后端验证：**
   - 验证了更新后的API在各种测试用例中返回正确结果。
   - 确保了对无效输入参数的正确处理。

2. **前端验证：**
   - 确认了新后端功能的成功集成。
   - 测试了工作台的运行时行为和UI响应。

---

## 下一步

1. 完成边界情况的运行时验证。
2. 继续监控实际使用中的潜在问题。
3. 规划未来的增强功能，包括支持异步回测。

---

**作者：** GitHub Copilot

本文档记录了回测API和前端工作台更新的更改和实现细节。