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


# ---- C 档：zettaranc 真实上下文注入测试 ----


def test_zettaranc_profile_injects_data_source_field(monkeypatch) -> None:
    """profile=zettaranc_style 时应通过 adapter 拿到 source 并透传到 advice。"""
    from web.backend.services import tracking_llm_service as svc_mod

    monkeypatch.setattr(svc_mod, "load_llm_config", lambda: {"provider": "mock"})
    monkeypatch.setattr(
        svc_mod.zettaranc_adapter,
        "prepare_context",
        lambda code, days=60: {"source": "local_csv", "text": "FAKE-SNAPSHOT", "error": None},
    )
    service = svc_mod.TrackingLLMService()
    advice = service.propose_action(
        dict(_BASE_ITEM), _HIGH_PRIORITY_ALERT, profile="zettaranc_style"
    )
    _assert_schema(advice)
    assert advice["zettaranc_data_source"] == "local_csv"


def test_default_profile_does_not_call_zettaranc(monkeypatch) -> None:
    """default profile 不应触发 adapter 调用，也不应有 zettaranc 字段。"""
    from web.backend.services import tracking_llm_service as svc_mod

    monkeypatch.setattr(svc_mod, "load_llm_config", lambda: {"provider": "mock"})
    called = {"n": 0}

    def _spy(code, days=60):
        called["n"] += 1
        return {"source": "none", "text": "", "error": None}

    monkeypatch.setattr(svc_mod.zettaranc_adapter, "prepare_context", _spy)
    service = svc_mod.TrackingLLMService()
    advice = service.propose_action(dict(_BASE_ITEM), _HIGH_PRIORITY_ALERT, profile="default")
    assert called["n"] == 0
    assert "zettaranc_data_source" not in advice


def test_zettaranc_adapter_exception_does_not_break(monkeypatch) -> None:
    """adapter 抛错应被吞掉，链路继续走 mock 决策。"""
    from web.backend.services import tracking_llm_service as svc_mod

    monkeypatch.setattr(svc_mod, "load_llm_config", lambda: {"provider": "mock"})

    def _boom(code, days=60):
        raise RuntimeError("adapter exploded")

    monkeypatch.setattr(svc_mod.zettaranc_adapter, "prepare_context", _boom)
    service = svc_mod.TrackingLLMService()
    advice = service.propose_action(
        dict(_BASE_ITEM), _HIGH_PRIORITY_ALERT, profile="zettaranc_style"
    )
    _assert_schema(advice)
    # adapter 异常 → context 退回 source=none → 字段被写为 "none"
    assert advice["zettaranc_data_source"] == "none"
