"""验证 P7：OrderIntent 确认 / 否决两个动作只写事件，不接入真实交易通道。"""

import sqlite3

import pandas as pd
import pytest

from web.backend.services.tracking_service import TrackingService


def _memory_connection():
    # 使用独立内存连接，避免污染真实 sqlite 文件
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _loader(code: str) -> pd.DataFrame:
    # 简化的最小行情，仅满足 create_item 解析需要
    return pd.DataFrame(
        [
            {"date": "2026-04-30", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": "2026-05-06", "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 1000},
        ]
    )


def _make_item(service: TrackingService) -> dict:
    return service.create_item(
        {
            "code": "000001",
            "name": "测试股",
            "strategy_name": "BowlReboundStrategy",
            "source": "manual",
            "source_date": "2026-05-01",
            "signal_date": "2026-04-30",
            "params": {"buy_offset_days": 1, "buy_price": "open", "intent_quantity": 200},
        }
    )


def test_confirm_intent_writes_event_and_keeps_intent():
    """确认意图：写入 intent_confirmed 事件，保留 latest_intent 字段。"""
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_loader)
    item = _make_item(service)

    confirmed = service.confirm_intent(
        item["tracking_id"],
        intent={"side": "SELL", "code": "000001", "qty_hint": 100, "reason": "manual_confirm"},
    )

    events = service.list_events(item["tracking_id"])
    types = [evt["event_type"] for evt in events]
    assert "intent_confirmed" in types
    confirm_evt = next(evt for evt in events if evt["event_type"] == "intent_confirmed")
    assert confirm_evt["action"] == "SELL"
    assert confirm_evt["payload"]["intent"]["qty_hint"] == 100
    assert confirmed["latest_intent"]["side"] == "SELL"


def test_confirm_intent_unknown_raises():
    """未知 tracking_id 应抛 KeyError，避免静默成功。"""
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_loader)
    with pytest.raises(KeyError):
        service.confirm_intent("trk_missing")


def test_reject_intent_clears_next_action_and_writes_event():
    """否决意图：next_action 回落到 HOLD，并写入 intent_rejected 事件。"""
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_loader)
    item = _make_item(service)
    # 模拟有过 next_action 推荐
    service._update_item(item["tracking_id"], next_action="SELL")  # type: ignore[attr-defined]

    rejected = service.reject_intent(item["tracking_id"], reason="操盘手判断为假信号")

    events = service.list_events(item["tracking_id"])
    reject_evt = next(evt for evt in events if evt["event_type"] == "intent_rejected")
    assert reject_evt["payload"]["reason"] == "操盘手判断为假信号"
    assert rejected["next_action"] == "HOLD"


def test_reject_intent_unknown_raises():
    """未知 tracking_id 应抛 KeyError。"""
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_loader)
    with pytest.raises(KeyError):
        service.reject_intent("trk_missing", reason="x")
