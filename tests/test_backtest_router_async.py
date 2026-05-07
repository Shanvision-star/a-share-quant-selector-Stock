"""验证回测异步任务 API。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.routers import backtest


class FakeBacktestJobManager:
    def __init__(self):
        self.submitted_params = None

    def submit(self, params):
        self.submitted_params = dict(params)
        return {
            "task_id": "bt_test",
            "status": "queued",
            "created_at": "2026-05-07 10:00:00",
            "started_at": None,
            "finished_at": None,
            "error": "",
            "result": None,
            "params": dict(params),
        }

    def get(self, task_id):
        if task_id != "bt_test":
            return None
        return {
            "task_id": task_id,
            "status": "done",
            "created_at": "2026-05-07 10:00:00",
            "started_at": "2026-05-07 10:00:01",
            "finished_at": "2026-05-07 10:00:02",
            "error": "",
            "result": {"summary": {"trade_count": 1}},
            "params": {"start_date": "2026-04-24", "end_date": "2026-04-24"},
        }


def _client():
    app = FastAPI()
    app.include_router(backtest.router)
    return TestClient(app)


def _payload():
    return {
        "start_date": "2026-04-24",
        "end_date": "2026-04-24",
        "source": "manual",
        "strategy": "all",
        "holding_days": 1,
        "buy_offset_days": 1,
        "max_positions_per_day": 20,
    }


def test_submit_backtest_task_returns_task_id(monkeypatch):
    fake_manager = FakeBacktestJobManager()
    monkeypatch.setattr(backtest, "backtest_job_manager", fake_manager)

    response = _client().post("/api/backtest/tasks", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["task_id"] == "bt_test"
    assert body["data"]["status"] == "queued"
    assert fake_manager.submitted_params["start_date"] == "2026-04-24"


def test_get_backtest_task_returns_result(monkeypatch):
    monkeypatch.setattr(backtest, "backtest_job_manager", FakeBacktestJobManager())

    response = _client().get("/api/backtest/tasks/bt_test")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "done"
    assert body["data"]["result"]["summary"]["trade_count"] == 1


def test_get_unknown_backtest_task_returns_404(monkeypatch):
    monkeypatch.setattr(backtest, "backtest_job_manager", FakeBacktestJobManager())

    response = _client().get("/api/backtest/tasks/missing")

    assert response.status_code == 404
