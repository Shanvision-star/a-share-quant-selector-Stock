from fastapi.testclient import TestClient

from web.backend import main
from web.backend.routers import system_status


class FakeSystemStatusService:
    def build_status(self):
        return {
            "checked_at": "2026-06-21T10:00:00+08:00",
            "overall_status": "ready",
            "backend": {"status": "ready"},
            "data": {"status": "ready"},
            "strategy_cache": {"status": "ready"},
            "update_pipeline": {"status": "missing"},
            "tracking": {"status": "ready"},
            "integrations": {"status": "disabled"},
            "frontend_hints": ["数据和策略缓存均可用，可以查看策略结果。"],
        }


def test_system_status_route_returns_payload(monkeypatch):
    monkeypatch.setattr(system_status, "system_status_service", FakeSystemStatusService())
    client = TestClient(main.app)

    response = client.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["overall_status"] == "ready"
