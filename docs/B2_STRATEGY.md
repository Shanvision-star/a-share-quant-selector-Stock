# B2 策略文档

## 1. 文档目标
本文档不再把 B2 只写成一个笼统的“6 步突破策略”，而是按经典案例拆成可落代码的分类框架，方便后续继续整理到 `strategy/b2_strategy.py`。

当前建议把 B2 拆为 3 个主分类：

1. 横盘突破型
2. 灾后重建型
3. 平行重炮型

这 3 类共用同一套底层指标，但在“前置背景”“整理区识别”“攻击波结构”上明显不同，应该在文档和代码里分开维护。

## 2. 共用底层条件
无论属于哪一类，B2 都保留以下共用过滤条件，作为 `b2_strategy.py` 的基础层：

1. B1 前提成立：短期趋势线在多空线上方，或至少已经重新站回多空线。
2. B1 低位确认：B1 附近 `J < 13`，B2 前一日 `J < 20`，B2 当日 `J < 60`。
3. B2 强突破：突破日涨幅 `>= 4%`。
4. B2 放量确认：突破日成交量 `> 近10日均量 x 1.5`。
5. 突破有效性：收盘价要突破整理区高点，不能只看盘中上冲。
6. 突破后站稳：突破后连续 3 天收盘在多空线上方。

建议后续代码里把这些共用条件抽成统一的基础检查函数：

- `check_b1_context()`
- `check_kdj_filter()`
- `check_volume_breakout()`
- `check_hold_above_bull_bear()`

## 3. 分类一: 横盘突破型

### 3.1 代表案例
- 星环科技 688663

### 3.2 核心特征
横盘突破型的重点不在“深跌修复”，而在“平台蓄势后的标准突破”。主力先在一个相对稳定的平台里控盘、缩量、磨时间，然后用一根放量阳线穿过平台高点。

### 3.3 识别重点
1. 必须存在清晰的平台整理区。
2. 平台内高低点相对稳定，波动率逐步收缩。
3. 平台结束前已经有 3 到 5 根攻击性大阳线，说明主力不是突然点火，而是先试盘再突破。
4. B2 当日是“平台突破日”，不是单纯反弹日。

### 3.4 代码建议
建议在 `b2_strategy.py` 中使用：

- `pattern_type = "sideways_breakout"`
- 独立函数：`identify_sideways_consolidation()`
- 输出字段：
  - `consolidation_start`
  - `consolidation_end`
  - `consolidation_high`
  - `consolidation_low`
  - `breakout_strength`

### 3.5 当前案例映射
- 案例1 星环科技

## 4. 分类二: 灾后重建型

### 4.1 代表案例
- 晶科科技 601778

### 4.2 核心特征
灾后重建型的前提不是横盘，而是“先经历大幅杀跌或情绪性破坏”，然后主力通过巨量长阳反包、回补缺口、逐步修复趋势，最后在修复后期给出 B2 买点。

### 4.3 识别重点
1. 前期必须存在明显的破坏段，通常表现为快速下跌、长阴、连续弱势或情绪性砸盘。
2. 修复初段要出现标志性反转 K 线，最好是巨量长阳反包。
3. B2 不是第一根反转阳线，而是修复一段时间后的再次确认突破。
4. 整理区识别不能只看横盘箱体，还要考虑“灾后修复平台”。

### 4.4 代码建议
建议在 `b2_strategy.py` 中使用：

- `pattern_type = "post_crash_rebuild"`
- 独立函数：
  - `identify_damage_zone()`
  - `identify_rebuild_platform()`
  - `check_reversal_impulse()`
- 输出字段：
  - `damage_start`
  - `damage_end`
  - `reversal_date`
  - `rebuild_start`
  - `rebuild_end`

### 4.5 当前案例映射
- 案例2 晶科科技

## 5. 分类三: 平行重炮型

### 5.1 代表案例
- 四会富仕 300852
- 中坚科技 250801
- 百普赛斯 301080

### 5.2 核心特征
平行重炮型不是标准箱体突破，而是“多根大阳在相近价格带重复出现”。这些大阳像在同一水平位置连续打炮，说明主力反复试盘、吸筹、震仓，然后在 B1 之后发动真正的 B2。

### 5.3 识别重点
1. 至少 2 根放量大阳，收盘位置相近，建议用 `±2%` 作为平行价格带阈值。
2. 大阳之间的阴线或小阳线明显缩量，形成“红肥绿瘦”。
3. 大阳之间的回调不应有效跌破多空线或关键支撑。
4. B1 往往出现在缩量回踩后的末端，B2 是随后再次放量启动。
5. 平行重炮的整理区不一定是完整箱体，更像“平行攻击带 + 缩量中继”。

### 5.4 子类型建议
平行重炮型后续还可以细分为两个子类：

1. `parallel_artillery_platform`
   说明：多根大阳围绕一个相对平行的平台区间展开。
2. `parallel_artillery_rebuild`
   说明：先有一根底部确认长阳，之后在更高一级的平台内再次出现平行重炮。

### 5.5 代码建议
建议在 `b2_strategy.py` 中使用：

- `pattern_type = "parallel_artillery"`
- 独立函数：
  - `identify_parallel_big_candles()`
  - `check_parallel_close_band()`
  - `check_red_fat_green_thin()`
  - `check_b1_to_b2_transition()`
- 输出字段：
  - `parallel_candle_dates`
  - `parallel_close_band_pct`
  - `big_up_count`
  - `shrinking_volume_between_big_ups`
  - `pattern_subtype`

### 5.6 当前案例映射
- 案例3 四会富仕
- 案例4 中坚科技
- 案例5 百普赛斯

## 6. 建议的代码结构
为了方便后面输出 `b2_strategy.py`，建议把 B2 拆成“基础层 + 分类层”两层：

### 6.1 基础层
处理所有分类共用的指标和过滤：

1. 计算 KDJ
2. 计算知行双线
3. 检查 B1 上下文
4. 检查放量突破
5. 检查站稳多空线

### 6.2 分类层
按 `pattern_type` 分发到不同检测器：

1. `detect_sideways_breakout()`
2. `detect_post_crash_rebuild()`
3. `detect_parallel_artillery()`

### 6.3 统一输出结构
后续 `b2_strategy.py` 建议统一返回：

```python
{
    "code": code,
    "name": name,
    "pattern_type": "parallel_artillery",
    "pattern_subtype": "parallel_artillery_platform",
    "matched_case_id": "b2_case_003",
    "matched_case_name": "四会富仕",
    "b1_date": "2025-09-09",
    "b2_date": "2025-09-10",
    "entry_price": 0.0,
    "stop_loss_price": 0.0,
    "breakout_pct": 0.0,
    "volume_ratio": 0.0,
    "j_value": 0.0,
    "pattern_notes": [],
}
```

## 7. 文档与案例库的关系
`docs/B2_STRATEGY_CASE_LIBRARY.md` 负责存放案例事实和复盘描述。

`docs/B2_STRATEGY.md` 则负责提炼成代码规则，重点回答三件事：

1. 这一类模式为什么单独成类。
2. 这一类模式该看哪些量化条件。
3. 这一类模式在 `b2_strategy.py` 里应该输出哪些结构化字段。

后续如果继续补案例，建议优先补到案例库，再同步更新这里的分类规则，不要反过来直接往代码里硬塞特殊判断。

## 8. 当前结论
按目前案例库，B2 已经不适合继续写成单一策略描述，而应该明确拆成：

1. 横盘突破型
2. 灾后重建型
3. 平行重炮型

这样后续再输出 `strategy/b2_strategy.py` 时，才能避免一个函数里堆太多 if/else，也更方便单独调参和扩充案例。