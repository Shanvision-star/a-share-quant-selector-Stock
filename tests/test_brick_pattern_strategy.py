import pandas as pd
import pytest

from strategy.brick_pattern import BrickPatternStrategy, calculate_brick_indicators


def _tdx_sma(values: pd.Series, n: int, m: int) -> pd.Series:
    result = pd.Series(index=values.index, dtype=float)
    result.iloc[0] = values.iloc[0]
    for i in range(1, len(values)):
        result.iloc[i] = (values.iloc[i] * m + result.iloc[i - 1] * (n - m)) / n
    return result


def _expected_brick_value(df: pd.DataFrame) -> pd.Series:
    calc = df.copy()
    calc["_source_index"] = calc.index
    calc["date"] = pd.to_datetime(calc["date"])
    calc = calc.sort_values("date", ascending=True).reset_index(drop=True)

    high_4 = calc["high"].rolling(window=4, min_periods=1).max()
    low_4 = calc["low"].rolling(window=4, min_periods=1).min()
    price_range = (high_4 - low_4).replace(0, pd.NA)

    var1a = ((high_4 - calc["close"]) / price_range * 100 - 90).fillna(0)
    var2a = _tdx_sma(var1a, 4, 1) + 100
    var3a = ((calc["close"] - low_4) / price_range * 100).fillna(0)
    var4a = _tdx_sma(var3a, 6, 1)
    var5a = _tdx_sma(var4a, 6, 1) + 100
    var6a = var5a - var2a
    brick = (var6a - 4).where(var6a > 4, 0)

    restored = pd.Series(brick.values, index=calc["_source_index"].values)
    return restored.sort_index()


def test_calculate_brick_indicators_matches_tdx_formula_on_descending_data():
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=12, freq="D"),
        "open": [10.0, 10.2, 10.1, 10.5, 10.4, 10.7, 10.6, 11.0, 10.9, 11.3, 11.1, 11.5],
        "high": [10.4, 10.5, 10.3, 10.8, 10.7, 11.0, 10.9, 11.4, 11.2, 11.8, 11.6, 12.0],
        "low": [9.8, 10.0, 9.9, 10.2, 10.1, 10.3, 10.2, 10.6, 10.5, 10.8, 10.7, 11.0],
        "close": [10.2, 10.1, 10.25, 10.6, 10.35, 10.85, 10.5, 11.2, 10.8, 11.5, 11.0, 11.7],
        "volume": [1000, 980, 1200, 1500, 1100, 1600, 1400, 2100, 1700, 2300, 1800, 2500],
    }).iloc[::-1].reset_index(drop=True)

    result = calculate_brick_indicators(df)

    assert result["brick_value"].tolist() == pytest.approx(_expected_brick_value(df).tolist())
    assert set(["brick_rising", "brick_turn_up", "brick_xg"]).issubset(result.columns)


def test_brick_pattern_strategy_selects_latest_rebound_signal():
    strategy = BrickPatternStrategy()
    df = pd.DataFrame([
        {
            "date": "2026-04-30",
            "open": 10.0,
            "high": 10.4,
            "low": 9.9,
            "close": 10.2,
            "volume": 10000,
            "brick_xg": True,
            "brick_value": 6.8,
            "brick_prev_1": 3.5,
            "brick_prev_2": 7.0,
            "short_term_trend": 10.1,
            "bull_bear_line": 9.9,
            "upper_shadow_ratio": 0.2,
        },
    ])

    signals = strategy.select_stocks(df, "测试股票")

    assert len(signals) == 1
    assert signals[0]["category"] == "brick_trend_reversal"
    assert signals[0]["brick_value"] == 6.8
    assert "砖型图由绿转红" in signals[0]["reasons"]
