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

## 修复方案

1. `CSVManager.update_stock` 在补 `amount` 和 `turnover` 前增加 `mask.any()` 判断；没有需要补的行时直接跳过赋值。
2. `fetch_stock_update` 增加 `prefer_fast_fallback` 参数。短窗已确认 EastMoney 失败后，慢路径跳过 EastMoney，优先使用新浪快通道，再用 Baostock 兜底。
3. `_update_single_stock` 记录单股更新异常，避免后续只有前端失败数、没有后端根因。
4. `agent.md` 记录该边界：短窗失败转慢路径后不能重复等待 EastMoney；CSV 字段补全必须 guard 空 mask。

## 验证

- 红灯测试：`tests/test_csv_manager.py::test_update_stock_all_false_turnover_mask_does_not_raise` 先复现 `Invalid value '[]' for dtype 'float64'`。
- 修复后测试通过。
- 单股实测：
  - 普通慢路径：`002007` 成功，约 1.56 秒。
  - 短窗失败后的快兜底：`002007` 成功，约 0.08 秒。
- 合并前验证：`python -m pytest tests/test_csv_manager.py tests/test_daily_update_fast_path.py tests/test_data_service_update_date.py -q`，结果 `16 passed`。
- 后端导入 smoke：`python -c "import web.backend.main as main; print(type(main.app).__name__)"`，结果 `FastAPI`。

## 后续风险

- 新浪快通道成交额/换手率字段可能为空；当前 CSV 层会用 `close * volume * 100` 估算成交额，换手率在缺市值时保持 0。
- 如果未来策略强依赖换手率，建议单独做“市值派生股本 + 换手率估算”任务，而不是阻塞每日 K 线更新。
