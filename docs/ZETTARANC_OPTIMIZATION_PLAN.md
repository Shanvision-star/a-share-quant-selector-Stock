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
- 现状缺口：`scripts/run_zettaranc_backtest.py` 的手续费百分点口径（P0 修复点）与 X2「连续 2 日破 BBI」出场（P1#2）目前**没有任何单测覆盖**，只靠手工实跑确认。一旦后续改动很容易悄悄回退。
- 方案：新增 `tests/test_zettaranc_backtest_script.py`，用构造的小型 DataFrame 直接驱动 `simulate_trade`：
  - 用例 A：纯涨/纯跌序列断言 `pnl_pct == raw_pct - 2*fee_pct`（锁死手续费口径，防 100 倍回归）。
  - 用例 B：构造收盘连续 2 日 < BBI 的序列，断言 `exit_reason=="break_bbi"` 且按收盘价离场；构造仅 1 日破位则不触发。
  - 用例 C：止损/止盈/时间止损优先级各一条，断言出场优先级顺序。
- 验证：`pytest tests/test_zettaranc_backtest_script.py -q` → 全量回归 237+→ 应升至 240+ 全绿。

**T2 — DEFAULT_PARAMS 与 yaml 口径收口（消除双源默认）**
- 状态：本轮已收口。
- 已执行：`strategy/zettaranc_combo.py`、`scripts/run_zettaranc_backtest.py`、`web/backend/routers/zettaranc.py`、`web/frontend/src/views/ZettarancView.vue` 默认值已同步为 `J_BUY=0 / VOL_RATIO_MIN=1.3`；文档同时标记旧值 `-5 / 2.0` 为历史基线。
- 验证：新增默认值断言，要求策略类与 API 回测入参默认值均与 yaml 选型一致。

**T3 — 持仓纪律钉钉推送钩子（P2#5）**
- 现状：`zettaranc_holdings_service.py` docstring 第 3 点标注「钉钉推送钩子（可选；测试中不会真正调用）」，尚未接入真实 `DingTalkNotifier`。
- 方案：在纪律巡检产出 `HoldingAlert` 后，新增可选 `push_alerts(alerts, notifier=None)`：复用既有钉钉通知模块，仅推送 X1 止损/越上限等硬告警；`notifier=None` 时 no-op，保证现有 7 项测试零回归。配置开关放 yaml（如 `zettaranc.push_enabled`）。
- 验证：新增 1~2 条注入 mock notifier 的断言用例。

**T4 — 接入在线 StrategyRegistry/QuantSystem（P2#6，范围最大）**
- 现状核查：`strategy/zettaranc_combo.py` 是 `BaseStrategy` 子类且位于 `strategy/` 目录，`auto_register_from_directory()` 会自动注册，故「注册」本身已具备。真正缺口在于：在线 `QuantSystem` 执行链路、CLI 命令、导出、钉钉、web 结果页是否把它纳入候选并保持**结果形状一致**。
- 方案：
  1. 确认 registry 实际已注册（写一条 import 冒烟/单测断言 `ZettarancCombo` 在注册表内）。
  2. 核对 `quant_system.py` 选股结果字段与 web `web_strategy_results.json` 形状，使 zettaranc 输出对齐既有 strategy result schema（`strategy_name`、入选股列表、信号字段）。
  3. 保证 CLI（`main.py run`）可选中该策略且不破坏其他策略输出。
- 风险控制：此项最容易触及既有在线链路，建议**单独一轮 + 单独验收**，先只读核查再改；保持对 b1/b2/bowl/brick 零影响。

**T5 — 样本外/滚动窗口稳健性验证（P3）**
- 动机：当前选型基于单一区间 2024-01-01~2026-05-28 的 300 只池，存在过拟合到该窗口的风险。
- 方案：用现有回测脚本做时间切分——以 2024 全年为「样本内」选参，2025+ 为「样本外」复跑，比对胜率/盈亏比是否在样本外仍达标（胜率≥45%、盈亏比≥1.5）。结论追加到本文件。
- 不新增引擎：复用 `run_zettaranc_backtest.py` 的 `--start/--end`，仅脚本编排。

**T6 — 扩大股票池 + 参数敏感性复核（P3）**
- 动机：sweep 与回测都限于 `--limit 300`，全量池下样本量与稳定性需复核。
- 方案：以 `--pool local_all --limit 0` 跑全量，复核 J_BUY=0/VOL=1.3 在更大样本下指标是否稳定；如偏移，回到 sweep 网格微调并更新 yaml + 第 5 节表格。

### 6.3 验收基线（与第 3 节叠加）
- 每项 Python 改动：focused `pytest tests/test_zettaranc_*.py -q` + `python -c "import ..."` 冒烟。
- 收尾全量：`.venv/Scripts/python.exe -m pytest tests/ -q` 保持全绿（T1 完成后基线应为 240+）。
- 涉及在线链路（T4）：额外实跑 `python main.py run --help` 与一次窄量选股，确认其他策略输出不受影响。
