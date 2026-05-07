# 回测任务取消与详情抽屉阶段记忆

## 任务边界

本阶段只处理回测异步任务的用户可控性与可观察性：

- 增加取消任务能力。
- 增加任务详情抽屉。
- 保持现有 `/api/backtest/tasks` 异步 API 主结构不大改。
- 不改变现有回测撮合、收益统计、人工选股池导入规则。

## 实现摘要

### 后端

- 在 `BacktestJobManager` 增加 `cancel(task_id)`。
- 新增任务状态：
  - `cancel_requested`：运行中任务已收到取消请求，等待下一次进度边界停止。
  - `canceled`：任务已取消，属于终态。
- 排队任务通过 `Future.cancel()` 直接取消，不进入 runner。
- 运行中任务通过 `progress_callback` 检查取消状态，在候选处理边界抛出内部取消异常。
- 取消事件写入 `backtest_task_events`：
  - `cancel_requested`
  - `canceled`
- 新增接口：`POST /api/backtest/tasks/{task_id}/cancel`。

### 前端

- API 客户端增加 `cancelBacktestTask(taskId)`。
- 回测任务面板增加当前任务取消入口。
- 任务历史表增加每行详情和可取消任务的取消入口。
- 新增任务详情抽屉，展示：
  - 任务 ID、状态、进度
  - 提交/开始/结束时间
  - 当前代码
  - 结果摘要
  - 任务参数 JSON
  - 事件流
- 前端轮询将 `canceled` 作为终态，`cancel_requested` 作为继续轮询状态。

## 正确性推导

- 回测任务不能被强制杀线程，所以取消点放在进度回调边界。
- 当前回测执行按候选股票推进，进度回调天然是低成本边界，不需要给每个撮合函数都塞取消判断。
- 排队任务还没进入线程执行，可以直接取消 Future，避免占用回测资源。
- 运行中任务如果没有马上停，是因为正在处理当前候选；下一次回调会停止并标记为 `canceled`。
- 取消状态和事件都持久化，页面刷新后仍可看到任务结论和取消记录。

## 验证结果

- 红灯验证：
  - 先新增运行中取消、排队取消、取消 API 测试。
  - 初次运行失败于 `BacktestJobManager.cancel` 缺失和取消路由 404。
- 绿灯验证：
  - `python -m pytest tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q`
  - 结果：14 passed。
- 回测相关扩展验证：
  - `python -m pytest tests/test_backtest_job_service.py tests/test_backtest_router_async.py tests/test_backtest_service.py tests/test_backtest_engine.py tests/test_strategy_service_backtest_dates.py -q`
  - 结果：28 passed。
- 导入 smoke：
  - 回测路由、任务管理器、仓储、全局 job manager 均可导入。
- 前端验证：
  - `npm run build`
  - 结果：`vue-tsc -b && vite build` 通过。

## 下一步计划

1. 回测任务详情继续增强：
   - 支持任务参数一键复跑。
   - 支持按任务导出交易明细 CSV/TXT。
   - 支持任务事件筛选，只看 warning/error。

2. 回测执行正确性继续增强：
   - 对分钟线买入/卖出时间加入更细的成交价兜底。
   - 对涨跌停、停牌、无成交量边界增加更多样本测试。
   - 把取消检查下沉到更细的执行循环，减少单个候选过慢时的等待。

3. 性能与可观察性：
   - 记录每只股票回测耗时。
   - 在详情抽屉中展示慢候选排名。
   - 对长任务提供估算剩余时间。

4. 重启恢复边界：
   - 本阶段已处理“服务重启后没有内存 Future 的未完成任务可取消”。
   - 后续可增加启动时扫描未完成任务，把历史 queued/running 统一标记为 interrupted，避免用户误以为仍在运行。
