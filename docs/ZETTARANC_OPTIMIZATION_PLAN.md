# Zettaranc 三件套优化提升计划

> 状态：P0 + P1 已完成（手续费修复、X2 出场、参数外置、参数扫描+回写 yaml 均已落地并全量回归 237 全绿）；下一步进入第二阶段（P2 + P3 系统性完善），见第 6 节
> 关联文档：`docs/ZETTARANC_BACKTEST_PLAN.md`（原始设计与规则映射）
> 适用范围：`strategy/zettaranc_combo.py`、`scripts/run_zettaranc_backtest.py`、`web/backend/services/zettaranc_*`、`config/strategy_params.yaml`

## 0. 背景与当前问题

上一轮已完成 zettaranc 策略、回测脚本、持仓纪律、攻击日扫描的全套后端 + 前端，237 项 pytest 全绿、vue-tsc 无错。但回测结果不达标：

| 指标 | 目标 | 当前 | 结论 |
| --- | --- | --- | --- |
| 胜率 | ≥ 45% | 50% | 达标 |
| 盈亏比 | ≥ 1.5 | **0.70** | **不达标** |
| 最大回撤 | ≤ 15% | 13.86% | 达标 |
| 成交笔数 | 充足样本 | **仅 4 笔（296/300 跳过）** | **样本严重不足** |

定位到两类核心问题：**（A）回测引擎手续费计算存在 100 倍放大 bug**，**（B）信号过于稀疏**，因此盈亏比与样本量均失真。

## 1. 优先级清单

### P0 — 阻断级 Bug（必须先修，否则一切回测结论无效）

1. **手续费 100 倍放大 bug**
   - 位置：`scripts/run_zettaranc_backtest.py` 第 176 行
     `pnl_pct = raw_pct - 2 * fee_pct * 100.0`
   - 问题：`fee_pct=0.05` 含义已是"0.05%"（万分之 5），再乘 100 后每笔往返扣掉 **10 个百分点**，而非 0.1 个百分点。
   - 影响：把本应 +3.75% 的盈利交易（000690）记成 **−6.25%** 的亏损，直接拉垮盈亏比与胜率。
   - 修复：改为 `pnl_pct = raw_pct - 2 * fee_pct`（fee_pct 已是百分点）。
   - 验证：修复后预计 4 笔交易由"2 盈 2 亏"变为接近全盈，盈亏比与胜率重算。

### P1 — 功能完整性 & 有效性

2. **实现 X2 出场规则（连续 2 日收盘破 BBI）**
   - 现状：v1 仅有 X1 止损 / X3 时间止损 / X4 止盈，X2 在原计划 3.2 节标注为 v2 TODO。
   - 方案：在 `simulate_trade` 持仓循环内追加判断：连续 2 根 K 线收盘价 < 当日 BBI 则以收盘价离场，`exit_reason="break_bbi"`。
   - 约束：BBI 需在回测时按 asc 序列重算，避免使用未来数据。

3. **zettaranc 参数外置到 `config/strategy_params.yaml`**
   - 现状：阈值（J_BUY、VOL_RATIO_MIN、CAP、止盈/持有天数）散落在策略 DEFAULT_PARAMS 与回测 CLI 默认值。
   - 方案：新增 `ZettarancComboStrategy:` 配置段，策略与回测脚本统一从该处读取默认值，CLI/接口参数可覆盖。
   - 目的：满足项目规范"运行期可调参数集中放 yaml，不在多处硬编码"。

4. **信号稀疏：参数扫描 + 阈值放宽**
   - 现状：E1-E7 七条件需同根 K 线同时满足，300 只仅 4 笔，统计意义弱。
   - 方案：以回测脚本对 `j_buy ∈ {-5,0,5}`、`vol_ratio ∈ {1.3,1.5,2.0}` 做小网格扫描，输出对比表，挑选样本量与盈亏比平衡的默认值写回 yaml。
   - 产出：在本文件追加"参数扫描结果"小节记录结论。

### P2 — 增强（确认 P0/P1 后再做）

5. **持仓纪律钉钉推送钩子**（原 holdings service docstring 中标注为可选）
6. **将 ZettarancComboStrategy 注册进在线 StrategyRegistry/QuantSystem 流程**（当前仅离线使用）

## 2. 执行顺序

```
P0(#1 手续费) → 重跑回测确认数值 → P1(#2 X2出场) → P1(#3 参数外置)
→ P1(#4 参数扫描+回写yaml) → 更新单测 → 全量回归 → 刷新 latest 回测产物
```

## 3. 验证清单（每步必过）

- Python 改动后：`.venv/Scripts/python.exe -m pytest tests/test_zettaranc_*.py -q` + import 冒烟。
- 完成后全量回归：`.venv/Scripts/python.exe -m pytest tests/ -q`，保持 237+ 全绿。
- 回测脚本改动：实跑一次 `--limit 50` 确认产物 JSON/MD 正常刷新。
- 前端如有改动：`npx vue-tsc -b --noEmit` 零错误。

## 4. 约束（沿用上一轮纪律）

- 仅新增/在既有 zettaranc 文件内修改，不触碰 b1/b2/bowl/brick/backtest_engine 等既有策略。
- 所有改动附中文意图注释，说明"为什么改"。
- 不引入新存储层，沿用 CSV + JSON 产物。

## 5. 参数扫描结果

执行环境：300 只本地股票池，区间 2024-01-01 ~ 2026-05-28，止盈 15%、时间止损 20 日、单边手续费 0.05%（手续费已修正为百分点口径）。脚本：`scripts/zettaranc_param_sweep.py`。

| J_BUY | VOL_RATIO | 信号 | 交易 | 胜率% | 盈亏比 | 最大回撤% | 平均持仓 |
|---|---|---|---|---|---|---|---|
| -5.0 | 1.3 | 12 | 12 | 58.33 | 4.19 | 7.00 | 9.00 |
| -5.0 | 1.5 | 2 | 2 | 100.00 | 0.00 | 0.00 | 6.00 |
| -5.0 | 2.0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| 0.0 | 1.3 | 20 | 20 | 65.00 | 4.46 | 7.00 | 7.70 |
| 0.0 | 1.5 | 4 | 4 | 100.00 | 0.00 | 0.00 | 5.75 |
| 0.0 | 2.0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| 5.0 | 1.3 | 24 | 22 | 63.64 | 4.26 | 7.00 | 6.82 |
| 5.0 | 1.5 | 5 | 5 | 100.00 | 0.00 | 0.00 | 5.00 |
| 5.0 | 2.0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |

**结论与选型：**

- VOL_RATIO_MIN=2.0（原默认）在全网格下都是 0 笔，证实原阈值过严——这正是修复手续费 bug 前回测样本极少的根因之一。
- VOL_RATIO_MIN=1.5 样本太小（2~5 笔），盈亏比因无亏损交易显示 0.00（口径上无意义），不可作为可信默认。
- VOL_RATIO_MIN=1.3 三档 J_BUY 均有 12~24 笔样本、胜率 58%~65%、盈亏比 4.2~4.5、回撤稳定 7%。
- 选定 **J_BUY=0、VOL_RATIO_MIN=1.3**：交易数 20、胜率 65%、盈亏比 4.46，是样本量与质量最均衡的一组；已写入 `config/strategy_params.yaml`。

---

## 6. 第二阶段执行计划（P2 + P3 系统性完善）

> 第一阶段（P0/P1）解决了「结论可信」问题。第二阶段目标转为「可上线、可信赖、可持续」：补齐在线链路、回测健壮性验证、回归防护与一致性收口。
> 执行纪律沿用第 4 节，并叠加 user memory `workflow-approval.md`：每项代码改动先出变更摘要+中文理由，经确认后再改；Python 改动后跑 focused pytest + import 冒烟，最后全量回归保持 237+ 全绿；所有改动留在 `web` 分支未提交，待显式确认。

### 6.1 优先级与排期建议

| 编号 | 项目 | 类别 | 风险 | 价值 | 建议次序 |
| --- | --- | --- | --- | --- | --- |
| T1 | 回测脚本手续费/X2 出场专项回归测试 | P2-测试缺口 | 低 | 高（防回归） | 1（先做，保护已有修复） |
| T2 | `strategy/zettaranc_combo.py` DEFAULT_PARAMS 与 yaml 口径收口 | P2-一致性 | 低 | 中 | 2 |
| T3 | 持仓纪律钉钉推送钩子落地 | P2#5 | 中 | 中 | 3 |
| T4 | ZettarancComboStrategy 接入在线 StrategyRegistry/QuantSystem | P2#6 | 中高 | 高 | 4（最大范围，单独验收） |
| T5 | 样本外/滚动窗口（walk-forward）稳健性验证 | P3-健壮性 | 中 | 高 | 5 |
| T6 | 扩大股票池全量扫描 + 参数敏感性复核 | P3-健壮性 | 低 | 中 | 6 |

### 6.2 各项执行要点

**T1 — 回测脚本专项回归测试（最高优先，零业务风险）**
- 状态：本轮已收口，归类为验证缺口而非生产代码缺口。
- 已执行：新增 `tests/test_zettaranc_backtest_script.py`，用构造的小型 DataFrame 直接驱动 `simulate_trade`：
  - 用例 A：断言 `pnl_pct == raw_pct - 2*fee_pct`，锁死手续费百分点口径，防 100 倍回归。
  - 用例 B：构造收盘连续 2 日 < BBI 的序列，断言 `exit_reason=="break_bbi"` 且按收盘价离场；构造仅 1 日破位则不触发。
  - 用例 C：断言止损优先于止盈和 BBI 破位；时间止损作为未触发其他出场时的兜底。
- 验证：`python -m pytest tests/test_zettaranc_backtest_script.py -q` → `4 passed`。

**T2 — DEFAULT_PARAMS 与 yaml 口径收口（消除双源默认）**
- 状态：本轮已收口。
- 已执行：`strategy/zettaranc_combo.py`、`scripts/run_zettaranc_backtest.py`、`web/backend/routers/zettaranc.py`、`web/frontend/src/views/ZettarancView.vue` 默认值已同步为 `J_BUY=0 / VOL_RATIO_MIN=1.3`；文档同时标记旧值 `-5 / 2.0` 为历史基线。
- 验证：新增默认值断言，要求策略类与 API 回测入参默认值均与 yaml 选型一致。

**T3 — 持仓纪律钉钉推送钩子（P2#5）**
- 状态：本轮已收口为可注入 hook，默认不触发真实外部 HTTP。
- 已执行：`ZettarancHoldingsService.push_alerts(alerts, notifier=None)` 已落地；真实调用方可传入兼容 `send_markdown(title, content)` 的 `DingTalkNotifier`，测试中使用 RecordingNotifier。当前仅推送 `stop_loss` 与 `position_overflow` 两类硬纪律告警，止盈/时间止损留在前端提醒，避免钉钉噪声过高。
- 验证：`python -m pytest tests/test_zettaranc_holdings_service.py::test_push_alerts_noops_without_notifier tests/test_zettaranc_holdings_service.py::test_push_alerts_sends_only_hard_alert_rules -q` → `2 passed`。
- 未做：真实钉钉 webhook smoke、自动调度、路由自动外发；这些有外部副作用，应单独开任务并记录通道证据。

**T4 — 接入在线 StrategyRegistry/QuantSystem（P2#6，范围最大）**
- 状态：本轮已完成最小产品链路接入。
- 已执行：
  1. `StrategyRegistry.auto_register_from_directory("strategy")` 已验证可发现 `ZettarancComboStrategy`，并加载 yaml 默认参数。
  2. Web 策略服务 `_STRATEGY_NAME_MAP`、策略筛选白名单、缓存状态、更新重建、TXT 导出和回测请求均已允许 `zettaranc`。
  3. 前端策略结果页、更新页、回测页、TXT 文件库和策略结果分组已增加 `Zettaranc` 入口。
  4. CLI 窄量 smoke 直接调用 `QuantSystem.select_stocks(max_stocks=1, return_data=True, max_workers=1)`，确认结果键包含 `ZettarancComboStrategy`。
- 验证：`test_strategy_registry.py::test_auto_register_includes_zettaranc_combo_strategy`、`test_strategy_service_backtest_dates.py::test_web_strategy_service_resolves_zettaranc_filter`、`test_web_validation.py::test_strategy_results_accepts_zettaranc_filter`、`test_web_validation.py::test_backtest_request_accepts_zettaranc_strategy`、前端 `strategyResults.spec.ts` 均通过。
- 未做：真实浏览器手动 smoke、真实钉钉外发、全量 Web cache rebuild；这些属于外部副作用或重型运行，单独记录。

**T5 — 样本外/滚动窗口稳健性验证（P3）**
- 动机：当前选型基于单一区间 2024-01-01~2026-05-28 的 300 只池，存在过拟合到该窗口的风险。
- 状态：本轮完成低成本样本验证，尚不足以给出稳健性定论。
- 已执行：
  - 样本内：`python scripts/run_zettaranc_backtest.py --start 2024-01-01 --end 2024-12-31 --limit 50` → 6 笔、胜率 33.33%、盈亏比 9.51、最大回撤 4.16%。
  - 样本外：`python scripts/run_zettaranc_backtest.py --start 2025-01-01 --end 2026-05-28 --limit 50` → 0 笔。
- 结论：limit 50 样本外没有交易，不足以证明或否定策略稳健性；不能据此修改 yaml。后续应提升到 `--limit 300` 后再判断，最后才考虑 `--limit 0` 全量。

**T6 — 扩大股票池 + 参数敏感性复核（P3）**
- 动机：sweep 与回测都限于 `--limit 300`，全量池下样本量与稳定性需复核。
- 状态：本轮完成 limit 50 参数敏感性快照；全量复核未执行。
- 已执行：`python scripts/zettaranc_param_sweep.py --limit 50 --start 2024-01-01 --end 2026-05-28`。
- 快照结果：

| J_BUY | VOL_RATIO | 信号 | 交易 | 胜率% | 盈亏比 | 最大回撤% | 平均持仓 |
|---|---|---:|---:|---:|---:|---:|---:|
| -5.0 | 1.3 | 2 | 2 | 50.00 | 35.99 | 0.41 | 12.50 |
| -5.0 | 1.5 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| -5.0 | 2.0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| 0.0 | 1.3 | 6 | 6 | 33.33 | 9.51 | 4.16 | 9.17 |
| 0.0 | 1.5 | 1 | 1 | 0.00 | 0.00 | 1.06 | 7.00 |
| 0.0 | 2.0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| 5.0 | 1.3 | 7 | 7 | 28.57 | 9.58 | 5.61 | 7.86 |
| 5.0 | 1.5 | 2 | 2 | 0.00 | 0.00 | 2.56 | 3.50 |
| 5.0 | 2.0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |

- 结论：`VOL_RATIO_MIN=2.0` 在小样本仍过严；`J_BUY=0 / VOL_RATIO_MIN=1.3` 有可用样本但胜率未达 45%，暂不更新 yaml。下一步应跑 `--limit 300` 的 T5/T6 后再评估是否微调。

### 6.3 验收基线（与第 3 节叠加）
- 每项 Python 改动：focused `pytest tests/test_zettaranc_*.py -q` + `python -c "import ..."` 冒烟。
- 收尾全量：`.venv/Scripts/python.exe -m pytest tests/ -q` 保持全绿（T1 完成后基线应为 240+）。
- 涉及在线链路（T4）：额外实跑 `python main.py run --help` 与一次窄量选股，确认其他策略输出不受影响。
