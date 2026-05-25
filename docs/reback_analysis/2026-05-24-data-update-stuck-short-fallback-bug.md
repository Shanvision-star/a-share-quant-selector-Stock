# 2026-05-24 数据更新长时间停留与慢路径全失败复盘

## 现象

- 页面：`/update`
- 阶段：数据更新 `update`
- 页面显示：`更新超时：慢路径已执行 3580/5155，累计完成 3580/5155，成功 0，失败 3580`
- 慢路径原因主要为：`短窗快补失败转慢路径 5022`

## 证据链

1. 单独调用 `_update_single_stock('600908', 10, {})`、`_update_single_stock('002007', 10, {})` 均返回 `False`。
2. 拆开数据源后，EastMoney 返回连接错误，但新浪和 Baostock 对 `002007` 均能返回 20 行数据。
3. 直接调用 `csv_manager.update_stock('002007', df)` 复现异常：
   `TypeError: Invalid value '[]' for dtype 'float64'`。
4. 异常发生在 `utils/csv_manager.py` 的换手率补全逻辑：
   当 `turnover_missing` 全为 `False` 时，仍执行空序列赋值，pandas 新版本会抛错。

## 根因

本次问题不是“所有外部数据源都失败”，而是两个问题叠加：

1. EastMoney 当前网络不可达，导致短窗快补大量失败并转入慢路径。
2. 慢路径实际能从新浪/Baostock 获取数据，但 CSV 写入阶段因为空 mask 赋值异常失败；`_update_single_stock` 原来吞掉异常，前端只能看到成功 0、失败持续增加。
3. 慢路径触发超时后，代码仍处于 `with ThreadPoolExecutor(...)` 上下文，退出时会默认等待未完成线程；即使页面已经显示“更新超时”，SSE 仍可能被少量挂起任务拖住，表现为“一直在更新”。

## 修复方案

1. `CSVManager.update_stock` 在补 `amount` 和 `turnover` 前增加 `mask.any()` 判断；没有需要补的行时直接跳过赋值。
2. `fetch_stock_update` 增加 `prefer_fast_fallback` 参数。短窗已确认 EastMoney 失败后，慢路径跳过 EastMoney，优先使用新浪快通道，再用 Baostock 兜底。
3. `_update_single_stock` 记录单股更新异常，避免后续只有前端失败数、没有后端根因。
4. 慢路径超时后取消未完成 future，并使用 `shutdown(wait=False, cancel_futures=True)` 退出，避免 SSE 被线程池上下文继续阻塞。
5. `agent.md` 记录该边界：短窗失败转慢路径后不能重复等待 EastMoney；CSV 字段补全必须 guard 空 mask；慢路径超时不能继续等待线程池。

## 验证

- 红灯测试：`tests/test_csv_manager.py::test_update_stock_all_false_turnover_mask_does_not_raise` 先复现 `Invalid value '[]' for dtype 'float64'`。
- 修复后测试通过。
- 单股实测：
  - 普通慢路径：`002007` 成功，约 1.56 秒。
  - 短窗失败后的快兜底：`002007` 成功，约 0.08 秒。
- 合并前验证：`python -m pytest tests/test_csv_manager.py tests/test_daily_update_fast_path.py tests/test_data_service_update_date.py -q`，结果 `16 passed`。
- 后端导入 smoke：`python -c "import web.backend.main as main; print(type(main.app).__name__)"`，结果 `FastAPI`。
- 2026-05-25 补充验证：新增慢路径超时回归测试，相关测试结果 `17 passed`。
- 2026-05-25 单股快兜底抽样：`688809`、`600908`、`002007`、`300750`、`603289` 均成功，耗时约 `0.09-0.17s`。

## 后续风险

- 新浪快通道成交额/换手率字段可能为空；当前 CSV 层会用 `close * volume * 100` 估算成交额，换手率在缺市值时保持 0。
- 如果未来策略强依赖换手率，建议单独做“市值派生股本 + 换手率估算”任务，而不是阻塞每日 K 线更新。

## 2026-05-25 追加复盘：重复启动导致批量失败

### 现象

- 页面再次显示：慢路径 `4600/4612`，成功 `171`，失败 `4429`。
- 页面同时显示“市值缓存初始化中，K线更新会继续推进”。

### 新证据

1. 单独调用 `fetch_stock_update('688800', prefer_fast_fallback=True)` 能拿到 `2026-05-22` 的 20 行日 K。
2. 单独调用 `_update_single_stock('688800', 10, {}, prefer_fast_fallback=True)` 能成功写入 CSV。
3. SQLite `strategy_runs` 中同时存在多个 `status='running'` 的 `update_and_rebuild` run，例如 `20260525_003931_0e21f156` 与 `20260525_010310_8ed9e85f`。
4. 启动清理后，旧 running 更新任务被统一标记为 `error`，`running update count = 0`。

### 结论

失败 4429 不是市值更新导致。市值缓存只是后台维护状态，K 线更新会先用缓存继续推进。

更直接的根因是：页面允许重复启动全市场更新，旧 run 和新 run 会同时抓取并写入同一批 CSV。多 run 叠加后会造成：

- 同一个 CSV 文件被多个任务抢写。
- 新浪/Baostock/EastMoney 请求被并发放大，触发超时或限流。
- 前端只展示当前 run 的计数，容易误判为单个任务内部失败。

### 补充修复

1. `web/backend/services/data_service.py` 增加 `_UPDATE_JOB_LOCK` 和 `_UPDATE_JOB_STATE`，同一进程只允许一个 `/api/update` 运行。
2. 重复启动时后端返回 `status='busy'`，并带上 `active_run_id`。
3. `web/frontend/src/stores/updateJob.ts` 把 `busy` 当作终止态处理，停止本地转圈并显示错误信息。
4. `web/backend/main.py` 启动时调用 `mark_stale_update_runs_interrupted()`，把旧进程遗留的 running 更新任务标记为中断。

### 补充验证

- 红灯测试：
  - `tests/test_data_service_update_date.py::test_run_data_update_rejects_overlapping_jobs`
  - `tests/test_data_service_update_date.py::test_mark_stale_update_runs_interrupted`
  - `web/frontend/src/stores/__tests__/updateJob.spec.ts`
- 修复后验证：
  - `python -m pytest tests/test_csv_manager.py tests/test_daily_update_fast_path.py tests/test_data_service_update_date.py tests/test_strategy_cache_status.py -q`，结果 `20 passed`。
  - `npm run test -- updateJob --run`，结果 `1 passed`。
  - `npm run build` 通过。
  - `start_dev.bat` 启动后，`/api/health` 返回 `ok`；SQLite 中 running 更新任务数量为 `0`。

## 2026-05-25 追加复盘：执行完不等于数据完整

### 现象

- 最新 `/api/update` run 在 SQLite 中显示 `status='done'`，并进入策略重建。
- 但 `/api/data/status` 仍显示大量股票停留在 `2026-05-19`，只有部分 CSV 到达 `2026-05-22`。
- `.update_cache.json` 仍停留在旧日期，说明缓存并没有确认全量完成。

### 根因

`utils/akshare_fetcher.py::daily_update()` 原来的完成判定把 `all_done` 当成成功：

- `all_done=True` 只表示慢路径线程池里的 future 都已经返回。
- 如果 future 返回 `False`，`failed` 会增加，但最终仍可能进入 `return build_summary('done', ...)`。
- 抽样验证不达标时只是不写缓存，最终状态仍可能是 `done`。
- `web/backend/services/data_service.py` 只把 `status='error'` 当失败，收到 `partial` 时仍会继续自动策略重建。

因此前端会看到“统一作业完成”，但本地 CSV 实际只更新了部分股票，策略结果也可能基于不完整数据。

### 修复

1. 慢路径记录第一轮失败股票集合，全部 future 返回后对失败集合进行一次低并发重试，降低外部接口瞬时断连造成的大批量失败。
2. `daily_update` 的成功条件收紧为：`all_done and failed == 0 and verification_passed`。
3. 只要仍有最终失败或抽样验证未通过，就返回 `status='partial'`，不写 `.update_cache.json`。
4. `data_service` 把 `partial` 当成终止态，写入 run `error`，SSE 返回 `event='error'` 和 `update_status='partial'`，不进入策略重建。
5. `agent.md` 写入长期规则：以后不能把“线程池执行完”当成“数据完整”。

### 验证

- 红灯测试：
  - `tests/test_daily_update_fast_path.py::test_daily_update_returns_partial_when_completed_tasks_still_have_failures`
  - `tests/test_daily_update_fast_path.py::test_daily_update_retries_transient_slow_path_failures_before_partial`
  - `tests/test_data_service_update_date.py::test_run_data_update_stops_rebuild_when_update_is_partial`
- 修复后验证：
  - 上述 3 个测试通过。
  - `python -m pytest tests/test_csv_manager.py tests/test_daily_update_fast_path.py tests/test_data_service_update_date.py tests/test_strategy_cache_status.py -q`，结果 `23 passed`。
  - `python -c "import web.backend.main as main; print(type(main.app).__name__)"`，结果 `FastAPI`。
