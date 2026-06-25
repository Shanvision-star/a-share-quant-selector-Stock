"""验证 Post-close Loop Runner 路由。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.routers import tracking_loop as router_module


class _RunnerStub:
    def __init__(self) -> None:
        self.calls = []

    def run_post_close(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "run_id": "tlr_test",
            "loop_type": "post_close",
            "status": "done",
            **kwargs,
        }

    def latest_run(self, loop_type="post_close"):
        return {"run_id": "tlr_latest", "loop_type": loop_type, "status": "done"}


def _client(runner: _RunnerStub) -> TestClient:
    app = FastAPI()
    router_module.tracking_loop_runner_service = runner
    app.include_router(router_module.router)
    return TestClient(app)


def test_post_close_run_endpoint_calls_runner_with_payload():
    runner = _RunnerStub()
    client = _client(runner)

    resp = client.post(
        "/api/tracking/loops/post-close/run",
        json={
            "eval_date": "2026-06-25",
            "slot": "post_close",
            "per_slot_limit": 3,
            "sync_first": False,
            "trigger": "api",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "done"
    assert runner.calls == [
        {
            "eval_date": "2026-06-25",
            "slot": "post_close",
            "per_slot_limit": 3,
            "sync_first": False,
            "trigger": "api",
        }
    ]


def test_latest_run_endpoint_returns_runner_payload():
    runner = _RunnerStub()
    client = _client(runner)

    resp = client.get("/api/tracking/loops/runs/latest")

    assert resp.status_code == 200
    assert resp.json()["data"]["run_id"] == "tlr_latest"
