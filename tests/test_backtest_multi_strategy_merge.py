"""任务 C：多战法融合与组合权重逻辑的回归测试。

目标：
1. 默认参数下，引擎对候选列表的处理与历史行为保持一致（single 模式）；
2. multi_strategy + critical_first 必须正确把 SELL/CRITICAL 信号排在前面，
   避免重现 zettaranc 项目 Priority.value 升序导致 OBSERVE 抢先的 bug；
3. buy_first / sell_first 模式按指定 action 优先选择；
4. weight_cap + position_pct + max_weight_per_code 能阻断单股累计权重超限；
5. 引擎汇总（summary）必须把组合模式字段透出，便于前端展示与审计。
"""

from __future__ import annotations

import pytest

from web.backend.backtest_engine.signal_source import (
    PRIORITY_RANK,
    apply_max_weight_per_code,
    merge_same_day_signals,
)
from web.backend.backtest_engine.models import SignalCandidate


def _mk(code: str, strategy: str, date: str = "2026-04-01") -> SignalCandidate:
    return SignalCandidate(
        code=code,
        name=f"name-{code}",
        strategy_name=strategy,
        trade_date=date,
        signal_date=date,
        source="test",
    )


def test_merge_default_critical_first_picks_sell_over_observe():
    """zettaranc 回归：同一只股票同日有 BUY 与 S1(SELL) 时，必须优先保留 SELL。"""
    candidates = [_mk("000001", "b1_pattern"), _mk("000001", "S1_stop_loss")]
    merged = merge_same_day_signals(candidates, priority_mode="critical_first")
    assert len(merged) == 1
    assert merged[0].strategy_name == "S1_stop_loss"


def test_merge_buy_first_picks_buy_signal():
    candidates = [_mk("000002", "S2_exit"), _mk("000002", "bowl_rebound")]
    merged = merge_same_day_signals(candidates, priority_mode="buy_first")
    assert merged[0].strategy_name == "bowl_rebound"


def test_merge_sell_first_picks_sell_signal():
    candidates = [_mk("000003", "brick_buy"), _mk("000003", "S3_break")]
    merged = merge_same_day_signals(candidates, priority_mode="sell_first")
    assert merged[0].strategy_name == "S3_break"


def test_merge_preserves_distinct_dates():
    candidates = [
        _mk("000004", "b1", date="2026-04-01"),
        _mk("000004", "b1", date="2026-04-02"),
    ]
    merged = merge_same_day_signals(candidates)
    assert len(merged) == 2
    assert {c.signal_date for c in merged} == {"2026-04-01", "2026-04-02"}


def test_apply_max_weight_drops_excess_signals():
    cs = [_mk("000005", "b1", date=f"2026-04-{i:02d}") for i in range(1, 6)]
    kept, dropped = apply_max_weight_per_code(cs, max_weight_pct=20.0, position_pct=10.0)
    # 单股最多容纳 2 笔 (2 * 10% = 20%)，剩余 3 笔被丢弃
    assert len(kept) == 2
    assert dropped == 3


def test_apply_max_weight_disabled_when_position_pct_zero():
    cs = [_mk("000006", "b1", date=f"2026-04-{i:02d}") for i in range(1, 4)]
    kept, dropped = apply_max_weight_per_code(cs, max_weight_pct=10.0, position_pct=0.0)
    assert kept == cs
    assert dropped == 0


def test_priority_rank_dict_is_explicit_not_enum_value():
    """显式 PRIORITY_RANK 字典：CRITICAL 必须排在 OPPORTUNITY/OBSERVE 之前。"""
    assert PRIORITY_RANK["CRITICAL"] < PRIORITY_RANK["OPPORTUNITY"] < PRIORITY_RANK["OBSERVE"]


if __name__ == "__main__":  # pragma: no cover - 仅本地手测
    pytest.main([__file__, "-v"])
