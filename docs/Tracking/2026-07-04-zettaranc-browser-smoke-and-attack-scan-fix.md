# 2026-07-04 Zettaranc 浏览器 smoke 与 attack-scan 修复记录

## 目的

补齐 `/zettaranc` 页面真实浏览器 smoke，并记录攻击日候选 tab 暴露出的性能问题。此记录只覆盖本地 smoke 和后端性能边界，不代表真实钉钉外发、全量 cache rebuild 或策略参数稳健性验证已经完成。

## 浏览器 smoke 结果

- 入口：`http://127.0.0.1:5173/zettaranc`
- 后端：`http://127.0.0.1:8001`
- 页面标题：`Zettaranc 综合看板`
- 回测结果 tab：`/api/zettaranc/backtest/latest` 返回 200，页面展示信号数、成交笔数、胜率、平均盈亏与最大回撤；console error 为 0。
- 持仓纪律 tab：`/api/zettaranc/holdings` 与 `/api/zettaranc/holdings/alerts` 返回 200，页面展示暂无持仓与无告警；console error 为 0。
- 攻击日候选 tab：`/api/zettaranc/attack-scan?limit=50` 在浏览器中长时间 pending；直接调用 `limit=1` 可返回，但 `limit=50` 在重复请求堆积后出现超时。

## 根因

`ZettarancAttackScanner.scan_today()` 只判断最新一根 K 线是否命中攻击日，但旧实现对每只股票执行 `read_stock(code)`，读取多年历史后再计算整段指标。前端默认 `limit=50` 时，这会把不必要的历史指标计算放大，并且重复浏览器请求会让运行态排队。

## 修复

- 新增 `ATTACK_SCAN_RECENT_ROWS = max(MIN_HISTORY, 320)`。
- `scan_today()` 改为 `read_stock(code, nrows=ATTACK_SCAN_RECENT_ROWS)`。
- 320 根窗口覆盖 Zettaranc 当前 `MIN_HISTORY=120`、MA114、BBI、KDJ 和最新一根判定安全余量；回测历史扫描逻辑不变。

## 验证

- 红灯测试：`pytest tests/test_zettaranc_attack_scanner.py::test_scan_reads_recent_window_for_latest_attack_check -q` 先失败，失败原因为旧实现未传 `nrows`。
- 绿灯测试：同一测试通过。
- 相关回归：`python -m pytest tests/test_zettaranc_attack_scanner.py tests/test_zettaranc_router.py -q` -> 9 passed。
- import smoke：`python -c "from web.backend.main import app; print('import-ok')"` -> import-ok。
- 真实数据性能对照：
  - 旧路径 50 只直接服务扫描约 `6.818s`。
  - 新路径 50 只直接服务扫描约 `2.232s`。

## 未验证

- 尚未在重启后的 patched backend 上重新跑完整浏览器 smoke。
- 尚未执行真实钉钉外发 smoke。
- 尚未执行全量 Web cache rebuild。
- 尚未执行 `limit=300` / `limit=0` 的 Zettaranc walk-forward 或参数敏感性复核。
