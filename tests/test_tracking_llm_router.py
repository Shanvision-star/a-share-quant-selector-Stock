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
            return {
                "decision": "cut",
                "confidence": 0.85,
                "rationale": "mock",
                "suggested_action": "SELL",
                "suggested_intent": {"side": "SELL"},
                "alerts_summary": {"count": len(alerts)},
                "profile": profile or "default",
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


def test_llm_advice_endpoint_404_unknown(client) -> None:
    resp = client.post("/api/tracking/T-missing/llm-advice")
    assert resp.status_code == 404
