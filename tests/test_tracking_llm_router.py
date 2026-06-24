"""P6 LLM 建议 REST 接口测试。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from web.backend.routers import tracking_llm as router_module

    class _StubTrackingService:
        def get_item(self, tracking_id):
            if tracking_id == "T-known":
                return {
                    "tracking_id": "T-known",
                    "code": "000001",
                    "name": "Test",
                    "status": "holding",
                    "current_qty": 1000,
                }
            return None

    class _StubAlertService:
        def list_alerts(self, tracking_id=None, eval_date=None, ui_status=None, limit=20):
            return [{"rule_id": "STOP_LOSS", "priority": 10, "message": "跌破止损"}]

    class _StubLLM:
        def propose_action(self, item, alerts, frame=None, profile=None):
            if profile == "minimal_contract":
                return {
                    "decision": "cut",
                    "confidence": 0.85,
                    "rationale": "mock",
                    "suggested_action": "SELL",
                    "suggested_intent": {"side": "SELL"},
                    "alerts_summary": {"count": len(alerts)},
                }
            return {
                "decision": "cut",
                "confidence": 0.85,
                "rationale": "mock",
                "suggested_action": "SELL",
                "suggested_intent": {"code": item["code"], "side": "SELL", "qty_hint": 100, "reason": "test"},
                "alerts_summary": {"count": len(alerts)},
                "provider": "mock",
                "provider_fallback": False,
                "profile": profile or "default",
                "zettaranc_data_source": "local_csv" if profile == "zettaranc_style" else None,
            }

    monkeypatch.setattr(router_module, "tracking_service", _StubTrackingService())
    monkeypatch.setattr(router_module, "tracking_alert_service", _StubAlertService())
    monkeypatch.setattr(router_module, "tracking_llm_service", _StubLLM())

    app = FastAPI()
    app.include_router(router_module.router)
    return TestClient(app)


def test_llm_advice_endpoint_returns_payload(client) -> None:
    resp = client.post("/api/tracking/T-known/llm-advice")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["decision"] == "cut"
    assert data["suggested_action"] == "SELL"
    assert "tracking_id" in data and data["tracking_id"] == "T-known"


def test_llm_advice_endpoint_preserves_zettaranc_profile_and_data_source(client) -> None:
    resp = client.post(
        "/api/tracking/T-known/llm-advice",
        json={"profile": "zettaranc_style"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["profile"] == "zettaranc_style"
    assert data["provider"] == "mock"
    assert data["provider_fallback"] is False
    assert data["zettaranc_data_source"] == "local_csv"
    assert data["suggested_intent"] == {
        "code": "000001",
        "side": "SELL",
        "qty_hint": 100,
        "reason": "test",
    }


def test_llm_advice_endpoint_fills_schema_defaults_when_provider_omitted(client) -> None:
    resp = client.post(
        "/api/tracking/T-known/llm-advice",
        json={"profile": "minimal_contract"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["provider"] == "mock"
    assert data["provider_fallback"] is False
    assert data["profile"] == "minimal_contract"
    assert data["tracking_id"] == "T-known"
    assert "suggested_intent" in data
    assert "intent" not in data


def test_llm_advice_endpoint_404_unknown(client) -> None:
    resp = client.post("/api/tracking/T-missing/llm-advice")
    assert resp.status_code == 404
