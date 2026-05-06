"""
砖型图指标与选股策略。

核心思路：
- 先在时间正序上实现通达信公式，保证 SMA/REF 的递归方向正确。
- 再把结果恢复到原 DataFrame 顺序，兼容项目内“最新日期在前”的 CSV 结构。
- 指标计算同时供 K 线副图展示和策略选股使用，避免同一公式出现两套口径。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategy.base_strategy import BaseStrategy
from utils.technical import calculate_zhixing_trend


def _tdx_sma(values: pd.Series, n: int, m: int) -> pd.Series:
    """通达信 SMA(X,N,M)，必须按时间正序递归计算。"""
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0)
    result = pd.Series(index=numeric.index, dtype=float)
    if numeric.empty:
        return result

    result.iloc[0] = numeric.iloc[0]
    for i in range(1, len(numeric)):
        result.iloc[i] = (numeric.iloc[i] * m + result.iloc[i - 1] * (n - m)) / n
    return result


def _restore_to_source_index(calc: pd.DataFrame, values: pd.Series, source_index: pd.Index) -> pd.Series:
    restored = pd.Series(values.values, index=calc["_source_index"].values)
    return restored.reindex(source_index)


def calculate_brick_indicators(
    df: pd.DataFrame,
    rebound_strength_ratio: float = 0.8,
    upper_shadow_max: float = 0.25,
) -> pd.DataFrame:
    """
    计算砖型图指标和策略判定字段。

    输出字段：
    - brick_value: 砖型图柱值，对应公式 B2/砖型图。
    - brick_rising: 当日砖型图高于前一交易日。
    - brick_turn_up: 由非上升切换为上升，对应副图公式 XG。
    - brick_xg: 完整选股条件，包含趋势、回升力度、上影线过滤。
    """
    result = df.copy()
    if result.empty:
        return result

    required_columns = {"date", "open", "high", "low", "close"}
    missing = required_columns - set(result.columns)
    if missing:
        raise ValueError(f"砖型图指标缺少必要字段: {', '.join(sorted(missing))}")

    calc = result.copy()
    calc["_source_index"] = result.index
    calc["date"] = pd.to_datetime(calc["date"], errors="coerce")
    calc = calc.sort_values("date", ascending=True).reset_index(drop=True)

    open_ = pd.to_numeric(calc["open"], errors="coerce")
    high = pd.to_numeric(calc["high"], errors="coerce")
    low = pd.to_numeric(calc["low"], errors="coerce")
    close = pd.to_numeric(calc["close"], errors="coerce")

    high_4 = high.rolling(window=4, min_periods=1).max()
    low_4 = low.rolling(window=4, min_periods=1).min()
    price_range = (high_4 - low_4).replace(0, np.nan)

    a3 = ((high_4 - close) / price_range * 100).fillna(0.0)
    a4 = a3 - 90
    a5 = _tdx_sma(a4, 4, 1)
    a6 = a5 + 100

    a7 = ((close - low_4) / price_range * 100).fillna(0.0)
    a8 = _tdx_sma(a7, 6, 1)
    a9 = _tdx_sma(a8, 6, 1)
    a10 = a9 + 100

    b1 = a10 - a6
    b2 = (b1 - 4).where(b1 > 4, 0.0).fillna(0.0)

    prev_1 = b2.shift(1)
    prev_2 = b2.shift(2)
    brick_rising = (prev_1 < b2).fillna(False)
    brick_turn_up = ((brick_rising.shift(1).fillna(False) == False) & brick_rising).fillna(False)

    pullback_before_rebound = (prev_1 < prev_2).fillna(False)
    rebound_now = (b2 > prev_1).fillna(False)
    prior_drop = (prev_2 - prev_1).fillna(0.0)
    current_rebound = (b2 - prev_1).fillna(0.0)
    rebound_strength_ok = (current_rebound >= prior_drop * rebound_strength_ratio).fillna(False)

    result["brick_value"] = _restore_to_source_index(calc, b2, result.index)
    result["brick_prev_1"] = _restore_to_source_index(calc, prev_1, result.index)
    result["brick_prev_2"] = _restore_to_source_index(calc, prev_2, result.index)
    result["brick_rising"] = _restore_to_source_index(calc, brick_rising, result.index).fillna(False).astype(bool)
    result["brick_turn_up"] = _restore_to_source_index(calc, brick_turn_up, result.index).fillna(False).astype(bool)
    result["brick_pullback_rebound"] = _restore_to_source_index(
        calc,
        pullback_before_rebound & rebound_now,
        result.index,
    ).fillna(False).astype(bool)
    result["brick_rebound_strength_ok"] = _restore_to_source_index(
        calc,
        rebound_strength_ok,
        result.index,
    ).fillna(False).astype(bool)

    zhixing = calculate_zhixing_trend(result)
    result["short_term_trend"] = zhixing["short_term_trend"]
    result["bull_bear_line"] = zhixing["bull_bear_line"]
    result["brick_trend_ok"] = (
        pd.to_numeric(result["short_term_trend"], errors="coerce")
        > pd.to_numeric(result["bull_bear_line"], errors="coerce")
    ) & (
        pd.to_numeric(result["close"], errors="coerce")
        > pd.to_numeric(result["bull_bear_line"], errors="coerce")
    )

    upper_shadow = pd.to_numeric(result["high"], errors="coerce") - np.maximum(
        pd.to_numeric(result["open"], errors="coerce"),
        pd.to_numeric(result["close"], errors="coerce"),
    )
    candle_range = pd.to_numeric(result["high"], errors="coerce") - pd.to_numeric(result["low"], errors="coerce")
    result["upper_shadow_ratio"] = (upper_shadow / (candle_range + 0.01)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    result["brick_upper_shadow_ok"] = result["upper_shadow_ratio"] <= upper_shadow_max
    result["brick_xg"] = (
        result["brick_pullback_rebound"]
        & result["brick_rebound_strength_ok"]
        & result["brick_trend_ok"]
        & result["brick_upper_shadow_ok"]
    )

    return result


class BrickPatternStrategy(BaseStrategy):
    """砖型图正常趋势判定选股策略。"""

    def __init__(self, params=None):
        default_params = {
            "rebound_strength_ratio": 0.8,
            "upper_shadow_max": 0.25,
        }
        if params:
            default_params.update(params)
        super().__init__("砖型图策略", default_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        return calculate_brick_indicators(
            df,
            rebound_strength_ratio=float(self.params["rebound_strength_ratio"]),
            upper_shadow_max=float(self.params["upper_shadow_max"]),
        )

    def select_stocks(self, df, stock_name="") -> list:
        if df.empty:
            return []

        if stock_name:
            invalid_keywords = ("退", "未知", "退市", "已退")
            if any(keyword in stock_name for keyword in invalid_keywords):
                return []
            if stock_name.startswith("ST") or stock_name.startswith("*ST"):
                return []

        latest = df.iloc[0]
        close = latest.get("close")
        volume = latest.get("volume", 0)
        if pd.isna(close) or float(volume or 0) <= 0:
            return []

        if not bool(latest.get("brick_xg", False)):
            return []

        def _round(value, digits=2):
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if math.isnan(number) or not math.isfinite(number):
                return None
            return round(number, digits)

        signal = {
            "date": latest.get("date"),
            "close": _round(close),
            "brick_value": _round(latest.get("brick_value")),
            "brick_prev_1": _round(latest.get("brick_prev_1")),
            "brick_prev_2": _round(latest.get("brick_prev_2")),
            "short_term_trend": _round(latest.get("short_term_trend")),
            "bull_bear_line": _round(latest.get("bull_bear_line")),
            "upper_shadow_ratio": _round(latest.get("upper_shadow_ratio"), 4),
            "reasons": [
                "砖型图由绿转红",
                f"回升力度>={float(self.params['rebound_strength_ratio']) * 100:.0f}%",
                "价格站上知行多空线",
                f"上影线<={float(self.params['upper_shadow_max']) * 100:.0f}%",
            ],
            "category": "brick_trend_reversal",
        }
        return [signal]
