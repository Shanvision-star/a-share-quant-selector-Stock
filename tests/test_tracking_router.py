"""验证单股跟踪 API。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.routers import tracking


class FakeTrackingService:
    def __init__(self):
        self.created_payload = None

    def create_item(self, payload):
        self.created_payload = dict(payload)
        return {
            "tracking_id": "trk_test",
            "code": payload["code"],
            "name": payload.get("name", ""),
            "strategy_name": payload.get("strategy_name", ""),
            "status": "watch_buy",
            "params": payload.get("params", {}),
            "next_action": "WAIT_BUY",
        }

    def list_items(self, status=None, code=None, limit=100):
        return [
            {
                "tracking_id": "trk_test",
                "code": code or "000559",
                "status": status if status and status != "all" else "watch_buy",
                "next_action": "WAIT_BUY",
            }
        ]

    def get_item(self, tracking_id):
        if tracking_id != "trk_test":
            return None
        return {"tracking_id": tracking_id, "code": "000559", "status": "watch_buy"}

    def evaluate_item(self, tracking_id, eval_date=None):
        if tracking_id != "trk_test":
            raise KeyError(tracking_id)
        return {
            "tracking_id": tracking_id,
            "code": "000559",
            "status": "holding",
            "entry_date": eval_date or "2026-05-06",
            "next_action": "BUY",
            "latest_intent": {"side": "BUY", "broker_order_id": None},
        }

    def evaluate_items(self, eval_date=None):
        return {"total": 1, "items": [self.evaluate_item("trk_test", eval_date)]}

    def list_events(self, tracking_id, limit=200):
        if tracking_id != "trk_test":
            return []
        return [
            {
                "event_id": 1,
                "tracking_id": tracking_id,
                "event_type": "created",
                "action": "WAIT_BUY",
                "payload": {"code": "000559"},
            }
        ]


def _client():
    app = FastAPI()
    app.include_router(tracking.router)
    return TestClient(app)


def test_create_tracking_item(monkeypatch):
    fake = FakeTrackingService()
    monkeypatch.setattr(tracking, "tracking_service", fake)

    response = _client().post(
        "/api/tracking",
        json={
            "code": "000559",
            "name": "万向钱潮",
            "strategy_name": "BowlReboundStrategy",
            "source": "manual",
            "source_date": "2026-05-01",
            "signal_date": "2026-04-30",
            "params": {"buy_offset_days": 1},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["tracking_id"] == "trk_test"
    assert fake.created_payload["code"] == "000559"


def test_list_and_evaluate_tracking_items(monkeypatch):
    monkeypatch.setattr(tracking, "tracking_service", FakeTrackingService())

    list_response = _client().get("/api/tracking", params={"status": "all"})
    eval_response = _client().post("/api/tracking/trk_test/evaluate", params={"date": "2026-05-06"})

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["code"] == "000559"
    assert eval_response.status_code == 200
    assert eval_response.json()["data"]["next_action"] == "BUY"
    assert eval_response.json()["data"]["latest_intent"]["broker_order_id"] is None


def test_get_tracking_events(monkeypatch):
    monkeypatch.setattr(tracking, "tracking_service", FakeTrackingService())

    response = _client().get("/api/tracking/trk_test/events")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["event_type"] == "created"

