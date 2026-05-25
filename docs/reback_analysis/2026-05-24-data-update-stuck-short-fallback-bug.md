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

## 2026-05-25 追加复盘：短窗批量 EastMoney 与坏 CSV 行

### 现象

- 页面显示：`短窗快补 0/4096`、`慢路径 4168`、`成功 93`、`失败 4075`。
- 抽样单股 `002529`、`002534`、`300001`、`600000`、`688800` 走 `prefer_fast_fallback=True` 都能在约 `0.05-0.13s` 内拿到 `2026-05-22` 并写入。
- `000838` 单股写入失败，异常为 `time data "001" doesn't match format "%Y-%m-%d"`。
- 扫描本地 CSV 后发现 `93` 个文件存在坏日期行，约 `4080` 个文件仍落后于 `2026-05-22`。

### 根因

1. EastMoney 精确短窗接口在当前网络下不稳定；全市场 4000+ 股票逐股先尝试短窗，会把时间浪费在同一失败源上。
2. 即使后续新浪兜底可用，前面的大批 EastMoney 失败会造成更新时间过长、状态混乱和失败放大。
3. 部分历史 CSV 混入坏日期行，`CSVManager.update_stock()` 原来直接 `pd.to_datetime(existing_df['date'])`，遇到坏行就抛异常，导致该股票更新失败。

### 修复

1. 大批量短窗缺口直接跳过 EastMoney 精确短窗，整批转入新浪/Baostock 快兜底慢路径。
2. 小批量短窗仍保留 EastMoney 精确窗口，避免完全丢掉原来的高质量通道。
3. `CSVManager.update_stock()` 合并前用 `errors='coerce'` 清洗坏日期行；新数据若日期无效则不写，历史坏行不再阻断整只股票更新。
4. `agent.md` 写入规则：短窗批量不能逐股打 EastMoney；CSV 合并必须清洗坏日期行。

### 验证

- 红灯测试：
  - `tests/test_csv_manager.py::test_update_stock_drops_malformed_existing_date_rows`
  - `tests/test_daily_update_fast_path.py::test_daily_update_short_gap_health_gate_skips_bulk_eastmoney_failures`
- 修复后验证：
  - 上述 2 个测试通过。
  - 更新链路回归：`python -m pytest tests/test_csv_manager.py tests/test_daily_update_fast_path.py tests/test_data_service_update_date.py tests/test_strategy_cache_status.py -q`，结果 `25 passed`。
  - 临时复制 80 只 `2026-05-19` stale CSV 完整跑 `daily_update(date='2026-05-22')`：`80/80` 成功，耗时约 `11.8s`，并写入 `2026-05-22`。

## 2026-05-25 追加复盘：混合日期格式导致合法历史行被误删

### 现象

- 页面仍显示：`检查 5157/5157`、`执行 4168/4168`、`成功 93`、`失败 4075`。
- 本地真实文件 `data/60/600106.csv` 同时存在：
  - `2026-04-23`
  - `2026-04-22 00:00:00.000000`
  - `2026-04-20 09:01:53.578508`
- 用 pandas 默认 `pd.to_datetime(..., errors='coerce')` 解析该文件时，`2212` 行里有 `2211` 行被误判为坏日期；使用 `format='mixed'` 后坏日期为 `0`。

### 根因

上一轮只处理了 `001` 这类明显坏日期，但没有处理“同一列混合纯日期和时间戳”的历史 CSV。pandas 会根据首行推断日期格式，如果首行是 `YYYY-MM-DD`，后面带微秒的合法时间戳可能被当成 `NaT`。

这会在批量更新时产生两个连锁问题：

1. 合法历史行被当成坏行清掉，导致 CSV 合并结果异常。
2. 单股数据源即使已经返回可用 K 线，写入层仍可能失败或变慢，前端就会看到几千只失败。

### 修复

1. `CSVManager` 新增混合日期解析逻辑：先把 date 转成字符串并要求以 `YYYY-MM-DD` 开头，再调用 `pd.to_datetime(..., format='mixed', errors='coerce')`。
2. pandas 低版本不支持 `format='mixed'` 时回退到旧解析，避免环境启动失败。
3. 写回 CSV 前统一归一化为 `YYYY-MM-DD`，避免日线文件继续混入 `00:00:00.000000`。
4. 保留 `001`、空值、错列数字的清洗规则，避免 mixed 解析把 `001` 误判成公元 1 年。

### 验证

- 红灯测试：
  - `tests/test_csv_manager.py::test_update_stock_accepts_mixed_existing_datetime_formats` 先失败，原因是旧逻辑只保留 2 行，丢掉合法时间戳行。
- 修复后验证：
  - `python -m pytest tests/test_csv_manager.py -q`，结果 `3 passed`。
  - `python -m pytest tests/test_csv_manager.py tests/test_daily_update_fast_path.py tests/test_data_service_update_date.py tests/test_strategy_cache_status.py -q`，结果 `26 passed`。
  - import smoke：`utils.csv_manager`、`utils.akshare_fetcher`、`web.backend.main` 均导入成功。
  - 真实数据样本：`600106` 默认解析坏行 `2211`，mixed 解析坏行 `0`；`000838` 的 `001` 仍被识别为坏行。
  - 临时复制 20 只真实 mixed/stale CSV 跑 `daily_update(date='2026-05-22')`：`20/20` 成功，抽样验证 `9/9`，耗时约 `39.7s`。

### 结论

这轮失败不是市值缓存导致。市值接口在当前网络下仍可能失败，但 K 线更新可以继续使用缓存或缺省市值推进。真正会把批量更新放大成几千只失败的是：

1. 短窗批量逐股打 EastMoney。
2. 历史 CSV 中明显坏日期行未清洗。
3. 历史 CSV 中混合日期格式未按 mixed 解析。

后续如果还要继续提速，应单独做“短窗 1-5 天批量快补直接走新浪/Baostock 并头插缺失行”，减少全量 `update_stock` 合并成本。

## 2026-05-25 追加复盘：Baostock 兜底被高并发打入失败

### 现象

- 页面最新 run `20260525_211224_ecb9599f` 显示：
  - 快路径：`1107/1107` 成功。
  - 短窗快补：`0/3994`，整批转慢路径。
  - 慢路径累计失败超过 `3000` 只。
- 此时服务已经是新代码，因为快路径和短窗批量分流都生效了。

### 新证据

单独抽样 `002674`、`300001`、`600000`、`688088` 执行：

```python
fetch_stock_update(code, days=10, prefer_fast_fallback=True)
```

均可拿到 `2026-05-25` 的 20 行数据。日志显示新浪接口先返回非 JSON，随后 Baostock 登录/查询成功。

### 根因

这次不是“没有数据”，而是短窗整批转慢路径后仍使用默认 `16` 路并发。当前网络下新浪快通道会先失败，批量任务就集中落到 Baostock；Baostock 每股 `login/query/logout` 不适合高并发，16 路会放大登录失败和熔断，形成“单股成功、批量失败”的现象。

### 修复

1. 短窗整批转慢路径且数量达到全市场批量级别时，将慢路径并发从 `16` 降为 `4`。
2. 普通大缺口慢路径仍保留原并发，避免把所有场景都拖慢。
3. 进度文案显示实际慢路径并发，方便以后从页面判断是否进入 Baostock 保护模式。
4. `agent.md` 写入规则：Baostock 是兜底源，不是高并发源。

### 验证

- 红灯测试：
  - `tests/test_daily_update_fast_path.py::test_daily_update_throttles_bulk_short_gap_fallback_concurrency`
  - 旧代码下 `max_active == 16`，测试失败。
- 修复后验证：
  - 上述测试通过，`max_active <= 4`。
  - 更新链路回归：`python -m pytest tests/test_daily_update_fast_path.py tests/test_csv_manager.py tests/test_data_service_update_date.py tests/test_strategy_cache_status.py -q`，结果 `27 passed`。
  - import smoke：`utils.akshare_fetcher`、`web.backend.main` 均导入成功。

### 后续提速方向

这个修复优先解决“批量失败”。如果要继续压缩全市场补数时间，下一步应做 Baostock 单连接批量查询或短窗缺口批量写入，而不是重新把并发提高。
