"""P2 规则引擎红灯测试。

按设计文档 §5 / §5.3 的 5 条规则定义，验证：
1. 每条规则在触发条件命中时返回正确 priority / action_label。
2. 不触发时返回空，不会污染输出。
3. 多规则同时命中时按 priority 升序聚合。
4. dedup_key 形如 ``{tracking_id}|{rule_id}|{eval_date}`` 用于 P4 去重。

规则引擎为纯函数（无 IO / 无 DB），输入升序 frame；故测试只依赖 pandas。
"""

from __future__ import annotations

import pandas as pd
import pytest

from web.backend.services.tracking_rule_engine import (
    RULE_META,
    evaluate_rules,
)


def _make_frame(closes: list[float], start: str = "2026-01-02") -> pd.DataFrame:
    """构造升序 OHLC frame，open=high=low=close，仅用于规则触发测试。"""
    dates = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


def _base_item(tracking_id: str = "trk_test", status: str = "holding", signal_date: str = "2026-01-02") -> dict:
    """跟踪项最小骨架：仅包含规则评估必需字段。"""
    return {
        "tracking_id": tracking_id,
        "code": "000559",
        "name": "测试",
        "status": status,
        "signal_date": signal_date,
        "params": {},
    }


# ---------------------------------------------------------------------------
# R001 rule_break_short_trend：close 连续跌破 MA(5)*(1-0.5%)
# ---------------------------------------------------------------------------


def test_rule_break_short_trend_triggers_with_priority_10():
    """近 5 日均价高于收盘，应命中 rule_break_short_trend。"""
    # 前 5 日维持在 10 附近，最后一天跳水到 8.5；MA(5)≈9.7，阈值≈9.65
    closes = [10.0, 10.1, 10.0, 9.9, 10.0, 8.5]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_break_short_trend"]
    assert len(triggered) == 1
    assert triggered[0]["priority"] == 10
    assert triggered[0]["action_label"] == "TREND_BREAK"
    assert triggered[0]["evidence"]["close"] == pytest.approx(8.5)
    assert triggered[0]["evidence"]["short_ma"] > 8.5


def test_rule_break_short_trend_no_trigger_when_close_above_ma():
    """收盘价高于短均线时不应触发。"""
    closes = [10.0, 10.1, 10.0, 9.9, 10.0, 10.5]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_break_short_trend"]
    assert triggered == []


# ---------------------------------------------------------------------------
# R002 rule_break_bull_bear：连续 2 根 close < 多空线*(1-0.3%)
# ---------------------------------------------------------------------------


def test_rule_break_bull_bear_triggers_with_priority_20():
    """构造长期上行 + 末尾连续 2 根跳水跌破多空线，应命中。"""
    # 前 120 日均价 20，最后 2 日骤降至 10，必然显著低于多空线
    closes = [20.0] * 120 + [10.0, 10.0]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_break_bull_bear"]
    assert len(triggered) == 1
    assert triggered[0]["priority"] == 20
    assert triggered[0]["action_label"] == "STOP_LOSS"
    assert "bull_bear_line" in triggered[0]["evidence"]


def test_rule_break_bull_bear_no_trigger_when_only_one_day_below():
    """仅最后 1 根跌破，未达 confirm_close_count=2，不应触发。"""
    closes = [20.0] * 120 + [20.0, 10.0]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_break_bull_bear"]
    assert triggered == []


# ---------------------------------------------------------------------------
# R003 rule_short_overshoot：close > MA(5)*(1+8%)
# ---------------------------------------------------------------------------


def test_rule_short_overshoot_triggers_with_priority_50():
    """近 5 日 10 元附近，末尾跳到 12（+20%）应命中放飞。"""
    closes = [10.0, 10.0, 10.0, 10.0, 10.0, 12.0]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_short_overshoot"]
    assert len(triggered) == 1
    assert triggered[0]["priority"] == 50
    assert triggered[0]["action_label"] == "SELL_PARTIAL"


def test_rule_short_overshoot_no_trigger_when_within_threshold():
    """仅 +5% 偏离，未达 8%，不应触发。"""
    closes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.5]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_short_overshoot"]
    assert triggered == []


# ---------------------------------------------------------------------------
# R004 rule_stall_exit：跟踪 N 日累计涨幅 < stall_pct
# ---------------------------------------------------------------------------


def test_rule_stall_exit_triggers_when_no_movement_after_n_days():
    """signal_date 后 5+ 个交易日累计涨幅 <2%，应命中 stall_exit。"""
    # 8 个交易日，全部维持在 10.0 附近；signal_date 取 frame 第一根
    closes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.05]
    frame = _make_frame(closes, start="2026-01-02")
    item = _base_item(signal_date="2026-01-02")
    alerts = evaluate_rules(item, frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_stall_exit"]
    assert len(triggered) == 1
    assert triggered[0]["priority"] == 60
    assert triggered[0]["action_label"] == "WAIT_BUY"


def test_rule_stall_exit_no_trigger_when_days_insufficient():
    """跟踪不足 5 个交易日，不评估 stall_exit。"""
    closes = [10.0, 10.0, 10.0]
    frame = _make_frame(closes, start="2026-01-02")
    item = _base_item(signal_date="2026-01-02")
    alerts = evaluate_rules(item, frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_stall_exit"]
    assert triggered == []


# ---------------------------------------------------------------------------
# R005 rule_long_dead_cross：MA(60) 下穿 MA(120)
# ---------------------------------------------------------------------------


def test_rule_long_dead_cross_triggers_with_priority_70():
    """构造 MA60 由上转下穿 MA120，应命中长周期死叉。"""
    # 前 150 日上行至 17.5，随后陡跌使 MA60 在最后一根下穿 MA120
    closes = [10.0 + i * 0.05 for i in range(150)] + [17.5 - i * 0.3 for i in range(33)]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_long_dead_cross"]
    assert len(triggered) == 1
    assert triggered[0]["priority"] == 70
    assert triggered[0]["action_label"] == "TREND_BREAK"


def test_rule_long_dead_cross_no_trigger_when_no_cross():
    """MA60 一直高于 MA120，不应触发死叉。"""
    closes = [10.0 + i * 0.05 for i in range(180)]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    triggered = [a for a in alerts if a["rule_id"] == "rule_long_dead_cross"]
    assert triggered == []


# ---------------------------------------------------------------------------
# 聚合行为：按 priority 升序、dedup_key 形式、空 frame 容错
# ---------------------------------------------------------------------------


def test_evaluate_rules_sorts_alerts_by_priority_ascending():
    """同日多规则命中时，输出按 priority 升序，便于 P4 调度截断。"""
    # 短均线跌破（priority 10）+ 放飞同时不可能；用 break_short_trend + bull_bear 组合
    # 长期上行 20，末尾连续 2 根 9，命中 R001 和 R002
    closes = [20.0] * 120 + [9.0, 9.0]
    frame = _make_frame(closes)
    alerts = evaluate_rules(_base_item(), frame)

    rule_ids = [a["rule_id"] for a in alerts]
    priorities = [a["priority"] for a in alerts]
    assert "rule_break_short_trend" in rule_ids
    assert "rule_break_bull_bear" in rule_ids
    # 升序：10 应排在 20 之前
    assert priorities == sorted(priorities)


def test_evaluate_rules_dedup_key_combines_tracking_rule_and_date():
    """dedup_key 用于 P4 同一股票同一天同一规则只发一次。"""
    closes = [10.0, 10.1, 10.0, 9.9, 10.0, 8.5]
    frame = _make_frame(closes)
    item = _base_item(tracking_id="trk_abc")
    alerts = evaluate_rules(item, frame, eval_date="2026-01-09")

    triggered = [a for a in alerts if a["rule_id"] == "rule_break_short_trend"]
    assert triggered[0]["dedup_key"] == "trk_abc|rule_break_short_trend|2026-01-09"


def test_evaluate_rules_empty_frame_returns_empty_list():
    """空 frame 应安全返回空列表，不抛异常（避免 P5 批量评估被脏数据打断）。"""
    assert evaluate_rules(_base_item(), pd.DataFrame()) == []


def test_rule_meta_exposes_five_rules_with_design_priorities():
    """RULE_META 必须暴露 5 条规则，priority 与设计文档 §5.3 完全一致。"""
    expected = {
        "rule_break_short_trend": 10,
        "rule_break_bull_bear": 20,
        "rule_short_overshoot": 50,
        "rule_stall_exit": 60,
        "rule_long_dead_cross": 70,
    }
    assert {rid: meta["priority"] for rid, meta in RULE_META.items()} == expected
