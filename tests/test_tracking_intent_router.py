"""P7 OrderIntent 确认 / 否决路由测试。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from web.backend.routers import tracking_intent as router_module

    # 用闭包记录路由调用，避免依赖真实数据库
    calls: dict = {"confirm": [], "reject": []}

    class _StubService:
        def confirm_intent(self, tracking_id, intent=None):
            if tracking_id != "T-known":
                raise KeyError(tracking_id)
            calls["confirm"].append({"tracking_id": tracking_id, "intent": intent})
            return {
                "tracking_id": tracking_id,
                "status": "holding",
                "latest_intent": intent or {"side": "SELL"},
                "next_action": "SELL",
            }

        def reject_intent(self, tracking_id, reason=""):
            if tracking_id != "T-known":
                raise KeyError(tracking_id)
            calls["reject"].append({"tracking_id": tracking_id, "reason": reason})
            return {
                "tracking_id": tracking_id,
                "status": "holding",
                "next_action": "HOLD",
            }

    monkeypatch.setattr(router_module, "tracking_service", _StubService())

    app = FastAPI()
    app.include_router(router_module.router)
    client = TestClient(app)
    client._calls = calls  # type: ignore[attr-defined]
    return client


def test_confirm_intent_endpoint_returns_updated_item(client) -> None:
    resp = client.post(
        "/api/tracking/T-known/confirm-intent",
        json={"intent": {"side": "SELL", "qty_hint": 100}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["latest_intent"]["qty_hint"] == 100
    assert client._calls["confirm"][0]["intent"]["side"] == "SELL"


def test_confirm_intent_endpoint_404_unknown(client) -> None:
    resp = client.post("/api/tracking/T-missing/confirm-intent", json={})
    assert resp.status_code == 404


def test_reject_intent_endpoint_clears_next_action(client) -> None:
    resp = client.post(
        "/api/tracking/T-known/reject-intent",
        json={"reason": "假信号"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["next_action"] == "HOLD"
    assert client._calls["reject"][0]["reason"] == "假信号"


def test_reject_intent_endpoint_404_unknown(client) -> None:
    resp = client.post("/api/tracking/T-missing/reject-intent", json={"reason": "x"})
    assert resp.status_code == 404
