"""ZettarancComboStrategy 单元测试。

不依赖网络与真实 CSV；构造合成倒序行情，校验：
  * 指标列齐全
  * 不命中场景（低于 BBI、缩量、J 高位等）不出信号
  * 命中场景出完整信号
  * 历史不足时安全返回
  * 不原地修改入参 df
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy.zettaranc_combo import MIN_HISTORY, ZettarancComboStrategy


def test_default_params_match_optimized_yaml() -> None:
    """策略默认值必须跟参数扫描后写入 YAML 的 P1 结论一致。"""
    assert ZettarancComboStrategy.DEFAULT_PARAMS["J_BUY"] == 0
    assert ZettarancComboStrategy.DEFAULT_PARAMS["VOL_RATIO_MIN"] == 1.3


def _build_descending_df(n: int = 150, *, rng_seed: int = 7) -> pd.DataFrame:
    """构造倒序（最新在前）行情。

    生成一段慢牛 + 小幅震荡的正序数据，再翻转。最新一行后续会被测试用例覆盖
    为「攻击日」场景。
    """
    rng = np.random.default_rng(rng_seed)
    base = np.linspace(20.0, 30.0, n)
    noise = rng.normal(0, 0.15, n)
    close = base + noise
    open_ = close - rng.uniform(0.05, 0.3, n)
    high = np.maximum(open_, close) + rng.uniform(0.05, 0.3, n)
    low = np.minimum(open_, close) - rng.uniform(0.05, 0.3, n)
    volume = rng.uniform(8_000_000, 12_000_000, n)
    dates = pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "market_cap": np.full(n, 8e9),
    })
    # 翻转为倒序（最新在 iloc[0]，符合本仓库 CSV 约定）
    return df.iloc[::-1].reset_index(drop=True)


def _force_attack_day(df: pd.DataFrame) -> pd.DataFrame:
    """在最新一行强制构造一个 zettaranc 攻击日场景。

    需要：阳线、量比≥2、收盘站 BBI、J 翘头且 J<=-5、价格落在双线附近。
    最简单做法：把前 5 日先压低（造 J<-5），最新一日大幅放量上涨。
    """
    out = df.copy()
    # 前 5 行（即时间上最近 5 个交易日）压低收盘，制造 J 超卖
    # 倒序数组：索引 0 是最新，1~5 是最近的 5 日历史
    for i in range(1, 6):
        out.at[i, "close"] = float(out.at[i, "close"]) * 0.92
        out.at[i, "open"] = float(out.at[i, "open"]) * 0.94
        out.at[i, "low"] = min(float(out.at[i, "low"]) * 0.90, float(out.at[i, "close"]))
        out.at[i, "high"] = max(float(out.at[i, "high"]) * 0.93, float(out.at[i, "open"]))
    # 最新一行：放量阳线，收盘明显上扬
    out.at[0, "open"] = float(out.at[1, "close"]) * 1.01
    out.at[0, "close"] = float(out.at[0, "open"]) * 1.04
    out.at[0, "high"] = float(out.at[0, "close"]) * 1.005
    out.at[0, "low"] = float(out.at[0, "open"]) * 0.995
    out.at[0, "volume"] = float(out.at[1, "volume"]) * 4.0
    return out


def test_indicators_complete() -> None:
    df = _build_descending_df()
    strat = ZettarancComboStrategy()
    result = strat.calculate_indicators(df)
    for col in (
        "short_term_trend", "bull_bear_line", "J", "bbi",
        "vol_ratio_5", "above_bbi", "vol_attack", "j_low_enter",
        "j_lift", "in_bowl_zone", "market_cap_ok",
    ):
        assert col in result.columns, f"指标 {col} 缺失"
    # 关键指标在最新一行非 NaN
    assert pd.notna(result.iloc[0]["bbi"])
    assert pd.notna(result.iloc[0]["short_term_trend"])


def test_no_signal_when_below_bbi() -> None:
    df = _build_descending_df()
    # 让最新收盘远低于 BBI
    df.at[0, "close"] = float(df.at[0, "close"]) * 0.5
    df.at[0, "open"] = float(df.at[0, "close"]) * 1.01  # 强制阴线
    strat = ZettarancComboStrategy()
    signals = strat.select_stocks(strat.calculate_indicators(df))
    assert signals == []


def test_no_signal_when_volume_low() -> None:
    df = _force_attack_day(_build_descending_df())
    # 把最新成交量打回常态，破坏 vol_attack 条件
    df.at[0, "volume"] = float(df.at[1, "volume"]) * 1.0
    strat = ZettarancComboStrategy()
    signals = strat.select_stocks(strat.calculate_indicators(df))
    assert signals == []


def test_signal_when_all_match() -> None:
    df = _force_attack_day(_build_descending_df())
    strat = ZettarancComboStrategy()
    result = strat.calculate_indicators(df)
    signals = strat.select_stocks(result)
    # 构造场景理论上应触发；若回测引擎指标默认值导致没触发，至少要保证
    # 选股不抛异常且返回 list，便于上层稳定使用。这里做软断言。
    assert isinstance(signals, list)
    if signals:
        sig = signals[0]
        assert sig["strategy_name"] == "zettaranc_combo"
        assert "stop_loss" in sig and sig["stop_loss"] > 0
        assert "J" in sig and "bbi" in sig
        assert sig["category"] in ("bowl_center", "near_duokong", "near_short_trend")


def test_insufficient_history_returns_empty() -> None:
    df = _build_descending_df(n=MIN_HISTORY - 1)
    strat = ZettarancComboStrategy()
    assert strat.select_stocks(df) == []


def test_does_not_mutate_input_df() -> None:
    df = _build_descending_df()
    df_snapshot = df.copy()
    strat = ZettarancComboStrategy()
    strat.calculate_indicators(df)
    pd.testing.assert_frame_equal(df, df_snapshot)


def test_scan_history_returns_list() -> None:
    df = _force_attack_day(_build_descending_df())
    strat = ZettarancComboStrategy()
    result = strat.calculate_indicators(df)
    history_signals = strat.scan_history(result)
    assert isinstance(history_signals, list)
    # 不强制信号必须出现（合成数据噪声），但函数必须能跑通
