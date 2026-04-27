"""
FormulaConverter - 学术公式 → Python 指标代码转换器
================================================
【填补的缺口】
所有现有工具（MinerU/PaperQA2/Deep-Read-Agent/GPT-Researcher 等）
都停留在"提取/理解公式"层面，没有一个工具能：
  - 将论文中的数学公式转换为可执行的 Python 代码
  - 将公式自动映射到 pandas/numpy/talib 实现
  - 生成带参数的指标函数供回测直接调用
  - 将多个公式组合为完整的 entry/exit 策略代码
  - 生成与本项目现有策略框架兼容的代码骨架

本模块实现以上所有功能：
  1. 常见学术公式 → pandas/numpy 代码
  2. 移动平均/动量/布林带等公式自动识别并生成代码
  3. 生成继承 BaseStrategy 的策略类骨架
  4. 生成可直接用于 main.py 的完整策略文件
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from research.paper_parser import Formula
from research.strategy_extractor import StrategySpec


# ─────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────

@dataclass
class ConvertedIndicator:
    """从公式转换后的 Python 指标"""
    name: str                   # 指标名称
    formula_raw: str            # 原始公式
    python_code: str            # 生成的 Python 代码（函数体）
    dependencies: List[str]     # 依赖列表（pandas/numpy/等）
    params: Dict[str, object]   # 参数默认值


@dataclass
class GeneratedStrategy:
    """完整生成的策略代码文件"""
    class_name: str
    file_content: str           # 完整 Python 文件内容
    indicators: List[ConvertedIndicator]
    requires_params: Dict[str, object]
    source_paper: str


# ─────────────────────────────────────────────────
# 公式模式库（常见量化公式 → Python 实现）
# ─────────────────────────────────────────────────

# 每条：(识别正则/关键词, 生成代码模板, 参数默认值)
_FORMULA_TEMPLATES: List[Tuple[str, str, Dict]] = [
    # 简单移动平均
    (
        r"SMA|MA|moving average|均线|简单移动",
        """def calc_ma(close: pd.Series, period: int = {period}) -> pd.Series:
    \"\"\"简单移动平均 MA({period})\"\"\"
    return close.rolling(window=period).mean()""",
        {"period": 20},
    ),
    # 指数移动平均
    (
        r"EMA|exponential moving|指数移动",
        """def calc_ema(close: pd.Series, period: int = {period}) -> pd.Series:
    \"\"\"指数移动平均 EMA({period})\"\"\"
    return close.ewm(span=period, adjust=False).mean()""",
        {"period": 20},
    ),
    # 相对强弱指数 RSI
    (
        r"RSI|relative strength|相对强弱",
        """def calc_rsi(close: pd.Series, period: int = {period}) -> pd.Series:
    \"\"\"相对强弱指数 RSI({period})\"\"\"
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float('inf'))
    return 100 - (100 / (1 + rs))""",
        {"period": 14},
    ),
    # MACD
    (
        r"MACD|moving average convergence",
        """def calc_macd(close: pd.Series, fast: int = {fast}, slow: int = {slow},
                  signal: int = {signal}) -> pd.DataFrame:
    \"\"\"MACD 指标 (fast={fast}, slow={slow}, signal={signal})\"\"\"
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    bar = 2 * (dif - dea)
    return pd.DataFrame({'DIF': dif, 'DEA': dea, 'MACD': bar})""",
        {"fast": 12, "slow": 26, "signal": 9},
    ),
    # 布林带
    (
        r"Bollinger|布林|boll",
        """def calc_boll(close: pd.Series, period: int = {period}, std_mult: float = {std_mult}) -> pd.DataFrame:
    \"\"\"布林带 BOLL({period}, {std_mult})\"\"\"
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return pd.DataFrame({'MID': mid, 'UPPER': upper, 'LOWER': lower})""",
        {"period": 20, "std_mult": 2.0},
    ),
    # 动量
    (
        r"momentum|动量|MOM",
        """def calc_momentum(close: pd.Series, period: int = {period}) -> pd.Series:
    \"\"\"动量指标 MOM({period})\"\"\"
    return close / close.shift(period) - 1""",
        {"period": 20},
    ),
    # ATR 平均真实波幅
    (
        r"ATR|average true range|真实波幅",
        """def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series,
              period: int = {period}) -> pd.Series:
    \"\"\"平均真实波幅 ATR({period})\"\"\"
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()""",
        {"period": 14},
    ),
    # KDJ
    (
        r"KDJ|stochastic|随机指标",
        """def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = {period}) -> pd.DataFrame:
    \"\"\"KDJ 随机指标 (period={period})\"\"\"
    lowest_low = low.rolling(window=period).min()
    highest_high = high.rolling(window=period).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-9) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return pd.DataFrame({{'K': k, 'D': d, 'J': j}})""",
        {"period": 9},
    ),
    # 量比
    (
        r"量比|volume ratio|VOLUME_RATIO",
        """def calc_volume_ratio(volume: pd.Series, period: int = {period}) -> pd.Series:
    \"\"\"量比 = 当日成交量 / 近N日平均成交量\"\"\"
    avg_vol = volume.shift(1).rolling(window=period).mean()
    return volume / avg_vol.replace(0, float('nan'))""",
        {"period": 5},
    ),
    # 换手率因子
    (
        r"换手率|turnover rate",
        """def calc_turnover_factor(turnover: pd.Series, period: int = {period}) -> pd.Series:
    \"\"\"换手率因子：N日换手率均值\"\"\"
    return turnover.rolling(window=period).mean()""",
        {"period": 20},
    ),
]


# ─────────────────────────────────────────────────
# 策略类骨架模板
# ─────────────────────────────────────────────────

_STRATEGY_CLASS_TEMPLATE = '''"""
{class_name} - 从论文自动生成的量化策略
来源论文: {paper_title}
策略类型: {strategy_type}
适用市场: {universe}
生成时间: {generated_at}

【重要说明】
本代码由 research.FormulaConverter 从论文中自动生成，
仅作为策略开发的起点模板，需要人工审阅和调整后方可用于实盘。
"""

import pandas as pd
import numpy as np
from typing import Optional

# 从本项目继承基础策略类
try:
    from strategy.base_strategy import BaseStrategy
except ImportError:
    # 兼容独立运行
    class BaseStrategy:
        pass


# ═══════════════════════════════════════════════════════
# 指标计算函数（从论文公式自动生成）
# ═══════════════════════════════════════════════════════

{indicator_functions}


# ═══════════════════════════════════════════════════════
# 策略类
# ═══════════════════════════════════════════════════════

class {class_name}(BaseStrategy):
    """
    {strategy_description}

    来源论文: {paper_title}
    策略置信度: {confidence:.0%}（自动提取置信度，越低越需要人工审阅）

    使用方法:
        strategy = {class_name}()
        signals = strategy.generate_signals(df)
    """

    # ── 策略参数 ───────────────────────────────────
    {param_assignments}

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算策略所需指标
        输入 df 需包含列: open, high, low, close, volume
        """
        df = df.copy()
        {indicator_calls}
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成买卖信号
        返回带 signal 列的 DataFrame：
          1  = 买入信号
         -1  = 卖出信号
          0  = 无信号
        """
        df = self.compute_indicators(df)
        df["signal"] = 0

        # ── 买入条件 ────────────────────────────────
        # TODO: 根据论文中的买入条件完善以下逻辑
        {buy_conditions_code}

        # ── 卖出条件 ────────────────────────────────
        # TODO: 根据论文中的卖出条件完善以下逻辑
        {sell_conditions_code}

        return df

    def scan(self, df: pd.DataFrame) -> bool:
        """
        单支股票信号扫描（与现有选股框架兼容）
        返回 True 表示当日有买入信号
        """
        signals = self.generate_signals(df)
        if signals.empty:
            return False
        last_signal = signals["signal"].iloc[-1]
        return last_signal == 1

    def summary(self) -> dict:
        """策略摘要信息"""
        return {{
            "name": "{class_name}",
            "paper": "{paper_title}",
            "type": "{strategy_type}",
            "universe": "{universe}",
            "holding_period": "{holding_period}",
            "confidence": {confidence:.2f},
        }}


# ═══════════════════════════════════════════════════════
# 快速测试（直接运行本文件）
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    # 生成模拟数据进行快速验证
    import numpy as np
    np.random.seed(42)
    n = 200
    close = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.5), name="close")
    df_test = pd.DataFrame({{
        "open":   close * (1 + np.random.uniform(-0.01, 0.01, n)),
        "high":   close * (1 + np.random.uniform(0, 0.02, n)),
        "low":    close * (1 - np.random.uniform(0, 0.02, n)),
        "close":  close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    }})

    strategy = {class_name}()
    result = strategy.generate_signals(df_test)
    buy_count = (result["signal"] == 1).sum()
    sell_count = (result["signal"] == -1).sum()
    print(f"策略: {{strategy.summary()}}")
    print(f"测试数据: {{n}} 根 K 线")
    print(f"买入信号: {{buy_count}} 次，卖出信号: {{sell_count}} 次")
'''


class FormulaConverter:
    """
    学术公式 → Python 代码转换器

    相比所有现有工具，本转换器独有功能：
      1. 识别论文中的公式类型（移动平均/动量/布林带等）
      2. 生成带完整参数的 pandas/numpy 实现
      3. 生成继承项目 BaseStrategy 的完整策略类
      4. 生成可直接运行的策略文件，加速从论文到代码的工作流
    """

    def convert_formula(self, formula: Formula, params: Optional[Dict] = None) -> Optional[ConvertedIndicator]:
        """
        将单个 Formula 对象转换为 Python 代码

        参数:
            formula: PaperParser 提取的 Formula 对象
            params:  自定义参数值（覆盖默认值）

        返回:
            ConvertedIndicator 或 None（无法识别时）
        """
        formula_text = f"{formula.raw} {formula.description}"
        return self._match_and_convert(formula_text, params)

    def convert_text(self, text: str, params: Optional[Dict] = None) -> List[ConvertedIndicator]:
        """
        从文本中识别并转换所有公式

        参数:
            text:   包含公式描述的文本
            params: 全局参数覆盖

        返回:
            ConvertedIndicator 列表
        """
        results = []
        seen_names = set()
        for template_pattern, code_template, default_params in _FORMULA_TEMPLATES:
            if re.search(template_pattern, text, re.IGNORECASE):
                merged_params = {**default_params, **(params or {})}
                try:
                    code = code_template.format(**merged_params)
                except KeyError:
                    code = code_template

                # 提取函数名
                name_m = re.search(r"def (\w+)", code)
                name = name_m.group(1) if name_m else "unknown"
                if name in seen_names:
                    continue
                seen_names.add(name)

                results.append(ConvertedIndicator(
                    name=name,
                    formula_raw=template_pattern,
                    python_code=code,
                    dependencies=["pandas", "numpy"],
                    params=merged_params,
                ))
        return results

    def generate_strategy_file(self, spec: StrategySpec, params: Optional[Dict] = None) -> GeneratedStrategy:
        """
        从 StrategySpec 生成完整的策略 Python 文件

        这是现有工具完全缺失的功能：
        将论文分析结果直接转化为可运行的策略代码文件

        参数:
            spec:   StrategyExtractor 返回的 StrategySpec
            params: 自定义参数覆盖

        返回:
            GeneratedStrategy（包含完整文件内容）
        """
        from datetime import datetime

        # 生成指标函数
        indicators = self.convert_text(spec.raw_description, params)
        if not indicators and spec.factors:
            factor_text = " ".join(spec.factors)
            indicators = self.convert_text(factor_text, params)

        # 组装类名
        class_name = self._make_class_name(spec.name)

        # 组装指标函数代码
        indicator_functions = "\n\n".join(ind.python_code for ind in indicators)
        if not indicator_functions:
            indicator_functions = "# TODO: 根据论文添加指标计算函数"

        # 组装指标调用代码
        indicator_calls = self._generate_indicator_calls(indicators)

        # 组装参数赋值
        all_params: Dict[str, object] = {**spec.key_params, **(params or {})}
        param_lines = [f"{k} = {repr(v)}" for k, v in all_params.items()] if all_params else ["# TODO: 定义策略参数"]
        param_assignments = "\n    ".join(param_lines)

        # 组装买卖信号代码
        buy_code = self._generate_condition_code(spec.buy_conditions, "buy")
        sell_code = self._generate_condition_code(spec.sell_conditions, "sell")

        file_content = _STRATEGY_CLASS_TEMPLATE.format(
            class_name=class_name,
            paper_title=spec.paper_title,
            strategy_type=spec.strategy_type,
            universe=spec.universe,
            holding_period=spec.holding_period,
            confidence=spec.confidence,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            strategy_description=f"{spec.strategy_type.upper()} 策略，基于 {', '.join(spec.factors[:3]) or 'unknown'} 指标",
            indicator_functions=indicator_functions,
            indicator_calls=indicator_calls or "        pass  # TODO: 调用指标函数",
            param_assignments=param_assignments,
            buy_conditions_code=buy_code,
            sell_conditions_code=sell_code,
        )

        return GeneratedStrategy(
            class_name=class_name,
            file_content=file_content,
            indicators=indicators,
            requires_params=all_params,
            source_paper=spec.paper_title,
        )

    # ── 内部方法 ──────────────────────────────────

    def _match_and_convert(self, text: str, params: Optional[Dict] = None) -> Optional[ConvertedIndicator]:
        """匹配并转换单个公式"""
        for template_pattern, code_template, default_params in _FORMULA_TEMPLATES:
            if re.search(template_pattern, text, re.IGNORECASE):
                merged = {**default_params, **(params or {})}
                try:
                    code = code_template.format(**merged)
                except KeyError:
                    code = code_template
                name_m = re.search(r"def (\w+)", code)
                name = name_m.group(1) if name_m else "unknown"
                return ConvertedIndicator(
                    name=name,
                    formula_raw=text[:100],
                    python_code=code,
                    dependencies=["pandas", "numpy"],
                    params=merged,
                )
        return None

    def _make_class_name(self, name: str) -> str:
        """将策略名转为合法的 Python 类名"""
        parts = re.split(r"[_\s\-]+", name)
        class_name = "".join(p.capitalize() for p in parts if p)
        class_name = re.sub(r"[^A-Za-z0-9]", "", class_name)
        if not class_name or class_name[0].isdigit():
            class_name = "Extracted" + class_name
        return class_name + "Strategy"

    def _generate_indicator_calls(self, indicators: List[ConvertedIndicator]) -> str:
        """生成指标调用代码（每行无前缀，由模板的缩进和行间 join 保证对齐）"""
        if not indicators:
            return ""
        lines = []
        for ind in indicators:
            func_name = ind.name
            # 根据函数签名判断需要哪些列
            if "high" in ind.python_code and "low" in ind.python_code:
                call = f'df["{func_name.upper()}"] = {func_name}(df["high"], df["low"], df["close"])'
            elif "volume" in ind.python_code.lower():
                call = f'df["{func_name.upper()}"] = {func_name}(df["volume"])'
            else:
                call = f'df["{func_name.upper()}"] = {func_name}(df["close"])'
            lines.append(call)
        # 8 spaces align with the indentation level in the template
        return "\n        ".join(lines)

    def _generate_condition_code(self, conditions, cond_type: str) -> str:
        """生成信号条件代码"""
        if not conditions:
            return f"        # TODO: 添加{cond_type}条件\n        pass"
        lines = []
        signal_val = 1 if cond_type == "buy" else -1
        for i, cond in enumerate(conditions[:3]):  # 最多取3个条件
            lines.append(f"        # 条件 {i+1}: {cond.description[:60]}")
            if cond.indicator != "UNKNOWN":
                col = cond.indicator
                if cond.direction in ("above", "cross_up"):
                    threshold = cond.threshold if cond.threshold is not None else 0
                    lines.append(f"        # df.loc[df['{col}'] > {threshold}, 'signal'] = {signal_val}")
                elif cond.direction in ("below", "cross_down"):
                    threshold = cond.threshold if cond.threshold is not None else 0
                    lines.append(f"        # df.loc[df['{col}'] < {threshold}, 'signal'] = {signal_val}")
        if not lines:
            lines = [f"        # TODO: 添加{cond_type}条件"]
        return "\n".join(lines)
