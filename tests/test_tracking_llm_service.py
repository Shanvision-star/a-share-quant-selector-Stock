"""P6 LLM 建议服务（确定性 mock）测试。

- 高优先级（priority<30）告警 -> 建议清仓
- 中等优先级（30<=priority<60）告警 -> 建议减仓
- 无告警且 watch_buy -> 观望
- 无告警且 holding -> 持有
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _force_mock_provider(monkeypatch):
    """这里强制走 mock provider：本测试套件断言确定性行为，不应触发真实网络。"""
    from web.backend.services import tracking_llm_service as svc_mod

    monkeypatch.setattr(svc_mod, "load_llm_config", lambda: {"provider": "mock"})


@pytest.fixture
def llm_service():
    from web.backend.services.tracking_llm_service import TrackingLLMService

    return TrackingLLMService()


def _make_item(status: str = "holding", code: str = "000001") -> dict:
    return {
        "tracking_id": "T-1",
        "code": code,
        "name": "Test",
        "status": status,
        "strategy_name": "B1",
        "entry_price": 10.0,
        "current_qty": 1000,
    }


def test_propose_action_cut_on_must_send_alert(llm_service) -> None:
    """priority<30 必发告警 -> 决策清仓。"""
    alerts = [
        {"rule_id": "STOP_LOSS", "priority": 10, "message": "跌破止损"},
    ]
    advice = llm_service.propose_action(_make_item("holding"), alerts, frame=None)

    assert advice["decision"] == "cut"
    assert advice["suggested_action"] == "SELL"
    assert advice["suggested_intent"]["side"] == "SELL"
    assert 0.0 < advice["confidence"] <= 1.0
    assert "止损" in advice["rationale"] or "高优先级" in advice["rationale"]


def test_propose_action_reduce_on_mid_priority(llm_service) -> None:
    """30<=priority<60 -> 减仓建议。"""
    alerts = [{"rule_id": "MA_BREAK_SHORT", "priority": 45, "message": "短均线破位"}]
    advice = llm_service.propose_action(_make_item("holding"), alerts, frame=None)

    assert advice["decision"] == "reduce"
    assert advice["suggested_action"] == "REDUCE"
    assert advice["suggested_intent"]["side"] == "SELL"


def test_propose_action_hold_when_no_alerts(llm_service) -> None:
    """holding 无告警 -> 持有。"""
    advice = llm_service.propose_action(_make_item("holding"), [], frame=None)

    assert advice["decision"] == "hold"
    assert advice["suggested_action"] == "HOLD"


def test_propose_action_watch_when_watch_buy_no_alerts(llm_service) -> None:
    """watch_buy 状态无告警 -> 观望。"""
    advice = llm_service.propose_action(_make_item("watch_buy"), [], frame=None)

    assert advice["decision"] == "watch"
    assert advice["suggested_action"] == "WAIT"


def test_propose_action_is_deterministic(llm_service) -> None:
    """同输入两次返回结构一致。"""
    item = _make_item("holding")
    alerts = [{"rule_id": "X", "priority": 50, "message": "m"}]
    a = llm_service.propose_action(item, alerts, frame=None)
    b = llm_service.propose_action(item, alerts, frame=None)

    assert a["decision"] == b["decision"]
    assert a["confidence"] == b["confidence"]
