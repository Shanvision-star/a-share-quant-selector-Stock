"""任务 D：profile 参数与 fallback 测试。

- profile=zettaranc_style 走 mock 时返回 schema 完整，并打 profile 标记
- profile=default 与不传等价
- 非法 profile 静默回退到 default
- DeepSeek 失败时返回 mock 结果 + provider_fallback=True，但仍带 profile 标记
"""

from __future__ import annotations

import pytest


_BASE_ITEM = {
    "tracking_id": "T-D",
    "code": "000001",
    "name": "Test",
    "status": "holding",
    "strategy_name": "B1",
    "entry_price": 10.0,
    "current_qty": 1000,
}

_HIGH_PRIORITY_ALERT = [{"priority": 10, "level": "must_send", "reason_text": "破位"}]


def _assert_schema(advice: dict) -> None:
    for key in (
        "decision",
        "confidence",
        "rationale",
        "suggested_action",
        "suggested_intent",
        "provider",
        "profile",
    ):
        assert key in advice, f"缺字段: {key}"
    assert advice["decision"] in {"cut", "reduce", "hold", "watch", "add"}
    assert advice["suggested_action"] in {"SELL", "REDUCE", "HOLD", "WAIT", "BUY"}


@pytest.fixture
def llm_service(monkeypatch):
    from web.backend.services import tracking_llm_service as svc_mod

    monkeypatch.setattr(svc_mod, "load_llm_config", lambda: {"provider": "mock"})
    return svc_mod.TrackingLLMService()


def test_profile_zettaranc_keeps_schema(llm_service) -> None:
    advice = llm_service.propose_action(
        dict(_BASE_ITEM), _HIGH_PRIORITY_ALERT, profile="zettaranc_style"
    )
    _assert_schema(advice)
    assert advice["profile"] == "zettaranc_style"
    assert advice["provider"] == "mock"


def test_profile_default_equivalent_to_none(llm_service) -> None:
    a = llm_service.propose_action(dict(_BASE_ITEM), _HIGH_PRIORITY_ALERT, profile=None)
    b = llm_service.propose_action(dict(_BASE_ITEM), _HIGH_PRIORITY_ALERT, profile="default")
    # mock 分支具备确定性：profile 仅做标记，决策/建议字段应完全一致
    assert a["decision"] == b["decision"]
    assert a["suggested_action"] == b["suggested_action"]
    assert a["profile"] == "default"
    assert b["profile"] == "default"


def test_invalid_profile_falls_back_to_default(llm_service) -> None:
    advice = llm_service.propose_action(
        dict(_BASE_ITEM), _HIGH_PRIORITY_ALERT, profile="not_a_real_profile"
    )
    _assert_schema(advice)
    assert advice["profile"] == "default"


def test_deepseek_failure_returns_mock_with_fallback(monkeypatch) -> None:
    from web.backend.services import tracking_llm_service as svc_mod

    monkeypatch.setattr(
        svc_mod,
        "load_llm_config",
        lambda: {
            "provider": "deepseek",
            "deepseek": {"api_key": "x", "base_url": "http://x", "model": "deepseek-chat"},
        },
    )

    def _boom(**_kwargs):
        raise svc_mod.DeepSeekError("network down")

    monkeypatch.setattr(svc_mod, "call_deepseek", _boom)
    service = svc_mod.TrackingLLMService()

    advice = service.propose_action(
        dict(_BASE_ITEM), _HIGH_PRIORITY_ALERT, profile="zettaranc_style"
    )
    _assert_schema(advice)
    assert advice["provider"] == "mock"
    assert advice["provider_fallback"] is True
    assert advice["profile"] == "zettaranc_style"
    assert advice["provider_error"]
