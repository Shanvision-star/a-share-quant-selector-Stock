"""Zettaranc 离线回测脚本专项回归测试。

这些用例只覆盖逐笔成交模拟的边界，不读取真实 CSV，也不触发网络。
目标是锁住 P0/P1 已修复过的手续费百分点口径与 X2 连续破 BBI 出场规则。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_zettaranc_backtest import simulate_trade


def _frame(rows: list[dict]) -> pd.DataFrame:
    base = {
        "code": "000001",
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 100.0,
        "bbi": 90.0,
    }
    normalized = []
    for i, row in enumerate(rows):
        item = dict(base)
        item["date"] = f"2026-01-{i + 1:02d}"
        item.update(row)
        normalized.append(item)
    return pd.DataFrame(normalized)


def test_simulate_trade_deducts_fee_as_percentage_points() -> None:
    df = _frame([
        {"low": 90.0},
        {"open": 100.0, "high": 104.0, "low": 95.0, "close": 105.0, "bbi": 90.0},
        {"close": 110.0, "bbi": 90.0},
    ])

    trade = simulate_trade(
        df,
        0,
        take_profit_pct=20.0,
        hold_days_limit=1,
        fee_pct=0.05,
        category="unit",
    )

    assert trade is not None
    assert trade.exit_reason == "time_stop"
    assert trade.pnl_pct == 9.9


def test_simulate_trade_exits_after_two_consecutive_bbi_breaks() -> None:
    df = _frame([
        {"low": 80.0},
        {"open": 100.0, "high": 102.0, "low": 95.0, "close": 99.0, "bbi": 100.0},
        {"high": 101.0, "low": 94.0, "close": 98.0, "bbi": 100.0},
        {"close": 110.0, "bbi": 90.0},
    ])

    trade = simulate_trade(
        df,
        0,
        take_profit_pct=20.0,
        hold_days_limit=10,
        fee_pct=0.05,
        category="unit",
    )

    assert trade is not None
    assert trade.exit_reason == "break_bbi"
    assert trade.exit_date == "2026-01-03"
    assert trade.exit_price == 98.0


def test_single_bbi_break_does_not_exit_before_time_stop() -> None:
    df = _frame([
        {"low": 80.0},
        {"open": 100.0, "high": 102.0, "low": 95.0, "close": 99.0, "bbi": 100.0},
        {"high": 101.0, "low": 94.0, "close": 101.0, "bbi": 100.0},
        {"close": 103.0, "bbi": 90.0},
    ])

    trade = simulate_trade(
        df,
        0,
        take_profit_pct=20.0,
        hold_days_limit=2,
        fee_pct=0.05,
        category="unit",
    )

    assert trade is not None
    assert trade.exit_reason == "time_stop"
    assert trade.exit_date == "2026-01-04"


def test_stop_loss_has_priority_over_take_profit_and_bbi_break() -> None:
    df = _frame([
        {"low": 98.0},
        {"open": 100.0, "high": 130.0, "low": 97.0, "close": 90.0, "bbi": 100.0},
        {"close": 80.0, "bbi": 100.0},
    ])

    trade = simulate_trade(
        df,
        0,
        take_profit_pct=15.0,
        hold_days_limit=10,
        fee_pct=0.05,
        category="unit",
    )

    assert trade is not None
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == 98.0
