# Zettaranc 组合策略回测验证执行文档

> 创建：2026-05-29
> 范围：在不修改任何现有策略与回测引擎核心的前提下，把 zettaranc-skill 的完整入场/出场规则封装为 `ZettarancComboStrategy`，并通过历史回测验证方法论本身的胜率、赔率、最大回撤。
> 原则：**新增不改旧**；所有新增代码强制中文注释（含意图、约束、为何这样写）。

---

## 1. 目标与非目标

### 目标
- 用现有 `backtest_engine` + `strategy_registry` 跑出 zettaranc 整套规则的实证数据，回答三件事：
  1. 胜率是否 ≥ 45%；
  2. 盈亏比是否 ≥ 1.5；
  3. 最大回撤是否 ≤ 15%。
- 输出一份 `output/zettaranc_backtest_<时间戳>.json/.md`，列出样本数、命中分布、平均持仓天数、按月统计。

### 非目标
- 不接入实盘下单。
- 不修改 `b1_case_analyzer.py / b2_strategy.py / bowl_rebound.py / brick_pattern.py` 任何一行。
- 不改 `web/backend/backtest_engine/*` 任何文件的现有函数签名；只通过既有 `SignalSource` 协议接入。
- 不动 LLM 链路（`tracking_llm_service`、`zettaranc_adapter`）。

---

## 2. 现状盘点（已确认）

| 组件 | 路径 | 现状 |
|---|---|---|
| 策略基类 | `strategy/base_strategy.py` | `BaseStrategy.analyze_stock(code, name, df)` 返回 `{code, name, signals:[...]}` |
| 策略注册器 | `strategy/strategy_registry.py` | `auto_register_from_directory("strategy")` 扫描目录自动挂载 |
| 知行双线 | `utils/technical.py::calculate_zhixing_state` | 已稳定，依赖 ≥114 根 K 线（MA114） |
| KDJ/MA/EMA | `utils/technical.py` | 现成可复用 |
| 回测引擎 | `web/backend/backtest_engine/engine.py` | 依赖 `SignalSource.fetch(params)` → `list[SignalCandidate]` |
| 候选合并 | `signal_source.merge_same_day_signals` | 已支持，多策略同股同日去重 |
| 单票仓位上限 | `signal_source.apply_max_weight_per_code` | 已支持 `max_weight_per_code` |
| 执行模拟 | `backtest_engine/execution.py::DailyExecutionSimulator` | 已支持止损、持仓上限、滑点 |
| CSV 行情 | `data/{prefix2}/{code}.csv` | 倒序存储（最新在前），下游统一 reverse |
| 测试基线 | `pytest tests/` | 216/216 |

---

## 3. Zettaranc 规则到代码的映射

> 来源：`third_party/zettaranc/SKILL.md` + `knowledge/*.md` + 本项目 `docs/B1_*.md / B2_*.md`。
> 阈值默认值经过 P1 参数扫描收口：攻击日 `量比>20` 只作为极强攻击日参考，不作为默认入场门槛；当前默认使用 `J_BUY=0 / VOL_RATIO_MIN=1.3`，与 `config/strategy_params.yaml` 保持一致。

### 3.1 入场条件（全部满足才出候选）
| 编号 | 规则 | 实现 | 默认参数 |
|---|---|---|---|
| E1 | 知行双线已成形 | `len(df) >= 114` 且 `calculate_zhixing_state` 全字段非 NaN | — |
| E2 | 价格落在"碗"内 | `between_lines == True` **或** `near_duokong == True` **或** `near_short_trend == True` | `duokong_pct=3, short_pct=2` |
| E3 | KDJ 低位回升 | `J <= J_BUY` 且 `J > REF(J,1)`（J 值已从底部翘起） | `J_BUY=0` |
| E4 | 量比攻击 | `volume / MA(volume,5) >= VOL_RATIO_MIN` | `VOL_RATIO_MIN=1.3` |
| E5 | 收盘站上 BBI | `close > BBI`，`BBI = (MA3+MA6+MA12+MA24)/4` | — |
| E6 | 阳线确认 | `close > open` | — |
| E7 | 市值门槛 | 复用 `bowl_rebound._check_market_cap`（≥40 亿） | `CAP=4e9` |

> 备注：`J_BUY=-5 / VOL_RATIO_MIN=2.0` 是历史基线。P1 参数扫描显示 `VOL_RATIO_MIN=2.0` 样本过少，当前默认已同步为 `0 / 1.3`；后续若继续调参，应同时更新策略默认值、yaml、路由默认值和前端表单默认值。

### 3.2 出场条件（任一触发即卖出）
| 编号 | 规则 | 实现位置 |
|---|---|---|
| X1 | 跌破买入日最低价 | 通过 `BacktestParams` 的 `stop_loss_mode="entry_low"` 传给执行器 |
| X2 | 连续 2 日收盘破 BBI | 由策略在出场日补一组 `S` 信号，或通过 execution 自定义 stop（v1 走 X1，X2 留作 v2） |
| X3 | 时间止损 N 日未盈利 | `hold_days_limit` 参数（v1 默认 20，超期且回撤>5%出场） |
| X4 | 止盈 | `take_profit_pct=15` 触发 |

> v1 仅启用 X1+X3+X4；X2 留 TODO 注释，避免一次改动过多。

### 3.3 仓位/纪律
- 单票上限：`max_weight_per_code=0.10`（直接复用引擎已有参数）。
- 同日最大开仓：`max_positions_per_day=5`。
- 初始资金：100 万。

---

## 4. 新增文件清单（仅新增，零改动）

```
strategy/
  zettaranc_combo.py              # 新策略：ZettarancComboStrategy
scripts/
  run_zettaranc_backtest.py       # 离线回测入口，输出 output/zettaranc_backtest_*.json/.md
tests/
  test_zettaranc_combo_strategy.py # 单元测试：指标计算 + 选股触发 + 边界
docs/
  ZETTARANC_BACKTEST_PLAN.md      # 本文档
```

**确认不修改**：
- `strategy/b1_case_analyzer.py` `b2_strategy.py` `bowl_rebound.py` `brick_pattern.py` `pattern_*.py`
- `web/backend/backtest_engine/*`（如需调用，只通过既有公有接口）
- `utils/technical.py`
- 任何 web/backend/services/* 与 tracking_* 文件

---

## 5. ZettarancComboStrategy 设计

### 5.1 类骨架（仅示意，不是最终代码）

```python
# strategy/zettaranc_combo.py
"""
Zettaranc 组合策略
===================
将 zettaranc-skill 的完整入场规则（碗底 + KDJ 低位回升 + 量比攻击 + 站上 BBI）
固化为单一策略，便于在 backtest_engine 中作为独立信号源跑历史验证。

为什么单独建一个类而不是直接复用 BowlReboundStrategy：
1) bowl_rebound 已经在线上承担 B1 选股职责，参数和阈值是为 LLM 提示和前端展示
   调过的；直接挂规则会污染既有结果与缓存。
2) zettaranc 把"量比攻击日 + KDJ 翘头 + 站 BBI"作为强约束，这三条 bowl_rebound
   没有同时强制，需要独立策略以保证回测口径一致。
3) 独立类便于后续按 zettaranc_params.yaml 单独调参，不影响其他战法。

不修改任何现有策略文件。
"""
```

### 5.2 关键计算（中文注释强制）
- BBI：`(MA3 + MA6 + MA12 + MA24) / 4`，复用 `utils.technical.MA`。
- 量比：`volume / MA(volume, 5)`；避免用前 1 日比，因单日噪声大（zettaranc 原文也按 5 日基线）。
- J 翘头：当日 J - 昨日 J > 0 且 J <= J_BUY；用 `REF` 实现。
- 复用 `calculate_zhixing_state` 拿 `near_duokong / near_short_trend / between_lines / J/K/D`。

### 5.3 signals 输出格式（向下兼容现有引擎）

```python
{
  "code": "688380",
  "name": "中微公司",
  "signals": [{
      "strategy_name": "zettaranc_combo",
      "signal_date": "2026-04-12",
      "trade_date": "2026-04-15",      # 次日开盘买入
      "price": 46.0,
      "stop_loss": 44.5,                # 买入日最低价
      "category": "碗底攻击",            # 命中规则组合
      "meta": {
          "J": -6.3, "vol_ratio": 2.34, "bbi": 45.8,
          "short_term_trend": 49.9, "bull_bear_line": 47.57,
      }
  }]
}
```

> 字段命名复刻 `bowl_rebound` 输出，使 `_classify_candidate` 自动识别为 BUY/OPPORTUNITY。

---

## 6. 回测脚本设计

### 6.1 `scripts/run_zettaranc_backtest.py`

```python
"""
离线回测入口
==============
读取股票池（默认沪深300成分 + 本地 data/*.csv 已有覆盖的部分），
按 ZettarancComboStrategy 在 START~END 区间逐日扫描候选，注入
BacktestEngine 跑日级回测，输出胜率/盈亏比/最大回撤/分月统计。

不动 web 服务，不动数据库；仅依赖本地 CSV 与现有引擎。
"""
```

### 6.2 入参
- `--start 2024-01-01 --end 2026-05-28`
- `--pool hs300 | all_csv | file:scripts/pool_xxx.txt`
- `--init-cash 1000000`
- `--out output/zettaranc_backtest_<ts>.json`

### 6.3 输出指标
| 指标 | 公式 |
|---|---|
| 样本数 | 总开仓笔数 |
| 胜率 | 盈利笔数 / 总笔数 |
| 平均盈利% / 平均亏损% | 分组求均 |
| 盈亏比 | 平均盈利 / 平均亏损 |
| 最大回撤 | 净值序列 peak-to-trough |
| 平均持仓天数 | trades.exit_date - entry_date |
| 月度收益 | groupby month → sum(pnl_pct) |
| 命中分布 | 按 category 统计触发次数 |

### 6.4 同步输出 Markdown 报告（便于直接看）
- `output/zettaranc_backtest_<ts>.md`：核心指标 + 月度表 + 触发 TOP10。

---

## 7. 测试计划

### 7.1 单元测试 `tests/test_zettaranc_combo_strategy.py`
- ✅ `test_indicators_complete`：构造 150 根 K 线，校验 BBI/J/vol_ratio/zhixing 全部计算到位。
- ✅ `test_no_signal_when_below_bbi`：构造数据 close < BBI，断言无信号。
- ✅ `test_no_signal_when_volume_low`：vol_ratio < 2，断言无信号。
- ✅ `test_signal_when_all_match`：构造满足 E1~E7 的数据，断言出信号且 meta 字段完整。
- ✅ `test_insufficient_history`：< 114 根 K 线，断言安全返回 None。
- ✅ `test_no_mutation_of_input_df`：传入 df 不被原地修改（重要！）。

### 7.2 集成测试（不新增文件，靠脚本验证）
- 跑 `scripts/run_zettaranc_backtest.py --pool file:scripts/test_pool_3.txt --start 2025-01-01 --end 2025-06-30` 输出非空且无异常。

### 7.3 回归保证
- `pytest tests/ -q` 仍 216/216（新增 6 条后变 222/222）。
- 不触发任何现有测试的 import 变化（独立模块）。

---

## 8. 执行步骤（一次跑完）

| 步骤 | 内容 | 验收 |
|---|---|---|
| S1 | 创建 `strategy/zettaranc_combo.py` + 中文注释 | pylance 无 error |
| S2 | 创建 `tests/test_zettaranc_combo_strategy.py` 6 条用例 | `pytest tests/test_zettaranc_combo_strategy.py -q` 6 passed |
| S3 | 创建 `scripts/run_zettaranc_backtest.py` | `python scripts/run_zettaranc_backtest.py --help` 正常 |
| S4 | 全量回归 | `pytest tests/ -q` 222 passed |
| S5 | 跑一次小样本回测（3 只票 + 半年） | 生成 json + md，无异常 |
| S6 | 跑正式样本（沪深300 + 近 2 年）| 输出落 `output/`，指标摘要给用户决策 |
| S7 | 等用户确认是否提交（按 workflow-approval 规则） | — |

---

## 9. 风险与回滚

| 风险 | 应对 |
|---|---|
| 沪深300 成分历史 CSV 不全 | 自动回退到 `data/*.csv` 实际可用集合，跳过缺失股票并在报告中标注 |
| BBI 在样本前 24 天 NaN | 跳过前 30 根，从 `len(df) >= 120` 开始判信号 |
| 信号过少（<50 笔/年） | 报告中提示放宽 J_BUY 到 -2 后重跑（参数化，不改代码） |
| 引擎执行器对 stop_loss_mode 不支持 | v1 用 `take_profit_pct + hold_days_limit` 替代，X1 留 TODO |

**回滚**：所有改动都是新增文件，直接 `rm` 三个文件即可零影响回滚。

---

## 10. 待用户确认事项

1. **股票池**：默认用本地 `data/*.csv` 已覆盖股票（最稳，无需联网）；是否需要严格沪深300？
2. **回测区间**：默认 2024-01-01 ~ 2026-05-28（近 2.5 年）；是否调整？
3. **E3 J_BUY 阈值**：默认 -5（在严格 -10 与宽松 0 之间折中）；是否锁定？
4. **是否包含 X2「连续 2 日破 BBI」**：v1 暂不实现，是否同意？

---

## 11. 完成后产出

- 本文档 `docs/ZETTARANC_BACKTEST_PLAN.md`
- 代码：`strategy/zettaranc_combo.py` + `scripts/run_zettaranc_backtest.py` + `tests/test_zettaranc_combo_strategy.py`
- 数据：`output/zettaranc_backtest_<ts>.json` + `output/zettaranc_backtest_<ts>.md`
- 总结消息：把胜率/盈亏比/最大回撤摆出来，给 ② 持仓看板 / ③ 攻击日扫描的决策依据。
